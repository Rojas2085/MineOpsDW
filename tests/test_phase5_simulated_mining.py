"""Phase 5 tests: Deterministic simulated miner/pool adapter, session lifecycle, and payout separation."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from mineops_dw.adapters import SimulatedMinerPoolAdapter
from mineops_dw.storage import MineOpsRepository, SQLiteDatabase


def test_simulated_session_lifecycle_and_pool_disconnect_reconnection(tmp_path: Path) -> None:
    """Verify session states (running, paused, stopped, error) and pool outage/reconnection."""
    db = SQLiteDatabase(tmp_path / "phase5_sim.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)

    sim = SimulatedMinerPoolAdapter(
        seed=100,
        scenario_name="lifecycle_test",
        reward_per_accepted_share_btc=Decimal("0.00000100"),
        pool_fee_ratio=Decimal("0.02"),
        payout_threshold_btc=Decimal("0.00000190"),
    )

    # 1. Start session
    sess = sim.start_session("sim_sess_alpha", started_at_utc="2026-10-21T17:00:00Z")
    assert sess.session_state == "running"
    assert sess.data_mode == "simulated"

    # 2. First accepted share -> estimated = 0.00000100, pool pending = 0.00000098 (< threshold)
    step1 = sim.step_simulation(
        observed_at_utc="2026-10-21T17:00:10Z",
        force_accept=True,
    )
    sim.sync_step_to_repository(step1, repo)
    assert step1.share is not None and step1.share.accepted is True
    assert step1.estimated_reward.amount_btc == "0.000001"
    assert step1.pool_reported_reward is not None
    assert step1.pool_reported_reward.amount_btc == "0.00000098"
    assert step1.payout_event is None

    # 3.Rejected share (stale) -> neither estimated nor pool balance increases
    step2 = sim.step_simulation(
        observed_at_utc="2026-10-21T17:00:20Z",
        force_accept=False,
        reject_reason="stale",
    )
    sim.sync_step_to_repository(step2, repo)
    assert step2.share is not None and step2.share.accepted is False
    assert step2.share.reject_reason == "stale"
    assert step2.estimated_reward.amount_btc == "0.000001"
    assert step2.pool_reported_reward is not None
    assert step2.pool_reported_reward.amount_btc == "0.00000098"

    # 4. Pool disconnects -> share rejected with 'pool_disconnected', pool_reported_reward is None
    sim.set_pool_connected(False)
    assert sim.is_connected is False
    step3 = sim.step_simulation(observed_at_utc="2026-10-21T17:00:30Z")
    sim.sync_step_to_repository(step3, repo)
    assert step3.pool_connected is False
    assert step3.share is not None
    assert step3.share.accepted is False
    assert step3.share.reject_reason == "pool_disconnected"
    assert step3.pool_reported_reward is None

    # 5. Pool reconnects and 2nd accepted share reaches payout threshold (0.00000196 >= 0.00000190)
    sim.set_pool_connected(True)
    step4 = sim.step_simulation(
        observed_at_utc="2026-10-21T17:00:40Z",
        force_accept=True,
    )
    sim.sync_step_to_repository(step4, repo)
    assert step4.payout_event is not None
    assert step4.payout_event.event_type == "payout_issued"
    assert step4.payout_event.amount == "0.00000196"
    assert step4.payout_event.external_reference == "SIM-TX-SIM_SESS_ALPHA-0001"
    # Pool pending balance resets to 0 after payout is issued
    assert step4.pool_reported_reward is not None
    assert step4.pool_reported_reward.amount_btc == "0"
    # Importantly: no exchange deposit is automatically fabricated when pool issues a payout
    deposits = repo.list_payment_events(event_type="deposit_detected")
    assert len(deposits) == 0

    # 6. Pause session -> hashrate is 0.0 and no share is emitted
    sim.pause_session()
    step5 = sim.step_simulation(observed_at_utc="2026-10-21T17:00:50Z")
    sim.sync_step_to_repository(step5, repo)
    assert step5.session.session_state == "paused"
    assert step5.hashrate_measurement.value == 0.0
    assert step5.share is None

    # 7. Resume, then fail session, then stop
    sim.resume_session()
    assert sim.current_session() is not None
    assert sim.current_session().session_state == "running"  # type: ignore[union-attr]

    failed = sim.fail_session(ended_at_utc="2026-10-21T17:01:00Z", reason="simulated_fault")
    repo.upsert_session(failed)
    assert failed.session_state == "error"
    assert failed.stop_reason == "simulated_fault"

    # Re-syncing the exact same step to SQLite is completely idempotent (no duplicate shares/payouts)
    sim.sync_step_to_repository(step4, repo)
    stored_shares = repo.list_pool_shares("sim_sess_alpha")
    stored_payouts = repo.list_payment_events(event_type="payout_issued")
    assert len(stored_shares) == 4
    assert len(stored_payouts) == 1


def test_deterministic_reproducibility_by_seed() -> None:
    """Two simulator instances with the same seed must produce identical hashrates and share outcomes."""
    sim_a = SimulatedMinerPoolAdapter(seed=777, scenario_name="repro")
    sim_b = SimulatedMinerPoolAdapter(seed=777, scenario_name="repro")

    sim_a.start_session("sim_repro_1", started_at_utc="2026-10-21T18:00:00Z")
    sim_b.start_session("sim_repro_1", started_at_utc="2026-10-21T18:00:00Z")

    for i in range(10):
        ts = f"2026-10-21T18:00:{i:02d}Z"
        res_a = sim_a.step_simulation(observed_at_utc=ts)
        res_b = sim_b.step_simulation(observed_at_utc=ts)
        assert res_a.hashrate_measurement.value == res_b.hashrate_measurement.value
        assert res_a.share is not None and res_b.share is not None
        assert res_a.share.accepted == res_b.share.accepted
        assert res_a.estimated_reward.amount_btc == res_b.estimated_reward.amount_btc
