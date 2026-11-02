"""Conceptual and operational models for MinerConnector, ControlAuthorization, and XMRig passive observation.

Implements the approved MineOps DW decisions:
- A-01..A-06: MinerConnector contract, orthogonal state dimensions, session-scoped ControlAuthorization.
- R-01..R-05: Logical dispatch commit, CommandResult phases, 7 preconditions of R-03 (including process_progress),
  passive thermal alerts, and external state change / override conflict handling.
- XMR-01..XMR-05, CP-01-A, CP-02 (Option B adjusted): Conservative schema validation and read-only passive mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Generic, Literal, Protocol, TypeVar, runtime_checkable

from mineops_dw.domain.models import normalize_utc_timestamp

T = TypeVar("T")

ControlAuthorizationState = Literal["NOT_GRANTED", "GRANTED", "REVOKED"]
ConnectionStatus = Literal["REACHABLE", "UNREACHABLE", "DEGRADED"]
MinerOperationalState = Literal["RUNNING", "PAUSED", "STOPPED", "STARTING", "STOPPING", "UNKNOWN"]
StateConfidence = Literal["CONFIRMED", "INFERRED", "UNKNOWN"]
ProcessProgressState = Literal[
    "ADVANCING",
    "UNCHANGED_WITHIN_RESOLUTION",
    "STALLED_SUSPECTED",
    "UNKNOWN",
]
MinerCapabilitiesStatus = Literal["AVAILABLE", "READ_ONLY", "UNAVAILABLE"]
CapabilityEvidenceState = Literal[
    "CONFIRMED_AVAILABLE",
    "CONFIRMED_UNAVAILABLE",
    "UNVERIFIED_PASSIVELY",
]
LocalClientReadiness = Literal[
    "TOKEN_CONFIGURED",
    "MISSING_LOCAL_TOKEN",
    "READ_AUTH_REJECTED",
    "WRITE_TOKEN_REJECTED",
    "CONTROL_DISABLED_LOCALLY",
]
SupervisorMode = Literal[
    "PASSIVE_IDLE",
    "OBSERVING_UNCONTROLLED",
    "ACTIVE_SUPERVISION",
    "DEGRADED_WAIT",
    "THERMAL_ALERT_UNCONTROLLED",
    "EXTERNAL_OVERRIDE_CONFLICT",
]
DataOrigin = Literal["REAL", "SIMULATED", "UNKNOWN"]
TelemetryQuality = Literal["VALID", "STALE", "UNAVAILABLE", "INVALID", "SUSPECT"]
SourceFreshness = Literal[
    "VERIFIED_FRESH",
    "VERIFIED_STALE",
    "UNVERIFIABLE_NO_SOURCE_TIMESTAMP",
]
DeliveryPhase = Literal["NOT_SENT", "RESPONSE_RECEIVED", "UNKNOWN"]
AcceptancePhase = Literal["ACCEPTED", "REJECTED", "UNKNOWN"]
PostconditionPhase = Literal["VERIFIED", "FAILED", "NOT_ATTEMPTED", "UNKNOWN"]
CausalAttribution = Literal["UNDETERMINED", "NOT_APPLICABLE"]


@dataclass(frozen=True)
class MetricObservation(Generic[T]):
    """Individual metric observation preserving independent quality and source freshness."""

    value: T | None
    quality: TelemetryQuality
    source_freshness: SourceFreshness = "UNVERIFIABLE_NO_SOURCE_TIMESTAMP"
    source_updated_at_utc: str | None = None
    quality_note: str | None = None

    def __post_init__(self) -> None:
        if self.source_updated_at_utc is not None:
            object.__setattr__(
                self,
                "source_updated_at_utc",
                normalize_utc_timestamp(self.source_updated_at_utc),
            )


@dataclass(frozen=True)
class MinerSnapshot:
    """Normalized point-in-time observation of a mining process (A-06, XMR-02, XMR-03, CP-02)."""

    observed_at_utc: str
    connection_status: ConnectionStatus
    operational_state: MinerOperationalState
    state_confidence: StateConfidence
    operational_state_quality: TelemetryQuality
    process_progress: ProcessProgressState
    data_origin: DataOrigin
    version: str | None = None
    kind: str | None = None
    algorithm: str | None = None
    pool_url: str | None = None
    hashrate_10s_hs: MetricObservation[float] = field(
        default_factory=lambda: MetricObservation(None, "UNAVAILABLE")
    )
    hashrate_60s_hs: MetricObservation[float] = field(
        default_factory=lambda: MetricObservation(None, "UNAVAILABLE")
    )
    hashrate_15m_hs: MetricObservation[float] = field(
        default_factory=lambda: MetricObservation(None, "UNAVAILABLE")
    )
    shares_good: MetricObservation[int] = field(
        default_factory=lambda: MetricObservation(None, "UNAVAILABLE")
    )
    shares_total: MetricObservation[int] = field(
        default_factory=lambda: MetricObservation(None, "UNAVAILABLE")
    )
    hashes_total: MetricObservation[int] = field(
        default_factory=lambda: MetricObservation(None, "UNAVAILABLE")
    )
    uptime_seconds: MetricObservation[int] = field(
        default_factory=lambda: MetricObservation(None, "UNAVAILABLE")
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observed_at_utc", normalize_utc_timestamp(self.observed_at_utc)
        )


@dataclass(frozen=True)
class MinerCapabilities:
    """Capabilities evaluation separating server evidence, local readiness, and global status (XMR-04, CP-01-A)."""

    evaluated_at_utc: str
    status: MinerCapabilitiesStatus
    connection_status: ConnectionStatus
    local_readiness: LocalClientReadiness
    observe: CapabilityEvidenceState
    state_verification: CapabilityEvidenceState
    pause: CapabilityEvidenceState
    resume: CapabilityEvidenceState
    config_fingerprint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evaluated_at_utc", normalize_utc_timestamp(self.evaluated_at_utc)
        )


@dataclass(frozen=True)
class CommandResult:
    """Immutable record of a pause() or resume() control operation (R-02, XMR-05)."""

    command_id: str
    action: Literal["PAUSE", "RESUME"]
    requested_at_utc: str
    completed_at_utc: str
    delivery: DeliveryPhase
    acceptance: AcceptancePhase
    postcondition: PostconditionPhase
    authorization_generation: int
    revoked_during_execution: bool = False
    pre_snapshot: MinerSnapshot | None = None
    post_snapshot: MinerSnapshot | None = None
    causal_attribution: CausalAttribution = "UNDETERMINED"

    def __post_init__(self) -> None:
        if isinstance(self.authorization_generation, bool) or self.authorization_generation < 0:
            raise ValueError("authorization_generation must be a non-negative integer.")
        object.__setattr__(
            self, "requested_at_utc", normalize_utc_timestamp(self.requested_at_utc)
        )
        object.__setattr__(
            self, "completed_at_utc", normalize_utc_timestamp(self.completed_at_utc)
        )


class ControlAuthorization:
    """Session-scoped ephemeral governance state for miner control (A-03, A-04, R-02, R-03)."""

    def __init__(self, *, session_mode: Literal["REAL", "SIMULATED"] = "REAL") -> None:
        self._session_mode: Literal["REAL", "SIMULATED"] = session_mode
        self._state: ControlAuthorizationState = "NOT_GRANTED"
        self._generation: int = 0
        self._granted_at_utc: str | None = None
        self._revoked_at_utc: str | None = None

    @property
    def state(self) -> ControlAuthorizationState:
        return self._state

    @property
    def authorization_generation(self) -> int:
        return self._generation

    @property
    def granted_at_utc(self) -> str | None:
        return self._granted_at_utc

    @property
    def revoked_at_utc(self) -> str | None:
        return self._revoked_at_utc

    def revoke(self, *, now: datetime | str | None = None) -> None:
        """Immediately revoke control authorization if granted (or keep NOT_GRANTED if never granted)."""
        ts = normalize_utc_timestamp(now or datetime.now(UTC))
        if self._state == "GRANTED":
            self._state = "REVOKED"
            self._revoked_at_utc = ts
        elif self._state == "REVOKED":
            self._revoked_at_utc = ts

    def try_grant(
        self,
        *,
        explicit_user_action: bool,
        has_in_flight_or_unreconciled_command: bool,
        snapshot: MinerSnapshot,
        capabilities: MinerCapabilities,
        mandatory_thermal_metrics_valid: bool,
        now: datetime | str | None = None,
    ) -> bool:
        """Evaluate the 7 preconditions of R-03 (including process_progress) to transition to GRANTED."""
        if not explicit_user_action:
            return False
        if has_in_flight_or_unreconciled_command:
            return False
        if snapshot.connection_status != "REACHABLE":
            return False
        if snapshot.data_origin == "UNKNOWN":
            return False
        if self._session_mode == "REAL" and snapshot.data_origin != "REAL":
            return False
        if self._session_mode == "SIMULATED" and snapshot.data_origin not in ("SIMULATED", "REAL"):
            return False
        if snapshot.operational_state not in ("RUNNING", "PAUSED"):
            return False
        if snapshot.state_confidence != "CONFIRMED":
            return False
        if snapshot.operational_state_quality != "VALID":
            return False
        if capabilities.status != "AVAILABLE":
            return False
        if (
            capabilities.pause != "CONFIRMED_AVAILABLE"
            or capabilities.resume != "CONFIRMED_AVAILABLE"
        ):
            return False
        if not mandatory_thermal_metrics_valid:
            return False
        if snapshot.process_progress in ("STALLED_SUSPECTED", "UNKNOWN"):
            return False

        ts = normalize_utc_timestamp(now or datetime.now(UTC))
        self._generation += 1
        self._state = "GRANTED"
        self._granted_at_utc = ts
        return True


@runtime_checkable
class MinerConnector(Protocol):
    """Common contract for mining process connectors (A-01)."""

    def get_snapshot(self) -> MinerSnapshot:
        """Observe the current miner operational state and telemetry."""
        ...

    def get_capabilities(self) -> MinerCapabilities:
        """Evaluate current observation and control capabilities passively."""
        ...

    def pause(self) -> CommandResult:
        """Request pause and verify postcondition (or reject locally if passive-only)."""
        ...

    def resume(self) -> CommandResult:
        """Request resume and verify postcondition (or reject locally if passive-only)."""
        ...
