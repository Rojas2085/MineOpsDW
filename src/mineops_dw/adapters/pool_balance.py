"""Read-only pool pending balance adapter with PARAM-06 inhibition and rate-limit protection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import logging
from typing import Any

import httpx

from mineops_dw.domain.models import (
    QualityStatus,
    normalize_decimal_str,
    normalize_utc_timestamp,
)

logger = logging.getLogger("mineops_dw.adapters.pool_balance")


@dataclass(frozen=True)
class PayoutProgress:
    """Normalized snapshot of pending pool balance and payout threshold progress."""

    observed_at_utc: str
    pool_name: str
    coin: str
    wallet_address: str
    network: str
    pending_balance: str | None
    payout_threshold: str | None
    progress_pct: float | None
    status: QualityStatus
    quality_note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observed_at_utc", normalize_utc_timestamp(self.observed_at_utc)
        )


class UnmineablePoolBalanceAdapter:
    """Read-only public adapter for unMineable address balance with PARAM-06 inhibition."""

    def __init__(
        self,
        *,
        payout_coin: str = "",
        payout_address: str = "",
        payout_network: str = "",
        base_url: str = "https://api.unmineable.com",
        timeout_seconds: float = 5.0,
        min_poll_interval_seconds: float = 300.0,
        http_client: httpx.Client | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 10.0:
            raise ValueError("timeout_seconds must be in (0, 10.0].")
        if min_poll_interval_seconds < 0:
            raise ValueError("min_poll_interval_seconds must be non-negative.")

        self._coin = payout_coin.strip().upper()
        self._address = payout_address.strip()
        self._network = payout_network.strip().upper()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._min_poll_interval_seconds = min_poll_interval_seconds
        self._http_client = http_client
        self._clock = clock or (lambda: datetime.now(UTC))

        self._last_polled_at: datetime | None = None
        self._cached_progress: PayoutProgress | None = None

    @property
    def is_payout_configured(self) -> bool:
        """Return True only when coin, wallet address, and network are all non-empty (PARAM-06)."""
        return bool(self._coin and self._address and self._network)

    def fetch_payout_progress(self) -> PayoutProgress:
        """Query pending balance if configured; inhibit network I/O when PARAM-06 is empty."""
        now_dt = self._clock()
        now_utc = normalize_utc_timestamp(now_dt)

        if not self.is_payout_configured:
            return PayoutProgress(
                observed_at_utc=now_utc,
                pool_name="unmineable",
                coin=self._coin,
                wallet_address=self._address,
                network=self._network,
                pending_balance=None,
                payout_threshold=None,
                progress_pct=None,
                status="unavailable",
                quality_note="Payout configuration is empty (PARAM-06); network polling inhibited.",
            )

        if (
            self._cached_progress is not None
            and self._last_polled_at is not None
            and (now_dt - self._last_polled_at).total_seconds() < self._min_poll_interval_seconds
        ):
            return self._cached_progress

        url = f"{self._base_url}/v4/address/{self._address}"
        params = {"coin": self._coin}
        try:
            if self._http_client is not None:
                response = self._http_client.get(
                    url, params=params, timeout=self._timeout_seconds
                )
            else:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.get(url, params=params)
        except Exception as exc:
            logger.warning("unMineable balance poll failed (%s).", type(exc).__name__)
            return self._unavailable(now_utc, f"Pool API unreachable ({type(exc).__name__}).")

        if response.status_code != 200:
            return self._unavailable(now_utc, f"Pool API returned HTTP {response.status_code}.")

        try:
            payload: Any = response.json()
        except Exception:
            return self._unavailable(now_utc, "Pool API returned invalid JSON.")

        if not isinstance(payload, dict):
            return self._unavailable(now_utc, "Pool API payload is not a JSON object.")

        data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        raw_balance = data_obj.get("balance")
        raw_threshold = data_obj.get("payment_threshold")

        try:
            bal_str = normalize_decimal_str(str(raw_balance))
            bal_dec = Decimal(bal_str)
            if bal_dec < Decimal("0"):
                return self._unavailable(now_utc, "Pool API returned negative balance.")
        except Exception:
            return self._unavailable(now_utc, "Pool API balance field is missing or invalid.")

        threshold_str: str | None = None
        progress_pct: float | None = None
        if raw_threshold is not None:
            try:
                threshold_str = normalize_decimal_str(str(raw_threshold))
                thresh_dec = Decimal(threshold_str)
                if thresh_dec <= Decimal("0"):
                    return self._unavailable(now_utc, "Pool API payment_threshold must be positive.")
                pct = float((bal_dec / thresh_dec) * Decimal("100"))
                progress_pct = round(max(0.0, min(100.0, pct)), 4)
            except Exception:
                return self._unavailable(now_utc, "Pool API payment_threshold is invalid.")

        result = PayoutProgress(
            observed_at_utc=now_utc,
            pool_name="unmineable",
            coin=self._coin,
            wallet_address=self._address,
            network=self._network,
            pending_balance=bal_str,
            payout_threshold=threshold_str,
            progress_pct=progress_pct,
            status="measured",
        )
        self._last_polled_at = now_dt
        self._cached_progress = result
        return result

    def _unavailable(self, observed_at_utc: str, note: str) -> PayoutProgress:
        return PayoutProgress(
            observed_at_utc=observed_at_utc,
            pool_name="unmineable",
            coin=self._coin,
            wallet_address=self._address,
            network=self._network,
            pending_balance=None,
            payout_threshold=None,
            progress_pct=None,
            status="unavailable",
            quality_note=note,
        )
