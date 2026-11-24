"""Hardware telemetry adapters for CPU, RAM, processes, iGPU, and Libre Hardware Monitor."""

from __future__ import annotations

import ctypes
from datetime import UTC, datetime
import logging
import sys
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from mineops_dw.domain.models import Measurement, QualityStatus, normalize_utc_timestamp

logger = logging.getLogger("mineops_dw.adapters.sensors")

MIB_BYTES = float(1024 * 1024)


class SensorAdapter(Protocol):
    """Protocol implemented by all hardware telemetry adapters."""

    def collect(
        self,
        observed_at_utc: datetime | str | None = None,
        session_id: str | None = None,
    ) -> list[Measurement]:
        """Collect a batch of measurements without raising unhandled sensor exceptions."""


def build_safe_measurement(
    *,
    metric_name: str,
    value: float | None,
    unit: str,
    status: QualityStatus,
    source: str,
    observed_at_utc: str,
    session_id: str | None = None,
    quality_note: str | None = None,
) -> Measurement:
    """Construct a validated Measurement; degrade out-of-range values to 'unavailable'."""
    if status != "unavailable" and unit == "°C" and value is not None:
        if not (-20.0 <= value <= 130.0):
            return Measurement(
                session_id=session_id,
                metric_name=metric_name,
                value=None,
                unit=unit,
                status="unavailable",
                source=source,
                observed_at_utc=observed_at_utc,
                quality_note=f"Sensor value out of physical temperature range [-20, 130] °C: {value}",
            )

    try:
        return Measurement(
            session_id=session_id,
            metric_name=metric_name,
            value=value,
            unit=unit,
            status=status,
            source=source,
            observed_at_utc=observed_at_utc,
            quality_note=quality_note,
        )
    except ValidationError as exc:
        logger.warning(
            "Invalid reading for %s from %s (%s); marking unavailable: %s",
            metric_name,
            source,
            value,
            exc,
        )
        return Measurement(
            session_id=session_id,
            metric_name=metric_name,
            value=None,
            unit=unit,
            status="unavailable",
            source=source,
            observed_at_utc=observed_at_utc,
            quality_note=f"Rejected out-of-range or invalid reading ({value}): {exc.errors()[0]['msg']}",
        )


