"""Read-only Binance Spot API adapter for querying deposit history (/sapi/v1/capital/deposit/hisrec)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import hmac
import logging
from typing import Any, Literal, Protocol
from urllib.parse import urlencode

import httpx
from pydantic import SecretStr

from mineops_dw.domain.models import (
    PaymentEvent,
    SettlementStatus,
    normalize_utc_timestamp,
)
from mineops_dw.logging_config import redact_sensitive_text

logger = logging.getLogger("mineops_dw.adapters.binance")

BINANCE_DEPOSIT_HISTORY_PATH = "/sapi/v1/capital/deposit/hisrec"
BinanceConnectionStatus = Literal["connected", "disconnected", "auth_error", "network_error"]


@dataclass(frozen=True)
class BinanceDepositFetchResult:
    """Result of querying deposit history from Binance in read-only mode."""

    connection_status: BinanceConnectionStatus
    deposits: list[PaymentEvent]
    pages_fetched: int = 0
    error_note: str | None = None


class ExchangeReadOnlyAdapter(Protocol):
    """Protocol for read-only exchange deposit history adapters (no trading or withdrawals)."""

    def fetch_deposit_history(
        self,
        *,
        coin: str = "BTC",
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> BinanceDepositFetchResult:
        """Query deposit records in read-only mode."""


class BinanceDepositReadOnlyAdapter:
    """Strictly read-only adapter for Binance Spot Deposit History (`GET /sapi/v1/capital/deposit/hisrec`).

    Security guarantees:
    - Never implements or calls withdrawal, transfer, or trading endpoints.
    - Operates cleanly in 'disconnected' mode when API key/secret are empty.
    - Signs requests with HMAC-SHA256 and strips keys/secrets/signatures from all logs.
    """

    def __init__(
        self,
        *,
        api_key: SecretStr | str = "",
        api_secret: SecretStr | str = "",
        base_url: str = "https://api.binance.com",
        timeout_seconds: float = 4.0,
        page_limit: int = 100,
        max_pages: int = 5,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._api_key = (
            api_key.get_secret_value().strip()
            if isinstance(api_key, SecretStr)
            else api_key.strip()
        )
        self._api_secret = (
            api_secret.get_secret_value().strip()
            if isinstance(api_secret, SecretStr)
            else api_secret.strip()
        )
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._page_limit = max(1, min(page_limit, 1000))
        self._max_pages = max(1, max_pages)
        self._http_client = http_client

    @property
    def is_configured(self) -> bool:
        """Return True only when both read-only API key and secret are provided."""
        return bool(self._api_key and self._api_secret)

    def fetch_deposit_history(
        self,
        *,
        coin: str = "BTC",
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        timestamp_ms: int | None = None,
    ) -> BinanceDepositFetchResult:
        """Query `GET /sapi/v1/capital/deposit/hisrec` with pagination and HMAC-SHA256 signature."""
        if not self.is_configured:
            return BinanceDepositFetchResult(
                connection_status="disconnected",
                deposits=[],
                pages_fetched=0,
                error_note="Binance read-only API credentials are not configured.",
            )

        collected: list[PaymentEvent] = []
        pages = 0
        offset = 0
        req_ts_ms = (
            timestamp_ms
            if timestamp_ms is not None
            else int(datetime.now(UTC).timestamp() * 1000)
        )

        for _ in range(self._max_pages):
            params: dict[str, Any] = {
                "coin": coin.upper(),
                "limit": self._page_limit,
                "offset": offset,
                "timestamp": req_ts_ms,
            }
            if start_time_ms is not None:
                params["startTime"] = start_time_ms
            if end_time_ms is not None:
                params["endTime"] = end_time_ms

            query_string = urlencode(params)
            signature = hmac.new(
                self._api_secret.encode("utf-8"),
                query_string.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            signed_url = (
                f"{self._base_url}{BINANCE_DEPOSIT_HISTORY_PATH}"
                f"?{query_string}&signature={signature}"
            )
            headers = {
                "X-MBX-APIKEY": self._api_key,
                "Accept": "application/json",
            }

            try:
                if self._http_client is not None:
                    resp = self._http_client.get(
                        signed_url,
                        headers=headers,
                        timeout=self._timeout_seconds,
                    )
                else:
                    with httpx.Client(timeout=self._timeout_seconds) as client:
                        resp = client.get(signed_url, headers=headers)

                if resp.status_code in {401, 403}:
                    safe_detail = self._sanitize(
                        f"HTTP {resp.status_code}: invalid key or insufficient read permissions",
                        signature=signature,
                    )
                    logger.warning("Binance auth/permission failure: %s", safe_detail)
                    return BinanceDepositFetchResult(
                        connection_status="auth_error",
                        deposits=[],
                        pages_fetched=pages,
                        error_note=safe_detail,
                    )

                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, list):
                    raise ValueError("Binance deposit history response must be a JSON array.")
            except Exception as exc:
                safe_err = self._sanitize(str(exc), signature=signature)
                logger.warning("Binance deposit query failed: %s", safe_err)
                return BinanceDepositFetchResult(
                    connection_status="network_error",
                    deposits=collected,
                    pages_fetched=pages,
                    error_note=f"Binance API error ({type(exc).__name__}): {safe_err}",
                )

            pages += 1
            if not payload:
                break

            for raw_item in payload:
                if isinstance(raw_item, dict):
                    collected.append(_map_binance_deposit_record(raw_item))

            if len(payload) < self._page_limit:
                break
            offset += self._page_limit

        return BinanceDepositFetchResult(
            connection_status="connected",
            deposits=collected,
            pages_fetched=pages,
            error_note=None,
        )

    def _sanitize(self, text: str, signature: str = "") -> str:
        secrets = [s for s in (self._api_key, self._api_secret, signature) if s]
        return redact_sensitive_text(text, explicit_secrets=secrets)


def _map_binance_deposit_record(item: dict[str, Any]) -> PaymentEvent:
    """Map a Binance `/sapi/v1/capital/deposit/hisrec` item to a PaymentEvent."""
    tx_id = str(item.get("txId", "")).strip() or None
    rec_id = str(item.get("id") or tx_id or item.get("insertTime") or "unknown")
    coin = str(item.get("coin", "BTC")).strip().upper()
    amount_dec = Decimal(str(item.get("amount", "0")).strip())

    # Binance deposit status codes: 0=pending, 6=credited but cannot withdraw, 1=success
    raw_status = item.get("status")
    if raw_status in {1, 6, "1", "6", "SUCCESS"}:
        settlement: SettlementStatus = "confirmed"
    elif raw_status in {0, "0", "PENDING"}:
        settlement = "pending"
    elif raw_status in {2, "2", "FAILED"}:
        settlement = "failed"
    else:
        settlement = "unknown"

    insert_time = item.get("insertTime")
    if isinstance(insert_time, (int, float)):
        obs_dt = datetime.fromtimestamp(float(insert_time) / 1000.0, tz=UTC)
        observed_iso = normalize_utc_timestamp(obs_dt)
    elif item.get("observed_at_utc"):
        observed_iso = normalize_utc_timestamp(str(item["observed_at_utc"]))
    else:
        observed_iso = normalize_utc_timestamp(datetime.now(UTC))

    return PaymentEvent(
        id=f"binance_dep_{rec_id}",
        event_type="deposit_detected",
        asset=coin,
        amount=amount_dec,
        network_fee=None,
        settlement_status=settlement,
        data_status="measured",
        source="binance_read_only_api",
        external_reference=tx_id,
        observed_at_utc=observed_iso,
    )
