"""Mock-only tests for KryptexProcessAdapter (MinerConnector) and API payout/profitability KPIs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from mineops_dw.adapters import (
    KryptexProcessAdapter,
    SRBMinerApiAdapter,
    UnmineablePoolBalanceAdapter,
)
from mineops_dw.api import MineOpsApiService
from mineops_dw.config import AppSettings
from mineops_dw.domain import (
    ControlAuthorization,
    MinerConnector,
    PeriodicReport,
    PriceSnapshot,
)
from mineops_dw.storage import MineOpsRepository, SQLiteDatabase


def test_kryptex_process_adapter_conforms_to_miner_connector_and_never_invents_hashrate() -> None:
    now = datetime(2026, 11, 2, 14, 0, 0, tzinfo=UTC)
    running_procs = [{"name": "kryptex.exe", "create_time": now.timestamp() - 95.0}]

    adapter_running = KryptexProcessAdapter(
        process_iter_fn=lambda: running_procs,
        clock=lambda: now,
    )
    assert isinstance(adapter_running, MinerConnector)

    snap = adapter_running.get_snapshot()
    caps = adapter_running.get_capabilities()

    assert snap.connection_status == "REACHABLE"
    assert snap.operational_state == "RUNNING"
    assert snap.state_confidence == "INFERRED"
    assert snap.operational_state_quality == "VALID"
    assert snap.process_progress == "UNKNOWN"
    assert snap.uptime_seconds.value == 95
    assert snap.uptime_seconds.quality == "VALID"

    # Hashing metrics must remain strictly UNAVAILABLE (value=None, never 0)
    assert snap.hashrate_10s_hs.value is None
    assert snap.hashrate_10s_hs.quality == "UNAVAILABLE"
    assert snap.shares_good.value is None
    assert snap.shares_good.quality == "UNAVAILABLE"

    # Capabilities are READ_ONLY with pause/resume CONFIRMED_UNAVAILABLE
    assert caps.status == "READ_ONLY"
    assert caps.observe == "CONFIRMED_AVAILABLE"
    assert caps.pause == "CONFIRMED_UNAVAILABLE"
    assert caps.resume == "CONFIRMED_UNAVAILABLE"

    # R-03 must reject ControlAuthorization for KryptexProcessAdapter
    auth = ControlAuthorization()
    assert (
        auth.try_grant(
            explicit_user_action=True,
            has_in_flight_or_unreconciled_command=False,
            snapshot=snap,
            capabilities=caps,
            mandatory_thermal_metrics_valid=True,
        )
        is False
    )
    assert auth.state == "NOT_GRANTED"

    # pause() and resume() reject locally without OS signals
    for res in (adapter_running.pause(), adapter_running.resume()):
        assert res.delivery == "NOT_SENT"
        assert res.acceptance == "UNKNOWN"
        assert res.postcondition == "NOT_ATTEMPTED"

    # When process is not present -> STOPPED (INFERRED)
    adapter_stopped = KryptexProcessAdapter(
        process_iter_fn=lambda: [{"name": "explorer.exe", "create_time": 100.0}],
        clock=lambda: now,
    )
    snap_stopped = adapter_stopped.get_snapshot()
    assert snap_stopped.operational_state == "STOPPED"
    assert snap_stopped.state_confidence == "INFERRED"


def test_api_supervisor_status_exposes_payout_progress_and_profitability_kpi(
    tmp_path: Path,
) -> None:
    db = SQLiteDatabase(tmp_path / "phase16_api.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    settings = AppSettings(
        TELEMETRY_MODE="real",
        PAYOUT_COIN="BTC",
        PAYOUT_ADDRESS="bc1qwallet",
        PAYOUT_NETWORK="BTC",
    )

    repo.insert_price_snapshot(
        PriceSnapshot(
            id="p_real_1",
            asset="BTC",
            quote_asset="USD",
            price="80000.00",
            status="measured",
            source="market_http",
            observed_at_utc="2026-11-02T14:00:00Z",
        )
    )
    repo.insert_periodic_report(
        PeriodicReport(
            id="rep_real_1",
            window_start_utc="2026-11-02T13:30:00Z",
            window_end_utc="2026-11-02T14:00:00Z",
            data_mode="real",
            sample_coverage_pct=100.0,
            gaps_count=0,
            summary_json='{"electricity": {"status": "estimated", "total_energy_wh": 25.0, "electricity_cost_usd": "10.00"}}',
            generated_at_utc="2026-11-02T14:00:01Z",
        )
    )

    def pool_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"balance": "0.00100000", "payment_threshold": "0.00200000"}},
        )

    with httpx.Client(transport=httpx.MockTransport(pool_handler)) as client:
        pool_adapter = UnmineablePoolBalanceAdapter(
            payout_coin="BTC",
            payout_address="bc1qwallet",
            payout_network="BTC",
            http_client=client,
        )
        api = MineOpsApiService(
            db,
            repo,
            settings,
            pool_balance_adapter=pool_adapter,
        )
        resp = api.handle_request("GET", "/api/v1/supervisor/status")

    assert resp.status_code == 200
    payout = resp.body["payout"]
    assert payout["is_configured"] is True
    assert payout["progress"]["status"] == "measured"
    assert payout["progress"]["pending_balance"] == "0.001"
    assert payout["progress"]["progress_pct"] == 50.0

    kpi = resp.body["profitability_kpi"]
    assert kpi["status"] == "estimated"
    assert kpi["gross_income_usd"] == "80"
    assert kpi["electricity_cost_usd"] == "10"
    assert kpi["net_margin_usd"] == "70"


def test_srbminer_api_adapter_passive_observation_progress_and_local_control_rejection() -> None:
    now = datetime(2026, 11, 2, 14, 30, 0, tzinfo=UTC)
    mining_time = {"val": 60}
    calls: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path))
        return httpx.Response(
            200,
            json={
                "miner_version": "2.6.8",
                "mining_time": mining_time["val"],
                "algorithms": [
                    {
                        "name": "randomx",
                        "hashrate": {"cpu": {"total": 2450.5}},
                        "shares": {"accepted": 8, "rejected": 1},
                        "pool": {"pool": "rx.pool.example:3333"},
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = SRBMinerApiAdapter(http_client=client, clock=lambda: now)
        assert isinstance(adapter, MinerConnector)

        s1 = adapter.get_snapshot()
        assert s1.connection_status == "REACHABLE"
        assert s1.operational_state == "RUNNING"
        assert s1.state_confidence == "INFERRED"
        assert s1.operational_state_quality == "VALID"
        assert s1.process_progress == "UNKNOWN"
        assert s1.version == "2.6.8"
        assert s1.algorithm == "randomx"
        assert s1.hashrate_10s_hs.value == 2450.5
        assert s1.hashrate_10s_hs.quality == "VALID"
        assert s1.shares_good.value == 8
        assert s1.shares_total.value == 9

        now += timedelta(seconds=10)
        mining_time["val"] = 70
        s2 = adapter.get_snapshot()
        assert s2.process_progress == "ADVANCING"

        caps = adapter.get_capabilities()
        assert caps.status == "READ_ONLY"
        assert caps.observe == "CONFIRMED_AVAILABLE"
        assert caps.pause == "UNVERIFIED_PASSIVELY"
        assert caps.resume == "UNVERIFIED_PASSIVELY"

        # pause() and resume() reject locally without HTTP I/O
        before_calls = len(calls)
        p_res = adapter.pause()
        r_res = adapter.resume()
        assert len(calls) == before_calls
        assert p_res.delivery == "NOT_SENT"
        assert r_res.delivery == "NOT_SENT"


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"algorithms": []},  # missing miner_version
        {"miner_version": "   ", "algorithms": []},  # blank miner_version
        {"miner_version": "2.6.8", "algorithms": "not-a-list"},  # invalid algorithms
        {"miner_version": "2.6.8", "algorithms": [], "is_paused": "no"},  # non-bool is_paused
    ],
)
def test_srbminer_conservative_schema_rejection_and_loopback_validation(
    bad_payload: dict[str, Any],
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=bad_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = SRBMinerApiAdapter(http_client=client)
        snap = adapter.get_snapshot()
        caps = adapter.get_capabilities()

    assert snap.connection_status == "DEGRADED"
    assert snap.operational_state == "UNKNOWN"
    assert snap.operational_state_quality == "INVALID"
    assert caps.status == "UNAVAILABLE"

    with pytest.raises(ValueError):
        SRBMinerApiAdapter(base_url="http://example.com:21550")
    with pytest.raises(ValueError):
        SRBMinerApiAdapter(base_url="https://127.0.0.1:21550")

