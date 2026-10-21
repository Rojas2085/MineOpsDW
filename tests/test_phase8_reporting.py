"""Phase 8 tests: 30-minute reports, exact UTC windows, gaps, altered clock, idempotency, and export."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

from mineops_dw.domain import Measurement, MiningSession, PoolShare, RewardSnapshot
from mineops_dw.reporting import PeriodicReportGenerator, align_window_utc
from mineops_dw.storage import MineOpsRepository, SQLiteDatabase


def test_align_window_utc_exact_30_minute_boundaries() -> None:
    """Any UTC timestamp must align to its exact 30-minute floor and ceiling."""
    start, end = align_window_utc("2026-10-21T14:17:45.123Z", interval_minutes=30)
    assert start == "2026-10-21T14:00:00.000Z"
    assert end == "2026-10-21T14:30:00.000Z"

    start2, end2 = align_window_utc("2026-10-21T14:49:00Z", interval_minutes=30)
    assert start2 == "2026-10-21T14:30:00.000Z"
    assert end2 == "2026-10-21T15:00:00.000Z"


def test_report_gaps_altered_clock_unavailable_power_and_idempotency(tmp_path: Path) -> None:
    """Verify gap detection, out-of-order insertion, unavailable cost when power missing, and retry."""
    db = SQLiteDatabase(tmp_path / "phase8.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)

    sess = MiningSession(
        id="sim_sess_rep",
        started_at_utc="2026-10-21T14:00:00Z",
        session_state="running",
        data_mode="simulated",
    )
    repo.upsert_session(sess)

    # Insert samples out of chronological order (simulating altered system clock)
    # and with a large gap between 14:00:10Z and 14:20:00Z
    repo.insert_measurement(
        Measurement(
            session_id=sess.id,
            metric_name="cpu_percent_total",
            value=60.0,
            unit="%",
            status="simulated",
            source="simulator:clock",
            observed_at_utc="2026-10-21T14:20:00Z",
        )
    )
    repo.insert_measurement(
        Measurement(
            session_id=sess.id,
            metric_name="cpu_percent_total",
            value=40.0,
            unit="%",
            status="simulated",
            source="simulator:clock",
            observed_at_utc="2026-10-21T14:00:00Z",
        )
    )
    repo.insert_measurement(
        Measurement(
            session_id=sess.id,
            metric_name="cpu_percent_total",
            value=50.0,
            unit="%",
            status="simulated",
            source="simulator:clock",
            observed_at_utc="2026-10-21T14:00:10Z",
        )
    )
    # Thermal sensor unavailable throughout window -> never filled with 0
    repo.insert_measurement(
        Measurement(
            session_id=sess.id,
            metric_name="cpu_temp_c",
            value=None,
            unit="°C",
            status="unavailable",
            source="lhm_http",
            observed_at_utc="2026-10-21T14:00:00Z",
            quality_note="LHM not running",
        )
    )

    # Add 1 accepted and 1 rejected share + separated rewards
    repo.insert_pool_share(
        PoolShare(
            id="sim_sh_1",
            session_id=sess.id,
            accepted=True,
            difficulty=1024.0,
            status="simulated",
            source="simulator:clock",
            observed_at_utc="2026-10-21T14:05:00Z",
        )
    )
    repo.insert_pool_share(
        PoolShare(
            id="sim_sh_2",
            session_id=sess.id,
            accepted=False,
            difficulty=1024.0,
            reject_reason="stale",
            status="simulated",
            source="simulator:clock",
            observed_at_utc="2026-10-21T14:06:00Z",
        )
    )
    repo.insert_reward_snapshot(
        RewardSnapshot(
            id="sim_r_est",
            session_id=sess.id,
            amount_btc="0.00000100",
            reward_stage="estimated",
            status="simulated",
            source="simulator:clock",
            observed_at_utc="2026-10-21T14:10:00Z",
        )
    )

    gen = PeriodicReportGenerator(
        repo,
        sample_interval_seconds=60,  # 30 expected cycles in 30 minutes
        electricity_Wait_rate_usd_per_kwh=Decimal("0.12"),
    )

    rep1 = gen.generate_window_report(
        "2026-10-21T14:00:00Z",
        "2026-10-21T14:30:00Z",
        data_mode="simulated",
        generated_at_utc="2026-10-21T14:30:02Z",
    )

    # 3 distinct cycle timestamps out of 30 expected -> 10.0% coverage and gaps detected
    assert rep1.sample_coverage_pct == 10.0
    assert rep1.gaps_count >= 2

    summary = json.loads(rep1.summary_json)
    assert summary["timezone"] == "UTC"
    assert summary["metrics"]["cpu_percent_total"]["avg"] == 50.0
    assert summary["metrics"]["cpu_percent_total"]["max"] == 60.0
    assert summary["metrics"]["cpu_percent_total"]["min"] == 40.0

    # Unavailable temperature must have avg=None, max=None (never 0)
    assert summary["metrics"]["cpu_temp_c"]["avg"] is None
    assert summary["metrics"]["cpu_temp_c"]["max"] is None
    assert summary["metrics"]["cpu_temp_c"]["dominant_status"] == "unavailable"

    # Electricity cost must be unavailable because no energy_consumed_wh was measured
    assert summary["electricity"]["status"] == "unavailable"
    assert summary["electricity"]["electricity_cost_usd"] is None

    # Shares & rewards summary
    assert summary["shares"]["accepted_count"] == 1
    assert summary["shares"]["rejected_count"] == 1
    assert summary["rewards_separated"]["estimated_latest_btc"] == "0.000001"
    assert summary["rewards_separated"]["pool_reported_latest_btc"] is None

    # Re-running after service restart is idempotent (does not duplicate report in SQLite)
    rep2 = gen.generate_window_report(
        "2026-10-21T14:00:00Z",
        "2026-10-21T14:30:00Z",
        data_mode="simulated",
        generated_at_utc="2026-10-21T14:35:00Z",
    )
    assert rep2.id == rep1.id
    stored_reports = repo.list_periodic_reports(data_mode="simulated")
    assert len(stored_reports) == 1

    # Export JSON and CSV files
    json_path, csv_path = gen.export_report_files(rep1, tmp_path / "exports")
    assert json_path.is_file()
    assert csv_path.is_file()
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "cpu_percent_total" in csv_text
    assert "cpu_temp_c" in csv_text
