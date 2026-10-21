"""Phase 9 tests: BTC market price adapter, stale/invalid responses, FX missing, and economics."""

from __future__ import annotations

from decimal import Decimal

import httpx

from mineops_dw.adapters import MarketPriceAdapter
from mineops_dw.domain import (
    Measurement,
    PaymentEvent,
    RewardSnapshot,
    evaluate_economics,
)


def test_market_price_adapter_valid_stale_invalid_and_missing_fx() -> None:
    """Verify valid BTC/USD + BOB conversion, missing FX fallback, stale rejection, and API outage."""
    # 1. Valid quote with FX rate configured (1 USD = 6.96 BOB)
    def _mock_valid(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "symbol": "BTCUSDT",
                "price": "70000.00",
                "observed_at_utc": "2026-10-21T20:00:00Z",
            },
        )

    adapter_ok = MarketPriceAdapter(
        usd_to_bob_rate=Decimal("6.96"),
        stale_after_seconds=300,
        http_client=httpx.Client(transport=httpx.MockTransport(_mock_valid)),
    )
    snaps_ok = adapter_ok.fetch_prices(observed_at_utc="2026-10-21T20:01:00Z", include_bob=True)
    by_quote = {s.quote_asset: s for s in snaps_ok}
    assert by_quote["USD"].status == "measured"
    assert by_quote["USD"].price == "70000"
    assert by_quote["BOB"].status == "measured"
    assert by_quote["BOB"].price == "487200"

    # 2. Missing FX rate -> USD is measured, BOB is explicitly 'unavailable' (price=None)
    adapter_no_fx = MarketPriceAdapter(
        usd_to_bob_rate=None,
        http_client=httpx.Client(transport=httpx.MockTransport(_mock_valid)),
    )
    snaps_no_fx = adapter_no_fx.fetch_prices(
        observed_at_utc="2026-10-21T20:01:00Z",
        include_bob=True,
    )
    by_quote_no_fx = {s.quote_asset: s for s in snaps_no_fx}
    assert by_quote_no_fx["USD"].status == "measured"
    assert by_quote_no_fx["BOB"].status == "unavailable"
    assert by_quote_no_fx["BOB"].price is None

    # 3. Stale quote (observed 20 minutes ago > 300s threshold) -> marked 'unavailable'
    snaps_stale = adapter_ok.fetch_prices(
        observed_at_utc="2026-10-21T20:20:00Z",
        include_bob=True,
    )
    for s in snaps_stale:
        assert s.status == "unavailable"
        assert s.price is None

    # 4. API down / invalid negative price -> marked 'unavailable'
    def _mock_bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"symbol": "BTCUSDT", "price": "-50.0"})

    adapter_bad = MarketPriceAdapter(
        http_client=httpx.Client(transport=httpx.MockTransport(_mock_bad)),
    )
    snaps_bad = adapter_bad.fetch_prices(observed_at_utc="2026-10-21T20:01:00Z")
    assert all(s.status == "unavailable" and s.price is None for s in snaps_bad)


def test_evaluate_economics_separates_estimated_from_confirmed_and_checks_power() -> None:
    """Estimated reward value must stay separate from confirmed deposit value; no fake power cost."""
    from mineops_dw.domain import PriceSnapshot

    usd_snap = PriceSnapshot(
        id="p_usd",
        asset="BTC",
        quote_asset="USD",
        price="70000",
        status="simulated",
        source="simulator:price",
        observed_at_utc="2026-10-21T20:00:00Z",
    )
    est_rew = RewardSnapshot(
        id="r_est",
        amount_btc="0.00010000",  # $7.00 USD estimated
        reward_stage="estimated",
        status="simulated",
        source="simulator:calc",
        observed_at_utc="2026-10-21T20:00:00Z",
    )
    pool_rew = RewardSnapshot(
        id="r_pool",
        amount_btc="0.00005000",  # $3.50 USD pending in pool
        reward_stage="pool_reported",
        status="simulated",
        source="simulator:pool",
        observed_at_utc="2026-10-21T20:00:00Z",
    )
    # Payout issued (NOT a confirmed Binance deposit) must NOT be counted as confirmed_deposit_btc
    payout_only = PaymentEvent(
        id="pay_1",
        event_type="payout_issued",
        asset="BTC",
        amount="0.00020000",
        settlement_status="confirmed",
        data_status="simulated",
        source="simulator:pool",
        external_reference="SIM-TX-1",
        observed_at_utc="2026-10-21T20:00:00Z",
    )

    # Case A: Power sensor unavailable -> electricity cost is 'unavailable' (None)
    unavail_energy = Measurement(
        metric_name="energy_consumed_wh",
        value=None,
        unit="Wh",
        status="unavailable",
        source="calculation",
        observed_at_utc="2026-10-21T20:00:00Z",
        quality_note="No watt sensor",
    )
    econ_no_power = evaluate_economics(
        usd_price_snapshot=usd_snap,
        estimated_reward=est_rew,
        pool_reported_reward=pool_rew,
        confirmed_deposits=[payout_only],
        energy_measurements=[unavail_energy],
        tariff_usd_per_kwh="0.10",
        fx_usd_to_bob="6.96",
    )
    assert econ_no_power.estimated_reward_usd == "7"
    assert econ_no_power.pool_pending_usd == "3.5"
    # Payout issued is not a deposit -> confirmed deposit is 0 BTC / $0 USD
    assert econ_no_power.confirmed_deposit_btc == "0"
    assert econ_no_power.confirmed_deposit_usd == "0"
    assert econ_no_power.electricity_cost_status == "unavailable"
    assert econ_no_power.electricity_cost_usd is None

    # Case B: Valid energy (500 Wh = 0.5 kWh) at $0.10/kWh = $0.05 USD (0.348 BOB) + confirmed deposit
    valid_energy = Measurement(
        metric_name="energy_consumed_wh",
        value=500.0,
        unit="Wh",
        status="simulated",
        source="calculation",
        observed_at_utc="2026-10-21T20:00:00Z",
    )
    real_deposit = PaymentEvent(
        id="dep_1",
        event_type="deposit_detected",
        asset="BTC",
        amount="0.00020000",  # $14.00 USD confirmed
        settlement_status="confirmed",
        data_status="simulated",
        source="simulator:binance",
        external_reference="SIM-TX-1",
        observed_at_utc="2026-10-21T20:05:00Z",
    )
    econ_with_power = evaluate_economics(
        usd_price_snapshot=usd_snap,
        estimated_reward=est_rew,
        pool_reported_reward=pool_rew,
        confirmed_deposits=[payout_only, real_deposit],
        energy_measurements=[valid_energy],
        tariff_usd_per_kwh="0.10",
        fx_usd_to_bob="6.96",
    )
    assert econ_with_power.energy_consumed_kwh == "0.5"
    assert econ_with_power.electricity_cost_usd == "0.05"
    assert econ_with_power.electricity_cost_bob == "0.348"
    assert econ_with_power.electricity_cost_status == "simulated"
    assert econ_with_power.confirmed_deposit_btc == "0.0002"
    assert econ_with_power.confirmed_deposit_usd == "14"
