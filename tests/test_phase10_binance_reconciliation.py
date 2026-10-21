"""Phase 10 tests: Read-only Binance deposit adapter, auth/timeout/pagination, reconciliation, and log safety."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from mineops_dw.adapters import BinanceDepositReadOnlyAdapter
from mineops_dw.api import MineOpsApiService
from mineops_dw.config import AppSettings
from mineops_dw.domain import PaymentEvent, reconcile_payouts_and_deposits
from mineops_dw.logging_config import configure_logging
from mineops_dw.storage import MineOpsRepository, SQLiteDatabase


def test_binance_adapter_without_credentials_runs_in_disconnected_mode() -> None:
    """Case 10: Without API key/secret, Binance adapter returns 'disconnected' and never crashes."""
    adapter = BinanceDepositReadOnlyAdapter(api_key="", api_secret="")
    assert adapter.is_configured is False
    res = adapter.fetch_deposit_history()
    assert res.connection_status == "disconnected"
    assert res.deposits == []
    assert res.pages_fetched == 0


def test_binance_adapter_invalid_key_timeout_empty_pagination_and_log_redaction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify 401/403 handling, timeout, empty list, multi-page pagination, and zero secrets in logs."""
    fake_key = "BINANCE_RO_KEY_ABCDEF123456"
    fake_secret = "BINANCE_RO_SECRET_9988776655"
    configure_logging(
        level="WARNING",
        explicit_secrets=(fake_key, fake_secret),
        logger_name="mineops_dw.adapters.binance",
    )

    # 1. Invalid key / insufficient permission (401)
    def _mock_401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": -2015, "msg": "Invalid API-key, IP, or permissions"})

    adapter_401 = BinanceDepositReadOnlyAdapter(
        api_key=fake_key,
        api_secret=fake_secret,
        http_client=httpx.Client(transport=httpx.MockTransport(_mock_401)),
    )
    with caplog.at_level("WARNING", logger="mineops_dw.adapters.binance"):
        res_401 = adapter_401.fetch_deposit_history(timestamp_ms=1700000000000)
    assert res_401.connection_status == "auth_error"
    assert res_401.deposits == []

    # 2. Timeout error including sensitive query string in exception
    def _mock_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"Read timeout on {request.url} with key={fake_key}")

    adapter_timeout = BinanceDepositReadOnlyAdapter(
        api_key=fake_key,
        api_secret=fake_secret,
        http_client=httpx.Client(transport=httpx.MockTransport(_mock_timeout)),
    )
    with caplog.at_level("WARNING", logger="mineops_dw.adapters.binance"):
        res_timeout = adapter_timeout.fetch_deposit_history(timestamp_ms=1700000000000)
    assert res_timeout.connection_status == "network_error"
    assert fake_key not in (res_timeout.error_note or "")
    assert fake_secret not in (res_timeout.error_note or "")

    # Ensure no log record ever contains the API key, secret, or raw signature
    for record in caplog.records:
        msg = record.getMessage()
        assert fake_key not in msg
        assert fake_secret not in msg

    # 3. Empty response
    def _mock_empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    adapter_empty = BinanceDepositReadOnlyAdapter(
        api_key=fake_key,
        api_secret=fake_secret,
        http_client=httpx.Client(transport=httpx.MockTransport(_mock_empty)),
    )
    res_empty = adapter_empty.fetch_deposit_history(timestamp_ms=1700000000000)
    assert res_empty.connection_status == "connected"
    assert res_empty.deposits == []
    assert res_empty.pages_fetched == 1

    # 4. Pagination across 2 pages (page_limit=2 -> page 1 returns 2 items, page 2 returns 1 item)
    def _mock_paginated(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-MBX-APIKEY") == fake_key
        parsed = urlparse(str(request.url))
        qs = parse_qs(parsed.query)
        assert "signature" in qs
        offset = int(qs["offset"][0])
        if offset == 0:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "d_1",
                        "amount": "0.00020000",
                        "coin": "BTC",
                        "status": 1,
                        "txId": "tx_hash_001",
                        "insertTime": 1761060000000,
                    },
                    {
                        "id": "d_2",
                        "amount": "0.00030000",
                        "coin": "BTC",
                        "status": 1,
                        "txId": "tx_hash_002",
                        "insertTime": 1761063600000,
                    },
                ],
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": "d_3",
                    "amount": "0.00015000",
                    "coin": "BTC",
                    "status": 0,
                    "txId": "tx_hash_003",
                    "insertTime": 1761067200000,
                }
            ],
        )

    adapter_paged = BinanceDepositReadOnlyAdapter(
        api_key=fake_key,
        api_secret=fake_secret,
        page_limit=2,
        max_pages=5,
        http_client=httpx.Client(transport=httpx.MockTransport(_mock_paginated)),
    )
    res_paged = adapter_paged.fetch_deposit_history(timestamp_ms=1700000000000)
    assert res_paged.connection_status == "connected"
    assert res_paged.pages_fetched == 2
    assert len(res_paged.deposits) == 3
    assert res_paged.deposits[0].external_reference == "tx_hash_001"
    assert res_paged.deposits[0].settlement_status == "confirmed"
    assert res_paged.deposits[2].settlement_status == "pending"


