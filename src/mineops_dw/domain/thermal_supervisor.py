"""Thermal supervisor and control governance engine (A-02..A-06, R-01..R-05, PARAM-01..PARAM-04).

Enforces:
- Passive observation when ControlAuthorization in {NOT_GRANTED, REVOKED}.
- Precedence of THERMAL_ALERT_UNCONTROLLED over DEGRADED_WAIT when no active authorization exists,
  with edge-triggered transition detection.
- Automatic thermal pause under GRANTED when temperature >= critical_temp_c (75.0 °C) or when the
  mandatory thermal sensor is missing/stale (> 30 s).
- Zero automatic start or resume: recovery requires continuous stability <= recovery_temp_c (60.0 °C)
  for stability_window_seconds (120 s) AND an explicit manual user_resume() action.
- Zero automatic retry of uncertain pause commands (transitions to DEGRADED_WAIT with reason
  UNCERTAIN_PAUSE_STILL_RUNNING_CRITICAL_THERMAL).
- Detection of external override conflicts (EXTERNAL_OVERRIDE_CONFLICT, R-05).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from mineops_dw.domain.miner_connector import (
    CommandResult,
    ControlAuthorization,
    ControlAuthorizationState,
    MinerCapabilities,
    MinerConnector,
    MinerSnapshot,
    SupervisorMode,
    TelemetryQuality,
)
from mineops_dw.domain.models import Measurement, normalize_utc_timestamp


def _parse_utc(ts: str) -> datetime:
    normalized = normalize_utc_timestamp(ts)
    return datetime.fromisoformat(normalized.replace("Z", "+00:00")).astimezone(UTC)


@dataclass(frozen=True)
class SupervisorEvaluation:
    """Result of a single thermal supervisor evaluation cycle."""

    evaluated_at_utc: str
    mode: SupervisorMode
    authorization_state: ControlAuthorizationState
    authorization_generation: int
    thermal_quality: TelemetryQuality
    cpu_temp_c: float | None
    is_critical_thermal: bool
    alert_edge_triggered: bool
    cooldown_elapsed_seconds: float
    cooldown_ready: bool
    degraded_reason: str | None = None
    dispatched_command: CommandResult | None = None
    snapshot: MinerSnapshot | None = None
    capabilities: MinerCapabilities | None = None


class ThermalSupervisor:
    """Supervises a MinerConnector with thermal hysteresis and session-scoped ControlAuthorization."""

    def __init__(
        self,
        connector: MinerConnector,
        authorization: ControlAuthorization | None = None,
        *,
        critical_temp_c: float = 75.0,
        recovery_temp_c: float = 60.0,
        stability_window_seconds: float = 120.0,
        max_staleness_seconds: float = 30.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if recovery_temp_c >= critical_temp_c:
            raise ValueError("recovery_temp_c must be strictly less than critical_temp_c.")
        if stability_window_seconds <= 0:
            raise ValueError("stability_window_seconds must be positive.")
        if max_staleness_seconds <= 0:
            raise ValueError("max_staleness_seconds must be positive.")

        self._connector = connector
        self._auth = authorization if authorization is not None else ControlAuthorization()
        self._critical_temp_c = critical_temp_c
        self._recovery_temp_c = recovery_temp_c
        self._stability_window_seconds = stability_window_seconds
        self._max_staleness_seconds = max_staleness_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

        self._mode: SupervisorMode = "PASSIVE_IDLE"
        self._degraded_reason: str | None = None
        self._supervised_thermal_pause_active: bool = False
        self._has_unreconciled_uncertain_command: bool = False
        self._recovery_stable_since: datetime | None = None
        self._last_Snapshot: MinerSnapshot | None = None

    @property
    def mode(self) -> SupervisorMode:
        return self._mode

    @property
    def authorization(self) -> ControlAuthorization:
        return self._auth

    @property
    def has_unreconciled_uncertain_command(self) -> bool:
        return self._has_unreconciled_uncertain_command

    def evaluate_thermal_measurement(
        self,
        temp_measurement: Measurement | None,
        now_dt: datetime | None = None,
    ) -> tuple[TelemetryQuality, float | None]:
        """Classify mandatory CPU temperature measurement quality and freshness (PARAM-04)."""
        ref_dt = now_dt if now_dt is not None else self._clock()
        if temp_measurement is None:
            return "UNAVAILABLE", None
        if temp_measurement.metric_name != "cpu_temp_c" or temp_measurement.unit != "°C":
            return "INVALID", None
        if temp_measurement.status != "measured" or temp_measurement.value is None:
            return "UNAVAILABLE", None
        val = float(temp_measurement.value)
        if not (0.0 <= val <= 130.0):
            return "INVALID", None
        observed_dt = _parse_utc(temp_measurement.observed_at_utc)
        age_seconds = (ref_dt - observed_dt).total_seconds()
        if age_seconds > self._max_staleness_seconds:
            return "STALE", val
        if age_seconds < -5.0:
            return "INVALID", val
        return "VALID", val

    def request_control_authorization(
        self,
        *,
        explicit_user_action: bool,
        temp_measurement: Measurement | None,
    ) -> bool:
        """Attempt to transition ControlAuthorization to GRANTED under all 7 preconditions of R-03."""
        now_dt = self._clock()
        snap = self._connector.get_snapshot()
        caps = self._connector.get_capabilities()
        thermal_quality, temp_val = self.evaluate_thermal_measurement(temp_measurement, now_dt)
        mandatory_valid = (
            thermal_quality == "VALID"
            and temp_val is not None
            and temp_val < self._critical_temp_c
        )
        return self._auth.try_grant(
            explicit_user_action=explicit_user_action,
            has_in_flight_or_unreconciled_command=self._has_unreconciled_uncertain_command,
            snapshot=snap,
            capabilities=caps,
            mandatory_thermal_metrics_valid=mandatory_valid,
        )

    def revoke_control_authorization(self) -> int:
        """Revoke active control authorization without issuing compensatory commands (R-01)."""
        self._auth.revoke(now=self._clock())
        return self._auth.authorization_generation

    def step(self, temp_measurement: Measurement | None) -> SupervisorEvaluation:
        """Execute one supervisor evaluation tick."""
        now_dt = self._clock()
        now_utc = normalize_utc_timestamp(now_dt)
        prev_mode = self._mode

        snap = self._connector.get_snapshot()
        caps = self._connector.get_capabilities()
        self._last_Snapshot = snap

        thermal_quality, temp_val = self.evaluate_thermal_measurement(temp_measurement, now_dt)
        is_critical = (
            thermal_quality != "VALID"
            or temp_val is None
            or temp_val >= self._critical_temp_c
        )

        # Update continuous recovery stability window (PARAM-02, PARAM-03)
        if thermal_quality == "VALID" and temp_val is not None and temp_val <= self._recovery_temp_c:
            if self._recovery_stable_since is None:
                self._recovery_stable_since = now_dt
            cooldown_elapsed = max(0.0, (now_dt - self._recovery_stable_since).total_seconds())
        else:
            self._recovery_stable_since = None
            cooldown_elapsed = 0.0

        cooldown_ready = cooldown_elapsed >= self._stability_window_seconds
        dispatched_cmd: CommandResult | None = None

        # Reconcile uncertain command if a clean confirmed state is now observed
        if self._has_unreconciled_uncertain_command and snap.state_confidence == "CONFIRMED":
            if snap.operational_state == "PAUSED":
                self._has_unreconciled_uncertain_command = False
                self._supervised_thermal_pause_active = True
                if self._degraded_reason == "UNCERTAIN_PAUSE_STILL_RUNNING_CRITICAL_THERMAL":
                    self._degraded_reason = None

        # 1. Governance when authorization is NOT_GRANTED or REVOKED
        #    Precedence rule: THERMAL_ALERT_UNCONTROLLED > DEGRADED_WAIT / OBSERVING_UNCONTROLLED
        if self._auth.state in ("NOT_GRANTED", "REVOKED"):
            self._degraded_reason = None
            miner_potentially_active = snap.operational_state in ("RUNNING", "STARTING", "UNKNOWN")
            if miner_potentially_active and (
                (thermal_quality == "VALID" and temp_val is not None and temp_val >= self._critical_temp_c)
                or (snap.operational_state == "RUNNING" and is_critical)
            ):
                self._mode = "THERMAL_ALERT_UNCONTROLLED"
            elif snap.operational_state == "RUNNING":
                self._mode = "OBSERVING_UNCONTROLLED"
            else:
                self._mode = "PASSIVE_IDLE"

            alert_edge = (
                self._mode == "THERMAL_ALERT_UNCONTROLLED"
                and prev_mode != "THERMAL_ALERT_UNCONTROLLED"
            )
            return SupervisorEvaluation(
                evaluated_at_utc=now_utc,
                mode=self._mode,
                authorization_state=self._auth.state,
                authorization_generation=self._auth.authorization_generation,
                thermal_quality=thermal_quality,
                cpu_temp_c=temp_val,
                is_critical_thermal=is_critical,
                alert_edge_triggered=alert_edge,
                cooldown_elapsed_seconds=cooldown_elapsed,
                cooldown_ready=cooldown_ready,
                degraded_reason=self._degraded_reason,
                dispatched_command=None,
                snapshot=snap,
                capabilities=caps,
            )

        # 2. Governance when ControlAuthorization == GRANTED
        # Check R-05 external override conflict: supervisor paused miner, but it resumed externally
        if (
            self._supervised_thermal_pause_active
            and snap.operational_state == "RUNNING"
            and snap.state_confidence == "CONFIRMED"
        ):
            self._mode = "EXTERNAL_OVERRIDE_CONFLICT"
            self._degraded_reason = "EXTERNAL_RESUME_DETECTED_DURING_SUPERVISED_PAUSE"
            return SupervisorEvaluation(
                evaluated_at_utc=now_utc,
                mode=self._mode,
                authorization_state=self._auth.state,
                authorization_generation=self._auth.authorization_generation,
                thermal_quality=thermal_quality,
                cpu_temp_c=temp_val,
                is_critical_thermal=is_critical,
                alert_edge_triggered=False,
                cooldown_elapsed_seconds=cooldown_elapsed,
                cooldown_ready=cooldown_ready,
                degraded_reason=self._degraded_reason,
                dispatched_command=None,
                snapshot=snap,
                capabilities=caps,
            )

        # If an uncertain pause command is still unreconciled (R-01: zero automatic retries)
        if self._has_unreconciled_uncertain_command:
            if is_critical and snap.operational_state in ("RUNNING", "UNKNOWN"):
                self._mode = "DEGRADED_WAIT"
                self._degraded_reason = "UNCERTAIN_PAUSE_STILL_RUNNING_CRITICAL_THERMAL"
            else:
                self._mode = "DEGRADED_WAIT"
                self._degraded_reason = "UNRECONCILED_UNCERTAIN_COMMAND"
            return SupervisorEvaluation(
                evaluated_at_utc=now_utc,
                mode=self._mode,
                authorization_state=self._auth.state,
                authorization_generation=self._auth.authorization_generation,
                thermal_quality=thermal_quality,
                cpu_temp_c=temp_val,
                is_critical_thermal=is_critical,
                alert_edge_triggered=False,
                cooldown_elapsed_seconds=cooldown_elapsed,
                cooldown_ready=cooldown_ready,
                degraded_reason=self._degraded_reason,
                dispatched_command=None,
                snapshot=snap,
                capabilities=caps,
            )

        # Automatic thermal pause when critical thermal or stale/unavailable sensor occurs while RUNNING
        if is_critical and snap.operational_state == "RUNNING":
            dispatched_cmd = self._connector.pause()
            if dispatched_cmd.postcondition == "VERIFIED" or (
                dispatched_cmd.post_snapshot is not None
                and dispatched_cmd.post_snapshot.operational_state == "PAUSED"
                and dispatched_cmd.post_snapshot.state_confidence == "CONFIRMED"
            ):
                self._supervised_thermal_pause_active = True
                self._recovery_stable_since = None
                self._mode = "ACTIVE_SUPERVISION"
                self._degraded_reason = None
            else:
                self._has_unreconciled_uncertain_command = (
                    dispatched_cmd.delivery == "UNKNOWN"
                    or dispatched_cmd.acceptance == "UNKNOWN"
                    or dispatched_cmd.postcondition == "UNKNOWN"
                )
                self._mode = "DEGRADED_WAIT"
                self._degraded_reason = "UNCERTAIN_PAUSE_STILL_RUNNING_CRITICAL_THERMAL"
        elif snap.connection_status != "REACHABLE" or snap.operational_state == "UNKNOWN":
            self._mode = "DEGRADED_WAIT"
            self._degraded_reason = "MINER_SNAPSHOT_DEGRADED_OR_UNKNOWN"
        else:
            self._mode = "ACTIVE_SUPERVISION"
            self._degraded_reason = None

        return SupervisorEvaluation(
            evaluated_at_utc=now_utc,
            mode=self._mode,
            authorization_state=self._auth.state,
            authorization_generation=self._auth.authorization_generation,
            thermal_quality=thermal_quality,
            cpu_temp_c=temp_val,
            is_critical_thermal=is_critical,
            alert_edge_triggered=False,
            cooldown_elapsed_seconds=cooldown_elapsed,
            cooldown_ready=cooldown_ready,
            degraded_reason=self._degraded_reason,
            dispatched_command=dispatched_cmd,
            snapshot=snap,
            capabilities=caps,
        )

    def user_resume(
        self,
        *,
        explicit_user_action: bool,
        temp_measurement: Measurement | None,
    ) -> CommandResult:
        """Execute a manual user-requested resume() only when stability and safety conditions hold."""
        now_dt = self._clock()
        now_utc = normalize_utc_timestamp(now_dt)
        pre_snap = self._connector.get_snapshot()

        if (
            not explicit_user_action
            or self._auth.state != "GRANTED"
            or self._has_unreconciled_uncertain_command
            or self._mode == "EXTERNAL_OVERRIDE_CONFLICT"
        ):
            return CommandResult(
                command_id=f"sup-resume-rejected-{now_utc}",
                action="RESUME",
                requested_at_utc=now_utc,
                completed_at_utc=now_utc,
                delivery="NOT_SENT",
                acceptance="UNKNOWN",
                postcondition="NOT_ATTEMPTED",
                pre_snapshot=pre_snap,
                post_snapshot=pre_snap,
                authorization_generation=self._auth.authorization_generation,
                revoked_during_execution=False,
                causal_attribution="NOT_APPLICABLE",
            )

        thermal_quality, temp_val = self.evaluate_thermal_measurement(temp_measurement, now_dt)
        cooldown_elapsed = (
            max(0.0, (now_dt - self._recovery_stable_since).total_seconds())
            if self._recovery_stable_since is not None
            else 0.0
        )
        if (
            thermal_quality != "VALID"
            or temp_val is None
            or temp_val > self._recovery_temp_c
            or (self._supervised_thermal_pause_active and cooldown_elapsed < self._stability_window_seconds)
        ):
            return CommandResult(
                command_id=f"sup-resume-cooldown-not-ready-{now_utc}",
                action="RESUME",
                requested_at_utc=now_utc,
                completed_at_utc=now_utc,
                delivery="NOT_SENT",
                acceptance="UNKNOWN",
                postcondition="NOT_ATTEMPTED",
                pre_snapshot=pre_snap,
                post_snapshot=pre_snap,
                authorization_generation=self._auth.authorization_generation,
                revoked_during_execution=False,
                causal_attribution="NOT_APPLICABLE",
            )

        res = self._connector.resume()
        if res.postcondition == "VERIFIED":
            self._supervised_thermal_pause_active = False
            self._mode = "ACTIVE_SUPERVISION"
            self._degraded_reason = None
        elif res.delivery == "UNKNOWN" or res.postcondition == "UNKNOWN":
            self._has_unreconciled_uncertain_command = True
            self._mode = "DEGRADED_WAIT"
            self._degraded_reason = "UNRECONCILED_UNCERTAIN_COMMAND"
        return res
