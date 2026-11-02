"""Telemetry collection service and periodic background scheduler."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import threading

from mineops_dw.adapters.mining import SimulatedMinerPoolAdapter
from mineops_dw.adapters.sensors import SensorAdapter
from mineops_dw.config import AppSettings
from mineops_dw.domain.models import Measurement, MiningSession, normalize_utc_timestamp
from mineops_dw.domain.telemetry import (
    SafetyEvaluation,
    compute_energy_measurement,
    estimate_power_from_tdp,
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
        simulator: SimulatedMinerPoolAdapter | None = None,
        *,
        enable_tdp_fallback: bool = False,
        cpu_tdp_watts: float = 65.0,
        tdp_kappa: float = 1.0,
    ) -> None:
        self._repo = repository
        self._adapters = list(adapters)
        self._settings = settings
        self._simulator = simulator
        self._enable_tdp_fallback = enable_tdp_fallback
        self._cpu_tdp_watts = cpu_tdp_watts
        self._tdp_kappa = tdp_kappa
        self._previous_power: Measurement | None = None
        self._last_cycle_at_utc: str | None = None
        self._last_sim_step_key: tuple[str, str] | None = None
        self._lock = threading.Lock()

    @property
    def last_cycle_at_utc(self) -> str | None:
        """Return the UTC timestamp of the most recent completed collection cycle."""
        return self._last_cycle_at_utc

    @property
    def simulator(self) -> SimulatedMinerPoolAdapter | None:
        """Return the attached simulated miner/pool adapter, if any."""
        return self._simulator

    def set_simulator(self, simulator: SimulatedMinerPoolAdapter | None) -> None:
        """Attach or replace the persistent simulated miner/pool adapter."""
        with self._lock:
            self._simulator = simulator

    def collect_once(
        self,
        observed_at_utc: datetime | str | None = None,
        active_session_id: str | None = None,
    ) -> CollectionCycleResult:
        """Execute all configured sensor adapters once, evaluate safety limits, and persist."""
        with self._lock:
            ts = normalize_utc_timestamp(observed_at_utc or datetime.now(UTC))
            collected: list[Measurement] = []

            active_session: MiningSession | None = None
            if active_session_id is not None:
                active_session = self._repo.get_session(active_session_id)
            else:
                active_session = self._repo.get_active_session(
                    data_mode=self._settings.telemetry_mode
                )

            if active_session is not None:
                if (
                    active_session.data_mode == self._settings.telemetry_mode
                    and active_session.session_state == "running"
                ):
                    effective_session_id: str | None = active_session.id
                else:
                    effective_session_id = None
            else:
                effective_session_id = active_session_id

            for adapter in self._adapters:
                try:
                    batch = adapter.collect(observed_at_utc=ts, session_id=effective_session_id)
                    collected.extend(batch)
                except Exception as exc:
                    logger.error(
                        "Unhandled exception in sensor adapter %s: %s",
                        type(adapter).__name__,
                        exc,
                    )

            # Compute energy (Wh) if cpu_package_power_w was emitted in this cycle (or via optional TDP fallback)
            power_sample = next(
                (m for m in collected if m.metric_name == "cpu_package_power_w"),
                None,
            )
            if (
                self._enable_tdp_fallback
                and (power_sample is None or power_sample.status == "unavailable" or power_sample.value is None)
            ):
                cpu_sample = next(
                    (m for m in collected if m.metric_name == "cpu_percent_total"),
                    None,
                )
                tdp_sample = estimate_power_from_tdp(
                    cpu_sample,
                    tdp_watts=self._cpu_tdp_watts,
                    kappa=self._tdp_kappa,
                    observed_at_utc=ts,
                    session_id=effective_session_id,
                )
                if power_sample is not None:
                    collected = [m for m in collected if m.metric_name != "cpu_package_power_w"]
                collected.append(tdp_sample)
                power_sample = tdp_sample

            if power_sample is not None:
                energy_sample = compute_energy_measurement(
                    self._previous_power,
                    power_sample,
                    session_id=effective_session_id,
                )
                collected.append(energy_sample)
                if power_sample.status != "unavailable" and power_sample.value is not None:
                    self._previous_power = power_sample

            # Advance simulated mining step if a simulated session is running
            if (
                active_session is not None
                and active_session.session_state == "running"
                and active_session.data_mode == "simulated"
                and self._settings.telemetry_mode == "simulated"
                and self._simulator is not None
            ):
                sim_curr = self._simulator.current_session()
                if sim_curr is None or sim_curr.id != active_session.id:
                    self._simulator.start_session(
                        session_id=active_session.id,
                        started_at_utc=active_session.started_at_utc,
                    )
                elif sim_curr.session_state == "paused":
                    self._simulator.resume_session()

                step_key = (active_session.id, ts)
                if self._last_sim_step_key != step_key:
                    step_res = self._simulator.step_simulation(observed_at_utc=ts)
                    self._last_sim_step_key = step_key
                    collected.append(step_res.hashrate_measurement)
                    if step_res.share is not None:
                        self._repo.insert_pool_share(step_res.share)
                    self._repo.insert_reward_snapshot(step_res.estimated_reward)
                    if step_res.pool_reported_reward is not None:
                        self._repo.insert_reward_snapshot(step_res.pool_reported_reward)
                    if step_res.payout_event is not None:
                        self._repo.insert_payment_event(step_res.payout_event)

            persisted_count = 0
            for measurement in collected:
                row_id = self._repo.insert_measurement(measurement)
                if row_id is not None:
                    persisted_count += 1

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
                    if (
                        self._simulator is not None
                        and self._simulator.current_session() is not None
                        and self._simulator.current_session().id == active_session.id
                    ):
                        self._simulator.stop_session(
                            ended_at_utc=ts,
                            reason=safety.reason or "safety_stop",
                        )
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
                    if (
                        self._simulator is not None
                        and self._simulator.current_session() is not None
                        and self._simulator.current_session().id == active_session.id
                    ):
                        self._simulator.pause_session(
                            reason=safety.reason or "safety_pause"
                        )
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
                active_session_id=effective_session_id,
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
