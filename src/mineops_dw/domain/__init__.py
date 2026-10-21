"""Domain layer package for MineOps DW."""

from __future__ import annotations

from mineops_dw.domain.economics import EconomicEvaluation, evaluate_economics
from mineops_dw.domain.models import (
    DataMode,
    Measurement,
    MiningSession,
    PaymentEvent,
    PaymentEventType,
    PeriodicReport,
    PoolShare,
    PriceSnapshot,
    QualityStatus,
    RewardSnapshot,
    RewardStage,
    SessionState,
    SettlementStatus,
    normalize_decimal_str,
    normalize_utc_timestamp,
)
from mineops_dw.domain.reconciliation import (
    MatchedPayoutDeposit,
    ReconciliationReport,
    reconcile_payouts_and_deposits,
)
from mineops_dw.domain.telemetry import (
    SafetyEvaluation,
    compute_energy_measurement,
    evaluate_safety_limits,
)

__all__ = [
    "DataMode",
    "EconomicEvaluation",
    "MatchedPayoutDeposit",
    "Measurement",
    "MiningSession",
    "PaymentEvent",
    "PaymentEventType",
    "PeriodicReport",
    "PoolShare",
    "PriceSnapshot",
    "QualityStatus",
    "ReconciliationReport",
    "RewardSnapshot",
    "RewardStage",
    "SafetyEvaluation",
    "SessionState",
    "SettlementStatus",
    "compute_energy_measurement",
    "evaluate_economics",
    "evaluate_safety_limits",
    "normalize_decimal_str",
    "normalize_utc_timestamp",
    "reconcile_payouts_and_deposits",
]
