"""Phase 6 optional read-only HTTP pool adapter and real miner safety guard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import logging
from typing import Any

import httpx
from pydantic import SecretStr

from mineops_dw.config import AppSettings
from mineops_dw.domain.models import (
    Measurement,
    PaymentEvent,
    RewardSnapshot,
    normalize_utc_timestamp,
)
from mineops_dw.logging_config import redact_sensitive_text

logger = logging.getLogger("mineops_dw.adapters.pool_http")


@dataclass(frozen=True)
class PoolStatusSnapshot:
    """Snapshot retrieved from a read-only pool status endpoint."""

    is_connected: bool
    hashrate_measurement: Measurement
    pool_reported_reward: RewardSnapshot | None
    recent_payouts: list[PaymentEvent]


class MinerExecutionGuard:
    """Safety gate that prevents automatic installation or execution of real mining binaries."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        user_explicitly_authorized: bool = False,
        hardware_asic_present: bool = False,
    ) -> None:
        self._settings = settings
        self._user_authorized = user_explicitly_authorized
        self._hardware_asic_present = hardware_asic_present

    @property
    def can_execute_real_miner(self) -> bool:
        """Return True only when telemetry_mode=='real', user authorized, and hardware gate passes."""
        return (
            self._settings.telemetry_mode == "real"
            and self._user_authorized
            and self._hardware_asic_present
        )

    def assert_execution_permitted(self) -> None:
        """Raise PermissionError unless all safety and hardware gates are satisfied."""
        if self._settings.telemetry_mode != "real":
            raise PermissionError(
                "Real miner execution blocked: TELEMETRY_MODE is set to 'simulated'."
            )
        if not self._user_authorized:
            raise PermissionError(
                "Real miner execution blocked: explicit user authorization is required."
            )
        if not self._hardware_asic_present:
            raise PermissionError(
                "Real miner execution blocked by Phase 6 hardware gate: no SHA-256 ASIC detected "
                "(host is CPU/iGPU only; keep SimulatedMinerPoolAdapter active)."
            )


class ReadOnlyHttpPoolAdapter:
    """Read-only HTTP adapter for querying external pool statistics without running a local miner.

    Supports bounded retries, strict timeouts, secret redaction in logs, and safe degradation
    when unconfigured or unreachable.
    """

    def __init__(
        self,
        *,
        pool_name: str = "external_pool",
        status_url: str | None = None,
        auth_token: SecretStr | str | None = None,
        timeout_seconds: float = 3.0,
        max_retries: int = 2,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._pool_name = pool_name.strip() or "external_pool"
        self._status_url = status_url.strip() if status_url else None
        if isinstance(auth_token, SecretStr):
            self._token = auth_token.get_secret_value().strip()
        elif isinstance(auth_token, str):
            self._token = auth_token.strip()
        else:
            self._token = ""

        self._timeout_seconds = timeout_seconds
        self._max_retries = max(1, max_retries)
        self._http_client = http_client
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Return True if the last poll succeeded."""
        return self._connected

    def fetch_snapshot(
        self,
        observed_at_utc: datetime | str | None = None,
        session_id: str | None = None,
    ) -> PoolStatusSnapshot:
        """Poll the external pool API in read-only mode with bounded retry and timeout."""
        ts = normalize_utc_timestamp(observed_at_utc or datetime.now(UTC))
        source = f"pool_api:{self._pool_name}"

        if not self._status_url:
            self._connected = False
            return PoolStatusSnapshot(
                is_connected=False,
                hashrate_measurement=Measurement(
                    session_id=session_id,
                    metric_name="hashrate_hs",
                    value=None,
                    unit="H/s",
                    status="unavailable",
                    source=source,
                    observed_at_utc=ts,
                    quality_note="External pool URL is not configured (disconnected mode).",
                ),
                pool_reported_reward=None,
                recent_payouts=[],
            )

        headers: dict[str, str] = {"Accept": "application/json"}
        if self._token:
            headers["Pool-Auth-Token"] = self._token

        last_error: Exception | None = None
        payload: dict[str, Any] | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                if self._http_client is not None:
                    resp = self._http_client.get(
                        self._status_url,
                        headers=headers,
                        timeout=self._timeout_seconds,
                    )
                else:
                    with httpx.Client(timeout=self._timeout_seconds) as client:
                        resp = client.get(self._status_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise ValueError("Pool response JSON root must be an object.")
                payload = data
                break
            except Exception as exc:
                last_error = exc
                safe_msg = redact_sensitive_text(
                    str(exc),
                    explicit_secrets=(self._token,) if self._token else (),
                )
                logger.warning(
                    "Pool API poll attempt %d/%d failed (%s): %s",
                    attempt,
                    self._max_retries,
                    self._pool_name,
                    safe_msg,
                )

        if payload is None:
            self._connected = False
            err_type = type(last_error).__name__ if last_error else "UnknownError"
            return PoolStatusSnapshot(
                is_connected=False,
                hashrate_measurement=Measurement(
                    session_id=session_id,
                    metric_name="hashrate_hs",
                    value=None,
                    unit="H/s",
                    status="unavailable",
                    source=source,
                    observed_at_utc=ts,
                    quality_note=f"Pool API unreachable after {self._max_retries} attempts ({err_type}).",
                ),
                pool_reported_reward=None,
                recent_payouts=[],
            )

        self._connected = True
        raw_hs = payload.get("hashrate_hs")
        if raw_hs is not None:
            hs_measurement = Measurement(
                session_id=session_id,
                metric_name="hashrate_hs",
                value=float(raw_hs),
                unit="H/s",
                status="measured",
                source=source,
                observed_at_utc=ts,
            )
        else:
            hs_measurement = Measurement(
                session_id=session_id,
                metric_name="hashrate_hs",
                value=None,
                unit="H/s",
                status="unavailable",
                source=source,
                observed_at_utc=ts,
                quality_note="Pool API response did not include hashrate_hs.",
            )

        pool_reward: RewardSnapshot | None = None
        if payload.get("unpaid_balance_btc") is not None:
            balance_str = str(payload["unpaid_balance_btc"])
            pool_reward = RewardSnapshot(
                id=f"pool_bal_{self._pool_name}_{ts}",
                session_id=session_id,
                amount_btc=Decimal(balance_str),
                reward_stage="pool_reported",
                status="measured",
                source=source,
                observed_at_utc=ts,
            )

        payouts: list[PaymentEvent] = []
        raw_payouts = payload.get("payouts")
        if isinstance(raw_payouts, list):
            for item in raw_payouts:
                if not isinstance(item, dict):
                    continue
                tx_ref = str(item.get("txid", "")).strip() or None
                payout_id = str(item.get("id") or tx_ref or f"payout_{ts}")
                payouts.append(
                    PaymentEvent(
                        id=f"pool_pay_{self._pool_name}_{payout_id}",
                        event_type="payout_issued",
                        asset="BTC",
                        amount=Decimal(str(item["amount_btc"])),
                        network_fee=(
                            Decimal(str(item["fee_btc"]))
                            if item.get("fee_btc") is not None
                            else None
                        ),
                        settlement_status="confirmed",
                        data_status="measured",
                        source=source,
                        external_reference=tx_ref,
                        observed_at_utc=item.get("paid_at_utc", ts),
                    )
                )

        return PoolStatusSnapshot(
            is_connected=True,
            hashrate_measurement=hs_measurement,
            pool_reported_reward=pool_reward,
            recent_payouts=payouts,
        )
