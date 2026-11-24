"""Real-socket and real-API integration test suite for MineOps DW.

- Loopback TCP socket tests (`127.0.0.1`) and real Windows 11 host sensor tests run always.
- External live Internet API tests (`https://api.binance.com`) run when the environment
  variable `MINEOPS_RUN_LIVE_API_TESTS=1` is set, keeping default offline `pytest` deterministic.
"""

from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path

import pytest

from mineops_dw.config import AppSettings
from mineops_dw.storage.database import SQLiteDatabase
from mineops_dw.storage.repositories import MineOpsRepository
from tests.live_api_environment import LiveApiTestEnvironment

LIVE_INTERNET_ENABLED = os.environ.get("MINEOPS_RUN_LIVE_API_TESTS", "").strip() in (
    "1",
    "true",
    "TRUE",
    "yes",
)


def _sandbox_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        database_path=tmp_path / "live_real_api_test.sqlite3",
        app_host="127.0.0.1",
        allow_non_loopback=False,
    )


def test_real_windows_host_and_lhm_probe(tmp_path: Path) -> None:
    """Verify real Windows 11 CPU/RAM sensors, LHM loopback probe, and TDP fallback."""
    settings = _sandbox_settings(tmp_path)
    env = LiveApiTestEnvironment(base_settings=settings, include_external_internet=False)
    res = env.probe_host_and_lhm_telemetry(settings)

    assert res.passed is True
    assert res.details["cpu_percent_total"]["status"] == "measured"
    assert res.details["ram_used_mib"]["status"] == "measured"
    assert res.details["ram_used_mib"]["value"] > 0
    assert res.details["tdp_power_fallback"]["status"] == "estimated"


def test_real_tcp_loopback_miner_connectors_and_thermal_supervisor(tmp_path: Path) -> None:
    """Verify XMRig, SRBMiner, Kryptex, and ThermalSupervisor over real TCP loopback sockets."""
    settings = _sandbox_settings(tmp_path)
    env = LiveApiTestEnvironment(base_settings=settings, include_external_internet=False)
    res = env.probe_real_tcp_miner_connectors_and_supervisor(settings)

    assert res.passed is True
    assert res.details["xmrig_tcp_snapshot"]["connection_status"] == "REACHABLE"
    assert res.details["xmrig_tcp_snapshot"]["operational_state"] == "RUNNING"
    assert res.details["xmrig_tcp_snapshot"]["hashrate_10s_hs"] == 1925.5
    assert res.details["thermal_supervisor_over_tcp"]["mode"] == "THERMAL_ALERT_UNCONTROLLED"
    assert res.details["thermal_supervisor_over_tcp"]["alert_edge_triggered"] is True
    assert res.details["srbminer_tcp_snapshot"]["connection_status"] == "REACHABLE"
    assert res.details["kryptex_passive_os_scan"]["pause_delivery"] == "NOT_SENT"


def test_real_local_http_server_over_tcp_socket(tmp_path: Path) -> None:
    """Verify LocalHttpServer and MineOpsApiService over a real 127.0.0.1 TCP socket."""
    settings = _sandbox_settings(tmp_path)
    db = SQLiteDatabase(settings.database_path)
    db.apply_migrations()
    repo = MineOpsRepository(db)

    env = LiveApiTestEnvironment(base_settings=settings, include_external_internet=False)
    res = env.probe_real_local_http_server(settings, db, repo)

    assert res.passed is True
    assert res.details["health_status"] == "ok"
    assert res.details["measurements_persisted_on_collect"] > 0
    assert res.details["openapi_version"].startswith("3.1")


@pytest.mark.skipif(
    not LIVE_INTERNET_ENABLED,
    reason="Set MINEOPS_RUN_LIVE_API_TESTS=1 to execute live HTTPS calls against api.binance.com.",
)
def test_live_binance_public_market_apis_and_persistence(tmp_path: Path) -> None:
    """Execute real HTTPS requests against https://api.binance.com and persist real BTC/XMR prices."""
    settings = _sandbox_settings(tmp_path)
    db = SQLiteDatabase(settings.database_path)
    db.apply_migrations()
    repo = MineOpsRepository(db)

    env = LiveApiTestEnvironment(base_settings=settings, include_external_internet=True)
    res = env.probe_live_binance_public_apis(settings, repo)

    assert res.passed is True
    btc_24h = res.details["btc_usdt_24h"]
    assert btc_24h["status"] == "measured"
    assert Decimal(str(btc_24h["last_price"])) > Decimal("0")

    btc_bob = res.details["btc_bob_converted"]
    assert btc_bob["status"] in ("measured", "estimated")
    assert Decimal(str(btc_bob["price"])) > Decimal("0")

    saved_usd = repo.list_price_snapshots(quote_asset="USD")
    saved_usdt = repo.list_price_snapshots(quote_asset="USDT")
    assert len(saved_usd) >= 1
    assert len(saved_usdt) >= 2


@pytest.mark.skipif(
    not LIVE_INTERNET_ENABLED,
    reason="Set MINEOPS_RUN_LIVE_API_TESTS=1 to execute the full live environment with Internet APIs.",
)
def test_full_live_api_environment_end_to_end(tmp_path: Path) -> None:
    """Run the complete isolated LiveApiTestEnvironment including live Binance HTTPS APIs."""
    settings = _sandbox_settings(tmp_path)
    env = LiveApiTestEnvironment(base_settings=settings, include_external_internet=True)
    report = env.run_all()

    assert report.all_passed is True
    assert len(report.sections) == 5
