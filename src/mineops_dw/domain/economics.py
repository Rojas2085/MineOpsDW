"""Economic valuation and electricity cost calculations using exact Decimal arithmetic."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from mineops_dw.domain.models import (
    Measurement,
    PaymentEvent,
    PriceSnapshot,
    QualityStatus,
    RewardSnapshot,
    normalize_decimal_str,
)


@dataclass(frozen=True)
class EconomicEvaluation:
    """Strictly separated economic valuation of estimated rewards, pool balances, deposits, and power cost."""

    btc_price_usd: str | None
    btc_price_bob: str | None
    price_status: Literal["measured", "unavailable", "simulated"]

    estimated_reward_btc: str
    estimated_reward_usd: str | None
    estimated_reward_bob: str | None

    pool_pending_btc: str | None
    pool_pending_usd: str | None

    confirmed_deposit_btc: str
    confirmed_deposit_usd: str | None
    confirmed_deposit_bob: str | None

    energy_consumed_kwh: str | None
    electricity_cost_usd: str | None
    electricity_cost_bob: str | None
    electricity_cost_status: QualityStatus


def evaluate_economics(
    *,
    usd_price_snapshot: PriceSnapshot | None,
    bob_price_snapshot: PriceSnapshot | None = None,
    estimated_reward: RewardSnapshot | None = None,
    pool_reported_reward: RewardSnapshot | None = None,
    confirmed_deposits: list[PaymentEvent] | None = None,
    energy_measurements: list[Measurement] | None = None,
    tariff_usd_per_kwh: Decimal | str | None = None,
    fx_usd_to_bob: Decimal | str | None = None,
) -> EconomicEvaluation:
    """Compute fiat valuations and electricity costs without mixing estimated and confirmed BTC."""
    if (
        usd_price_snapshot is not None
        and usd_price_snapshot.status != "unavailable"
        and usd_price_snapshot.price is not None
    ):
        price_usd: Decimal | None = Decimal(usd_price_snapshot.price)
        price_status = usd_price_snapshot.status
    else:
        price_usd = None
        price_status = "unavailable"

    if (
        bob_price_snapshot is not None
        and bob_price_snapshot.status != "unavailable"
        and bob_price_snapshot.price is not None
    ):
        price_bob: Decimal | None = Decimal(bob_price_snapshot.price)
    elif price_usd is not None and fx_usd_to_bob is not None:
        fx = Decimal(normalize_decimal_str(fx_usd_to_bob))
        price_bob = (price_usd * fx).quantize(Decimal("0.01")) if fx > Decimal("0") else None
    else:
        price_bob = None

    # 1. Estimated reward (never treated as confirmed income)
    est_btc = (
        Decimal(estimated_reward.amount_btc)
        if estimated_reward is not None and estimated_reward.reward_stage == "estimated"
        else Decimal("0")
    )
    est_usd = _multiply_fiat(est_btc, price_usd)
    est_bob = _multiply_fiat(est_btc, price_bob)

    # 2. Pool-reported pending balance
    if pool_reported_reward is not None and pool_reported_reward.reward_stage == "pool_reported":
        pool_btc: Decimal | None = Decimal(pool_reported_reward.amount_btc)
        pool_usd = _multiply_fiat(pool_btc, price_usd)
    else:
        pool_btc = None
        pool_usd = None

    # 3. Confirmed Exchange Deposits (only event_type == 'deposit_detected' and confirmed)
    dep_list = confirmed_deposits or []
    conf_btc = sum(
        (
            Decimal(ev.amount)
            for ev in dep_list
            if ev.event_type == "deposit_detected" and ev.settlement_status == "confirmed"
        ),
        start=Decimal("0"),
    )
    conf_usd = _multiply_fiat(conf_btc, price_usd)
    conf_bob = _multiply_fiat(conf_btc, price_bob)

    # 4. Electricity cost (never invented if energy/power measurements are unavailable)
    valid_energy = [
        m
        for m in (energy_measurements or [])
        if m.metric_name == "energy_consumed_wh"
        and m.status != "unavailable"
        and m.value is not None
    ]
    if not valid_energy:
        return EconomicEvaluation(
            btc_price_usd=normalize_decimal_str(price_usd) if price_usd is not None else None,
            btc_price_bob=normalize_decimal_str(price_bob) if price_bob is not None else None,
            price_status=price_status,
            estimated_reward_btc=normalize_decimal_str(est_btc),
            estimated_reward_usd=est_usd,
            estimated_reward_bob=est_bob,
            pool_pending_btc=normalize_decimal_str(pool_btc) if pool_btc is not None else None,
            pool_pending_usd=pool_usd,
            confirmed_deposit_btc=normalize_decimal_str(conf_btc),
            confirmed_deposit_usd=conf_usd,
            confirmed_deposit_bob=conf_bob,
            energy_consumed_kwh=None,
            electricity_cost_usd=None,
            electricity_cost_bob=None,
            electricity_cost_status="unavailable",
        )

    total_wh = sum((Decimal(str(m.value)) for m in valid_energy), start=Decimal("0"))
    total_kwh = (total_wh / Decimal("1000")).quantize(Decimal("0.000000001"))
    energy_status: QualityStatus = (
        "simulated" if any(m.status == "simulated" for m in valid_energy) else "estimated"
    )

    if tariff_usd_per_kwh is None:
        return EconomicEvaluation(
            btc_price_usd=normalize_decimal_str(price_usd) if price_usd is not None else None,
            btc_price_bob=normalize_decimal_str(price_bob) if price_bob is not None else None,
            price_status=price_status,
            estimated_reward_btc=normalize_decimal_str(est_btc),
            estimated_reward_usd=est_usd,
            estimated_reward_bob=est_bob,
            pool_pending_btc=normalize_decimal_str(pool_btc) if pool_btc is not None else None,
            pool_pending_usd=pool_usd,
            confirmed_deposit_btc=normalize_decimal_str(conf_btc),
            confirmed_deposit_usd=conf_usd,
            confirmed_deposit_bob=conf_bob,
            energy_consumed_kwh=normalize_decimal_str(total_kwh),
            electricity_cost_usd=None,
            electricity_cost_bob=None,
            electricity_cost_status="unavailable",
        )

    tariff = Decimal(normalize_decimal_str(tariff_usd_per_kwh))
    cost_usd_dec = (total_kwh * tariff).quantize(Decimal("0.000001"))
    cost_usd_str = normalize_decimal_str(cost_usd_dec)

    if fx_usd_to_bob is not None:
        fx_dec = Decimal(normalize_decimal_str(fx_usd_to_bob))
        cost_bob_str: str | None = (
            normalize_decimal_str((cost_usd_dec * fx_dec).quantize(Decimal("0.000001")))
            if fx_dec > Decimal("0")
            else None
        )
    else:
        cost_bob_str = None

    return EconomicEvaluation(
        btc_price_usd=normalize_decimal_str(price_usd) if price_usd is not None else None,
        btc_price_bob=normalize_decimal_str(price_bob) if price_bob is not None else None,
        price_status=price_status,
        estimated_reward_btc=normalize_decimal_str(est_btc),
        estimated_reward_usd=est_usd,
        estimated_reward_bob=est_bob,
        pool_pending_btc=normalize_decimal_str(pool_btc) if pool_btc is not None else None,
        pool_pending_usd=pool_usd,
        confirmed_deposit_btc=normalize_decimal_str(conf_btc),
        confirmed_deposit_usd=conf_usd,
        confirmed_deposit_bob=conf_bob,
        energy_consumed_kwh=normalize_decimal_str(total_kwh),
        electricity_cost_usd=cost_usd_str,
        electricity_cost_bob=cost_bob_str,
        electricity_cost_status=energy_status,
    )


def _multiply_fiat(btc_amount: Decimal, price: Decimal | None) -> str | None:
    if price is None:
        return None
    val = (btc_amount * price).quantize(Decimal("0.000001"))
    return normalize_decimal_str(val)


@dataclass(frozen=True)
class ProfitabilityKpi:
    """Estimated operational profitability and net margin KPI (PROJECT_SPEC Section 7.3)."""

    gross_income_usd: str | None
    electricity_cost_usd: str | None
    estimated_fees_usd: str
    net_margin_usd: str | None
    status: QualityStatus
    quality_note: str | None = None


def compute_profitability_kpi(
    *,
    pending_pool_balance: Decimal | str | None,
    market_price_usd: Decimal | str | None,
    electricity_cost_usd: Decimal | str | None,
    estimated_fees_usd: Decimal | str = "0",
    is_simulated: bool = False,
) -> ProfitabilityKpi:
    """Compute estimated net margin in USD, reporting unavailable (never 0) if cost or income is missing."""
    fees_dec = Decimal(normalize_decimal_str(estimated_fees_usd))
    fees_str = normalize_decimal_str(fees_dec)

    if pending_pool_balance is None or market_price_usd is None:
        gross_dec: Decimal | None = None
        gross_str: str | None = None
    else:
        bal_dec = Decimal(normalize_decimal_str(pending_pool_balance))
        px_dec = Decimal(normalize_decimal_str(market_price_usd))
        gross_dec = (bal_dec * px_dec).quantize(Decimal("0.000001"))
        gross_str = normalize_decimal_str(gross_dec)

    if electricity_cost_usd is None:
        cost_dec: Decimal | None = None
        cost_str: str | None = None
    else:
        cost_dec = Decimal(normalize_decimal_str(electricity_cost_usd))
        cost_str = normalize_decimal_str(cost_dec)

    if gross_dec is None or cost_dec is None:
        missing_parts: list[str] = []
        if gross_dec is None:
            missing_parts.append("pool balance or market price")
        if cost_dec is None:
            missing_parts.append("electricity cost")
        return ProfitabilityKpi(
            gross_income_usd=gross_str,
            electricity_cost_usd=cost_str,
            estimated_fees_usd=fees_str,
            net_margin_usd=None,
            status="unavailable",
            quality_note=f"Cannot compute net margin: missing {', '.join(missing_parts)}.",
        )

    net_dec = (gross_dec - cost_dec - fees_dec).quantize(Decimal("0.000001"))
    return ProfitabilityKpi(
        gross_income_usd=gross_str,
        electricity_cost_usd=cost_str,
        estimated_fees_usd=fees_str,
        net_margin_usd=normalize_decimal_str(net_dec, allow_negative=True),
        status="simulated" if is_simulated else "estimated",
        quality_note="Estimated net margin (pool pending balance valuation minus electricity and fees).",
    )
