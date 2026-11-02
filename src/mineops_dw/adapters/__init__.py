"""External and hardware adapters package for MineOps DW."""

from __future__ import annotations

from mineops_dw.adapters.android import (
    AndroidTelemetryIngestionService,
    AndroidTelemetryPayload,
)
from mineops_dw.adapters.binance import (
    BINANCE_DEPOSIT_HISTORY_PATH,
    BinanceConnectionStatus,
    BinanceDepositFetchResult,
    BinanceDepositReadOnlyAdapter,
    ExchangeReadOnlyAdapter,
)
from mineops_dw.adapters.mining import (
    MinerAdapter,
    PoolAdapter,
    SimulatedMinerPoolAdapter,
    SimulationStepResult,
)
from mineops_dw.adapters.pool_balance import (
    PayoutProgress,
    UnmineablePoolBalanceAdapter,
)
from mineops_dw.adapters.pool_http import (
    MinerExecutionGuard,
    PoolStatusSnapshot,
    ReadOnlyHttpPoolAdapter,
)
from mineops_dw.adapters.prices import (
    BinancePublicMarketClient,
    BinanceTicker24h,
    MarketPriceAdapter,
    PriceAdapter,
)
from mineops_dw.adapters.xmrig import (
    ShareDelta,
    XMRigApiAdapter,
    XMRigApiError,
    XMRigShareCounter,
    XMRigSummary,
)
from mineops_dw.adapters.sensors import (
    HostResourceSensorAdapter,
    LhmSensorAdapter,
    SensorAdapter,
    build_safe_measurement,
)

__all__ = [
    "AndroidTelemetryIngestionService",
    "AndroidTelemetryPayload",
    "BINANCE_DEPOSIT_HISTORY_PATH",
    "BinanceConnectionStatus",
    "BinanceDepositFetchResult",
    "BinanceDepositReadOnlyAdapter",
    "BinancePublicMarketClient",
    "BinanceTicker24h",
    "ExchangeReadOnlyAdapter",
    "HostResourceSensorAdapter",
    "LhmSensorAdapter",
    "MarketPriceAdapter",
    "MinerAdapter",
    "MinerExecutionGuard",
    "PayoutProgress",
    "PoolAdapter",
    "PoolStatusSnapshot",
    "PriceAdapter",
    "ReadOnlyHttpPoolAdapter",
    "SensorAdapter",
    "SimulatedMinerPoolAdapter",
    "SimulationStepResult",
    "ShareDelta",
    "UnmineablePoolBalanceAdapter",
    "XMRigApiAdapter",
    "XMRigApiError",
    "XMRigShareCounter",
    "XMRigSummary",
    "build_safe_measurement",
]
