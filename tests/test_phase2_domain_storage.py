"""Phase 2 tests: Domain models, UTC normalization, SQLite migrations, rollback, and idempotency."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3

import pytest
from pydantic import ValidationError

from mineops_dw.domain import (
    Measurement,
    MiningSession,
    PaymentEvent,
    PeriodicReport,
    PoolShare,
    PriceSnapshot,
    RewardSnapshot,
)
from mineops_dw.storage import MigrationError, MineOpsRepository, SQLiteDatabase


def test_utc_timestamp_normalization_and_naive_rejection() -> None:
    """Timestamps with timezone offsets must normalize to UTC 'Z', and naive datetimes must fail."""
    tz_minus_4 = timezone(timedelta(hours=-4))
    local_dt = datetime(2026, 10, 21, 10, 30, 0, tzinfo=tz_minus_4)

    m = Measurement(
        metric_name="cpu_percent_total",
        value=24.5,
        unit="%",
        status="measured",
        source="psutil",
        observed_at_utc=local_dt,
    )
    assert m.observed_at_utc == "2026-10-21T14:30:00.000Z"

    with pytest.raises(ValidationError, match="timezone-aware"):
        Measurement(
            metric_name="cpu_percent_total",
            value=24.5,
            unit="%",
            status="measured",
            source="psutil",
            observed_at_utc=datetime(2026, 10, 21, 10, 30, 0),
        )


def test_unavailable_measurement_invariants() -> None:
    """Unavailable sensors must have value=None and an explicit quality_note; never 0."""
    valid_unavailable = Measurement(
        metric_name="cpu_temp_c",
        value=None,
        unit="°C",
        status="unavailable",
        source="lhm_http",
        observed_at_utc="2026-10-21T14:00:00Z",
        quality_note="Libre Hardware Monitor is not running",
    )
    assert valid_unavailable.value is None

    # Passing 0.0 for an unavailable sensor is strictly forbidden
    with pytest.raises(ValidationError, match="value must be None"):
        Measurement(
            metric_name="cpu_temp_c",
            value=0.0,
            unit="°C",
            status="unavailable",
            source="lhm_http",
            observed_at_utc="2026-10-21T14:00:00Z",
            quality_note="Sensor missing",
        )

    # Missing quality_note on unavailable sensor is forbidden
    with pytest.raises(ValidationError, match="quality_note"):
        Measurement(
            metric_name="cpu_temp_c",
            value=None,
            unit="°C",
            status="unavailable",
            source="lhm_http",
            observed_at_utc="2026-10-21T14:00:00Z",
        )

    # Out-of-range percentage (> 100%) must fail validation
    with pytest.raises(ValidationError, match="out of physical range"):
        Measurement(
            metric_name="cpu_percent_total",
            value=105.0,
            unit="%",
            status="measured",
            source="psutil",
            observed_at_utc="2026-10-21T14:00:00Z",
        )


def test_financial_decimal_precision_and_float_rejection() -> None:
    """Binary floats must be rejected for BTC/financial amounts; exact Decimal strings preserved."""
    with pytest.raises(ValidationError, match="Binary float is forbidden"):
        RewardSnapshot(
            id="rew_1",
            amount_btc=0.00000125,  # type: ignore[arg-type]
            reward_stage="estimated",
            status="simulated",
            source="simulator:basic",
            observed_at_utc="2026-10-21T14:00:00Z",
        )

    snap = RewardSnapshot(
        id="rew_1",
        amount_btc=Decimal("0.00000001"),
        reward_stage="estimated",
        status="simulated",
        source="simulator:basic",
        observed_at_utc="2026-10-21T14:00:00Z",
    )
    assert snap.amount_btc == "0.00000001"


def test_migrations_from_empty_db_and_rollback_on_failure(tmp_path: Path) -> None:
    """Migrations must apply cleanly from an empty file and roll back atomically on error."""
    db_file = tmp_path / "test_mineops.sqlite3"
    db = SQLiteDatabase(db_file)

    applied = db.apply_migrations()
    assert applied == ["0001_initial_schema"]
    # Running a second time is idempotent
    assert db.apply_migrations() == []
    assert db.applied_migrations() == ["0001_initial_schema"]

    # Create a custom migration folder with a failing second migration
    bad_migrations_dir = tmp_path / "bad_migrations"
    bad_migrations_dir.mkdir()
    bad_sql = (
        "CREATE TABLE temp_test_rollback (id INTEGER PRIMARY KEY);\n"
        "INSERT INTO non_existent_table_xyz VALUES (1);\n"
    )
    (bad_migrations_dir / "0002_broken.sql").write_text(bad_sql, encoding="utf-8")

    with pytest.raises(MigrationError, match="0002_broken"):
        db.apply_migrations(migrations_dir=bad_migrations_dir)

    # Verify rollback: temp_test_rollback must NOT exist and 0002_broken must NOT be recorded
    assert db.applied_migrations() == ["0001_initial_schema"]
    with db.session() as conn:
        tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='temp_test_rollback';"
        ).fetchone()
        assert tbl is None


def test_crud_persistence_across_restart_and_idempotency(tmp_path: Path) -> None:
    """All entities must persist across connection restarts, enforce foreign keys, and ignore duplicates."""
    db_file = tmp_path / "persisted.sqlite3"
    db = SQLiteDatabase(db_file)
    db.apply_migrations()
    repo = MineOpsRepository(db)

    # 1. MiningSession
    session = MiningSession(
        id="sim_session_001",
        started_at_utc="2026-10-21T14:00:00Z",
        session_state="running",
        data_mode="simulated",
        miner_name="SimulatedMinerPoolAdapter",
        pool_name="simulated_pool",
    )
    repo.upsert_session(session)

    # 2. Measurements (1 measured + 1 unavailable + duplicate attempt)
    m_cpu = Measurement(
        session_id=session.id,
        metric_name="cpu_percent_total",
        value=42.0,
        unit="%",
        status="measured",
        source="psutil",
        observed_at_utc="2026-10-21T14:00:10Z",
    )
    m_temp = Measurement(
        session_id=session.id,
        metric_name="cpu_temp_c",
        value=None,
        unit="°C",
        status="unavailable",
        source="lhm_http",
        observed_at_utc="2026-10-21T14:00:10Z",
        quality_note="LHM not active",
    )
    assert repo.insert_measurement(m_cpu) is not None
    assert repo.insert_measurement(m_temp) is not None
    # Duplicate measurement at exact same timestamp/source/metric is ignored idempotently
    assert repo.insert_measurement(m_cpu) is None

    # 3. PoolShare (accepted + rejected + duplicate) and Foreign Key check
    share_ok = PoolShare(
        id="sim_share_01",
        session_id=session.id,
        accepted=True,
        difficulty=1024.0,
        status="simulated",
        source="simulator:default",
        observed_at_utc="2026-10-21T14:01:00Z",
    )
    share_rej = PoolShare(
        id="sim_share_02",
        session_id=session.id,
        accepted=False,
        difficulty=1024.0,
        reject_reason="stale",
        status="simulated",
        source="simulator:default",
        observed_at_utc="2026-10-21T14:01:20Z",
    )
    assert repo.insert_pool_share(share_ok) is True
    assert repo.insert_pool_share(share_rej) is True
    assert repo.insert_pool_share(share_ok) is False  # Idempotent duplicate

    # Foreign key integrity: inserting a share for a non-existent session must raise IntegrityError
    orphan_share = PoolShare(
        id="sim_share_orphan",
        session_id="sim_non_existent",
        accepted=True,
        status="simulated",
        source="simulator:default",
        observed_at_utc="2026-10-21T14:02:00Z",
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.insert_pool_share(orphan_share)

    # 4. Separate financial states: RewardSnapshot (estimated vs pool_reported) & PaymentEvent
    rew_est = RewardSnapshot(
        id="sim_rew_est_01",
        session_id=session.id,
        amount_btc="0.00000150",
        reward_stage="estimated",
        status="simulated",
        source="simulator:calc",
        observed_at_utc="2026-10-21T14:05:00Z",
    )
    rew_pool = RewardSnapshot(
        id="sim_rew_pool_01",
        session_id=session.id,
        amount_btc="0.00000140",
        reward_stage="pool_reported",
        status="simulated",
        source="simulator:pool",
        observed_at_utc="2026-10-21T14:10:00Z",
    )
    assert repo.insert_reward_snapshot(rew_est) is True
    assert repo.insert_reward_snapshot(rew_pool) is True
    assert repo.insert_reward_snapshot(rew_est) is False

    payout_ev = PaymentEvent(
        id="sim_pay_01",
        event_type="payout_issued",
        asset="BTC",
        amount="0.00020000",
        network_fee="0.00001000",
        settlement_status="confirmed",
        data_status="simulated",
        source="simulator:pool",
        external_reference="SIM-TX-0001",
        observed_at_utc="2026-10-21T14:15:00Z",
    )
    deposit_ev = PaymentEvent(
        id="sim_dep_01",
        event_type="deposit_detected",
        asset="BTC",
        amount="0.00019000",
        settlement_status="confirmed",
        data_status="simulated",
        source="simulator:binance",
        external_reference="SIM-TX-0001",
        observed_at_utc="2026-10-21T14:25:00Z",
    )
    assert repo.insert_payment_event(payout_ev) is True
    assert repo.insert_payment_event(deposit_ev) is True
    assert repo.insert_payment_event(payout_ev) is False

    # 5. PriceSnapshot & PeriodicReport
    price = PriceSnapshot(
        id="price_btc_usd_1",
        asset="BTC",
        quote_asset="USD",
        price="68500.25",
        status="simulated",
        source="simulator:market",
        observed_at_utc="2026-10-21T14:00:00Z",
    )
    assert repo.insert_price_snapshot(price) is True
    assert repo.insert_price_snapshot(price) is False

    report = PeriodicReport(
        id="rep_20261021_1400_1430_sim",
        window_start_utc="2026-10-21T14:00:00Z",
        window_end_utc="2026-10-21T14:30:00Z",
        data_mode="simulated",
        sample_coverage_pct=100.0,
        gaps_count=0,
        summary_json='{"cpu_avg": 42.0, "cpu_temp_c": null}',
        generated_at_utc="2026-10-21T14:30:01Z",
    )
    assert repo.insert_periodic_report(report) is True
    assert repo.insert_periodic_report(report) is False

    # Re-instantiate SQLiteDatabase and MineOpsRepository to verify persistence across restarts
    restarted_db = SQLiteDatabase(db_file)
    restarted_repo = MineOpsRepository(restarted_db)

    loaded_session = restarted_repo.get_session("sim_session_001")
    assert loaded_session is not None
    assert loaded_session.session_state == "running"

    measurements = restarted_repo.list_measurements()
    assert len(measurements) == 2
    temp_row = next(m for m in measurements if m.metric_name == "cpu_temp_c")
    assert temp_row.value is None
    assert temp_row.status == "unavailable"

    shares = restarted_repo.list_pool_shares("sim_session_001")
    assert len(shares) == 2
    assert shares[0].accepted is True
    assert shares[1].accepted is False
    assert shares[1].reject_reason == "stale"

    est_rewards = restarted_repo.list_reward_snapshots(reward_stage="estimated")
    pool_rewards = restarted_repo.list_reward_snapshots(reward_stage="pool_reported")
    assert len(est_rewards) == 1
    assert len(pool_rewards) == 1
    assert est_rewards[0].amount_btc == "0.0000015"
    assert pool_rewards[0].amount_btc == "0.0000014"

    payouts = restarted_repo.list_payment_events(event_type="payout_issued")
    deposits = restarted_repo.list_payment_events(event_type="deposit_detected")
    assert len(payouts) == 1
    assert len(deposits) == 1
    assert payouts[0].amount == "0.0002"
    assert deposits[0].amount == "0.00019"

    reports = restarted_repo.list_periodic_reports(data_mode="simulated")
    assert len(reports) == 1
    assert reports[0].sample_coverage_pct == 100.0
