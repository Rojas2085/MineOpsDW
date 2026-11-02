"""Market price adapters for BTC/USD and optional BTC/BOB conversion with staleness checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import logging
import re
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


_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}$")


@dataclass(frozen=True)
class BinanceTicker24h:
    """Normalized 24-hour public ticker statistics from Binance (/api/v3/ticker/24hr)."""

    observed_at_utc: str
    symbol: str
    asset: str
    quote_asset: str
    last_price: str | None
    weighted_avg_price: str | None
    price_change_pct: str | None
    status: str
    quality_note: str | None = None


class BinancePublicMarketClient:
    """Read-only public client for Binance /api/v3/ticker/24hr requiring zero API keys."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.binance.com",
        timeout_seconds: float = 5.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 10.0:
            raise ValueError("timeout_seconds must be in (0, 10.0].")
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    def fetch_ticker_24h(
        self,
        *,
        asset: str = "BTC",
        quote_asset: str = "USDT",
        observed_at_utc: datetime | str | None = None,
    ) -> tuple[BinanceTicker24h, PriceSnapshot]:
        """Fetch 24h ticker for {asset}{quote_asset} and return both ticker stats and PriceSnapshot."""
        clean_asset = asset.strip().upper()
        clean_quote = quote_asset.strip().upper()
        symbol = f"{clean_asset}{clean_quote}"
        if not _SYMBOL_RE.match(clean_asset) or not _SYMBOL_RE.match(clean_quote):
            raise ValueError(f"Invalid trading pair symbol components: {clean_asset}/{clean_quote}")

        now_iso = normalize_utc_timestamp(observed_at_utc or datetime.now(UTC))
        snap_id = f"price_{clean_asset}_{clean_quote}_binance_24h_{now_iso}"
        url = f"{self._base_url}/api/v3/ticker/24hr"

        try:
            if self._http_client is not None:
                resp = self._http_client.get(
                    url, params={"symbol": symbol}, timeout=self._timeout_seconds
                )
            else:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    resp = client.get(url, params={"symbol": symbol})
            resp.raise_for_status()
            payload: Any = resp.json()
            if not isinstance(payload, dict) or "lastPrice" not in payload:
                raise ValueError("Missing 'lastPrice' in /api/v3/ticker/24hr response.")

            last_dec = Decimal(str(payload["lastPrice"]).strip())
            if not last_dec.is_finite() or last_dec <= Decimal("0"):
                raise ValueError("Non-positive lastPrice in /api/v3/ticker/24hr response.")
            last_str = normalize_decimal_str(last_dec)

            w_avg_raw = payload.get("weightedAvgPrice")
            w_avg_str: str | None = None
            if w_avg_raw is not None:
                w_dec = Decimal(str(w_avg_raw).strip())
                if w_dec.is_finite() and w_dec > Decimal("0"):
                    w_avg_str = normalize_decimal_str(w_dec)

            pct_raw = payload.get("priceChangePercent")
            pct_str: str | None = None
            if pct_raw is not None:
                p_dec = Decimal(str(pct_raw).strip())
                if p_dec.is_finite():
                    pct_str = normalize_decimal_str(p_dec)

            ticker = BinanceTicker24h(
                observed_at_utc=now_iso,
                symbol=symbol,
                asset=clean_asset,
                quote_asset=clean_quote,
                last_price=last_str,
                weighted_avg_price=w_avg_str,
                price_change_pct=pct_str,
                status="measured",
            )
            snapshot = PriceSnapshot(
                id=snap_id,
                asset=clean_asset,
                quote_asset=clean_quote,
                price=last_str,
                status="measured",
                source="binance_public_24h",
                observed_at_utc=now_iso,
            )
            return ticker, snapshot
        except (httpx.HTTPError, ValueError, InvalidOperation, TypeError) as exc:
            logger.warning("Binance 24h ticker fetch failed for %s: %s", symbol, exc)
            ticker = BinanceTicker24h(
                observed_at_utc=now_iso,
                symbol=symbol,
                asset=clean_asset,
                quote_asset=clean_quote,
                last_price=None,
                weighted_avg_price=None,
                price_change_pct=None,
                status="unavailable",
                quality_note=f"Binance 24h ticker error ({type(exc).__name__}).",
            )
            snapshot = PriceSnapshot(
                id=snap_id,
                asset=clean_asset,
                quote_asset=clean_quote,
                price=None,
                status="unavailable",
                source="binance_public_24h",
                observed_at_utc=now_iso,
            )
            return ticker, snapshot
