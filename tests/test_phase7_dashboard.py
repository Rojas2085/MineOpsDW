"""Phase 7 tests: Cyberpunk Mining Operations Center UI, history ordering, mode separation, and contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from mineops_dw.adapters import HostResourceSensorAdapter, SimulatedMinerPoolAdapter
from mineops_dw.api import LocalHttpServer, MineOpsApiService
from mineops_dw.collector import TelemetryCollectorService
from mineops_dw.config import AppSettings
from mineops_dw.domain import Measurement, PaymentEvent, PriceSnapshot, RewardSnapshot
from mineops_dw.storage import MineOpsRepository, SQLiteDatabase


def test_dashboard_html_and_js_served_with_separated_units_and_accessibility(
    tmp_path: Path,
) -> None:
    """Verify GET / and GET /dashboard.js render Mining Operations Center, 3 panels, and strict mode separation."""
    db = SQLiteDatabase(tmp_path / "phase7.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    settings = AppSettings()
    api = MineOpsApiService(db, repo, settings)

    server = LocalHttpServer(api, host="127.0.0.1", port=0)
    server.start()
    try:
        with httpx.Client(timeout=2.0) as client:
            html_resp = client.get(f"{server.base_url}/")
            js_resp = client.get(f"{server.base_url}/dashboard.js")

        assert html_resp.status_code == 200
        assert "text/html" in html_resp.headers.get("content-type", "")
        html_text = html_resp.text

        # Cyberpunk Mining Operations Center identity and palette
        assert "MineOps DW — Mining Operations Center" in html_text
        assert "--bg: #060a12;" in html_text
        assert "--neon-green: #00ff9d;" in html_text
        assert "--electric-blue: #00d2ff;" in html_text
        assert "--btc-gold: #f7931a;" in html_text

        # Three main panels: Left (hardware), Center (Mining Core), Right (Bitcoin economics)
        assert 'id="panel-left-resources"' in html_text
        assert 'id="panel-center-session"' in html_text
        assert 'id="panel-right-market"' in html_text

        # Central Mining Core SVG reactor and honest hashes indicator
        assert 'id="mining-core-svg"' in html_text
        assert 'id="core-hashrate-value"' in html_text
        assert 'id="core-hashes-processed"' in html_text
        assert "N/D (Sin fuente)" in html_text

        # Real telemetry collection control (no fake "Start Miner" button)
        assert 'id="btn-collect"' in html_text
        assert "Recolectar telemetría" in html_text
        assert "Iniciar minería" not in html_text

        # Bottom analytics zone (SVG charts + 30-minute reports) & secondary collapsible table drawer
        assert 'id="panel-bottom-analytics"' in html_text
        assert 'id="chart-hardware-container"' in html_text
        assert 'id="chart-hashrate-container"' in html_text
        assert 'id="reports-30m-box"' in html_text
        assert 'id="telemetry-details-drawer"' in html_text

        # Responsive CSS grid & reduced-motion accessibility
        assert "@media (max-width: 960px)" in html_text
        assert "@media (prefers-reduced-motion: reduce)" in html_text
        assert 'aria-live="polite"' in html_text
        assert 'role="status"' in html_text

        # Separate unit groups (never mix % with W)
        assert 'data-unit-group="percent"' in html_text
        assert 'data-unit-group="memory-mib"' in html_text
        assert 'data-unit-group="temperature-c"' in html_text
        assert 'data-unit-group="power-energy"' in html_text

        # Four financial states explicitly separated
        assert "fin-estimated" in html_text
        assert "fin-pool-reported" in html_text
        assert "fin-payout-issued" in html_text
        assert "fin-deposit-detected" in html_text

        # JS bundle includes deduplication, strict mode isolation, and existing API endpoints
        assert js_resp.status_code == 200
        assert "application/javascript" in js_resp.headers.get("content-type", "")
        js_text = js_resp.text
        assert "function deduplicateMeasurements" in js_text
        assert "function filterByTelemetryMode" in js_text
        assert 'telemetryMode === "real"' in js_text
        assert 'statusOrDataStatus !== "simulated"' in js_text
        assert "Sin fuente real de H/s" in js_text
        assert "No disponible" in js_text
        assert "Sin registros para el filtro actual (empty)" in js_text

        # Verify JS consumes existing real backend endpoints (including BOB prices, reports, reconciliation, collect, sessions)
        assert 'fetch("/health")' in js_text
        assert 'fetch("/api/v1/measurements?limit=300")' in js_text
        assert 'fetch("/api/v1/prices?quote_asset=USD")' in js_text
        assert 'fetch("/api/v1/prices?quote_asset=BOB")' in js_text
        assert 'fetch("/api/v1/reconciliation")' in js_text
        assert 'fetch("/api/v1/reports")' in js_text
        assert 'fetch("/api/v1/sessions")' in js_text
        assert 'fetch("/api/v1/collect"' in js_text
        assert "state.activeSession = sessionsPayload.active_session || null;" in js_text
        assert 'id="btn-sim-start"' in html_text
        assert 'id="btn-sim-pause"' in html_text
        assert 'id="btn-sim-resume"' in html_text
        assert 'id="btn-sim-stop"' in html_text
    finally:
        server.stop()


def test_api_measurements_endpoint_returns_most_recent_samples_and_separates_modes(
    tmp_path: Path,
) -> None:
    """Verify /api/v1/measurements returns the newest samples when exceeding limit and preserves mode tags."""
    db = SQLiteDatabase(tmp_path / "phase7_modes.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    settings = AppSettings(TELEMETRY_MODE="real")
    api = MineOpsApiService(db, repo, settings)

    base_dt = datetime(2026, 10, 21, 18, 0, 0, tzinfo=timezone.utc)

    # 1. Seed 5 older simulated hashrate samples
    for i in range(5):
        repo.insert_measurement(
            Measurement(
                metric_name="hashrate_hs",
                value=1800.0 + i * 10.0,
                unit="H/s",
                status="simulated",
                source="simulator:live_demo",
                observed_at_utc=base_dt + timedelta(seconds=i * 10),
            )
        )

    # 2. Seed 15 newer real hardware samples (CPU measured + CPU temp unavailable)
    for j in range(15):
        ts = base_dt + timedelta(minutes=5, seconds=j * 10)
        repo.insert_measurement(
            Measurement(
                metric_name="cpu_percent_total",
                value=10.0 + j,
                unit="%",
                status="measured",
                source="win32_ctypes",
                observed_at_utc=ts,
            )
        )
        repo.insert_measurement(
            Measurement(
                metric_name="cpu_temp_c",
                value=None,
                unit="°C",
                status="unavailable",
                source="lhm_http",
                observed_at_utc=ts,
                quality_note="LHM not running",
            )
        )

    # 3. Seed separated financial stages (estimated vs confirmed deposit) & prices (simulated vs measured)
    repo.insert_reward_snapshot(
        RewardSnapshot(
            id="rew_est_real_1",
            amount_btc="0.00000120",
            reward_stage="estimated",
            status="estimated",
            source="local_estimator",
            observed_at_utc=base_dt + timedelta(minutes=10),
        )
    )
    repo.insert_payment_event(
        PaymentEvent(
            id="dep_real_1",
            event_type="deposit_detected",
            asset="BTC",
            amount="0.00050000",
            settlement_status="confirmed",
            data_status="measured",
            source="binance_read_only_api",
            external_reference="REAL-TX-01",
            observed_at_utc=base_dt + timedelta(minutes=11),
        )
    )
    repo.insert_price_snapshot(
        PriceSnapshot(
            id="p_sim_usd",
            asset="BTC",
            quote_asset="USD",
            price="68000.00",
            status="simulated",
            source="simulator:market",
            observed_at_utc=base_dt,
        )
    )
    repo.insert_price_snapshot(
        PriceSnapshot(
            id="p_real_usd",
            asset="BTC",
            quote_asset="USD",
            price="84500.00",
            status="measured",
            source="market_http",
            observed_at_utc=base_dt + timedelta(minutes=10),
        )
    )

    # Verify /health reports telemetry_mode == 'real'
    health_resp = api.handle_request("GET", "/health")
    assert health_resp.status_code == 200
    assert health_resp.body["telemetry_mode"] == "real"

    # Request limit=6 from /api/v1/measurements -> must return the 6 NEWEST samples (from the last 3 real cycles),
    # NOT the old simulated hashrate samples at the start of the table!
    meas_resp = api.handle_request("GET", "/api/v1/measurements?limit=6")
    assert meas_resp.status_code == 200
    items = meas_resp.body["items"]
    assert len(items) == 6
    assert all(m["status"] in {"measured", "unavailable"} for m in items)
    # Chronological ascending order preserved
    timestamps = [m["observed_at_utc"] for m in items]
    assert timestamps == sorted(timestamps)
    # Latest CPU sample is 10.0 + 14 = 24.0, and unavailable temp remains None (never 0)
    cpu_items = [m for m in items if m["metric_name"] == "cpu_percent_total"]
    temp_items = [m for m in items if m["metric_name"] == "cpu_temp_c"]
    assert cpu_items[-1]["value"] == 24.0
    assert temp_items[-1]["value"] is None
    assert temp_items[-1]["status"] == "unavailable"

    # Verify rewards and payments remain strictly separated
    rewards_resp = api.handle_request("GET", "/api/v1/rewards?reward_stage=estimated")
    payments_resp = api.handle_request("GET", "/api/v1/payments?event_type=deposit_detected")
    assert rewards_resp.body["items"][0]["reward_stage"] == "estimated"
    assert rewards_resp.body["items"][0]["status"] == "estimated"
    assert payments_resp.body["items"][0]["event_type"] == "deposit_detected"
    assert payments_resp.body["items"][0]["settlement_status"] == "confirmed"


def test_react_typescript_source_files_match_api_contracts() -> None:
    """Verify React + TypeScript source files exist and define strict quality and unit types."""
    root = Path(__file__).resolve().parents[1]
    pkg_json = root / "frontend" / "package.json"
    ts_config = root / "frontend" / "tsconfig.json"
    api_types = root / "frontend" / "src" / "types" / "api.ts"
    app_tsx = root / "frontend" / "src" / "App.tsx"

    assert pkg_json.is_file()
    assert ts_config.is_file()
    assert api_types.is_file()
    assert app_tsx.is_file()

    types_content = api_types.read_text(encoding="utf-8")
    assert '"measured" | "estimated" | "unavailable" | "simulated"' in types_content
    assert "export function deduplicateMeasurements" in types_content
    assert "export function formatMeasurementValue" in types_content

    app_content = app_tsx.read_text(encoding="utf-8")
    assert "panel-resources" in app_content
    assert "panel-mining-session" in app_content
    assert "panel-market-price" in app_content


def test_simulated_session_lifecycle_endpoints_and_collection_linking(
    tmp_path: Path,
) -> None:
    """Verify start, query, pause, resume, stop, invalid transitions, and measurement session_id linking."""
    db = SQLiteDatabase(tmp_path / "phase7_sim_lifecycle.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    settings = AppSettings(TELEMETRY_MODE="simulated", MAX_CPU_PERCENT=100)
    sim = SimulatedMinerPoolAdapter(seed=99, scenario_name="api_lifecycle")
    host_adapter = HostResourceSensorAdapter(psutil_module=None, use_win32_fallback=True)
    collector = TelemetryCollectorService(repo, [host_adapter], settings, simulator=sim)
    api = MineOpsApiService(db, repo, settings, collector=collector, simulator=sim)

    # 1. Initially no active session
    init_sessions = api.handle_request("GET", "/api/v1/sessions")
    assert init_sessions.status_code == 200
    assert init_sessions.body["active_session"] is None
    assert init_sessions.body["count"] == 0

    # Invalid pause when no session exists -> 404
    no_sess_pause = api.handle_request("POST", "/api/v1/sessions/pause")
    assert no_sess_pause.status_code == 404

    # 2. Start a simulated session -> 200 OK, id starts with 'sim_', state='running'
    start_resp = api.handle_request("POST", "/api/v1/sessions/start")
    assert start_resp.status_code == 200
    started = start_resp.body["item"]
    sess_id = started["id"]
    assert sess_id.startswith("sim_")
    assert started["data_mode"] == "simulated"
    assert started["session_state"] == "running"

    # Reject duplicate simultaneous start while a session is active -> 409 Conflict
    dup_start = api.handle_request("POST", "/api/v1/sessions/start")
    assert dup_start.status_code == 409
    assert dup_start.body["error"] == "session_already_active"

    # Reject resume while already running -> 409 Conflict
    bad_resume = api.handle_request("POST", "/api/v1/sessions/resume")
    assert bad_resume.status_code == 409
    assert bad_resume.body["error"] == "invalid_transition"

    # GET /api/v1/sessions returns the running session as active_session
    active_check = api.handle_request("GET", "/api/v1/sessions")
    assert active_check.status_code == 200
    assert active_check.body["active_session"]["id"] == sess_id
    assert active_check.body["active_session"]["session_state"] == "running"

    # 3. Trigger collection while running -> links measurements to sess_id, keeps CPU/RAM measured and hashrate simulated
    col1 = api.handle_request("POST", "/api/v1/collect")
    assert col1.status_code == 200
    assert col1.body["active_session_id"] == sess_id

    stored_meas = repo.list_measurements(limit=50)
    assert all(m.session_id == sess_id for m in stored_meas)
    by_metric = {m.metric_name: m for m in stored_meas}
    assert by_metric["ram_usage_percent"].status == "measured"
    assert by_metric["hashrate_hs"].status == "simulated"
    assert by_metric["hashrate_hs"].value is not None and by_metric["hashrate_hs"].value > 0
    assert len(repo.list_pool_shares(sess_id)) == 1
    assert len(repo.list_reward_snapshots(reward_stage="estimated")) == 1

    # 4. Pause session -> 200 OK, state='paused'
    pause_resp = api.handle_request("POST", "/api/v1/sessions/pause")
    assert pause_resp.status_code == 200
    assert pause_resp.body["item"]["session_state"] == "paused"
    assert pause_resp.body["item"]["stop_reason"] == "user_paused"

    # Reject second pause while already paused -> 409 Conflict
    dup_pause = api.handle_request("POST", "/api/v1/sessions/pause")
    assert dup_pause.status_code == 409

    # Collection while paused must NOT generate new simulated mining shares/steps for the session
    col_paused = api.handle_request("POST", "/api/v1/collect")
    assert col_paused.status_code == 200
    assert col_paused.body["active_session_id"] is None
    assert len(repo.list_pool_shares(sess_id)) == 1

    # 5. Resume session -> 200 OK, state='running', next collection advances simulation again
    resume_resp = api.handle_request("POST", "/api/v1/sessions/resume")
    assert resume_resp.status_code == 200
    assert resume_resp.body["item"]["session_state"] == "running"

    col2 = api.handle_request("POST", "/api/v1/collect")
    assert col2.status_code == 200
    assert col2.body["active_session_id"] == sess_id
    assert len(repo.list_pool_shares(sess_id)) == 2

    # 6. Stop session -> 200 OK, state='stopped', ended_at_utc populated, active_session becomes None
    stop_resp = api.handle_request("POST", "/api/v1/sessions/stop")
    assert stop_resp.status_code == 200
    assert stop_resp.body["item"]["session_state"] == "stopped"
    assert stop_resp.body["item"]["ended_at_utc"] is not None

    # Reject stopping or pausing an already stopped session -> 409 Conflict
    assert api.handle_request("POST", "/api/v1/sessions/stop").status_code == 409
    assert api.handle_request("POST", "/api/v1/sessions/pause").status_code == 409
    assert api.handle_request("POST", "/api/v1/sessions/resume").status_code == 409

    after_stop = api.handle_request("GET", "/api/v1/sessions")
    assert after_stop.body["active_session"] is None
    assert after_stop.body["count"] == 1
    assert after_stop.body["items"][0]["session_state"] == "stopped"


def test_real_mode_isolates_sessions_and_prevents_duplicate_simulation_steps(
    tmp_path: Path,
) -> None:
    """Verify real mode never exposes simulated sessions and collector deduplicates same-timestamp steps."""
    db = SQLiteDatabase(tmp_path / "phase7_isolation.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)

    # 1. Start a simulated session in simulated mode and verify same-timestamp collection does not duplicate steps
    sim_settings = AppSettings(TELEMETRY_MODE="simulated", MAX_CPU_PERCENT=100)
    sim = SimulatedMinerPoolAdapter(seed=123, scenario_name="dedup_test")
    host_adapter = HostResourceSensorAdapter(psutil_module=None, use_win32_fallback=True)
    sim_collector = TelemetryCollectorService(repo, [host_adapter], sim_settings, simulator=sim)
    sim_api = MineOpsApiService(db, repo, sim_settings, collector=sim_collector, simulator=sim)

    started = sim_api.handle_request("POST", "/api/v1/sessions/start").body["item"]
    sess_id = started["id"]

    fixed_ts = "2026-10-22T15:00:00Z"
    sim_collector.collect_once(observed_at_utc=fixed_ts)
    sim_collector.collect_once(observed_at_utc=fixed_ts)
    # Exactly 1 share and 1 hashrate sample must be generated for fixed_ts
    assert len(repo.list_pool_shares(sess_id)) == 1
    assert len(repo.list_measurements(metric_name="hashrate_hs")) == 1

    # 2. Switch API service to TELEMETRY_MODE="real" over the same SQLite database
    real_settings = AppSettings(TELEMETRY_MODE="real")
    real_collector = TelemetryCollectorService(repo, [host_adapter], real_settings)
    real_api = MineOpsApiService(db, repo, real_settings, collector=real_collector)

    real_sessions = real_api.handle_request("GET", "/api/v1/sessions")
    assert real_sessions.status_code == 200
    assert real_sessions.body["telemetry_mode"] == "real"
    assert real_sessions.body["active_session"] is None
    assert real_sessions.body["items"] == []

    # Direct lookup of a simulated session ID in real mode must return 404
    assert real_api.handle_request("GET", f"/api/v1/sessions/{sess_id}").status_code == 404

    # Attempting to start/pause/stop a simulated session in real mode must return 409 Conflict
    assert real_api.handle_request("POST", "/api/v1/sessions/start").status_code == 409
    assert real_api.handle_request("POST", "/api/v1/sessions/pause").status_code == 409
    assert real_api.handle_request("POST", "/api/v1/sessions/stop").status_code == 409


def test_performance_modes_and_rapido_auto_revert(tmp_path: Path) -> None:
    """Verify bajo, normal, and rapido performance modes and 10s automatic revert on a 12-thread host."""
    import json
    from mineops_dw.domain.hardware_profile import HostHardwareProfile

    db = SQLiteDatabase(tmp_path / "phase7_perf.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    hw_12t = HostHardwareProfile(
        cpu_model="Test 6C/12T CPU",
        physical_cores=6,
        logical_threads=12,
        total_ram_gib=16.0,
        gpu_model="Test GPU",
        estimated_tdp_watts=65.0,
        os_label="Windows 11",
    )
    api = MineOpsApiService(db, repo, AppSettings(TELEMETRY_MODE="real"), host_hardware=hw_12t)
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"cpu": {"rx": [0, 2, 4, 6, 8, 10, 9, 11], "priority": 2, "yield": true}}', encoding="utf-8")
    api._xmrig_config_path = cfg_file

    # Default is normal (8 threads)
    init_perf = api.handle_request("GET", "/api/v1/performance").body
    assert init_perf["mode"] == "normal"
    assert init_perf["threads_count"] == 8

    # Switch to bajo (4 threads)
    bajo_res = api.handle_request("POST", "/api/v1/performance", body_bytes=b'{"mode": "bajo"}').body
    assert bajo_res["mode"] == "bajo"
    assert bajo_res["threads_count"] == 4
    saved_cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert len(saved_cfg["cpu"]["rx"]) == 4
    assert saved_cfg["cpu"]["priority"] == 1

    # Switch to rapido (12 threads) with fallback to bajo after 10s
    rapido_res = api.handle_request(
        "POST",
        "/api/v1/performance",
        body_bytes=b'{"mode": "rapido", "fallback_mode": "bajo"}',
    ).body
    assert rapido_res["mode"] == "rapido"
    assert rapido_res["threads_count"] == 12
    assert rapido_res["auto_revert_seconds"] == 10
    saved_cfg_fast = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert len(saved_cfg_fast["cpu"]["rx"]) == 12
    assert saved_cfg_fast["cpu"]["priority"] == 3

    # Simulate 10 seconds elapsed and verify automatic revert to bajo
    api._perf_revert_at_monotonic = 0.0
    reverted = api.handle_request("GET", "/api/v1/performance").body
    assert reverted["mode"] == "bajo"
    assert reverted["threads_count"] == 4
    saved_cfg_reverted = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert len(saved_cfg_reverted["cpu"]["rx"]) == 4


def test_excel_and_powerbi_export_endpoints(tmp_path: Path) -> None:
    """Verify GET /api/v1/exports/excel and GET /api/v1/exports/bi-summary produce a valid 5-sheet .xlsx and Power BI scripts."""
    import io
    import zipfile

    db = SQLiteDatabase(tmp_path / "phase7_excel_bi.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    api = MineOpsApiService(db, repo, AppSettings(TELEMETRY_MODE="real"))

    summary_resp = api.handle_request("GET", "/api/v1/exports/bi-summary")
    assert summary_resp.status_code == 200
    body = summary_resp.body
    assert isinstance(body, dict)
    assert len(body["sheets"]) == 5
    assert "Fact_Telemetria_Activa" in body["sheets"]
    assert "Excel.Workbook" in body["power_query_m"]
    assert "Total_USDT_Minado" in body["dax_measures"]

    excel_resp = api.handle_request("GET", "/api/v1/exports/excel")
    assert excel_resp.status_code == 200
    assert isinstance(excel_resp.body, bytes)
    assert excel_resp.content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    with zipfile.ZipFile(io.BytesIO(excel_resp.body), "r") as zf:
        names = set(zf.namelist())
        assert "xl/workbook.xml" in names
        assert "xl/worksheets/sheet1.xml" in names
        assert "xl/worksheets/sheet5.xml" in names

    exec_resp = api.handle_request("GET", "/api/v1/exports/executive-report")
    assert exec_resp.status_code == 200
    assert isinstance(exec_resp.body, str)
    assert "INFORME EJECUTIVO DE OPERACIONES Y BI" in exec_resp.body
    assert "window.print()" in exec_resp.body

    html_resp = api.handle_request("GET", "/")
    js_resp = api.handle_request("GET", "/dashboard.js")
    assert "toast-alerts-container" in html_resp.body
    assert "btn-executive-pdf" in html_resp.body
    assert "showToastAlert" in js_resp.body
    assert "playAlertTone" in js_resp.body

    root = Path(__file__).resolve().parents[1]
    assert (root / "Iniciar_MineOps.bat").is_file()
    assert (root / "Detener_MineOps.bat").is_file()





