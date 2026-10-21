"""Phase 11 tests: Optional Android telemetry ingestion, permission denied, battery saver, stale, and auth."""

from __future__ import annotations

from pathlib import Path

import pytest

from mineops_dw.adapters import (
    AndroidTelemetryIngestionService,
    AndroidTelemetryPayload,
)
from mineops_dw.storage import MineOpsRepository, SQLiteDatabase


def test_android_ingestion_auth_permission_battery_saver_stale_and_reconnection(
    tmp_path: Path,
) -> None:
    """Verify invalid token rejection, permission denied, battery saver, stale data, and batch reconnect."""
    db = SQLiteDatabase(tmp_path / "phase11.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)

    service = AndroidTelemetryIngestionService(
        repo,
        expected_device_token="android_secret_tok_123",
        stale_after_seconds=120,
    )

    sample_ok = AndroidTelemetryPayload(
        device_id="pixel_test",
        observed_at_utc="2026-10-21T21:00:00Z",
        battery_percent=84.0,
        battery_temp_c=31.5,
        ram_used_mib=3800.0,
        is_charging=True,
        data_status="simulated",
    )

    # 1. Invalid token -> rejected with PermissionError
    with pytest.raises(PermissionError, match="Invalid or missing Android device token"):
        service.ingest_payload(
            sample_ok,
            provided_token="wrong_token",
            received_at_utc="2026-10-21T21:00:05Z",
        )

    # 2. Valid sample within staleness window
    ingested_ok = service.ingest_payload(
        sample_ok,
        provided_token="android_secret_tok_123",
        received_at_utc="2026-10-21T21:00:05Z",
    )
    by_name = {m.metric_name: m for m in ingested_ok}
    assert by_name["android_battery_percent"].value == 84.0
    assert by_name["android_battery_temp_c"].value == 31.5
    assert by_name["android_ram_used_mib"].value == 3800.0

    # 3. Permission denied on Android device -> all metrics recorded as 'unavailable' (None)
    sample_denied = AndroidTelemetryPayload(
        device_id="pixel_test",
        observed_at_utc="2026-10-21T21:01:00Z",
        permission_denied=True,
    )
    ingested_denied = service.ingest_payload(
        sample_denied,
        provided_token="android_secret_tok_123",
        received_at_utc="2026-10-21T21:01:02Z",
    )
    assert all(m.status == "unavailable" and m.value is None for m in ingested_denied)

    # 4. Battery saver mode active with omitted temperature sensor -> temp is 'unavailable'
    sample_saver = AndroidTelemetryPayload(
        device_id="pixel_test",
        observed_at_utc="2026-10-21T21:02:00Z",
        battery_percent=15.0,
        battery_temp_c=None,
        ram_used_mib=3200.0,
        battery_saver_active=True,
        data_status="simulated",
    )
    ingested_saver = service.ingest_payload(
        sample_saver,
        provided_token="android_secret_tok_123",
        received_at_utc="2026-10-21T21:02:03Z",
    )
    saver_map = {m.metric_name: m for m in ingested_saver}
    assert saver_map["android_battery_percent"].value == 15.0
    assert "Battery Saver" in (saver_map["android_battery_percent"].quality_note or "")
    assert saver_map["android_battery_temp_c"].status == "unavailable"
    assert saver_map["android_battery_temp_c"].value is None

    # 5. Network loss & reconnection with a stale queued sample (10 minutes old > 120s limit)
    sample_stale = AndroidTelemetryPayload(
        device_id="pixel_test",
        observed_at_utc="2026-10-21T20:50:00Z",
        battery_percent=90.0,
        battery_temp_c=30.0,
        ram_used_mib=3500.0,
    )
    ingested_stale = service.ingest_payload(
        sample_stale,
        provided_token="android_secret_tok_123",
        received_at_utc="2026-10-21T21:03:00Z",
    )
    assert all(
        m.status == "unavailable"
        and m.value is None
        and "Stale Android" in (m.quality_note or "")
        for m in ingested_stale
    )
