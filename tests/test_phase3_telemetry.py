"""Phase 3 tests: PC telemetry adapters, absent/failing sensors, timeouts, ranges, and energy."""

from __future__ import annotations

from types import SimpleNamespace
import time

import httpx

from mineops_dw.adapters import HostResourceSensorAdapter, LhmSensorAdapter
from mineops_dw.domain import compute_energy_measurement, evaluate_safety_limits


class _FakePsutilHappy:
    """Deterministic fake psutil module when all host sensors are present."""

    def cpu_percent(self, interval: float | None = None) -> float:
        return 34.5

    def cpu_freq(self) -> SimpleNamespace:
        return SimpleNamespace(current=3600.0)

    def virtual_memory(self) -> SimpleNamespace:
        return SimpleNamespace(
            percent=48.2,
            used=7900 * 1024 * 1024,
            available=8500 * 1024 * 1024,
        )

    def Process(self, pid: int) -> SimpleNamespace:  # noqa: N802
        return SimpleNamespace(
            cpu_percent=lambda interval=None: 12.4,
            memory_info=lambda: SimpleNamespace(rss=256 * 1024 * 1024),
        )


class _FakePsutilFailingAndDenied:
    """Fake psutil simulating sensor failure, out-of-range reading, and permission error."""

    def cpu_percent(self, interval: float | None = None) -> float:
        # Out-of-range value (>100%) to test range rejection
        return 145.0

    def cpu_freq(self) -> SimpleNamespace:
        raise RuntimeError("MSR read error")

    def virtual_memory(self) -> SimpleNamespace:
        return SimpleNamespace(
            percent=50.0,
            used=8000 * 1024 * 1024,
            available=8000 * 1024 * 1024,
        )

    def Process(self, pid: int) -> SimpleNamespace:  # noqa: N802
        raise PermissionError(f"AccessDenied to PID {pid}")


def test_host_sensor_adapter_present_metrics() -> None:
    """Case 1: Present sensors produce 'measured' records with unit, source, and UTC timestamp."""
    adapter = HostResourceSensorAdapter(
        psutil_module=_FakePsutilHappy(),
        miner_pid=4321,
    )
    samples = adapter.collect(
        observed_at_utc="2026-10-21T15:00:00Z",
        session_id="sim_sess_1",
    )
    by_name = {m.metric_name: m for m in samples}

    assert by_name["cpu_percent_total"].status == "measured"
    assert by_name["cpu_percent_total"].value == 34.5
    assert by_name["cpu_percent_total"].unit == "%"
    assert by_name["cpu_percent_total"].source == "psutil"

    assert by_name["cpu_freq_mhz"].value == 3600.0
    assert by_name["ram_usage_percent"].value == 48.2
    assert by_name["ram_used_mib"].value == 7900.0
    assert by_name["ram_available_mib"].value == 8500.0
    assert by_name["miner_process_cpu_percent"].value == 12.4
    assert by_name["miner_process_rss_mib"].value == 256.0


def test_host_sensor_out_of_range_and_permission_denied_degrade_safely() -> None:
    """Cases 3, 4 & Permission: Out-of-range or PermissionError marks metric 'unavailable' without crashing."""
    adapter = HostResourceSensorAdapter(
        psutil_module=_FakePsutilFailingAndDenied(),
        miner_pid=9999,
    )
    samples = adapter.collect(observed_at_utc="2026-10-21T15:01:00Z")
    by_name = {m.metric_name: m for m in samples}

    # Out of range 145% rejected -> value=None, status=unavailable
    assert by_name["cpu_percent_total"].status == "unavailable"
    assert by_name["cpu_percent_total"].value is None
    assert "out of physical range" in (by_name["cpu_percent_total"].quality_note or "")

    # Exception in cpu_freq -> unavailable
    assert by_name["cpu_freq_mhz"].status == "unavailable"
    assert by_name["cpu_freq_mhz"].value is None

    # Valid RAM still collected despite other sensor errors
    assert by_name["ram_usage_percent"].status == "measured"
    assert by_name["ram_usage_percent"].value == 50.0

    # PermissionError on miner PID -> unavailable with PermissionError note
    assert by_name["miner_process_cpu_percent"].status == "unavailable"
    assert by_name["miner_process_cpu_percent"].value is None
    assert "PermissionError" in (by_name["miner_process_cpu_percent"].quality_note or "")


