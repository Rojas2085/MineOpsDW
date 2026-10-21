"""Optional Phase 11 Android telemetry ingestion adapter with token auth and staleness checks."""

from __future__ import annotations

from datetime import UTC, datetime
import hmac
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mineops_dw.adapters.sensors import build_safe_measurement
from mineops_dw.domain.models import Measurement, QualityStatus, normalize_utc_timestamp
from mineops_dw.storage.repositories import MineOpsRepository


class AndroidTelemetryPayload(BaseModel):
    """Payload sent by the optional Kotlin Android agent over the local network."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str = Field(min_length=1)
    observed_at_utc: str
    battery_percent: float | None = None
    battery_temp_c: float | None = None
    ram_used_mib: float | None = None
    is_charging: bool | None = None
    battery_saver_active: bool = False
    permission_denied: bool = False
    data_status: Literal["measured", "simulated"] = "measured"

    @field_validator("device_id")
    @classmethod
    def _clean_device_id(cls, val: str) -> str:
        cleaned = val.strip()
        if not cleaned:
            raise ValueError("device_id cannot be empty.")
        return cleaned

    @field_validator("observed_at_utc", mode="before")
    @classmethod
    def _validate_utc(cls, val: datetime | str) -> str:
        return normalize_utc_timestamp(val)


class AndroidTelemetryIngestionService:
    """Validates and ingests optional Android telemetry without coupling or blocking the PC MVP."""

    def __init__(
        self,
        repository: MineOpsRepository,
        *,
        expected_device_token: str | None = None,
        stale_after_seconds: int = 120,
    ) -> None:
        self._repo = repository
        self._expected_token = (
            expected_device_token.strip() if expected_device_token else None
        )
        self._stale_after_seconds = max(1, stale_after_seconds)

    def authenticate_token(self, provided_token: str | None) -> bool:
        """Verify the device token in constant time."""
        if not self._expected_token:
            return False
        candidate = (provided_token or "").strip()
        if not candidate:
            return False
        return hmac.compare_digest(self._expected_token, candidate)

    def ingest_payload(
        self,
        payload: AndroidTelemetryPayload,
        *,
        provided_token: str | None,
        received_at_utc: datetime | str | None = None,
    ) -> list[Measurement]:
        """Validate token, check staleness/permissions/battery saver, and persist measurements."""
        if not self.authenticate_token(provided_token):
            raise PermissionError("Invalid or missing Android device token.")

        now_iso = normalize_utc_timestamp(received_at_utc or datetime.now(UTC))
        now_dt = _parse_utc(now_iso)
        obs_dt = _parse_utc(payload.observed_at_utc)
        age_seconds = (now_dt - obs_dt).total_seconds()

        source = f"android:{payload.device_id}"
        is_stale = age_seconds > self._stale_after_seconds

        specs: tuple[tuple[str, float | None, str], ...] = (
            ("android_battery_percent", payload.battery_percent, "%"),
            ("android_battery_temp_c", payload.battery_temp_c, "°C"),
            ("android_ram_used_mib", payload.ram_used_mib, "MiB"),
        )

        measurements: list[Measurement] = []
        for metric_name, raw_val, unit in specs:
            if payload.permission_denied:
                measurements.append(
                    build_safe_measurement(
                        metric_name=metric_name,
                        value=None,
                        unit=unit,
                        status="unavailable",
                        source=source,
                        observed_at_utc=payload.observed_at_utc,
                        quality_note="Android OS permission denied for sensor access.",
                    )
                )
            elif is_stale:
                measurements.append(
                    build_safe_measurement(
                        metric_name=metric_name,
                        value=None,
                        unit=unit,
                        status="unavailable",
                        source=source,
                        observed_at_utc=payload.observed_at_utc,
                        quality_note=(
                            f"Stale Android telemetry sample ({age_seconds:.1f}s old > "
                            f"{self._stale_after_seconds}s limit)."
                        ),
                    )
                )
            elif raw_val is None:
                reason = (
                    "Throttled or omitted due to Android Battery Saver mode."
                    if payload.battery_saver_active
                    else "Sensor not exposed by Android device/API."
                )
                measurements.append(
                    build_safe_measurement(
                        metric_name=metric_name,
                        value=None,
                        unit=unit,
                        status="unavailable",
                        source=source,
                        observed_at_utc=payload.observed_at_utc,
                        quality_note=reason,
                    )
                )
            else:
                qual_status: QualityStatus = payload.data_status
                note = (
                    "Collected while Android Battery Saver was active."
                    if payload.battery_saver_active
                    else None
                )
                measurements.append(
                    build_safe_measurement(
                        metric_name=metric_name,
                        value=round(float(raw_val), 2),
                        unit=unit,
                        status=qual_status,
                        source=source,
                        observed_at_utc=payload.observed_at_utc,
                        quality_note=note,
                    )
                )

        for m in measurements:
            self._repo.insert_measurement(m)

        return measurements


def _parse_utc(iso_str: str) -> datetime:
    cleaned = iso_str[:-1] + "+00:00" if iso_str.endswith("Z") else iso_str
    return datetime.fromisoformat(cleaned).astimezone(UTC)
