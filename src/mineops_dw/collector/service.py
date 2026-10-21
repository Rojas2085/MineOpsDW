"""Telemetry collection service and periodic background scheduler."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import threading

from mineops_dw.adapters.sensors import SensorAdapter
from mineops_dw.config import AppSettings
from mineops_dw.domain.models import Measurement, MiningSession, normalize_utc_timestamp
from mineops_dw.domain.telemetry import (
    SafetyEvaluation,
    compute_energy_measurement,
    evaluate_safety_limits,
)
from mineops_dw.storage.repositories import MineOpsRepository

logger = logging.getLogger("mineops_dw.collector")


@dataclass(frozen=True)
class CollectionCycleResult:
    """Summary of a single telemetry collection cycle."""

    observed_at_utc: str
    measurements_collected: int
    measurements_persisted: int
    safety_evaluation: SafetyEvaluation
    active_session_id: str | None = None


class TelemetryCollectorService:
    """Coordinates sensor adapters, energy calculation, safety policies, and SQLite persistence."""

    def __init__(
        self,
        repository: MineOpsRepository,
        adapters: Sequence[SensorAdapter],
        settings: AppSettings,
    ) -> None:
        self._repo = repository
        self._adapters = list(adapters)
        self._settings = settings
        self._previous_power: Measurement | None = None
        self._last_cycle_at_utc: str | None = None
        self._lock = threading.Lock()

    @property
    def last_cycle_at_utc(self) -> str | None:
        """Return the UTC timestamp of the most recent completed collection cycle."""
        return self._last_cycle_at_utc

    def collect_once(
        self,
        observed_at_utc: datetime | str | None = None,
        active_session_id: str | None = None,
    ) -> CollectionCycleResult:
        """Execute all configured sensor adapters once, evaluate safety limits, and persist."""
        with self._lock:
            ts = normalize_utc_timestamp(observed_at_utc or datetime.now(UTC))
            collected: list[Measurement] = []

            for adapter in self._adapters:
                try:
                    batch = adapter.collect(observed_at_utc=ts, session_id=active_session_id)
                    collected.extend(batch)
                except Exception as exc:
                    logger.error(
                        "Unhandled exception in sensor adapter %s: %s",
                        type(adapter).__name__,
                        exc,
                    )

            # Compute energy (Wh) if cpu_package_power_w was emitted in this cycle
            power_sample = next(
                (m for m in collected if m.metric_name == "cpu_package_power_w"),
                None,
            )
            if power_sample is not None:
                energy_sample = compute_energy_measurement(
                    self._previous_power,
                    power_sample,
                    session_id=active_session_id,
                )
                collected.append(energy_sample)
                if power_sample.status != "unavailable" and power_sample.value is not None:
                    self._previous_power = power_sample

            persisted_count = 0
            for measurement in collected:
                row_id = self._repo.insert_measurement(measurement)
                if row_id is not None:
                    persisted_count += 1

            active_session: MiningSession | None = None
            if active_session_id is not None:
                active_session = self._repo.get_session(active_session_id)

            safety = evaluate_safety_limits(
                collected,
                max_cpu_percent=self._settings.max_cpu_percent,
                max_cpu_temp_c=self._settings.max_cpu_temp_c,
                max_session_minutes=self._settings.max_session_minutes,
                session_started_at_utc=(
                    active_session.started_at_utc if active_session is not None else None
                ),
                now_utc=ts,
            )

            if active_session is not None and active_session.session_state == "running":
                if safety.should_stop:
                    updated = MiningSession(
                        id=active_session.id,
                        started_at_utc=active_session.started_at_utc,
                        ended_at_utc=ts,
                        session_state="stopped",
                        data_mode=active_session.data_mode,
                        miner_name=active_session.miner_name,
                        pool_name=active_session.pool_name,
                        stop_reason=safety.reason,
                    )
                    self._repo.upsert_session(updated)
                    logger.warning(
                        "Session %s automatically stopped due to safety limit: %s",
                        active_session.id,
                        safety.reason,
                    )
                elif safety.should_pause:
                    updated = MiningSession(
                        id=active_session.id,
                        started_at_utc=active_session.started_at_utc,
                        ended_at_utc=None,
                        session_state="paused",
                        data_mode=active_session.data_mode,
                        miner_name=active_session.miner_name,
                        pool_name=active_session.pool_name,
                        stop_reason=safety.reason,
                    )
                    self._repo.upsert_session(updated)
                    logger.warning(
                        "Session %s automatically paused due to safety limit: %s",
                        active_session.id,
                        safety.reason,
                    )

            self._last_cycle_at_utc = ts
            return CollectionCycleResult(
                observed_at_utc=ts,
                measurements_collected=len(collected),
                measurements_persisted=persisted_count,
                safety_evaluation=safety,
                active_session_id=active_session_id,
            )


class PeriodicCollectorScheduler:
    """Runs TelemetryCollectorService periodically on a daemon-safe background thread."""

    def __init__(
        self,
        collector: TelemetryCollectorService,
        interval_seconds: float,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive.")
        self._collector = collector
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        """Return True if the background scheduler thread is currently active."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start periodic collection in a background thread."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="MineOpsCollectorScheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_seconds: float = 5.0) -> None:
        """Signal the background loop to stop and wait cleanly for termination."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout_seconds)
        self._thread = None

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._collector.collect_once()
            except Exception as exc:
                logger.error("Periodic collection cycle failed: %s", exc)
            self._stop_event.wait(self._interval_seconds)
