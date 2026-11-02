"""Passive read-only HTTP loopback MinerConnector for SRBMiner-Multi (PROJECT_SPEC Sections 3, 6).

Enforces:
- Strict loopback-only URL validation (`http://127.0.0.1:21550` by default).
- Passive read-only observation via `GET /` with conservative structural schema validation
  (`miner_version` non-empty string and `algorithms` list).
- Independent per-metric TelemetryQuality (`hashrate`, `shares_good`, `shares_total`, `uptime_seconds`)
  and `process_progress` derived from `mining_time` advancement without inferring state from hashrate.
- Permanent passive mode: `MinerCapabilities.status = "READ_ONLY"` when observation works (or `"UNAVAILABLE"`
  on failure), `pause` and `resume` remain `"UNVERIFIED_PASSIVELY"`, and `pause()` / `resume()` reject
  locally without network I/O (`delivery="NOT_SENT"`, `acceptance="UNKNOWN"`, `postcondition="NOT_ATTEMPTED"`).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import ipaddress
import logging
import math
from typing import Any
from urllib.parse import urlsplit
import uuid

import httpx

from mineops_dw.domain.miner_connector import (
    CommandResult,
    ControlAuthorization,
    DataOrigin,
    MetricObservation,
    MinerCapabilities,
    MinerOperationalState,
    MinerSnapshot,
    ProcessProgressState,
    StateConfidence,
)
from mineops_dw.domain.models import normalize_utc_timestamp

logger = logging.getLogger("mineops_dw.adapters.srbminer")


class SRBMinerApiAdapter:
    """Passive read-only HTTP loopback adapter for SRBMiner-Multi implementing MinerConnector."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:21550",
        timeout_seconds: float = 2.0,
        http_client: httpx.Client | None = None,
        authorization: ControlAuthorization | None = None,
        data_origin: DataOrigin = "REAL",
        stall_threshold_seconds: float | None = 30.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 10.0:
            raise ValueError("SRBMiner timeout_seconds must be in (0, 10.0].")
        if stall_threshold_seconds is not None and stall_threshold_seconds <= 0:
            raise ValueError("stall_threshold_seconds must be positive when provided.")

        self._base_url = self._validate_loopback_base_url(base_url)
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._authorization = authorization
        self._data_origin: DataOrigin = data_origin
        self._stall_threshold_seconds = stall_threshold_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

        self._last_uptime_value: int | None = None
        self._last_uptime_changed_at: datetime | None = None

    @staticmethod
    def _validate_loopback_base_url(base_url: str) -> str:
        raw = base_url.strip()
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port
        if (
            parsed.scheme != "http"
            or not host
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or port is None
            or not 1 <= port <= 65535
        ):
            raise ValueError(
                "SRBMiner API URL must be an HTTP loopback origin with an explicit port."
            )
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host.lower() == "localhost"
        if not is_loopback:
            raise ValueError("SRBMiner API must be bound to loopback; remote hosts are forbidden.")
        rendered_host = f"[{host}]" if ":" in host else host
        return f"http://{rendered_host}:{port}"

    def _current_auth_generation(self) -> int:
        if self._authorization is not None:
            return self._authorization.authorization_generation
        return 0

    def _get_raw_telemetry(self) -> tuple[int | None, dict[str, Any] | None, str | None]:
        headers = {"Accept": "application/json"}
        url = f"{self._base_url}/"
        try:
            if self._http_client is not None:
                response = self._http_client.request(
                    "GET", url, headers=headers, timeout=self._timeout_seconds
                )
            else:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.request("GET", url, headers=headers)
        except Exception as exc:
            logger.warning("SRBMiner API GET / failed (%s).", type(exc).__name__)
            return None, None, "UNREACHABLE"

        status_code = response.status_code
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
        miner_version = data.get("miner_version")
        algorithms = data.get("algorithms")
        if not isinstance(miner_version, str) or not miner_version.strip():
            return False
        if not isinstance(algorithms, list) or not all(isinstance(a, dict) for a in algorithms):
            return False
        if "is_paused" in data and type(data["is_paused"]) is not bool:
            return False
        return True

    def _evaluate_process_progress(
        self, uptime_val: int | None, observed_dt: datetime
    ) -> ProcessProgressState:
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
        """Observe SRBMiner-Multi telemetry via GET / without inferring state from hashrate."""
        now_dt = self._clock()
        now_utc = normalize_utc_timestamp(now_dt)
        _, data, error_kind = self._get_raw_telemetry()

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

        if error_kind in ("HTTP_ERROR", "INVALID_JSON") or data is None:
            return MinerSnapshot(
                observed_at_utc=now_utc,
                connection_status="DEGRADED",
                operational_state="UNKNOWN",
                state_confidence="UNKNOWN",
                operational_state_quality="INVALID",
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

        if "is_paused" in data:
            op_state: MinerOperationalState = "PAUSED" if data["is_paused"] else "RUNNING"
            confidence: StateConfidence = "CONFIRMED"
        else:
            op_state = "RUNNING"
            confidence = "INFERRED"

        version_str = data["miner_version"].strip()
        algos: list[dict[str, Any]] = data["algorithms"]
        first_algo = algos[0] if algos else {}
        algo_name = (
            first_algo.get("name").strip()
            if isinstance(first_algo.get("name"), str) and first_algo.get("name").strip()
            else None
        )
        pool_info = first_algo.get("pool") if isinstance(first_algo.get("pool"), dict) else {}
        pool_url = (
            pool_info.get("pool").strip()
            if isinstance(pool_info.get("pool"), str) and pool_info.get("pool").strip()
            else None
        )

        uptime_obs = self._parse_nonnegative_int(
            data.get("mining_time"), present="mining_time" in data
        )
        progress = self._evaluate_process_progress(uptime_obs.value, now_dt)

        hs_obs = self._extract_hashrate(first_algo, data)
        shares_good_obs, shares_total_obs = self._extract_shares(first_algo)

        return MinerSnapshot(
            observed_at_utc=now_utc,
            connection_status="REACHABLE",
            operational_state=op_state,
            state_confidence=confidence,
            operational_state_quality="VALID",
            process_progress=progress,
            data_origin=self._data_origin,
            version=version_str,
            kind="srbminer",
            algorithm=algo_name,
            pool_url=pool_url,
            hashrate_10s_hs=hs_obs,
            hashrate_60s_hs=MetricObservation(None, "UNAVAILABLE"),
            hashrate_15m_hs=MetricObservation(None, "UNAVAILABLE"),
            shares_good=shares_good_obs,
            shares_total=shares_total_obs,
            hashes_total=MetricObservation(None, "UNAVAILABLE"),
            uptime_seconds=uptime_obs,
        )

    def get_capabilities(self) -> MinerCapabilities:
        """Evaluate passive capabilities (READ_ONLY when valid schema is observed, UNAVAILABLE otherwise)."""
        now_utc = normalize_utc_timestamp(self._clock())
        _, data, error_kind = self._get_raw_telemetry()
        if error_kind == "UNREACHABLE":
            return MinerCapabilities(
                evaluated_at_utc=now_utc,
                status="UNAVAILABLE",
                connection_status="UNREACHABLE",
                local_readiness="CONTROL_DISABLED_LOCALLY",
                observe="UNVERIFIED_PASSIVELY",
                state_verification="UNVERIFIED_PASSIVELY",
                pause="UNVERIFIED_PASSIVELY",
                resume="UNVERIFIED_PASSIVELY",
            )
        if error_kind is not None or data is None or not self._is_recognized_schema(data):
            return MinerCapabilities(
                evaluated_at_utc=now_utc,
                status="UNAVAILABLE",
                connection_status="DEGRADED",
                local_readiness="CONTROL_DISABLED_LOCALLY",
                observe="CONFIRMED_UNAVAILABLE",
                state_verification="CONFIRMED_UNAVAILABLE",
                pause="UNVERIFIED_PASSIVELY",
                resume="UNVERIFIED_PASSIVELY",
            )
        return MinerCapabilities(
            evaluated_at_utc=now_utc,
            status="READ_ONLY",
            connection_status="REACHABLE",
            local_readiness="CONTROL_DISABLED_LOCALLY",
            observe="CONFIRMED_AVAILABLE",
            state_verification="CONFIRMED_AVAILABLE",
            pause="UNVERIFIED_PASSIVELY",
            resume="UNVERIFIED_PASSIVELY",
        )

    def pause(self) -> CommandResult:
        """Reject pause() locally with zero network I/O."""
        now_utc = normalize_utc_timestamp(self._clock())
        return CommandResult(
            command_id=f"srbminer-pause-disabled-{uuid.uuid4().hex[:12]}",
            action="PAUSE",
            requested_at_utc=now_utc,
            completed_at_utc=now_utc,
            delivery="NOT_SENT",
            acceptance="UNKNOWN",
            postcondition="NOT_ATTEMPTED",
            authorization_generation=self._current_auth_generation(),
            revoked_during_execution=False,
            pre_snapshot=None,
            post_snapshot=None,
            causal_attribution="NOT_APPLICABLE",
        )

    def resume(self) -> CommandResult:
        """Reject resume() locally with zero network I/O."""
        now_utc = normalize_utc_timestamp(self._clock())
        return CommandResult(
            command_id=f"srbminer-resume-disabled-{uuid.uuid4().hex[:12]}",
            action="RESUME",
            requested_at_utc=now_utc,
            completed_at_utc=now_utc,
            delivery="NOT_SENT",
            acceptance="UNKNOWN",
            postcondition="NOT_ATTEMPTED",
            authorization_generation=self._current_auth_generation(),
            revoked_during_execution=False,
            pre_snapshot=None,
            post_snapshot=None,
            causal_attribution="NOT_APPLICABLE",
        )

    @staticmethod
    def _parse_nonnegative_int(value: Any, *, present: bool) -> MetricObservation[int]:
        if not present or value is None:
            return MetricObservation(None, "UNAVAILABLE")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return MetricObservation(None, "INVALID")
        return MetricObservation(value, "VALID")

    @staticmethod
    def _extract_hashrate(
        first_algo: dict[str, Any], root: dict[str, Any]
    ) -> MetricObservation[float]:
        hr_obj = first_algo.get("hashrate")
        raw_val: Any = None
        present = False
        if isinstance(hr_obj, dict):
            cpu_obj = hr_obj.get("cpu")
            if isinstance(cpu_obj, dict) and "total" in cpu_obj:
                raw_val = cpu_obj.get("total")
                present = True
            elif "now" in hr_obj:
                raw_val = hr_obj.get("now")
                present = True
        elif "total_cpu_hashrate" in root:
            raw_val = root.get("total_cpu_hashrate")
            present = True

        if not present or raw_val is None:
            return MetricObservation(None, "UNAVAILABLE")
        if isinstance(raw_val, bool) or not isinstance(raw_val, (int, float)):
            return MetricObservation(None, "INVALID")
        numeric = float(raw_val)
        if not math.isfinite(numeric) or numeric < 0.0:
            return MetricObservation(None, "INVALID")
        return MetricObservation(numeric, "VALID")

    @classmethod
    def _extract_shares(
        cls, first_algo: dict[str, Any]
    ) -> tuple[MetricObservation[int], MetricObservation[int]]:
        shares_obj = first_algo.get("shares")
        if not isinstance(shares_obj, dict):
            return MetricObservation(None, "UNAVAILABLE"), MetricObservation(None, "UNAVAILABLE")
        acc_obs = cls._parse_nonnegative_int(
            shares_obj.get("accepted"), present="accepted" in shares_obj
        )
        rej_obs = cls._parse_nonnegative_int(
            shares_obj.get("rejected"), present="rejected" in shares_obj
        )
        if acc_obs.value is not None and rej_obs.value is not None:
            total_obs = MetricObservation(acc_obs.value + rej_obs.value, "VALID")
        elif acc_obs.quality == "INVALID" or rej_obs.quality == "INVALID":
            total_obs = MetricObservation(None, "INVALID")
        else:
            total_obs = MetricObservation(None, "UNAVAILABLE")
        return acc_obs, total_obs
