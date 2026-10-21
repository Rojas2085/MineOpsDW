"""Market price adapters for BTC/USD and optional BTC/BOB conversion with staleness checks."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import logging
from typing import Any, Protocol

import httpx

from mineops_dw.domain.models import (
    PriceSnapshot,
    normalize_decimal_str,
    normalize_utc_timestamp,
)

logger = logging.getLogger("mineops_dw.adapters.prices")


class PriceAdapter(Protocol):
    """Protocol for fetching BTC market price snapshots."""

    def fetch_prices(
        self,
        observed_at_utc: datetime | str | None = None,
        include_bob: bool = True,
    ) -> list[PriceSnapshot]:
        """Fetch BTC/USD (and optionally BTC/BOB) price snapshots."""


class MarketPriceAdapter:
    """HTTP adapter for BTC/USD market price and optional USD->BOB conversion.

    Validates payload structure, rejects non-positive prices, checks timestamp staleness,
    and marks BTC/BOB as 'unavailable' when FX data is missing.
    """

    def __init__(
        self,
        *,
        ticker_url: str = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
        source_name: str = "market_http",
        timeout_seconds: float = 3.0,
        stale_after_seconds: int = 300,
        usd_to_bob_rate: Decimal | str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._ticker_url = ticker_url
        self._source_name = source_name
        self._timeout_seconds = timeout_seconds
        self._stale_after_seconds = max(1, stale_after_seconds)
        self._fx_usd_to_bob: Decimal | None = (
            Decimal(normalize_decimal_str(usd_to_bob_rate))
            if usd_to_bob_rate is not None
            else None
        )
        self._http_client = http_client

    def fetch_prices(
        self,
        observed_at_utc: datetime | str | None = None,
        include_bob: bool = True,
    ) -> list[PriceSnapshot]:
        """Fetch BTC/USD and optionally derive BTC/BOB if FX rate is available."""
        now_iso = normalize_utc_timestamp(observed_at_utc or datetime.now(UTC))
        now_dt = _parse_utc(now_iso)

        usd_snapshot = self._fetch_usd_snapshot(now_iso, now_dt)
        snapshots = [usd_snapshot]

        if include_bob:
            snapshots.append(self._derive_bob_snapshot(usd_snapshot, now_iso))

        return snapshots

    def _fetch_usd_snapshot(self, now_iso: str, now_dt: datetime) -> PriceSnapshot:
        snap_id = f"price_BTC_USD_{self._source_name}_{now_iso}"
        try:
            if self._http_client is not None:
                resp = self._http_client.get(self._ticker_url, timeout=self._timeout_seconds)
            else:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    resp = client.get(self._ticker_url)
            resp.raise_for_status()
            payload: Any = resp.json()
            if not isinstance(payload, dict) or "price" not in payload:
                raise ValueError("Missing 'price' field in market response.")

            raw_price = Decimal(str(payload["price"]).strip())
            if not raw_price.is_finite() or raw_price <= Decimal("0"):
                raise ValueError(f"Non-positive or non-finite BTC price: {raw_price}")

            # Check quote timestamp staleness if provided by API
            quote_ts_raw = payload.get("observed_at_utc") or payload.get("time")
            if quote_ts_raw is not None:
                quote_dt = _parse_quote_time(quote_ts_raw)
                age_seconds = (now_dt - quote_dt).total_seconds()
                if age_seconds > self._stale_after_seconds:
                    logger.warning(
                        "Market price from %s is stale (age %.1fs > %ds)",
                        self._source_name,
                        age_seconds,
                        self._stale_after_seconds,
                    )
                    return PriceSnapshot(
                        id=snap_id,
                        asset="BTC",
                        quote_asset="USD",
                        price=None,
                        status="unavailable",
                        source=f"{self._source_name}:stale",
                        observed_at_utc=now_iso,
                    )

            return PriceSnapshot(
                id=snap_id,
                asset="BTC",
                quote_asset="USD",
                price=normalize_decimal_str(raw_price),
                status="measured",
                source=self._source_name,
                observed_at_utc=now_iso,
            )
        except ( httpx.HTTPError, ValueError, InvalidOperation, TypeError) as exc:
            logger.warning("Market price fetch failed (%s): %s", self._source_name, exc)
            return PriceSnapshot(
                id=snap_id,
                asset="BTC",
                quote_asset="USD",
                price=None,
                status="unavailable",
                source=self._source_name,
                observed_at_utc=now_iso,
            )

    def _derive_bob_snapshot(
        self,
        usd_snapshot: PriceSnapshot,
        now_iso: str,
    ) -> PriceSnapshot:
        snap_id = f"price_BTC_BOB_{self._source_name}_{now_iso}"
        if (
            usd_snapshot.status == "unavailable"
            or usd_snapshot.price is None
            or self._fx_usd_to_bob is None
            or self._fx_usd_to_bob <= Decimal("0")
        ):
            return PriceSnapshot(
                id=snap_id,
                asset="BTC",
                quote_asset="BOB",
                price=None,
                status="unavailable",
                source=f"{self._source_name}:fx",
                observed_at_utc=now_iso,
            )

        btc_usd = Decimal(usd_snapshot.price)
        btc_bob = (btc_usd * self._fx_usd_to_bob).quantize(Decimal("0.01"))
        return PriceSnapshot(
            id=snap_id,
            asset="BTC",
            quote_asset="BOB",
            price=normalize_decimal_str(btc_bob),
            status=usd_snapshot.status,
            source=f"{self._source_name}:fx",
            observed_at_utc=now_iso,
        )


def _parse_utc(iso_str: str) -> datetime:
    cleaned = iso_str[:-1] + "+00:00" if iso_str.endswith("Z") else iso_str
    return datetime.fromisoformat(cleaned).astimezone(UTC)


def _parse_quote_time(raw_time: Any) -> datetime:
    if isinstance(raw_time, (int, float)):
        # Milliseconds epoch
        return datetime.fromtimestamp(float(raw_time) / 1000.0, tz=UTC)
    return _parse_utc(normalize_utc_timestamp(str(raw_time)))
