"""Miner and Pool adapter interfaces plus deterministic simulated provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import random
from typing import Protocol

from mineops_dw.domain.models import (
    Measurement,
    MiningSession,
    PaymentEvent,
    PoolShare,
    RewardSnapshot,
    normalize_utc_timestamp,
)
from mineops_dw.storage.repositories import MineOpsRepository


@dataclass(frozen=True)
class SimulationStepResult:
    """Artifacts produced by a single deterministic step of SimulatedMinerPoolAdapter."""

    session: MiningSession
    pool_connected: bool
    hashrate_measurement: Measurement
    share: PoolShare | None
    estimated_reward: RewardSnapshot
    pool_reported_reward: RewardSnapshot | None
    payout_event: PaymentEvent | None


class MinerAdapter(Protocol):
    """Interface for controlling and observing a local or simulated miner."""

    def current_session(self) -> MiningSession | None:
        """Return the current mining session state if any."""


class PoolAdapter(Protocol):
    """Interface for querying pool connectivity, shares, balances, and payouts."""

    @property
    def is_connected(self) -> bool:
        """Return True if the pool connection is currently healthy."""


class SimulatedMinerPoolAdapter:
    """Deterministic simulator for mining sessions, Stratum pool shares, and pool payouts.

    Never executes a real miner binary and labels every artifact as 'simulated'.
    Separates local estimated reward, pool-reported pending balance, and payout issued.
    """

    def __init__(
        self,
        *,
        seed: int = 42,
        scenario_name: str = "default",
        nominal_hashrate_hs: float = 1850.0,
        reward_per_accepted_share_btc: Decimal = Decimal("0.00000050"),
        pool_fee_ratio: Decimal = Decimal("0.02"),
        payout_threshold_btc: Decimal = Decimal("0.00000200"),
        network_fee_btc: Decimal = Decimal("0.00000010"),
    ) -> None:
        self._rng = random.Random(seed)
        self._scenario_name = scenario_name
        self._source = f"simulator:{scenario_name}"
        self._nominal_hashrate_hs = nominal_hashrate_hs
        self._reward_per_share = reward_per_accepted_share_btc
        self._pool_fee_ratio = pool_fee_ratio
        self._payout_threshold_btc = payout_threshold_btc
        self._network_fee_btc = network_fee_btc

        self._session: MiningSession | None = None
        self._pool_connected: bool = True
        self._step_counter: int = 0
        self._payout_counter: int = 0
        self._estimated_total_btc: Decimal = Decimal("0")
        self._pool_pending_btc: Decimal = Decimal("0")

    @property
    def is_connected(self) -> bool:
        """Return current simulated pool connectivity state."""
        return self._pool_connected

    def current_session(self) -> MiningSession | None:
        """Return the active or most recent simulated MiningSession."""
        return self._session

    def set_pool_connected(self, connected: bool) -> None:
        """Simulate pool disconnection or reconnection."""
        self._pool_connected = connected

    def start_session(
        self,
        session_id: str = "sim_session_001",
        started_at_utc: datetime | str | None = None,
    ) -> MiningSession:
        """Start a new simulated mining session."""
        if not session_id.startswith("sim_"):
            raise ValueError("Simulated session_id must start with 'sim_'.")
        ts = normalize_utc_timestamp(started_at_utc or datetime.now(UTC))
        self._session = MiningSession(
            id=session_id,
            started_at_utc=ts,
            ended_at_utc=None,
            session_state="running",
            data_mode="simulated",
            miner_name="SimulatedMinerPoolAdapter",
            pool_name=f"simulated_pool_{self._scenario_name}",
            stop_reason=None,
        )
        return self._session

    def pause_session(self, reason: str = "user_paused") -> MiningSession:
        """Pause the current running simulated session."""
        sess = self._require_session()
        self._session = MiningSession(
            id=sess.id,
            started_at_utc=sess.started_at_utc,
            ended_at_utc=None,
            session_state="paused",
            data_mode="simulated",
            miner_name=sess.miner_name,
            pool_name=sess.pool_name,
            stop_reason=reason,
        )
        return self._session

    def resume_session(self) -> MiningSession:
        """Resume a paused simulated session back to running."""
        sess = self._require_session()
        self._session = MiningSession(
            id=sess.id,
            started_at_utc=sess.started_at_utc,
            ended_at_utc=None,
            session_state="running",
            data_mode="simulated",
            miner_name=sess.miner_name,
            pool_name=sess.pool_name,
            stop_reason=None,
        )
        return self._session

    def stop_session(
        self,
        ended_at_utc: datetime | str | None = None,
        reason: str = "user_request",
    ) -> MiningSession:
        """Stop the current simulated session cleanly."""
        sess = self._require_session()
        ts = normalize_utc_timestamp(ended_at_utc or datetime.now(UTC))
        self._session = MiningSession(
            id=sess.id,
            started_at_utc=sess.started_at_utc,
            ended_at_utc=ts,
            session_state="stopped",
            data_mode="simulated",
            miner_name=sess.miner_name,
            pool_name=sess.pool_name,
            stop_reason=reason,
        )
        return self._session

    def fail_session(
        self,
        ended_at_utc: datetime | str | None = None,
        reason: str = "simulated_miner_crash",
    ) -> MiningSession:
        """Transition the current simulated session into an error state."""
        sess = self._require_session()
        ts = normalize_utc_timestamp(ended_at_utc or datetime.now(UTC))
        self._session = MiningSession(
            id=sess.id,
            started_at_utc=sess.started_at_utc,
            ended_at_utc=ts,
            session_state="error",
            data_mode="simulated",
            miner_name=sess.miner_name,
            pool_name=sess.pool_name,
            stop_reason=reason,
        )
        return self._session

    def step_simulation(
        self,
        observed_at_utc: datetime | str | None = None,
        *,
        force_accept: bool | None = None,
        reject_reason: str = "stale",
    ) -> SimulationStepResult:
        """Advance the simulation by one deterministic tick."""
        sess = self._require_session()
        ts = normalize_utc_timestamp(observed_at_utc or datetime.now(UTC))
        self._step_counter += 1
        step_idx = self._step_counter

        if sess.session_state != "running":
            hashrate = Measurement(
                session_id=sess.id,
                metric_name="hashrate_hs",
                value=0.0,
                unit="H/s",
                status="simulated",
                source=self._source,
                observed_at_utc=ts,
                quality_note=f"Session is {sess.session_state}; hashrate is 0.",
            )
            est_snap = RewardSnapshot(
                id=f"sim_rew_est_{sess.id}_{step_idx:04d}",
                session_id=sess.id,
                amount_btc=self._estimated_total_btc,
                reward_stage="estimated",
                status="simulated",
                source=self._source,
                observed_at_utc=ts,
            )
            return SimulationStepResult(
                session=sess,
                pool_connected=self._pool_connected,
                hashrate_measurement=hashrate,
                share=None,
                estimated_reward=est_snap,
                pool_reported_reward=None,
                payout_event=None,
            )

        jitter = self._rng.uniform(-45.0, 45.0)
        current_hs = round(max(0.0, self._nominal_hashrate_hs + jitter), 2)
        hashrate = Measurement(
            session_id=sess.id,
            metric_name="hashrate_hs",
            value=current_hs,
            unit="H/s",
            status="simulated",
            source=self._source,
            observed_at_utc=ts,
        )

        # Evaluate share submission
        share_id = f"sim_share_{sess.id}_{step_idx:04d}"
        if not self._pool_connected:
            share = PoolShare(
                id=share_id,
                session_id=sess.id,
                accepted=False,
                difficulty=1024.0,
                reject_reason="pool_disconnected",
                status="simulated",
                source=self._source,
                observed_at_utc=ts,
            )
            est_snap = RewardSnapshot(
                id=f"sim_rew_est_{sess.id}_{step_idx:04d}",
                session_id=sess.id,
                amount_btc=self._estimated_total_btc,
                reward_stage="estimated",
                status="simulated",
                source=self._source,
                observed_at_utc=ts,
            )
            return SimulationStepResult(
                session=sess,
                pool_connected=False,
                hashrate_measurement=hashrate,
                share=share,
                estimated_reward=est_snap,
                pool_reported_reward=None,
                payout_event=None,
            )

        if force_accept is not None:
            accepted = force_accept
        else:
            # Deterministic ~85% acceptance rate
            accepted = self._rng.random() < 0.85

        share = PoolShare(
            id=share_id,
            session_id=sess.id,
            accepted=accepted,
            difficulty=1024.0,
            reject_reason=None if accepted else reject_reason,
            status="simulated",
            source=self._source,
            observed_at_utc=ts,
        )

        if accepted:
            self._estimated_total_btc += self._reward_per_share
            net_pool_credit = self._reward_per_share * (Decimal("1") - self._pool_fee_ratio)
            self._pool_pending_btc += net_pool_credit

        est_snap = RewardSnapshot(
            id=f"sim_rew_est_{sess.id}_{step_idx:04d}",
            session_id=sess.id,
            amount_btc=self._estimated_total_btc,
            reward_stage="estimated",
            status="simulated",
            source=self._source,
            observed_at_utc=ts,
        )

        payout_event: PaymentEvent | None = None
        if self._pool_pending_btc >= self._payout_threshold_btc:
            self._payout_counter += 1
            payout_amount = self._pool_pending_btc
            self._pool_pending_btc = Decimal("0")
            payout_event = PaymentEvent(
                id=f"sim_payout_{sess.id}_{self._payout_counter:04d}",
                event_type="payout_issued",
                asset="BTC",
                amount=payout_amount,
                network_fee=self._network_fee_btc,
                settlement_status="confirmed",
                data_status="simulated",
                source=self._source,
                external_reference=f"SIM-TX-{sess.id.upper()}-{self._payout_counter:04d}",
                observed_at_utc=ts,
            )

        pool_snap = RewardSnapshot(
            id=f"sim_rew_pool_{sess.id}_{step_idx:04d}",
            session_id=sess.id,
            amount_btc=self._pool_pending_btc,
            reward_stage="pool_reported",
            status="simulated",
            source=self._source,
            observed_at_utc=ts,
        )

        return SimulationStepResult(
            session=sess,
            pool_connected=True,
            hashrate_measurement=hashrate,
            share=share,
            estimated_reward=est_snap,
            pool_reported_reward=pool_snap,
            payout_event=payout_event,
        )

    def sync_step_to_repository(
        self,
        step_result: SimulationStepResult,
        repository: MineOpsRepository,
    ) -> None:
        """Persist all artifacts from a simulation step idempotently into SQLite."""
        repository.upsert_session(step_result.session)
        repository.insert_measurement(step_result.hashrate_measurement)
        if step_result.share is not None:
            repository.insert_pool_share(step_result.share)
        repository.insert_reward_snapshot(step_result.estimated_reward)
        if step_result.pool_reported_reward is not None:
            repository.insert_reward_snapshot(step_result.pool_reported_reward)
        if step_result.payout_event is not None:
            repository.insert_payment_event(step_result.payout_event)

    def _require_session(self) -> MiningSession:
        if self._session is None:
            raise RuntimeError("No active simulated session. Call start_session() first.")
        return self._session
