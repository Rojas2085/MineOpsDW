"""Passive process-detection MinerConnector for Kryptex Desktop (PROJECT_SPEC Sections 3, 6, 9).

Strictly enforces:
- Process detection only confirms whether a target binary is running (`RUNNING` vs `STOPPED` with
  `StateConfidence = "INFERRED"` because OS process presence does not prove active hashing).
- Never invents hashrate, shares, or pool balances: all hashing metrics remain `UNAVAILABLE` (`value = None`).
- `pause` and `resume` capabilities are `CONFIRMED_UNAVAILABLE` and `MinerCapabilities.status` is
  `READ_ONLY` when OS process inspection succeeds (or `UNAVAILABLE` if process inspection fails).
- `pause()` and `resume()` are rejected locally with zero OS process signals (`delivery="NOT_SENT"`,
  `acceptance="UNKNOWN"`, `postcondition="NOT_ATTEMPTED"`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any
import uuid

from mineops_dw.domain.miner_connector import (
    CommandResult,
    ControlAuthorization,
    DataOrigin,
    MetricObservation,
    MinerCapabilities,
    MinerOperationalState,
    MinerSnapshot,
    ProcessProgressState,
)
from mineops_dw.domain.models import normalize_utc_timestamp

DEFAULT_KRYPTEX_PROCESS_NAMES: frozenset[str] = frozenset(
    {"kryptex.exe", "kryptex-app.exe", "kryptex"}
)


class KryptexProcessAdapter:
    """Passive OS process monitor for Kryptex Desktop implementing MinerConnector."""

    def __init__(
        self,
        *,
        process_names: Iterable[str] = DEFAULT_KRYPTEX_PROCESS_NAMES,
        process_iter_fn: Callable[[], Iterable[dict[str, Any]]] | None = None,
        authorization: ControlAuthorization | None = None,
        data_origin: DataOrigin = "REAL",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        normalized = frozenset(name.strip().lower() for name in process_names if name.strip())
        if not normalized:
            raise ValueError("process_names must contain at least one non-empty process name.")
        self._process_names = normalized
        self._process_iter_fn = process_iter_fn
        self._authorization = authorization
        self._data_origin: DataOrigin = data_origin
        self._clock = clock or (lambda: datetime.now(UTC))

    def _current_auth_generation(self) -> int:
        if self._authorization is not None:
            return self._authorization.authorization_generation
        return 0

    def _scan_processes(self) -> tuple[bool, bool, int | None]:
        """Return (scan_succeeded, is_running, uptime_seconds)."""
        now_epoch = self._clock().timestamp()
        try:
            if self._process_iter_fn is not None:
                entries = list(self._process_iter_fn())
            else:
                import psutil  # type: ignore[import-not-found]

                entries = [
                    p.info
                    for p in psutil.process_iter(["name", "create_time"])
                ]
        except Exception:
            return False, False, None

        matched_uptimes: list[int] = []
        for info in entries:
            raw_name = str(info.get("name") or "").strip().lower()
            if raw_name in self._process_names:
                create_time = info.get("create_time")
                if isinstance(create_time, (int, float)) and now_epoch >= float(create_time):
                    matched_uptimes.append(int(now_epoch - float(create_time)))
                else:
                    matched_uptimes.append(-1)

        if not matched_uptimes:
            return True, False, None

        valid_uptimes = [u for u in matched_uptimes if u >= 0]
        max_uptime = max(valid_uptimes) if valid_uptimes else None
        return True, True, max_uptime

    def get_snapshot(self) -> MinerSnapshot:
        """Observe Kryptex process presence without inventing hashrate or shares."""
        now_utc = normalize_utc_timestamp(self._clock())
        ok, is_running, uptime_sec = self._scan_processes()
        if not ok:
            return MinerSnapshot(
                observed_at_utc=now_utc,
                connection_status="UNREACHABLE",
                operational_state="UNKNOWN",
                state_confidence="UNKNOWN",
                operational_state_quality="UNAVAILABLE",
                process_progress="UNKNOWN",
                data_origin="UNKNOWN",
            )

        op_state: MinerOperationalState = "RUNNING" if is_running else "STOPPED"
        progress: ProcessProgressState = "UNKNOWN"
        uptime_obs = (
            MetricObservation(
                uptime_sec,
                "VALID",
                source_freshness="UNVERIFIABLE_NO_SOURCE_TIMESTAMP",
                quality_note="Derived from OS process create_time.",
            )
            if uptime_sec is not None
            else MetricObservation(
                None,
                "UNAVAILABLE",
                quality_note="Process create_time unavailable or process not running.",
            )
        )
        unavail_float = MetricObservation(
            None,
            "UNAVAILABLE",
            quality_note="Kryptex Desktop does not expose a verified local telemetry API for hashrate.",
        )
        unavail_int = MetricObservation(
            None,
            "UNAVAILABLE",
            quality_note="Kryptex Desktop does not expose share counters via process inspection.",
        )
        return MinerSnapshot(
            observed_at_utc=now_utc,
            connection_status="REACHABLE",
            operational_state=op_state,
            state_confidence="INFERRED",
            operational_state_quality="VALID",
            process_progress=progress,
            data_origin=self._data_origin,
            kind="kryptex_process",
            hashrate_10s_hs=unavail_float,
            hashrate_60s_hs=unavail_float,
            hashrate_15m_hs=unavail_float,
            shares_good=unavail_int,
            shares_total=unavail_int,
            hashes_total=unavail_int,
            uptime_seconds=uptime_obs,
        )

    def get_capabilities(self) -> MinerCapabilities:
        """Report READ_ONLY capabilities with pause/resume CONFIRMED_UNAVAILABLE."""
        now_utc = normalize_utc_timestamp(self._clock())
        ok, _, _ = self._scan_processes()
        if not ok:
            return MinerCapabilities(
                evaluated_at_utc=now_utc,
                status="UNAVAILABLE",
                connection_status="UNREACHABLE",
                local_readiness="CONTROL_DISABLED_LOCALLY",
                observe="CONFIRMED_UNAVAILABLE",
                state_verification="CONFIRMED_UNAVAILABLE",
                pause="CONFIRMED_UNAVAILABLE",
                resume="CONFIRMED_UNAVAILABLE",
            )
        return MinerCapabilities(
            evaluated_at_utc=now_utc,
            status="READ_ONLY",
            connection_status="REACHABLE",
            local_readiness="CONTROL_DISABLED_LOCALLY",
            observe="CONFIRMED_AVAILABLE",
            state_verification="CONFIRMED_UNAVAILABLE",
            pause="CONFIRMED_UNAVAILABLE",
            resume="CONFIRMED_UNAVAILABLE",
        )

    def pause(self) -> CommandResult:
        """Reject pause() locally without signaling or terminating OS processes."""
        now_utc = normalize_utc_timestamp(self._clock())
        return CommandResult(
            command_id=f"kryptex-pause-disabled-{uuid.uuid4().hex[:12]}",
            action="PAUSE",
            requested_at_utc=now_utc,
            completed_at_utc=now_utc,
            delivery="NOT_SENT",
            acceptance="UNKNOWN",
            postcondition="NOT_ATTEMPTED",
            authorization_generation=self._current_auth_generation(),
            revoked_during_execution=False,
            pre_snapshot=None,
            post_snapshot=None,
            causal_attribution="NOT_APPLICABLE",
        )

    def resume(self) -> CommandResult:
        """Reject resume() locally without starting or modifying OS processes."""
        now_utc = normalize_utc_timestamp(self._clock())
        return CommandResult(
            command_id=f"kryptex-resume-disabled-{uuid.uuid4().hex[:12]}",
            action="RESUME",
            requested_at_utc=now_utc,
            completed_at_utc=now_utc,
            delivery="NOT_SENT",
            acceptance="UNKNOWN",
            postcondition="NOT_ATTEMPTED",
            authorization_generation=self._current_auth_generation(),
            revoked_during_execution=False,
            pre_snapshot=None,
            post_snapshot=None,
            causal_attribution="NOT_APPLICABLE",
        )
