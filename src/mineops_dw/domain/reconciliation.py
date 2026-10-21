"""Reconciliation domain rules between pool payouts and Binance detected deposits."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from mineops_dw.domain.models import PaymentEvent


@dataclass(frozen=True)
class MatchedPayoutDeposit:
    """A verified match between a pool payout and an exchange deposit."""

    payout_id: str
    deposit_id: str
    asset: str
    payout_amount: str
    deposit_amount: str
    external_reference: str
    payout_at_utc: str
    deposit_at_utc: str


@dataclass(frozen=True)
class ReconciliationReport:
    """Complete reconciliation view separating matched, pending pool payouts, and unmatched deposits."""

    matched: list[MatchedPayoutDeposit]
    unmatched_payouts: list[PaymentEvent]
    unmatched_deposits: list[PaymentEvent]


def reconcile_payouts_and_deposits(
    events: list[PaymentEvent],
) -> ReconciliationReport:
    """Reconcile pool `payout_issued` events against exchange `deposit_detected` events.

    Strict rule from docs/BINANCE_INTEGRATION.md:
    Never assume a payout is the same event as a deposit solely because the amount matches.
    Matching requires:
    1. Same asset (e.g., BTC).
    2. Both events have a non-empty `external_reference` (e.g., on-chain txId) and they match.
    3. The deposit amount equals either the gross payout amount or net (`amount - network_fee`).
    4. The deposit timestamp is greater than or equal to the payout timestamp.
    """
    payouts = [e for e in events if e.event_type == "payout_issued"]
    deposits = [e for e in events if e.event_type == "deposit_detected"]

    matched: list[MatchedPayoutDeposit] = []
    used_deposit_ids: set[str] = set()
    unmatched_payouts: list[PaymentEvent] = []

    for payout in payouts:
        p_ref = (payout.external_reference or "").strip()
        p_gross = Decimal(payout.amount)
        p_fee = Decimal(payout.network_fee) if payout.network_fee is not None else Decimal("0")
        p_net = p_gross - p_fee

        found_dep: PaymentEvent | None = None
        if p_ref:
            for dep in deposits:
                if dep.id in used_deposit_ids:
                    continue
                d_ref = (dep.external_reference or "").strip()
                if not d_ref or d_ref != p_ref:
                    continue
                if dep.asset != payout.asset:
                    continue
                if dep.observed_at_utc < payout.observed_at_utc:
                    continue

                d_amt = Decimal(dep.amount)
                if d_amt in {p_gross, p_net}:
                    found_dep = dep
                    break

        if found_dep is not None:
            used_deposit_ids.add(found_dep.id)
            matched.append(
                MatchedPayoutDeposit(
                    payout_id=payout.id,
                    deposit_id=found_dep.id,
                    asset=payout.asset,
                    payout_amount=payout.amount,
                    deposit_amount=found_dep.amount,
                    external_reference=p_ref,
                    payout_at_utc=payout.observed_at_utc,
                    deposit_at_utc=found_dep.observed_at_utc,
                )
            )
        else:
            unmatched_payouts.append(payout)

    unmatched_deposits = [d for d in deposits if d.id not in used_deposit_ids]
    return ReconciliationReport(
        matched=matched,
        unmatched_payouts=unmatched_payouts,
        unmatched_deposits=unmatched_deposits,
    )
