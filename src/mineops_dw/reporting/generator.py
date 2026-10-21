"""30-minute analytical report generator with gap detection, quality tracking, and JSON/CSV export."""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from mineops_dw.domain.models import (
    DataMode,
    Measurement,
    PeriodicReport,
    normalize_decimal_str,
    normalize_utc_timestamp,
)
from mineops_dw.storage.repositories import MineOpsRepository

REPORT_SCHEMA_VERSION = "1.0"


def align_window_utc(
    reference_utc: datetime | str,
    interval_minutes: int = 30,
) -> tuple[str, str]:
    """Align a timestamp down to its exact UTC window boundaries [start, end)."""
    if interval_minutes <= 0 or 1440 % interval_minutes != 0:
        raise ValueError("interval_minutes must be a positive divisor of 1440 (e.g. 30).")

    dt = _parse_utc(normalize_utc_timestamp(reference_utc))
    total_minutes = dt.hour * 60 + dt.minute
    aligned_minutes = (total_minutes // interval_minutes) * interval_minutes
    start_dt = dt.replace(
        hour=aligned_minutes // 60,
        minute=aligned_minutes % 60,
        second=0,
        microsecond=0,
    )
    end_dt = start_dt + timedelta(minutes=interval_minutes)
    return (normalize_utc_timestamp(start_dt), normalize_utc_timestamp(end_dt))


class PeriodicReportGenerator:
    """Generates idempotent 30-minute reports without inventing missing data or mixing modes."""

    def __init__(
        self,
        repository: MineOpsRepository,
        *,
        sample_interval_seconds: int = 10,
        electricity_Wait_rate_usd_per_kwh: Decimal | str | None = None,
    ) -> None:
        self._repo = repository
        self._sample_interval_seconds = max(1, sample_interval_seconds)
        self._rate_usd_per_kwh: Decimal | None = (
            Decimal(normalize_decimal_str(electricity_Wait_rate_usd_per_kwh))
            if electricity_Wait_rate_usd_per_kwh is not None
            else None
        )

    def generate_window_report(
        self,
        window_start_utc: datetime | str,
        window_end_utc: datetime | str,
        *,
        data_mode: DataMode = "simulated",
        generated_at_utc: datetime | str | None = None,
        persist: bool = True,
    ) -> PeriodicReport:
        """Build (and optionally persist) a 30-minute report for [window_start_utc, window_end_utc)."""
        start_iso = normalize_utc_timestamp(window_start_utc)
        end_iso = normalize_utc_timestamp(window_end_utc)
        gen_iso = normalize_utc_timestamp(generated_at_utc or datetime.now(UTC))

        start_dt = _parse_utc(start_iso)
        end_dt = _parse_utc(end_iso)
        if end_dt <= start_dt:
            raise ValueError("window_end_utc must be strictly greater than window_start_utc.")

        window_seconds = (end_dt - start_dt).total_seconds()
        expected_cycles = max(1, int(round(window_seconds / self._sample_interval_seconds)))

        # Fetch and filter measurements strictly by window and data_mode
        all_measurements = self._repo.list_measurements(limit=100_000)
        window_measurements = [
            m
            for m in all_measurements
            if start_iso <= m.observed_at_utc < end_iso
            and _matches_data_mode(m.status, data_mode)
        ]
        # Sort by UTC timestamp to handle any system clock adjustments safely
        window_measurements.sort(key=lambda m: m.observed_at_utc)

        # Evaluate cycle timestamps and gaps using a primary heartbeat metric (or all unique timestamps)
        distinct_cycle_timestamps = sorted({m.observed_at_utc for m in window_measurements})
        observed_cycles = len(distinct_cycle_timestamps)
        coverage_pct = round(min(100.0, (observed_cycles / expected_cycles) * 100.0), 2)
        gaps_count = _count_sampling_gaps(
            start_dt,
            end_dt,
            [_parse_utc(ts) for ts in distinct_cycle_timestamps],
            self._sample_interval_seconds,
        )

        # Group metrics without filling missing values with 0
        metrics_summary = _summarize_metrics(window_measurements)

        # Energy & Electricity cost (never invented if power/energy is unavailable)
        energy_summary = _compute_electricity_summary(
            window_measurements,
            self._rate_usd_per_kwh,
        )

        # Shares in window
        shares_summary = self._summarize_shares_in_window(start_iso, end_iso, data_mode)

        # Rewards in window (strictly separated)
        rewards_summary = self._summarize_rewards_in_window(start_iso, end_iso, data_mode)

        # Latest BTC price in window
        price_summary = self._summarize_prices_in_window(start_iso, end_iso, data_mode)

        summary_payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "timezone": "UTC",
            "window_start_utc": start_iso,
            "window_end_utc": end_iso,
            "data_mode": data_mode,
            "sampling": {
                "sample_interval_seconds": self._sample_interval_seconds,
                "expected_cycles": expected_cycles,
                "observed_cycles": observed_cycles,
                "sample_coverage_pct": coverage_pct,
                "gaps_count": gaps_count,
            },
            "metrics": metrics_summary,
            "electricity": energy_summary,
            "shares": shares_summary,
            "rewards_separated": rewards_summary,
            "btc_price": price_summary,
        }

        report_id = (
            f"rep_{start_iso.replace(':', '').replace('-', '').replace('.', '')}"
            f"_{end_iso.replace(':', '').replace('-', '').replace('.', '')}_{data_mode}"
        )
        report = PeriodicReport(
            id=report_id,
            window_start_utc=start_iso,
            window_end_utc=end_iso,
            data_mode=data_mode,
            sample_coverage_pct=coverage_pct,
            gaps_count=gaps_count,
            summary_json=json.dumps(summary_payload, sort_keys=True),
            generated_at_utc=gen_iso,
        )

        if persist:
            self._repo.insert_periodic_report(report)

        return report

    def export_report_files(
        self,
        report: PeriodicReport,
        output_dir: Path | str,
    ) -> tuple[Path, Path]:
        """Export a PeriodicReport to versioned JSON and CSV files in output_dir."""
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        json_path = target_dir / f"{report.id}.json"
        csv_path = target_dir / f"{report.id}.csv"

        summary = json.loads(report.summary_json)
        full_doc = {
            "id": report.id,
            "window_start_utc": report.window_start_utc,
            "window_end_utc": report.window_end_utc,
            "data_mode": report.data_mode,
            "sample_coverage_pct": report.sample_coverage_pct,
            "gaps_count": report.gaps_count,
            "generated_at_utc": report.generated_at_utc,
            "summary": summary,
        }
        json_path.write_text(json.dumps(full_doc, indent=2), encoding="utf-8")

        metrics_map: dict[str, Any] = summary.get("metrics", {})
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "report_id",
                    "window_start_utc",
                    "window_end_utc",
                    "data_mode",
                    "metric_name",
                    "unit",
                    "avg_value",
                    "max_value",
                    "min_value",
                    "valid_count",
                    "unavailable_count",
                    "quality_status",
                    "sources",
                ]
            )
            for metric_name, m_data in sorted(metrics_map.items()):
                writer.writerow(
                    [
                        report.id,
                        report.window_start_utc,
                        report.window_end_utc,
                        report.data_mode,
                        metric_name,
                        m_data.get("unit", ""),
                        "" if m_data.get("avg") is None else m_data.get("avg"),
                        "" if m_data.get("max") is None else m_data.get("max"),
                        "" if m_data.get("min") is None else m_data.get("min"),
                        m_data.get("valid_count", 0),
                        m_data.get("unavailable_count", 0),
                        m_data.get("dominant_status", "unavailable"),
                        ";".join(m_data.get("sources", [])),
                    ]
                )

        return (json_path, csv_path)

    def _summarize_shares_in_window(
        self,
        start_iso: str,
        end_iso: str,
        data_mode: DataMode,
    ) -> dict[str, Any]:
        target_status = "simulated" if data_mode == "simulated" else "measured"
        with self._repo._db.session() as conn:
            rows = conn.execute(
                """
                SELECT accepted, reject_reason
                FROM pool_shares
                WHERE observed_at_utc >= ? AND observed_at_utc < ? AND status = ?;
                """,
                (start_iso, end_iso, target_status),
            ).fetchall()

        accepted_count = sum(1 for r in rows if bool(r["accepted"]))
        rejected_count = sum(1 for r in rows if not bool(r["accepted"]))
        reasons: dict[str, int] = {}
        for r in rows:
            if not bool(r["accepted"]) and r["reject_reason"]:
                reason = str(r["reject_reason"])
                reasons[reason] = reasons.get(reason, 0) + 1

        return {
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "reject_reasons": reasons,
            "status": target_status,
        }

    def _summarize_rewards_in_window(
        self,
        start_iso: str,
        end_iso: str,
        data_mode: DataMode,
    ) -> dict[str, Any]:
        all_rewards = self._repo.list_reward_snapshots()
        in_win = [
            r
            for r in all_rewards
            if start_iso <= r.observed_at_utc < end_iso
            and _matches_data_mode(r.status, data_mode)
        ]
        est = [r for r in in_win if r.reward_stage == "estimated"]
        pool_rep = [r for r in in_win if r.reward_stage == "pool_reported"]
        return {
            "estimated_latest_btc": est[-1].amount_btc if est else None,
            "pool_reported_latest_btc": pool_rep[-1].amount_btc if pool_rep else None,
        }

    def _summarize_prices_in_window(
        self,
        start_iso: str,
        end_iso: str,
        data_mode: DataMode,
    ) -> dict[str, Any]:
        usd_prices = [
            p
            for p in self._repo.list_price_snapshots("USD")
            if start_iso <= p.observed_at_utc < end_iso
            and (
                (data_mode == "simulated" and p.status in {"simulated", "unavailable"})
                or (data_mode == "real" and p.status in {"measured", "unavailable"})
            )
            and p.price is not None
        ]
        if not usd_prices:
            return {"quote_asset": "USD", "latest_price": None, "status": "unavailable"}
        last = usd_prices[-1]
        return {
            "quote_asset": "USD",
            "latest_price": last.price,
            "status": last.status,
            "source": last.source,
            "observed_at_utc": last.observed_at_utc,
        }


