"""External and hardware adapters package for MineOps DW."""

from __future__ import annotations

from mineops_dw.adapters.mining import (
    MinerAdapter,
    PoolAdapter,
    SimulatedMinerPoolAdapter,
    SimulationStepResult,
)
from mineops_dw.adapters.pool_http import (
    MinerExecutionGuard,
    PoolStatusSnapshot,
    ReadOnlyHttpPoolAdapter,
)
from mineops_dw.adapters.prices import MarketPriceAdapter, PriceAdapter
from mineops_dw.adapters.sensors import (
    HostResourceSensorAdapter,
    LhmSensorAdapter,
    SensorAdapter,
    build_safe_measurement,
)

__all__ = [
    "HostResourceSensorAdapter",
    "LhmSensorAdapter",
    "MarketPriceAdapter",
    "MinerAdapter",
    "MinerExecutionGuard",
    "PoolAdapter",
    "PoolStatusSnapshot",
    "PriceAdapter",
    "ReadOnlyHttpPoolAdapter",
    "SensorAdapter",
    "SimulatedMinerPoolAdapter",
    "SimulationStepResult",
    "build_safe_measurement",
]
