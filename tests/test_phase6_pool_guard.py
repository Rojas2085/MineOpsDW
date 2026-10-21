"""Phase 6 tests: Real miner safety gate, read-only pool HTTP adapter, reconnection, and log safety."""

from __future__ import annotations

import httpx
import pytest

from mineops_dw.adapters import MinerExecutionGuard, ReadOnlyHttpPoolAdapter
from mineops_dw.config import AppSettings
from mineops_dw.logging_config import configure_logging


def test_miner_execution_guard_blocks_unauthorized_or_non_asic_host() -> None:
    """Phase 6 gate: Real miner never starts automatically or without ASIC hardware & consent."""
    sim_settings = AppSettings(TELEMETRY_MODE="simulated")
    guard_sim = MinerExecutionGuard(
        sim_settings,
        user_explicitly_authorized=True,
        hardware_asic_present=True,
    )
    assert guard_sim.can_execute_real_miner is False
    with pytest.raises(PermissionError, match="TELEMETRY_MODE is set to 'simulated'"):
        guard_sim.assert_execution_permitted()

    real_settings = AppSettings(TELEMETRY_MODE="real")
    # Without explicit user authorization -> blocked
    guard_no_consent = MinerExecutionGuard(
        real_settings,
        user_explicitly_authorized=False,
        hardware_asic_present=True,
    )
    with pytest.raises(PermissionError, match="explicit user authorization"):
        guard_no_consent.assert_execution_permitted()

    # On CPU/iGPU host (Ryzen 5 5600GT, no ASIC) -> blocked by Phase 6 hardware gate
    guard_no_asic = MinerExecutionGuard(
        real_settings,
        user_explicitly_authorized=True,
        hardware_asic_present=False,
    )
    assert guard_no_asic.can_execute_real_miner is False
    with pytest.raises(PermissionError, match="no SHA-256 ASIC detected"):
        guard_no_asic.assert_execution_permitted()


def test_read_only_http_pool_adapter_reconnection_and_secret_free_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify bounded retry, reconnection recovery, payout parsing, and zero tokens in logs."""
    secret_token = "pool_secret_tok_987654321"
    configure_logging(
        level="WARNING",
        explicit_secrets=(secret_token,),
        logger_name="mineops_dw.adapters.pool_http",
    )

    # 1. Unconfigured adapter operates in disconnected mode cleanly
    unconf = ReadOnlyHttpPoolAdapter(pool_name="braiins_ro", status_url=None)
    snap_unconf = unconf.fetch_snapshot(observed_at_utc="2026-10-21T19:00:00Z")
    assert snap_unconf.is_connected is False
    assert snap_unconf.hashrate_measurement.status == "unavailable"
    assert snap_unconf.hashrate_measurement.value is None

    # 2. Simulate transient failure on attempt 1, then valid response on attempt 2 (reconnection)
    attempts = {"count": 0}

    def _mock_transport(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        assert request.headers.get("Pool-Auth-Token") == secret_token
        if attempts["count"] == 1:
            raise httpx.ConnectError(f"Connection reset for token={secret_token}")
        return httpx.Response(
            200,
            json={
                "hashrate_hs": 1520.5,
                "unpaid_balance_btc": "0.00012500",
                "payouts": [
                    {
                        "id": "p_101",
                        "amount_btc": "0.00050000",
                        "fee_btc": "0.00001000",
                        "txid": "abc123txid",
                        "paid_at_utc": "2026-10-21T18:55:00Z",
                    }
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(_mock_transport))
    adapter = ReadOnlyHttpPoolAdapter(
        pool_name="braiins_ro",
        status_url="https://pool.example.invalid/api/v1/status",
        auth_token=secret_token,
        max_retries=2,
        http_client=client,
    )

    with caplog.at_level("WARNING", logger="mineops_dw.adapters.pool_http"):
        snap = adapter.fetch_snapshot(observed_at_utc="2026-10-21T19:00:00Z")

    assert attempts["count"] == 2
    assert adapter.is_connected is True
    assert snap.is_connected is True
    assert snap.hashrate_measurement.status == "measured"
    assert snap.hashrate_measurement.value == 1520.5
    assert snap.pool_reported_reward is not None
    assert snap.pool_reported_reward.amount_btc == "0.000125"
    assert snap.pool_reported_reward.reward_stage == "pool_reported"
    assert len(snap.recent_payouts) == 1
    assert snap.recent_payouts[0].event_type == "payout_issued"
    assert snap.recent_payouts[0].amount == "0.0005"
    assert snap.recent_payouts[0].external_reference == "abc123txid"

    # Verify secret token never leaked in warning logs
    for record in caplog.records:
        assert secret_token not in record.getMessage()
