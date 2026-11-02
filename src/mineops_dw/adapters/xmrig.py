"""Local XMRig HTTP API passive observation adapter (CP-01-A, CP-02 Option B adjusted).

This adapter operates exclusively in passive read-only observation mode via GET /2/summary.
It never launches, terminates, pauses, or resumes XMRig over the network.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import ipaddress
import logging
import math
from typing import Any, Literal
from urllib.parse import urlsplit
import uuid

import httpx
from pydantic import SecretStr

from mineops_dw.domain.miner_connector import (
    CommandResult,
    ControlAuthorization,
    DataOrigin,
    LocalClientReadiness,
    MetricObservation,
    MinerCapabilities,
    MinerOperationalState,
    MinerSnapshot,
    ProcessProgressState,
)
from mineops_dw.domain.models import normalize_utc_timestamp

logger = logging.getLogger("mineops_dw.adapters.xmrig")


class XMRigApiError(RuntimeError):
    """Safe, user-facing error for XMRig API communication or response failures."""


@dataclass(frozen=True)
class XMRigSummary:
    """Normalized subset of XMRig's summary response preserved for compatibility."""

    version: str | None
    algorithm: str | None
    paused: bool | None
    hashrate_10s_hs: float | None
    hashrate_60s_hs: float | None
    hashrate_15m_hs: float | None
    shares_good: int | None
    shares_total: int | None
    hashes_total: int | None
    pool_url: str | None
    uptime_seconds: int | None


@dataclass(frozen=True)
class ShareDelta:
    """Non-negative counter differences since a session baseline."""

    shares_good: int
    shares_total: int
    hashes_total: int
    baseline_reset: bool = False


class XMRigShareCounter:
    """Track session-local deltas from XMRig's process-lifetime counters."""

    def __init__(self) -> None:
        self._baseline: tuple[int, int, int] | None = None
        self._previous: tuple[int, int, int] | None = None

    def start_session(self, summary: XMRigSummary) -> None:
        baseline = (
            summary.shares_good or 0,
            summary.shares_total or 0,
            summary.hashes_total or 0,
        )
        self._baseline = baseline
        self._previous = baseline

    def update(self, summary: XMRigSummary) -> ShareDelta:
        current = (
            summary.shares_good or 0,
            summary.shares_total or 0,
            summary.hashes_total or 0,
        )
        if self._baseline is None or self._previous is None:
            self._baseline = current
            self._previous = current
            return ShareDelta(0, 0, 0)

        reset = any(now < old for now, old in zip(current, self._previous, strict=True))
        if reset:
            self._baseline = current
            self._previous = current
            return ShareDelta(0, 0, 0, baseline_reset=True)

        self._previous = current
        deltas = (max(0, now - base) for now, base in zip(current, self._baseline, strict=True))
        return ShareDelta(*deltas)


