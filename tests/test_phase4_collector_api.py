"""Phase 4 tests: Collector service, safety auto-stop/pause, REST API, OpenAPI, and concurrency."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from mineops_dw.api import LocalHttpServer, MineOpsApiService
from mineops_dw.collector import PeriodicCollectorScheduler, TelemetryCollectorService
from mineops_dw.config import AppSettings
from mineops_dw.domain import Measurement, MiningSession, normalize_utc_timestamp
from mineops_dw.storage import MineOpsRepository, SQLiteDatabase


class _StubSensorAdapter:
    """Configurable stub sensor adapter for collector and API integration tests."""

    def __init__(self, cpu_pct: float = 40.0, temp_c: float | None = 62.0, watts: float = 35.0) -> None:
        self.cpu_pct = cpu_pct
        self.temp_c = temp_c
        self.watts = watts

    def collect(
        self,
        observed_at_utc: datetime | str | None = None,
        session_id: str | None = None,
    ) -> list[Measurement]:
        ts = normalize_utc_timestamp(observed_at_utc or "2026-10-21T16:00:00Z")
        items = [
            Measurement(
                session_id=session_id,
                metric_name="cpu_percent_total",
                value=self.cpu_pct,
                unit="%",
                status="simulated",
                source="simulator:stub",
                observed_at_utc=ts,
            ),
            Measurement(
                session_id=session_id,
                metric_name="cpu_package_power_w",
                value=self.watts,
                unit="W",
                status="simulated",
                source="simulator:stub",
                observed_at_utc=ts,
            ),
        ]
        if self.temp_c is not None:
            items.append(
                Measurement(
                    session_id=session_id,
                    metric_name="cpu_temp_c",
                    value=self.temp_c,
                    unit="°C",
                    status="simulated",
                    source="simulator:stub",
                    observed_at_utc=ts,
                )
            )
        else:
            items.append(
                Measurement(
                    session_id=session_id,
                    metric_name="cpu_temp_c",
                    value=None,
                    unit="°C",
                    status="unavailable",
                    source="simulator:stub",
                    observed_at_utc=ts,
                    quality_note="Thermal sensor absent",
                )
            )
        return items


def test_collector_persists_energy_and_enforces_safety_stop(tmp_path: Path) -> None:
    """Collector must persist samples, compute energy on 2nd tick, and stop session if temp >= limit."""
    db = SQLiteDatabase(tmp_path / "phase4.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    settings = AppSettings(MAX_CPU_PERCENT=75.0, MAX_CPU_TEMP_C=80.0, MAX_SESSION_MINUTES=30)

    session = MiningSession(
        id="sim_sess_safety",
        started_at_utc="2026-10-21T16:00:00Z",
        session_state="running",
        data_mode="simulated",
    )
    repo.upsert_session(session)

    stub = _StubSensorAdapter(cpu_pct=50.0, temp_c=65.0, watts=36.0)
    collector = TelemetryCollectorService(repo, [stub], settings)

    # First cycle at 16:00:00Z -> energy is unavailable (needs 2 consecutive power samples)
    res1 = collector.collect_once(
        observed_at_utc="2026-10-21T16:00:00Z",
        active_session_id=session.id,
    )
    assert res1.measurements_collected == 4  # cpu, power, temp, energy
    assert res1.safety_evaluation.should_stop is False

    # Second cycle at 16:10:00Z with high temperature (83 °C >= 80 °C)
    stub.temp_c = 83.0
    res2 = collector.collect_once(
        observed_at_utc="2026-10-21T16:10:00Z",
        active_session_id=session.id,
    )
    assert res2.safety_evaluation.should_stop is True
    assert res2.safety_evaluation.reason == "max_cpu_temp_exceeded"

    # Session in SQLite must now be automatically stopped
    updated_sess = repo.get_session(session.id)
    assert updated_sess is not None
    assert updated_sess.session_state == "stopped"
    assert updated_sess.stop_reason == "max_cpu_temp_exceeded"
    assert updated_sess.ended_at_utc == "2026-10-21T16:10:00.000Z"

    # Verify energy_consumed_wh was computed on the 2nd sample (36W for 10 min = 6.0 Wh)
    energy_rows = repo.list_measurements(metric_name="energy_consumed_wh")
    assert len(energy_rows) == 2
    assert energy_rows[0].status == "unavailable"
    assert energy_rows[1].status == "simulated"
    assert energy_rows[1].value == 6.0


def test_api_endpoints_openapi_validation_and_auth(tmp_path: Path) -> None:
    """API service must serve OpenAPI 3.1, validate inputs, enforce token auth, and forbid public bind."""
    db = SQLiteDatabase(tmp_path / "api_test.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    settings = AppSettings()
    stub = _StubSensorAdapter()
    collector = TelemetryCollectorService(repo, [stub], settings)

    # Non-loopback without token must be rejected
    non_loopback_settings = AppSettings(APP_HOST="0.0.0.0", ALLOW_NON_LOOPBACK=True)
    with pytest.raises(ValueError, match="requires a non-empty local authentication token"):
        MineOpsApiService(db, repo, non_loopback_settings, collector=collector, api_token=None)

    # LocalHttpServer also refuses non-loopback by default
    api = MineOpsApiService(db, repo, settings, collector=collector, api_token="local_secret_tok")
    with pytest.raises(ValueError, match="Refusing to bind HTTP server"):
        LocalHttpServer(api, host="0.0.0.0", port=0, allow_non_loopback=False)

    # Missing token -> 401 Unauthorized
    unauth = api.handle_request("GET", "/health")
    assert unauth.status_code == 401

    auth_headers = {"X-MineOps-Token": "local_secret_tok"}

    # Health check -> 200 OK
    health = api.handle_request("GET", "/health", headers=auth_headers)
    assert health.status_code == 200
    assert health.body["status"] == "ok"
    assert health.body["bound_host"] == "127.0.0.1"
    assert "0001_initial_schema" in health.body["applied_migrations"]

    # OpenAPI schema -> 200 OK with required components
    openapi = api.handle_request("GET", "/openapi.json", headers=auth_headers)
    assert openapi.status_code == 200
    assert openapi.body["openapi"] == "3.1.0"
    assert "Measurement" in openapi.body["components"]["schemas"]
    assert "PaymentEvent" in openapi.body["components"]["schemas"]

    # Trigger collection via POST /api/v1/collect
    collect_resp = api.handle_request("POST", "/api/v1/collect", headers=auth_headers)
    assert collect_resp.status_code == 200
    assert collect_resp.body["measurements_persisted"] == 4

    # Read measurements via GET /api/v1/measurements
    meas_resp = api.handle_request(
        "GET",
        "/api/v1/measurements?metric_name=cpu_percent_total&limit=10",
        headers=auth_headers,
    )
    assert meas_resp.status_code == 200
    assert meas_resp.body["count"] == 1
    assert meas_resp.body["items"][0]["value"] == 40.0

    # Invalid query parameter -> 400 Bad Request
    bad_limit = api.handle_request(
        "GET",
        "/api/v1/measurements?limit=99999",
        headers=auth_headers,
    )
    assert bad_limit.status_code == 400
    assert bad_limit.body["error"] == "validation_error"


def test_http_server_loopback_concurrency_and_scheduler_clean_shutdown(tmp_path: Path) -> None:
    """Verify real loopback HTTP server handles concurrent requests and scheduler stops cleanly."""
    db = SQLiteDatabase(tmp_path / "concurrent.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    settings = AppSettings()
    stub = _StubSensorAdapter()
    collector = TelemetryCollectorService(repo, [stub], settings)
    api = MineOpsApiService(db, repo, settings, collector=collector)

    scheduler = PeriodicCollectorScheduler(collector, interval_seconds=0.05)
    server = LocalHttpServer(api, host="127.0.0.1", port=0)

    scheduler.start()
    server.start()
    try:
        assert scheduler.is_running is True
        base_url = server.base_url
        assert base_url.startswith("http://127.0.0.1:")

        def _fetch_health(_: int) -> int:
            with httpx.Client(timeout=2.0) as client:
                r = client.get(f"{base_url}/health")
                return r.status_code

        with ThreadPoolExecutor(max_workers=6) as pool:
            statuses = list(pool.map(_fetch_health, range(12)))

        assert all(code == 200 for code in statuses)

        with httpx.Client(timeout=2.0) as client:
            m_resp = client.get(f"{base_url}/api/v1/measurements")
            assert m_resp.status_code == 200
            assert m_resp.json()["count"] >= 1
    finally:
        scheduler.stop()
        server.stop()

    assert scheduler.is_running is False