def test_reconciliation_requires_matching_reference_and_exposes_api(tmp_path: Path) -> None:
    """Verify payout-deposit reconciliation never matches by amount alone and works via API."""
    db = SQLiteDatabase(tmp_path / "phase10.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)

    # Payout 1: matches Deposit 1 by txId and net amount (0.00050000 - 0.00001000 = 0.00049000)
    p1 = PaymentEvent(
        id="pay_1",
        event_type="payout_issued",
        asset="BTC",
        amount="0.00050000",
        network_fee="0.00001000",
        settlement_status="confirmed",
        data_status="simulated",
        source="simulator:pool",
        external_reference="SIM-TX-MATCH-01",
        observed_at_utc="2026-10-21T18:00:00Z",
    )
    d1 = PaymentEvent(
        id="dep_1",
        event_type="deposit_detected",
        asset="BTC",
        amount="0.00049000",
        settlement_status="confirmed",
        data_status="simulated",
        source="simulator:binance",
        external_reference="SIM-TX-MATCH-01",
        observed_at_utc="2026-10-21T18:15:00Z",
    )

    # Payout 2 & Deposit 2 have the EXACT SAME amount (0.00030000) but DIFFERENT txId -> MUST NOT MATCH
    p2 = PaymentEvent(
        id="pay_2",
        event_type="payout_issued",
        asset="BTC",
        amount="0.00030000",
        settlement_status="confirmed",
        data_status="simulated",
        source="simulator:pool",
        external_reference="SIM-TX-POOL-ONLY",
        observed_at_utc="2026-10-21T19:00:00Z",
    )
    d2 = PaymentEvent(
        id="dep_2",
        event_type="deposit_detected",
        asset="BTC",
        amount="0.00030000",
        settlement_status="confirmed",
        data_status="simulated",
        source="simulator:binance",
        external_reference="SIM-TX-OTHER-SOURCE",
        observed_at_utc="2026-10-21T19:10:00Z",
    )

    for ev in (p1, d1, p2, d2):
        repo.insert_payment_event(ev)

    report = reconcile_payouts_and_deposits([p1, d1, p2, d2])
    assert len(report.matched) == 1
    assert report.matched[0].payout_id == "pay_1"
    assert report.matched[0].deposit_id == "dep_1"
    assert len(report.unmatched_payouts) == 1
    assert report.unmatched_payouts[0].id == "pay_2"
    assert len(report.unmatched_deposits) == 1
    assert report.unmatched_deposits[0].id == "dep_2"

    # Verify via GET /api/v1/reconciliation
    api = MineOpsApiService(db, repo, AppSettings())
    resp = api.handle_request("GET", "/api/v1/reconciliation")
    assert resp.status_code == 200
    assert isinstance(resp.body, dict)
    assert resp.body["matched_count"] == 1
    assert resp.body["unmatched_payouts_count"] == 1
    assert resp.body["unmatched_deposits_count"] == 1
