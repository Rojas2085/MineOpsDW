"""Domain rules for energy estimation and hardware safety limits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from mineops_dw.domain.models import Measurement, normalize_utc_timestamp


@dataclass(frozen=True)
class SafetyEvaluation:
    """Result of checking hardware telemetry and duration against configured safety thresholds."""

    should_stop: bool
    should_pause: bool
    reason: str | None = None


def compute_energy_measurement(
    previous_power: Measurement | None,
    current_power: Measurement,
    session_id: str | None = None,
) -> Measurement:
    """Compute energy consumed (Wh) between two power (W) samples via trapezoidal integration.

    Never invents energy if either power sample is unavailable.
    """
    observed_at = current_power.observed_at_utc

    if (
        previous_power is None
        or previous_power.status == "unavailable"
        or previous_power.value is None
        or current_power.status == "unavailable"
        or current_power.value is None
    ):
        return Measurement(
            session_id=session_id or current_power.session_id,
            metric_name="energy_consumed_wh",
            value=None,
            unit="Wh",
            status="unavailable",
            source="calculation",
            observed_at_utc=observed_at,
            quality_note="Cannot compute Wh: valid consecutive power (W) measurements are unavailable.",
        )

    t0 = _parse_utc(previous_power.observed_at_utc)
    t1 = _parse_utc(current_power.observed_at_utc)
    delta_seconds = (t1 - t0).total_seconds()

    if delta_seconds <= 0:
        return Measurement(
            session_id=session_id or current_power.session_id,
            metric_name="energy_consumed_wh",
            value=None,
            unit="Wh",
            status="unavailable",
            source="calculation",
            observed_at_utc=observed_at,
            quality_note="Cannot compute Wh: non-positive time delta between power samples.",
        )

    avg_watts = (previous_power.value + current_power.value) / 2.0
    energy_wh = avg_watts * (delta_seconds / 3600.0)
    derived_status = (
        "simulated"
        if "simulated" in (previous_power.status, current_power.status)
        else "estimated"
    )

    return Measurement(
        session_id=session_id or current_power.session_id,
        metric_name="energy_consumed_wh",
        value=round(energy_wh, 6),
        unit="Wh",
        status=derived_status,
        source="calculation",
        observed_at_utc=observed_at,
        quality_note="Trapezoidal integration from CPU package power (excludes PSU/wall losses).",
    )


def estimate_power_from_tdp(
    cpu_percent_measurement: Measurement | None,
    *,
    tdp_watts: float = 65.0,
    kappa: float = 1.0,
    observed_at_utc: str | datetime | None = None,
    session_id: str | None = None,
) -> Measurement:
    """Estimate CPU package power (W) from CPU load (%) and design TDP when physical sensor is absent.

    Strictly tags output as status='estimated' (or 'simulated' if input is simulated) and
    source='calculation:tdp_fallback' — never 'measured'.
    """
    obs_utc = normalize_utc_timestamp(
        observed_at_utc
        if observed_at_utc is not None
        else (
            cpu_percent_measurement.observed_at_utc
            if cpu_percent_measurement is not None
            else datetime.now(UTC)
        )
    )
    resolved_session = (
        session_id
        if session_id is not None
        else (cpu_percent_measurement.session_id if cpu_percent_measurement is not None else None)
    )

    if (
        cpu_percent_measurement is None
        or cpu_percent_measurement.metric_name != "cpu_percent_total"
        or cpu_percent_measurement.status == "unavailable"
        or cpu_percent_measurement.value is None
        or tdp_watts <= 0.0
        or kappa <= 0.0
    ):
        return Measurement(
            session_id=resolved_session,
            metric_name="cpu_package_power_w",
            value=None,
            unit="W",
            status="unavailable",
            source="calculation:tdp_fallback",
            observed_at_utc=obs_utc,
            quality_note="Cannot estimate TDP power: valid cpu_percent_total measurement is unavailable.",
        )

    cpu_pct = max(0.0, min(100.0, float(cpu_percent_measurement.value)))
    est_watts = round(tdp_watts * (cpu_pct / 100.0) * kappa, 4)
    derived_status = "simulated" if cpu_percent_measurement.status == "simulated" else "estimated"
    return Measurement(
        session_id=resolved_session,
        metric_name="cpu_package_power_w",
        value=est_watts,
        unit="W",
        status=derived_status,
        source="calculation:tdp_fallback",
        observed_at_utc=obs_utc,
        quality_note=f"Estimated from CPU load ({cpu_pct:.1f}%) and TDP ({tdp_watts:.1f}W, kappa={kappa:.2f}).",
    )


def evaluate_safety_limits(
    measurements: list[Measurement],
    *,
    max_cpu_percent: float,
    max_cpu_temp_c: float,
    max_session_minutes: int,
    session_started_at_utc: str | datetime | None = None,
    now_utc: str | datetime | None = None,
) -> SafetyEvaluation:
    """Evaluate current measurements and session duration against safety limits."""
    if session_started_at_utc is not None and now_utc is not None:
        start_dt = _parse_utc(normalize_utc_timestamp(session_started_at_utc))
        current_dt = _parse_utc(normalize_utc_timestamp(now_utc))
        elapsed_minutes = (current_dt - start_dt).total_seconds() / 60.0
        if elapsed_minutes >= max_session_minutes:
            return SafetyEvaluation(
                should_stop=True,
                should_pause=False,
                reason="max_duration_reached",
            )

    for m in measurements:
        if m.status == "unavailable" or m.value is None:
            continue
        if m.metric_name == "cpu_temp_c" and m.value >= max_cpu_temp_c:
            return SafetyEvaluation(
                should_stop=True,
                should_pause=False,
                reason="max_cpu_temp_exceeded",
            )

    for m in measurements:
        if m.status == "unavailable" or m.value is None:
            continue
        if m.metric_name == "cpu_percent_total" and m.value >= max_cpu_percent:
            return SafetyEvaluation(
                should_stop=False,
                should_pause=True,
                reason="max_cpu_load_exceeded",
            )

    return SafetyEvaluation(should_stop=False, should_pause=False, reason=None)


def _parse_utc(iso_str: str) -> datetime:
    cleaned = iso_str[:-1] + "+00:00" if iso_str.endswith("Z") else iso_str
    return datetime.fromisoformat(cleaned).astimezone(UTC)
