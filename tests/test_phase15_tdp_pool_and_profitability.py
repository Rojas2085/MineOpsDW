"""Mock-only tests for TDP power fallback, unMineable pool balance adapter (PARAM-06), and ProfitabilityKpi."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from mineops_dw.adapters import (
    BinancePublicMarketClient,
    HostResourceSensorAdapter,
    UnmineablePoolBalanceAdapter,
)
from mineops_dw.collector import TelemetryCollectorService
from mineops_dw.config import AppSettings
from mineops_dw.domain import (
    Measurement,
    compute_energy_measurement,
    compute_profitability_kpi,
    estimate_power_from_tdp,
)
from mineops_dw.storage import MineOpsRepository, SQLiteDatabase


def test_estimate_power_from_tdp_is_strictly_tagged_estimated_and_feeds_energy_integration() -> None:
    t0 = "2026-11-02T13:00:00Z"
    t1 = "2026-11-02T13:30:00Z"

    cpu0 = Measurement(
        metric_name="cpu_percent_total",
        value=50.0,
        unit="%",
        status="measured",
        source="psutil",
        observed_at_utc=t0,
    )
    cpu1 = Measurement(
        metric_name="cpu_percent_total",
        value=100.0,
        unit="%",
        status="measured",
        source="psutil",
        observed_at_utc=t1,
    )

    p0 = estimate_power_from_tdp(cpu0, tdp_watts=65.0, kappa=1.0)
    p1 = estimate_power_from_tdp(cpu1, tdp_watts=65.0, kappa=1.0)

    # Never tagged as "measured"
    assert p0.status == "estimated"
    assert p0.source == "calculation:tdp_fallback"
    assert p0.value == 32.5
    assert p1.status == "estimated"
    assert p1.value == 65.0

    # Trapezoidal integration over 0.5 hours -> ((32.5 + 65.0) / 2) * 0.5 = 24.375 Wh
    energy = compute_energy_measurement(p0, p1)
    assert energy.status == "estimated"
    assert energy.value == 24.375

    # Unavailable CPU load produces unavailable TDP power (value=None, never 0.0)
    cpu_unavail = Measurement(
        metric_name="cpu_percent_total",
        value=None,
        unit="%",
        status="unavailable",
        source="psutil",
        observed_at_utc=t1,
        quality_note="sensor error",
    )
    p_unavail = estimate_power_from_tdp(cpu_unavail, tdp_watts=65.0)
    assert p_unavail.status == "unavailable"
    assert p_unavail.value is None


def test_unmineable_pool_balance_inhibits_network_when_param06_empty() -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(200, json={"data": {"balance": "0.001", "payment_threshold": "0.005"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = UnmineablePoolBalanceAdapter(
            payout_coin="",
            payout_address="",
            payout_network="",
            http_client=client,
        )
        progress = adapter.fetch_payout_progress()

    assert adapter.is_payout_configured is False
    assert calls == []
    assert progress.status == "unavailable"
    assert progress.pending_balance is None
    assert progress.payout_threshold is None
    assert progress.progress_pct is None


def test_unmineable_pool_balance_parses_progress_enforces_5min_rate_limit_and_handles_errors() -> None:
    now = datetime(2026, 11, 2, 13, 0, 0, tzinfo=UTC)
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(
            200,
            json={"data": {"balance": "0.00025000", "payment_threshold": "0.00050000"}},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = UnmineablePoolBalanceAdapter(
            payout_coin="BTC",
            payout_address="bc1qtestwallet",
            payout_network="BTC",
            min_poll_interval_seconds=300.0,
            http_client=client,
            clock=lambda: now,
        )
        p1 = adapter.fetch_payout_progress()
        assert len(calls) == 1
        assert p1.status == "measured"
        assert p1.pending_balance == "0.00025"
        assert p1.payout_threshold == "0.0005"
        assert p1.progress_pct == 50.0

        # Polling 60s later (< 300s) returns cached snapshot without network I/O
        now += timedelta(seconds=60)
        p2 = adapter.fetch_payout_progress()
        assert len(calls) == 1
        assert p2 == p1

        # Polling 301s after initial poll performs a new network request
        now += timedelta(seconds=241)
        adapter.fetch_payout_progress()
        assert len(calls) == 2


def test_compute_profitability_kpi_separates_net_margin_and_never_invents_zero_on_missing_inputs() -> None:
    # Complete inputs -> estimated net margin
    kpi_ok = compute_profitability_kpi(
        pending_pool_balance="0.001",
        market_price_usd="80000.00",
        electricity_cost_usd="12.50",
        estimated_fees_usd="0.50",
    )
    assert kpi_ok.status == "estimated"
    assert kpi_ok.gross_income_usd == "80"
    assert kpi_ok.electricity_cost_usd == "12.5"
    assert kpi_ok.net_margin_usd == "67"

    # Missing electricity cost -> net_margin_usd is None and status is unavailable (never 0)
    kpi_no_power = compute_profitability_kpi(
        pending_pool_balance="0.001",
        market_price_usd="80000.00",
        electricity_cost_usd=None,
    )
    assert kpi_no_power.status == "unavailable"
    assert kpi_no_power.gross_income_usd == "80"
    assert kpi_no_power.net_margin_usd is None

    # Missing pool balance or price -> net_margin_usd is None and status is unavailable
    kpi_no_price = compute_profitability_kpi(
        pending_pool_balance="0.001",
        market_price_usd=None,
        electricity_cost_usd="12.50",
    )
    assert kpi_no_price.status == "unavailable"
    assert kpi_no_price.gross_income_usd is None
    assert kpi_no_price.net_margin_usd is None


def test_binance_public_market_client_24h_ticker_and_error_degradation() -> None:
    def ok_handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v3/ticker/24hr"
        assert req.url.params.get("symbol") == "BTCUSDT"
        return httpx.Response(
            200,
            json={
                "symbol": "BTCUSDT",
                "lastPrice": "84500.25",
                "weightedAvgPrice": "83900.10",
                "priceChangePercent": "2.45",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(ok_handler)) as client:
        market = BinancePublicMarketClient(http_client=client)
        ticker, snap = market.fetch_ticker_24h(
            asset="BTC",
            quote_asset="USDT",
            observed_at_utc="2026-11-02T13:00:00Z",
        )

    assert ticker.status == "measured"
    assert ticker.last_price == "84500.25"
    assert ticker.weighted_avg_price == "83900.1"
    assert ticker.price_change_pct == "2.45"
    assert snap.asset == "BTC"
    assert snap.quote_asset == "USDT"
    assert snap.price == "84500.25"
    assert snap.status == "measured"

    def err_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    with httpx.Client(transport=httpx.MockTransport(err_handler)) as client:
        market_err = BinancePublicMarketClient(http_client=client)
        ticker_err, snap_err = market_err.fetch_ticker_24h(
            observed_at_utc="2026-11-02T13:00:00Z"
        )

    assert ticker_err.status == "unavailable"
    assert snap_err.status == "unavailable"
    assert snap_err.price is None


def test_collector_tdp_fallback_integration_persists_estimated_power_and_energy(
    tmp_path: Path,
) -> None:
    class _FakeCpuOnlySensor:
        def __init__(self) -> None:
            self.calls = 0

        def collect(
            self,
            observed_at_utc: datetime | str | None = None,
            session_id: str | None = None,
        ) -> list[Measurement]:
            self.calls += 1
            return [
                Measurement(
                    session_id=session_id,
                    metric_name="cpu_percent_total",
                    value=40.0 if self.calls == 1 else 60.0,
                    unit="%",
                    status="measured",
                    source="psutil",
                    observed_at_utc=observed_at_utc,  # type: ignore[arg-type]
                )
            ]

    db = SQLiteDatabase(tmp_path / "phase15_collector.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    settings = AppSettings(TELEMETRY_MODE="real")
    collector = TelemetryCollectorService(
        repo,
        [_FakeCpuOnlySensor()],
        settings,
        enable_tdp_fallback=True,
        cpu_tdp_watts=65.0,
    )

    collector.collect_once(observed_at_utc="2026-11-02T13:00:00Z")
    collector.collect_once(observed_at_utc="2026-11-02T13:30:00Z")

    power_rows = repo.list_measurements(metric_name="cpu_package_power_w")
    energy_rows = repo.list_measurements(metric_name="energy_consumed_wh")
    assert len(power_rows) == 2
    assert all(m.status == "estimated" and m.source == "calculation:tdp_fallback" for m in power_rows)
    assert power_rows[0].value == 26.0
    assert power_rows[1].value == 39.0
    assert len(energy_rows) == 2
    assert energy_rows[1].status == "estimated"
    assert energy_rows[1].value == 16.25