class HostResourceSensorAdapter:
    """Collects CPU, RAM, and optional miner process metrics via psutil or Win32 fallback."""

    def __init__(
        self,
        psutil_module: Any | None = None,
        miner_pid: int | None = None,
        use_win32_fallback: bool = True,
    ) -> None:
        if psutil_module is not None:
            self._psutil = psutil_module
        else:
            try:
                import psutil as _psutil  # type: ignore[import-not-found]

                self._psutil = _psutil
            except ImportError:
                self._psutil = None

        self._miner_pid = miner_pid
        self._use_win32_fallback = use_win32_fallback
        self._prev_win32_times: tuple[int, int, int] | None = None

        if self._psutil is None and self._use_win32_fallback and sys.platform == "win32":
            self._prev_win32_times = _read_win32_system_times()

    def collect(
        self,
        observed_at_utc: datetime | str | None = None,
        session_id: str | None = None,
    ) -> list[Measurement]:
        """Collect host CPU, RAM, and process telemetry safely."""
        ts = normalize_utc_timestamp(observed_at_utc or datetime.now(UTC))
        if self._psutil is not None:
            return self._collect_with_psutil(ts, session_id)
        if self._use_win32_fallback and sys.platform == "win32":
            return self._collect_with_win32(ts, session_id)
        return self._all_unavailable(
            ts,
            session_id,
            source="psutil",
            reason="psutil is not installed and Win32 fallback is disabled.",
        )

    def _collect_with_psutil(self, ts: str, session_id: str | None) -> list[Measurement]:
        results: list[Measurement] = []
        source = "psutil"

        # 1. CPU Total %
        try:
            cpu_pct = float(self._psutil.cpu_percent(interval=None))
            results.append(
                build_safe_measurement(
                    metric_name="cpu_percent_total",
                    value=round(cpu_pct, 2),
                    unit="%",
                    status="measured",
                    source=source,
                    observed_at_utc=ts,
                    session_id=session_id,
                )
            )
        except Exception as exc:
            logger.warning("psutil cpu_percent failed: %s", exc)
            results.append(
                build_safe_measurement(
                    metric_name="cpu_percent_total",
                    value=None,
                    unit="%",
                    status="unavailable",
                    source=source,
                    observed_at_utc=ts,
                    session_id=session_id,
                    quality_note=f"CPU percent read failed: {type(exc).__name__}",
                )
            )

        # 2. CPU Frequency MHz
        try:
            freq = self._psutil.cpu_freq()
            if freq is not None and getattr(freq, "current", None) is not None:
                results.append(
                    build_safe_measurement(
                        metric_name="cpu_freq_mhz",
                        value=round(float(freq.current), 2),
                        unit="MHz",
                        status="measured",
                        source=source,
                        observed_at_utc=ts,
                        session_id=session_id,
                    )
                )
            else:
                results.append(
                    build_safe_measurement(
                        metric_name="cpu_freq_mhz",
                        value=None,
                        unit="MHz",
                        status="unavailable",
                        source=source,
                        observed_at_utc=ts,
                        session_id=session_id,
                        quality_note="cpu_freq returned None on this platform.",
                    )
                )
        except Exception as exc:
            logger.warning("psutil cpu_freq failed: %s", exc)
            results.append(
                build_safe_measurement(
                    metric_name="cpu_freq_mhz",
                    value=None,
                    unit="MHz",
                    status="unavailable",
                    source=source,
                    observed_at_utc=ts,
                    session_id=session_id,
                    quality_note=f"CPU frequency read failed: {type(exc).__name__}",
                )
            )

        # 3. Virtual Memory (%, used MiB, available MiB)
        try:
            vm = self._psutil.virtual_memory()
            results.extend(
                [
                    build_safe_measurement(
                        metric_name="ram_usage_percent",
                        value=round(float(vm.percent), 2),
                        unit="%",
                        status="measured",
                        source=source,
                        observed_at_utc=ts,
                        session_id=session_id,
                    ),
                    build_safe_measurement(
                        metric_name="ram_used_mib",
                        value=round(float(vm.used) / MIB_BYTES, 2),
                        unit="MiB",
                        status="measured",
                        source=source,
                        observed_at_utc=ts,
                        session_id=session_id,
                    ),
                    build_safe_measurement(
                        metric_name="ram_available_mib",
                        value=round(float(vm.available) / MIB_BYTES, 2),
                        unit="MiB",
                        status="measured",
                        source=source,
                        observed_at_utc=ts,
                        session_id=session_id,
                    ),
                ]
            )
        except Exception as exc:
            logger.warning("psutil virtual_memory failed: %s", exc)
            for m_name, m_unit in (
                ("ram_usage_percent", "%"),
                ("ram_used_mib", "MiB"),
                ("ram_available_mib", "MiB"),
            ):
                results.append(
                    build_safe_measurement(
                        metric_name=m_name,
                        value=None,
                        unit=m_unit,
                        status="unavailable",
                        source=source,
                        observed_at_utc=ts,
                        session_id=session_id,
                        quality_note=f"RAM read failed: {type(exc).__name__}",
                    )
                )

        # 4. Miner Process Metrics (if configured)
        results.extend(self._collect_miner_process_psutil(ts, session_id))
        return results

    def _collect_miner_process_psutil(
        self,
        ts: str,
        session_id: str | None,
    ) -> list[Measurement]:
        source = "psutil"
        if self._miner_pid is None:
            return [
                build_safe_measurement(
                    metric_name="miner_process_cpu_percent",
                    value=None,
                    unit="%",
                    status="unavailable",
                    source=source,
                    observed_at_utc=ts,
                    session_id=session_id,
                    quality_note="No active miner PID configured.",
                ),
                build_safe_measurement(
                    metric_name="miner_process_rss_mib",
                    value=None,
                    unit="MiB",
                    status="unavailable",
                    source=source,
                    observed_at_utc=ts,
                    session_id=session_id,
                    quality_note="No active miner PID configured.",
                ),
            ]

        try:
            proc = self._psutil.Process(self._miner_pid)
            proc_cpu = float(proc.cpu_percent(interval=None))
            proc_rss = float(proc.memory_info().rss) / MIB_BYTES
            return [
                build_safe_measurement(
                    metric_name="miner_process_cpu_percent",
                    value=round(proc_cpu, 2),
                    unit="%",
                    status="measured",
                    source=source,
                    observed_at_utc=ts,
                    session_id=session_id,
                ),
                build_safe_measurement(
                    metric_name="miner_process_rss_mib",
                    value=round(proc_rss, 2),
                    unit="MiB",
                    status="measured",
                    source=source,
                    observed_at_utc=ts,
                    session_id=session_id,
                ),
            ]
        except Exception as exc:
            logger.warning("Miner process %s inspection failed: %s", self._miner_pid, exc)
            reason = f"Process PID {self._miner_pid} unavailable: {type(exc).__name__}"
            return [
                build_safe_measurement(
                    metric_name="miner_process_cpu_percent",
                    value=None,
                    unit="%",
                    status="unavailable",
                    source=source,
                    observed_at_utc=ts,
                    session_id=session_id,
                    quality_note=reason,
                ),
                build_safe_measurement(
                    metric_name="miner_process_rss_mib",
                    value=None,
                    unit="MiB",
                    status="unavailable",
                    source=source,
                    observed_at_utc=ts,
                    session_id=session_id,
                    quality_note=reason,
                ),
            ]

    def _collect_with_win32(self, ts: str, session_id: str | None) -> list[Measurement]:
        """Collect real RAM and CPU load on Windows via ctypes when psutil is not installed."""
        source = "win32_ctypes"
        results: list[Measurement] = []

        # CPU total % via GetSystemTimes delta
        current_times = _read_win32_system_times()
        cpu_pct: float | None = None
        if current_times is not None and self._prev_win32_times is not None:
            idle_diff = current_times[0] - self._prev_win32_times[0]
            kernel_diff = current_times[1] - self._prev_win32_times[1]
            user_diff = current_times[2] - self._prev_win32_times[2]
            total_sys = kernel_diff + user_diff
            if total_sys > 0 and total_sys >= idle_diff >= 0:
                cpu_pct = round(((total_sys - idle_diff) / total_sys) * 100.0, 2)
        self._prev_win32_times = current_times

        if cpu_pct is not None:
            results.append(
                build_safe_measurement(
                    metric_name="cpu_percent_total",
                    value=cpu_pct,
                    unit="%",
                    status="measured",
                    source=source,
                    observed_at_utc=ts,
                    session_id=session_id,
                    quality_note="Measured via Win32 GetSystemTimes (psutil not installed).",
                )
            )
        else:
            results.append(
                build_safe_measurement(
                    metric_name="cpu_percent_total",
                    value=None,
                    unit="%",
                    status="unavailable",
                    source=source,
                    observed_at_utc=ts,
                    session_id=session_id,
                    quality_note="Initial GetSystemTimes baseline sample; delta requires two ticks or psutil.",
                )
            )

        # CPU frequency not exposed by GetSystemTimes
        results.append(
            build_safe_measurement(
                metric_name="cpu_freq_mhz",
                value=None,
                unit="MHz",
                status="unavailable",
                source=source,
                observed_at_utc=ts,
                session_id=session_id,
                quality_note="CPU frequency requires psutil or Libre Hardware Monitor.",
            )
        )

        # RAM via GlobalMemoryStatusEx
        mem_info = _read_win32_memory_status()
        if mem_info is not None:
            pct, used_mib, avail_mib = mem_info
            results.extend(
                [
                    build_safe_measurement(
                        metric_name="ram_usage_percent",
                        value=pct,
                        unit="%",
                        status="measured",
                        source=source,
                        observed_at_utc=ts,
                        session_id=session_id,
                    ),
                    build_safe_measurement(
                        metric_name="ram_used_mib",
                        value=used_mib,
                        unit="MiB",
                        status="measured",
                        source=source,
                        observed_at_utc=ts,
                        session_id=session_id,
                    ),
                    build_safe_measurement(
                        metric_name="ram_available_mib",
                        value=avail_mib,
                        unit="MiB",
                        status="measured",
                        source=source,
                        observed_at_utc=ts,
                        session_id=session_id,
                    ),
                ]
            )
        else:
            for m_name, m_unit in (
                ("ram_usage_percent", "%"),
                ("ram_used_mib", "MiB"),
                ("ram_available_mib", "MiB"),
            ):
                results.append(
                    build_safe_measurement(
                        metric_name=m_name,
                        value=None,
                        unit=m_unit,
                        status="unavailable",
                        source=source,
                        observed_at_utc=ts,
                        session_id=session_id,
                        quality_note="GlobalMemoryStatusEx call failed.",
                    )
                )

        # Miner process metrics require psutil
        for m_name, m_unit in (
            ("miner_process_cpu_percent", "%"),
            ("miner_process_rss_mib", "MiB"),
        ):
            results.append(
                build_safe_measurement(
                    metric_name=m_name,
                    value=None,
                    unit=m_unit,
                    status="unavailable",
                    source=source,
                    observed_at_utc=ts,
                    session_id=session_id,
                    quality_note="Per-process telemetry requires psutil or an active miner PID.",
                )
            )
        return results

    def _all_unavailable(
        self,
        ts: str,
        session_id: str | None,
        source: str,
        reason: str,
    ) -> list[Measurement]:
        specs = (
            ("cpu_percent_total", "%"),
            ("cpu_freq_mhz", "MHz"),
            ("ram_usage_percent", "%"),
            ("ram_used_mib", "MiB"),
            ("ram_available_mib", "MiB"),
            ("miner_process_cpu_percent", "%"),
            ("miner_process_rss_mib", "MiB"),
        )
        return [
            build_safe_measurement(
                metric_name=name,
                value=None,
                unit=unit,
                status="unavailable",
                source=source,
                observed_at_utc=ts,
                session_id=session_id,
                quality_note=reason,
            )
            for name, unit in specs
        ]


