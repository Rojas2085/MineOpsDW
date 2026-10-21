"""External and hardware adapters package for MineOps DW."""

from __future__ import annotations

from mineops_dw.adapters.mining import (
    MinerAdapter,
    PoolAdapter,
    SimulatedMinerPoolAdapter,
    SimulationStepResult,
)
from mineops_dw.adapters.sensors import (
    HostResourceSensorAdapter,
    LhmSensorAdapter,
    SensorAdapter,
    build_safe_measurement,
)

__all__ = [
    "HostResourceSensorAdapter",
    "LhmSensorAdapter",
    "MinerAdapter",
    "PoolAdapter",
    "SensorAdapter",
    "SimulatedMinerPoolAdapter",
    "SimulationStepResult",
    "build_safe_measurement",
]