def _matches_data_mode(status: str, data_mode: DataMode) -> bool:
    if data_mode == "simulated":
        return status in {"simulated", "unavailable"}
    return status in {"measured", "estimated", "unavailable"}


def _count_sampling_gaps(
    start_dt: datetime,
    end_dt: datetime,
    cycle_times: list[datetime],
    sample_interval_seconds: int,
) -> int:
    if not cycle_times:
        return 1
    threshold = sample_interval_seconds * 1.5
    gaps = 0
    prev = start_dt
    for ts in cycle_times:
        if (ts - prev).total_seconds() > threshold:
            gaps += 1
        prev = ts
    if (end_dt - prev).total_seconds() > threshold:
        gaps += 1
    return gaps


def _summarize_metrics(measurements: list[Measurement]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Measurement]] = {}
    for m in measurements:
        grouped.setdefault(m.metric_name, []).append(m)

    summary: dict[str, dict[str, Any]] = {}
    for metric_name, items in sorted(grouped.items()):
        valid_values = [
            m.value for m in items if m.status != "unavailable" and m.value is not None
        ]
        unavail_count = sum(1 for m in items if m.status == "unavailable" or m.value is None)
        sources = sorted({m.source for m in items})
        unit = items[0].unit

        if valid_values:
            avg_val = round(sum(valid_values) / len(valid_values), 4)
            max_val = round(max(valid_values), 4)
            min_val = round(min(valid_values), 4)
            non_unavail_statuses = [m.status for m in items if m.status != "unavailable"]
            dominant_status = non_unavail_statuses[-1] if non_unavail_statuses else "unavailable"
        else:
            avg_val = None
            max_val = None
            min_val = None
            dominant_status = "unavailable"

        summary[metric_name] = {
            "unit": unit,
            "avg": avg_val,
            "max": max_val,
            "min": min_val,
            "valid_count": len(valid_values),
            "unavailable_count": unavail_count,
            "dominant_status": dominant_status,
            "sources": sources,
        }
    return summary