def test_lhm_adapter_parses_valid_tree_and_handles_timeout() -> None:
    """Case 1 & 2: LHM adapter extracts Ryzen/Radeon sensors when up, and degrades to 'unavailable' on timeout."""
    sample_lhm_json = {
        "Text": "Computer",
        "Children": [
            {
                "Text": "AMD Ryzen 5 5600GT",
                "Children": [
                    {
                        "Text": "Temperatures",
                        "Children": [
                            {
                                "Text": "Core (Tctl/Tdie)",
                                "SensorId": "/amdcpu/0/temperature/2",
                                "Value": "61.5 °C",
                            }
                        ],
                    },
                    {
                        "Text": "Powers",
                        "Children": [
                            {
                                "Text": "Package",
                                "SensorId": "/amdcpu/0/power/0",
                                "Value": "44.0 W",
                            }
                        ],
                    },
                ],
            },
            {
                "Text": "AMD Radeon(TM) Graphics",
                "Children": [
                    {
                        "Text": "Load",
                        "Children": [
                            {
                                "Text": "GPU Core",
                                "SensorId": "/gpu-amd/0/load/0",
                                "Value": "18.0 %",
                            }
                        ],
                    },
                    {
                        "Text": "Temperatures",
                        "Children": [
                            {
                                "Text": "GPU VR SoC",
                                "SensorId": "/gpu-amd/0/temperature/0",
                                "Value": "49.0 °C",
                            }
                        ],
                    },
                ],
            },
        ],
    }

    def _mock_ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample_lhm_json)

    client_ok = httpx.Client(transport=httpx.MockTransport(_mock_ok))
    adapter_ok = LhmSensorAdapter(http_client=client_ok)
    metrics_ok = {
        m.metric_name: m
        for m in adapter_ok.collect(observed_at_utc="2026-10-21T15:00:00Z")
    }

    assert metrics_ok["cpu_temp_c"].status == "measured"
    assert metrics_ok["cpu_temp_c"].value == 61.5
    assert metrics_ok["cpu_package_power_w"].value == 44.0
    assert metrics_ok["gpu_util_percent"].value == 18.0
    assert metrics_ok["gpu_temp_c"].value == 49.0

    # Simulate timeout / LHM closed
    def _mock_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connection timed out")

    client_timeout = httpx.Client(transport=httpx.MockTransport(_mock_timeout))
    adapter_timeout = LhmSensorAdapter(http_client=client_timeout)
    metrics_timeout = {
        m.metric_name: m
        for m in adapter_timeout.collect(observed_at_utc="2026-10-21T15:00:10Z")
    }

    for name in ("cpu_temp_c", "cpu_package_power_w", "gpu_util_percent", "gpu_temp_c"):
        assert metrics_timeout[name].status == "unavailable"
        assert metrics_timeout[name].value is None
        assert "ConnectTimeout" in (metrics_timeout[name].quality_note or "")


def test_energy_calculation_and_safety_limits() -> None:
    """Energy (Wh) must be 'unavailable' when power is missing, and trapezoidal when power is measured."""
    from mineops_dw.domain import Measurement

    p1_unavail = Measurement(
        metric_name="cpu_package_power_w",
        value=None,
        unit="W",
        status="unavailable",
        source="lhm_http",
        observed_at_utc="2026-10-21T15:00:00Z",
        quality_note="LHM absent",
    )
    p2_measured = Measurement(
        metric_name="cpu_package_power_w",
        value=36.0,
        unit="W",
        status="measured",
        source="lhm_http",
        observed_at_utc="2026-10-21T15:01:00Z",
    )
    p3_measured = Measurement(
        metric_name="cpu_package_power_w",
        value=36.0,
        unit="W",
        status="measured",
        source="lhm_http",
        observed_at_utc="2026-10-21T15:11:00Z",
    )

    # Unavailable power -> unavailable energy (never 0 Wh)
    e_unavail = compute_energy_measurement(p1_unavail, p2_measured)
    assert e_unavail.status == "unavailable"
    assert e_unavail.value is None

    # 36 W constant for 10 minutes (600 s) -> 36 * (600/3600) = 6.0 Wh
    e_valid = compute_energy_measurement(p2_measured, p3_measured)
    assert e_valid.status == "estimated"
    assert e_valid.value == 6.0
    assert e_valid.unit == "Wh"

    # Safety limits evaluation
    hot_temp = Measurement(
        metric_name="cpu_temp_c",
        value=82.5,
        unit="°C",
        status="measured",
        source="lhm_http",
        observed_at_utc="2026-10-21T15:11:00Z",
    )
    eval_hot = evaluate_safety_limits(
        [hot_temp],
        max_cpu_percent=75.0,
        max_cpu_temp_c=80.0,
        max_session_minutes=30,
    )
    assert eval_hot.should_stop is True
    assert eval_hot.reason == "max_cpu_temp_exceeded"


def test_real_windows_host_fallback_and_low_collector_overhead() -> None:
    """Verify real Windows ctypes telemetry fallback runs in <50ms without inventing missing sensors."""
    adapter = HostResourceSensorAdapter(psutil_module=None, use_win32_fallback=True)
    t_start = time.perf_counter()
    samples = adapter.collect()
    elapsed_ms = (time.perf_counter() - t_start) * 1000.0

    assert elapsed_ms < 200.0
    by_name = {m.metric_name: m for m in samples}
    # On Windows 11, GlobalMemoryStatusEx must return real measured RAM
    assert by_name["ram_usage_percent"].status == "measured"
    assert by_name["ram_usage_percent"].value is not None
    assert 1.0 <= by_name["ram_usage_percent"].value <= 99.9
    assert by_name["ram_used_mib"].value is not None and by_name["ram_used_mib"].value > 500.0
    # CPU frequency is not invented
    assert by_name["cpu_freq_mhz"].status == "unavailable"
    assert by_name["cpu_freq_mhz"].value is None