class LhmSensorAdapter:
    """Optional adapter for Libre Hardware Monitor JSON endpoint (http://127.0.0.1:8085/data.json).

    Never invents temperature, power, or iGPU utilization when LHM is absent or unreachable.
    """

    def __init__(
        self,
        endpoint_url: str = "http://127.0.0.1:8085/data.json",
        timeout_seconds: float = 1.5,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    def collect(
        self,
        observed_at_utc: datetime | str | None = None,
        session_id: str | None = None,
    ) -> list[Measurement]:
        """Fetch and parse LHM sensor tree; return 'unavailable' measurements if unreachable."""
        ts = normalize_utc_timestamp(observed_at_utc or datetime.now(UTC))
        source = "lhm_http"

        try:
            if self._http_client is not None:
                response = self._http_client.get(
                    self._endpoint_url,
                    timeout=self._timeout_seconds,
                )
            else:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.get(self._endpoint_url)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.debug("LHM endpoint unreachable (%s): %s", self._endpoint_url, exc)
            reason = f"Libre Hardware Monitor unreachable ({type(exc).__name__})."
            return self._unavailable_lhm_metrics(ts, session_id, reason)

        extracted = _extract_lhm_metrics(payload)
        specs = (
            ("cpu_temp_c", "°C", "CPU temperature sensor (Tctl/Tdie/Package) not exposed in LHM tree."),
            ("cpu_package_power_w", "W", "CPU Package Power sensor not exposed in LHM tree."),
            ("gpu_util_percent", "%", "GPU/iGPU Core Load sensor not exposed in LHM tree."),
            ("gpu_temp_c", "°C", "GPU/iGPU Temperature sensor not exposed in LHM tree."),
        )

        results: list[Measurement] = []
        for metric_name, unit, missing_reason in specs:
            raw_val = extracted.get(metric_name)
            if raw_val is None:
                results.append(
                    build_safe_measurement(
                        metric_name=metric_name,
                        value=None,
                        unit=unit,
                        status="unavailable",
                        source=source,
                        observed_at_utc=ts,
                        session_id=session_id,
                        quality_note=missing_reason,
                    )
                )
            else:
                results.append(
                    build_safe_measurement(
                        metric_name=metric_name,
                        value=round(raw_val, 2),
                        unit=unit,
                        status="measured",
                        source=source,
                        observed_at_utc=ts,
                        session_id=session_id,
                    )
                )
        return results

    def _unavailable_lhm_metrics(
        self,
        ts: str,
        session_id: str | None,
        reason: str,
    ) -> list[Measurement]:
        return [
            build_safe_measurement(
                metric_name=name,
                value=None,
                unit=unit,
                status="unavailable",
                source="lhm_http",
                observed_at_utc=ts,
                session_id=session_id,
                quality_note=reason,
            )
            for name, unit in (
                ("cpu_temp_c", "°C"),
                ("cpu_package_power_w", "W"),
                ("gpu_util_percent", "%"),
                ("gpu_temp_c", "°C"),
            )
        ]


def _extract_lhm_metrics(node: Any) -> dict[str, float]:
    """Recursively traverse LHM JSON tree to extract CPU temp, CPU power, and GPU metrics."""
    found: dict[str, float] = {}

    def _walk(item: Any, parent_context: str = "") -> None:
        if not isinstance(item, dict):
            return

        text = str(item.get("Text", "")).strip()
        sensor_id = str(item.get("SensorId", item.get("id", ""))).strip().lower()
        raw_value = str(item.get("Value", "")).strip()
        context = f"{parent_context} / {text}".lower()

        parsed_num = _parse_lhm_numeric_value(raw_value)
        if parsed_num is not None:
            is_gpu_ctx = any(
                v in context or v in sensor_id
                for v in ("gpu", "radeon", "nvidia", "geforce", "rtx", "gtx", "graphics", "iris", "uhd", "arc")
            )
            is_cpu_ctx = not is_gpu_ctx and any(
                c in context or c in sensor_id for c in ("cpu", "amd", "intel", "ryzen", "core", "processor")
            )
            # CPU Temperature (Ryzen Tctl/Tdie or Intel/AMD CPU Package/Core)
            if (
                is_cpu_ctx
                and ("temperature" in sensor_id or "°c" in raw_value.lower())
                and any(
                    k in text.lower()
                    for k in (
                        "tctl",
                        "tdie",
                        "cpu package",
                        "core (tctl/tdie)",
                        "core max",
                        "core average",
                        "package",
                        "ccd1",
                    )
                )
            ):
                found.setdefault("cpu_temp_c", parsed_num)
            # CPU Package Power (W)
            elif (
                not is_gpu_ctx
                and ("power" in sensor_id or raw_value.endswith(" W"))
                and any(k in text.lower() for k in ("package", "cpu", "cpu package", "cpu cores", "processor"))
            ):
                found.setdefault("cpu_package_power_w", parsed_num)
            # GPU Core Load (%)
            elif (
                is_gpu_ctx
                and ("load" in sensor_id or "%" in raw_value)
                and any(k in text.lower() for k in ("gpu core", "d3d 3d", "core"))
            ):
                found.setdefault("gpu_util_percent", parsed_num)
            # GPU Temperature (°C)
            elif (
                is_gpu_ctx
                and ("temperature" in sensor_id or "°c" in raw_value.lower())
                and any(k in text.lower() for k in ("gpu", "vr soc", "core", "edge", "hot spot"))
            ):
                found.setdefault("gpu_temp_c", parsed_num)

        children = item.get("Children")
        if isinstance(children, list):
            for child in children:
                _walk(child, context)

    _walk(node)
    return found


def _parse_lhm_numeric_value(raw_value: str) -> float | None:
    """Parse LHM strings like '62.5 °C', '38,4 W', or '14.2 %' into float."""
    if not raw_value or raw_value == "-":
        return None
    first_token = raw_value.split()[0].replace(",", ".")
    try:
        return float(first_token)
    except ValueError:
        return None


# --- Win32 ctypes structures for zero-dependency host telemetry on Windows ---


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", ctypes.c_ulong),
        ("dwHighDateTime", ctypes.c_ulong),
    ]


def _read_win32_memory_status() -> tuple[float, float, float] | None:
    if sys.platform != "win32":
        return None
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        if not ok or stat.ullTotalPhys == 0:
            return None
        used_bytes = stat.ullTotalPhys - stat.ullAvailPhys
        pct = round((used_bytes / stat.ullTotalPhys) * 100.0, 2)
        used_mib = round(used_bytes / MIB_BYTES, 2)
        avail_mib = round(stat.ullAvailPhys / MIB_BYTES, 2)
        return (pct, used_mib, avail_mib)
    except Exception:
        return None


def _read_win32_system_times() -> tuple[int, int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        idle = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        ok = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not ok:
            return None
        idle_val = (idle.dwHighDateTime << 32) | idle.dwLowDateTime
        kernel_val = (kernel.dwHighDateTime << 32) | kernel.dwLowDateTime
        user_val = (user.dwHighDateTime << 32) | user.dwLowDateTime
        return (idle_val, kernel_val, user_val)
    except Exception:
        return None