def _compute_electricity_summary(
    measurements: list[Measurement],
    rate_usd_per_kwh: Decimal | None,
) -> dict[str, Any]:
    energy_samples = [
        m
        for m in measurements
        if m.metric_name == "energy_consumed_wh"
        and m.status != "unavailable"
        and m.value is not None
    ]
    if not energy_samples:
        return {
            "total_energy_wh": None,
            "electricity_cost_usd": None,
            "status": "unavailable",
            "quality_note": "No valid energy_consumed_wh measurements in window; cost not invented.",
        }

    total_wh = Decimal(str(round(sum(m.value for m in energy_samples if m.value is not None), 6)))
    derived_status = (
        "simulated"
        if any(m.status == "simulated" for m in energy_samples)
        else "estimated"
    )

    if rate_usd_per_kwh is None:
        return {
            "total_energy_wh": normalize_decimal_str(total_wh),
            "electricity_cost_usd": None,
            "status": "unavailable",
            "quality_note": "Energy measured/estimated, but electricity tariff (USD/kWh) is not configured.",
        }

    total_kwh = total_wh / Decimal("1000")
    cost_usd = (total_kwh * rate_usd_per_kwh).quantize(Decimal("0.000001"))
    return {
        "total_energy_wh": normalize_decimal_str(total_wh),
        "electricity_cost_usd": normalize_decimal_str(cost_usd),
        "status": derived_status,
        "quality_note": "Computed from integrated CPU package energy and configured tariff.",
    }


def _parse_utc(iso_str: str) -> datetime:
    cleaned = iso_str[:-1] + "+00:00" if iso_str.endswith("Z") else iso_str
    return datetime.fromisoformat(cleaned).astimezone(UTC)