class XMRigApiAdapter:
    """Passive read-only XMRig adapter implementing MinerConnector (CP-01-A, CP-02)."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:18080",
        access_token: SecretStr | str | None = None,
        timeout_seconds: float = 3.0,
        http_client: httpx.Client | None = None,
        authorization: ControlAuthorization | None = None,
        data_origin: DataOrigin = "REAL",
        stall_threshold_seconds: float | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._base_url = self._validate_base_url(base_url)
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive number.")
        if stall_threshold_seconds is not None and (
            not math.isfinite(stall_threshold_seconds) or stall_threshold_seconds <= 0
        ):
            raise ValueError("stall_threshold_seconds must be a finite positive number when provided.")
        if isinstance(access_token, SecretStr):
            self._token = access_token.get_secret_value().strip()
        elif isinstance(access_token, str):
            self._token = access_token.strip()
        else:
            self._token = ""
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._authorization = authorization
        self._data_origin: DataOrigin = data_origin
        self._stall_threshold_seconds = stall_threshold_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

        # Session progress tracking for uptime (XMR-03, CP-02)
        self._last_uptime_value: int | None = None
        self._last_uptime_changed_at: datetime | None = None

    @property
    def config_fingerprint(self) -> str:
        digest = hashlib.sha256(f"{self._base_url}|{self._token}".encode("utf-8")).hexdigest()
        return digest[:16]

    def update_credentials(self, access_token: SecretStr | str | None) -> None:
        """Update token and invalidate session evidence (XMR-04)."""
        if isinstance(access_token, SecretStr):
            self._token = access_token.get_secret_value().strip()
        elif isinstance(access_token, str):
            self._token = access_token.strip()
        else:
            self._token = ""
        self._last_uptime_value = None
        self._last_uptime_changed_at = None

    @staticmethod
    def _validate_base_url(value: str) -> str:
        """Require plain HTTP to an explicit loopback host, without URL credentials."""
        cleaned = value.strip().rstrip("/") if isinstance(value, str) else ""
        try:
            parsed = urlsplit(cleaned)
            host = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise ValueError("XMRig API URL is invalid.") from exc
        if (
            parsed.scheme != "http"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or port is None
            or not 1 <= port <= 65535
        ):
            raise ValueError("XMRig API URL must be an HTTP loopback origin with an explicit port.")
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host.lower() == "localhost"
        if not is_loopback:
            raise ValueError("XMRig API must be bound to loopback; remote hosts are forbidden.")
        rendered_host = f"[{host}]" if ":" in host else host
        return f"http://{rendered_host}:{port}"

    def _get_raw_summary(self) -> tuple[int | None, dict[str, Any] | None, str | None]:
        """Perform passive GET /2/summary returning (status_code, json_dict, error_kind)."""
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        url = f"{self._base_url}/2/summary"
        try:
            if self._http_client is not None:
                response = self._http_client.request(
                    "GET",
                    url,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            else:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.request("GET", url, headers=headers)
        except Exception as exc:
            logger.warning("XMRig API GET /2/summary failed (%s).", type(exc).__name__)
            return None, None, "UNREACHABLE"

        status_code = response.status_code
        if status_code in (401, 403):
            return status_code, None, "AUTH_REJECTED"
        if status_code != 200:
            return status_code, None, "HTTP_ERROR"

        try:
            data = response.json()
        except Exception:
            return status_code, None, "INVALID_JSON"

        if not isinstance(data, dict):
            return status_code, None, "INVALID_JSON"
        return status_code, data, None

    @staticmethod
    def _is_recognized_schema(data: dict[str, Any]) -> bool:
        """Validate CP-02 (Option B adjusted) root structural requirements."""
        version = data.get("version")
        kind = data.get("kind")
        paused = data.get("paused")
        if not isinstance(version, str) or not version.strip():
            return False
        if kind != "miner":
            return False
        if type(paused) is not bool:
            return False
        return True

    def _evaluate_process_progress(
        self, uptime_val: int | None, observed_dt: datetime
    ) -> ProcessProgressState:
        """Evaluate process_progress from uptime without inferring from hashrate (XMR-03, CP-01-A, CP-02)."""
        if uptime_val is None:
            return "UNKNOWN"
        if self._last_uptime_value is None or self._last_uptime_changed_at is None:
            self._last_uptime_value = uptime_val
            self._last_uptime_changed_at = observed_dt
            return "UNKNOWN"

        if uptime_val > self._last_uptime_value:
            self._last_uptime_value = uptime_val
            self._last_uptime_changed_at = observed_dt
            return "ADVANCING"

        if uptime_val < self._last_uptime_value:
            # Process counter reset; new baseline requires another sample to confirm advancement
            self._last_uptime_value = uptime_val
            self._last_uptime_changed_at = observed_dt
            return "UNKNOWN"

        elapsed = (observed_dt - self._last_uptime_changed_at).total_seconds()
        if self._stall_threshold_seconds is not None and elapsed > self._stall_threshold_seconds:
            return "STALLED_SUSPECTED"
        if elapsed <= 2.0:
            return "UNCHANGED_WITHIN_RESOLUTION"
        if self._stall_threshold_seconds is None:
            return "UNKNOWN"
        return "UNCHANGED_WITHIN_RESOLUTION"

    def get_snapshot(self) -> MinerSnapshot:
        """Observe current XMRig state via GET /2/summary (CP-02 Option B adjusted)."""
        now_dt = self._clock()
        now_utc = normalize_utc_timestamp(now_dt)
        status_code, data, error_kind = self._get_raw_summary()

        if error_kind == "UNREACHABLE":
            return MinerSnapshot(
                observed_at_utc=now_utc,
                connection_status="UNREACHABLE",
                operational_state="UNKNOWN",
                state_confidence="UNKNOWN",
                operational_state_quality="UNAVAILABLE",
                process_progress="UNKNOWN",
                data_origin="UNKNOWN",
            )

        if error_kind in ("AUTH_REJECTED", "HTTP_ERROR", "INVALID_JSON") or data is None:
            conn_status = "REACHABLE" if status_code in (401, 403) else "DEGRADED"
            quality = "UNAVAILABLE" if status_code in (401, 403) else "INVALID"
            return MinerSnapshot(
                observed_at_utc=now_utc,
                connection_status=conn_status,
                operational_state="UNKNOWN",
                state_confidence="UNKNOWN",
                operational_state_quality=quality,
                process_progress="UNKNOWN",
                data_origin=self._data_origin,
            )

        if not self._is_recognized_schema(data):
            return MinerSnapshot(
                observed_at_utc=now_utc,
                connection_status="DEGRADED",
                operational_state="UNKNOWN",
                state_confidence="UNKNOWN",
                operational_state_quality="INVALID",
                process_progress="UNKNOWN",
                data_origin=self._data_origin,
            )

        paused_bool: bool = data["paused"]
        op_state: MinerOperationalState = "PAUSED" if paused_bool else "RUNNING"
        version_str = data["version"].strip()
        kind_str = data["kind"]
        algo_str = self._optional_text(data.get("algo"))

        connection_obj = data.get("connection")
        connection_dict = connection_obj if isinstance(connection_obj, dict) else {}
        pool_url = self._optional_text(connection_dict.get("pool"))

        # Uptime can be at root or inside connection; optional for operational_state (CP-02)
        raw_uptime = data.get("uptime") if "uptime" in data else connection_dict.get("uptime")
        uptime_obs = self._parse_nonnegative_int_metric(
            raw_uptime, present=("uptime" in data or "uptime" in connection_dict)
        )
        progress = self._evaluate_process_progress(uptime_obs.value, now_dt)

        hashrate_obj = data.get("hashrate")
        rates_obs = self._parse_hashrate_metrics(hashrate_obj)

        results_obj = data.get("results")
        results_dict = results_obj if isinstance(results_obj, dict) else {}
        shares_good_obs = self._parse_nonnegative_int_metric(
            results_dict.get("shares_good"), present="shares_good" in results_dict
        )
        shares_total_obs = self._parse_nonnegative_int_metric(
            results_dict.get("shares_total"), present="shares_total" in results_dict
        )
        if (
            shares_good_obs.value is not None
            and shares_total_obs.value is not None
            and shares_total_obs.value < shares_good_obs.value
        ):
            shares_good_obs = MetricObservation(
                None, "INVALID", quality_note="shares_total < shares_good"
            )
            shares_total_obs = MetricObservation(
                None, "INVALID", quality_note="shares_total < shares_good"
            )
        hashes_total_obs = self._parse_nonnegative_int_metric(
            results_dict.get("hashes_total"), present="hashes_total" in results_dict
        )

        return MinerSnapshot(
            observed_at_utc=now_utc,
            connection_status="REACHABLE",
            operational_state=op_state,
            state_confidence="CONFIRMED",
            operational_state_quality="VALID",
            process_progress=progress,
            data_origin=self._data_origin,
            version=version_str,
            kind=kind_str,
            algorithm=algo_str,
            pool_url=pool_url,
            hashrate_10s_hs=rates_obs[0],
            hashrate_60s_hs=rates_obs[1],
            hashrate_15m_hs=rates_obs[2],
            shares_good=shares_good_obs,
            shares_total=shares_total_obs,
            hashes_total=hashes_total_obs,
            uptime_seconds=uptime_obs,
        )

    def get_capabilities(self) -> MinerCapabilities:
        """Evaluate XMRig capabilities passively (XMR-04, CP-01-A, CP-02)."""
        now_utc = normalize_utc_timestamp(self._clock())
        local_readiness: LocalClientReadiness = (
            "TOKEN_CONFIGURED" if self._token else "MISSING_LOCAL_TOKEN"
        )
        status_code, data, error_kind = self._get_raw_summary()

        if error_kind == "UNREACHABLE":
            return MinerCapabilities(
                evaluated_at_utc=now_utc,
                status="UNAVAILABLE",
                connection_status="UNREACHABLE",
                local_readiness=local_readiness,
                observe="UNVERIFIED_PASSIVELY",
                state_verification="UNVERIFIED_PASSIVELY",
                pause="UNVERIFIED_PASSIVELY",
                resume="UNVERIFIED_PASSIVELY",
                config_fingerprint=self.config_fingerprint,
            )

        if error_kind == "AUTH_REJECTED" or status_code in (401, 403):
            return MinerCapabilities(
                evaluated_at_utc=now_utc,
                status="UNAVAILABLE",
                connection_status="REACHABLE",
                local_readiness="READ_AUTH_REJECTED",
                observe="UNVERIFIED_PASSIVELY",
                state_verification="UNVERIFIED_PASSIVELY",
                pause="UNVERIFIED_PASSIVELY",
                resume="UNVERIFIED_PASSIVELY",
                config_fingerprint=self.config_fingerprint,
            )

        if error_kind is not None or data is None:
            return MinerCapabilities(
                evaluated_at_utc=now_utc,
                status="UNAVAILABLE",
                connection_status="DEGRADED",
                local_readiness=local_readiness,
                observe="UNVERIFIED_PASSIVELY",
                state_verification="UNVERIFIED_PASSIVELY",
                pause="UNVERIFIED_PASSIVELY",
                resume="UNVERIFIED_PASSIVELY",
                config_fingerprint=self.config_fingerprint,
            )

        if not self._is_recognized_schema(data):
            return MinerCapabilities(
                evaluated_at_utc=now_utc,
                status="UNAVAILABLE",
                connection_status="DEGRADED",
                local_readiness=local_readiness,
                observe="CONFIRMED_AVAILABLE",
                state_verification="CONFIRMED_UNAVAILABLE",
                pause="UNVERIFIED_PASSIVELY",
                resume="UNVERIFIED_PASSIVELY",
                config_fingerprint=self.config_fingerprint,
            )

        # CP-01-A: XMRig is permanently passive READ_ONLY; pause/resume stay UNVERIFIED_PASSIVELY
        return MinerCapabilities(
            evaluated_at_utc=now_utc,
            status="READ_ONLY",
            connection_status="REACHABLE",
            local_readiness=local_readiness,
            observe="CONFIRMED_AVAILABLE",
            state_verification="CONFIRMED_AVAILABLE",
            pause="UNVERIFIED_PASSIVELY",
            resume="UNVERIFIED_PASSIVELY",
            config_fingerprint=self.config_fingerprint,
        )

    def pause(self) -> CommandResult:
        """Reject pause locally without network I/O (CP-01-A)."""
        return self._reject_control_locally("PAUSE")

    def resume(self) -> CommandResult:
        """Reject resume locally without network I/O (CP-01-A)."""
        return self._reject_control_locally("RESUME")

    def _reject_control_locally(self, action: Literal["PAUSE", "RESUME"]) -> CommandResult:
        now_utc = normalize_utc_timestamp(self._clock())
        generation = (
            self._authorization.authorization_generation
            if self._authorization is not None
            else 0
        )
        return CommandResult(
            command_id=f"cmd-{uuid.uuid4().hex[:8]}",
            action=action,
            requested_at_utc=now_utc,
            completed_at_utc=now_utc,
            delivery="NOT_SENT",
            acceptance="UNKNOWN",
            postcondition="NOT_ATTEMPTED",
            authorization_generation=generation,
            revoked_during_execution=False,
            pre_snapshot=None,
            post_snapshot=None,
            causal_attribution="NOT_APPLICABLE",
        )

    def fetch_summary(self) -> XMRigSummary:
        """Fetch summary for legacy compatibility (GET /2/summary only)."""
        status_code, data, error_kind = self._get_raw_summary()
        if error_kind is not None or data is None:
            raise XMRigApiError(
                f"XMRig API GET /2/summary failed ({error_kind or status_code})."
            )
        hashrate = data.get("hashrate")
        results = data.get("results")
        connection = data.get("connection")
        hashrate = hashrate if isinstance(hashrate, dict) else {}
        results = results if isinstance(results, dict) else {}
        connection = connection if isinstance(connection, dict) else {}
        raw_rates = hashrate.get("total")
        rates: list[float | None] = [None, None, None]
        if isinstance(raw_rates, list):
            for index, raw in enumerate(raw_rates[:3]):
                if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                    value = float(raw)
                    if math.isfinite(value) and value >= 0:
                        rates[index] = value
        paused = data.get("paused")
        if type(paused) is not bool:
            paused = None
        raw_uptime = data.get("uptime") if "uptime" in data else connection.get("uptime")
        return XMRigSummary(
            version=self._optional_text(data.get("version")),
            algorithm=self._optional_text(data.get("algo")),
            paused=paused,
            hashrate_10s_hs=rates[0],
            hashrate_60s_hs=rates[1],
            hashrate_15m_hs=rates[2],
            shares_good=self._optional_nonnegative_int(results.get("shares_good")),
            shares_total=self._optional_nonnegative_int(results.get("shares_total")),
            hashes_total=self._optional_nonnegative_int(results.get("hashes_total")),
            pool_url=self._optional_text(connection.get("pool")),
            uptime_seconds=self._optional_nonnegative_int(raw_uptime),
        )

    @staticmethod
    def _parse_hashrate_metrics(
        hashrate_obj: Any,
    ) -> tuple[MetricObservation[float], MetricObservation[float], MetricObservation[float]]:
        if hashrate_obj is None:
            unavail = MetricObservation[float](None, "UNAVAILABLE", quality_note="hashrate block missing")
            return (unavail, unavail, unavail)
        if not isinstance(hashrate_obj, dict):
            inv = MetricObservation[float](None, "INVALID", quality_note="hashrate block is not an object")
            return (inv, inv, inv)
        raw_rates = hashrate_obj.get("total")
        if raw_rates is None:
            unavail = MetricObservation[float](None, "UNAVAILABLE", quality_note="hashrate.total missing")
            return (unavail, unavail, unavail)
        if not isinstance(raw_rates, list):
            inv = MetricObservation[float](None, "INVALID", quality_note="hashrate.total is not a list")
            return (inv, inv, inv)

        parsed: list[MetricObservation[float]] = []
        for idx in range(3):
            if idx >= len(raw_rates) or raw_rates[idx] is None:
                parsed.append(MetricObservation(None, "UNAVAILABLE", quality_note="window value unavailable"))
                continue
            item = raw_rates[idx]
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                parsed.append(MetricObservation(None, "INVALID", quality_note="non-numeric hashrate"))
                continue
            val = float(item)
            if not math.isfinite(val) or val < 0.0:
                parsed.append(MetricObservation(None, "INVALID", quality_note="negative or non-finite hashrate"))
                continue
            parsed.append(
                MetricObservation(
                    val,
                    "VALID",
                    source_freshness="UNVERIFIABLE_NO_SOURCE_TIMESTAMP",
                    source_updated_at_utc=None,
                )
            )
        return (parsed[0], parsed[1], parsed[2])

    @staticmethod
    def _parse_nonnegative_int_metric(raw: Any, *, present: bool) -> MetricObservation[int]:
        if not present or raw is None:
            return MetricObservation(None, "UNAVAILABLE", quality_note="metric not present")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            return MetricObservation(None, "INVALID", quality_note="metric must be a non-negative int")
        return MetricObservation(
            raw,
            "VALID",
            source_freshness="UNVERIFIABLE_NO_SOURCE_TIMESTAMP",
            source_updated_at_utc=None,
        )

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _optional_nonnegative_int(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value
