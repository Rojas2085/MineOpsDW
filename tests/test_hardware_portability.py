"""Tests for multi-PC hardware auto-detection, adaptive XMRig profiles, vendor-neutral LHM parsing, and Git safety."""

from __future__ import annotations

from pathlib import Path

import httpx

from mineops_dw.adapters.sensors import LhmSensorAdapter
from mineops_dw.api.server import MineOpsApiService
from mineops_dw.config import AppSettings
from mineops_dw.domain.hardware_profile import (
    HostHardwareProfile,
    build_adaptive_perf_profiles,
    build_adaptive_xmrig_config,
    detect_host_hardware,
    infer_cpu_tdp_watts,
    preferred_cpu_thread_indices,
)
from mineops_dw.security_scanner import scan_workspace_for_secrets
from mineops_dw.storage import MineOpsRepository, SQLiteDatabase


def test_adaptive_profiles_scale_across_cpu_and_ram_configurations() -> None:
    """Verify bajo/normal/rapido thread scaling across low-end, mid-range, and high-core hosts."""
    configs = [
        HostHardwareProfile("Dual Core Laptop", 2, 2, 8.0, None, 28.0, "Windows 11"),
        HostHardwareProfile("Intel Core i3-10100U (4T Low RAM)", 2, 4, 4.0, "Intel UHD", 28.0, "Windows 11"),
        HostHardwareProfile("Intel Core i5-12400H", 4, 8, 16.0, "NVIDIA RTX 3050", 45.0, "Windows 11"),
        HostHardwareProfile("AMD Ryzen 5 5600GT", 6, 12, 16.0, "Radeon Graphics", 65.0, "Windows 11"),
        HostHardwareProfile("Intel Core i9-13900K", 16, 24, 32.0, "NVIDIA RTX 4080", 105.0, "Windows 11"),
    ]
    for hw in configs:
        profiles = build_adaptive_perf_profiles(hw)
        bajo = profiles["bajo"]
        normal = profiles["normal"]
        rapido = profiles["rapido"]

        assert 1 <= bajo["threads_count"] <= normal["threads_count"] <= rapido["threads_count"]
        assert rapido["threads_count"] == hw.logical_threads
        for p in (bajo, normal, rapido):
            rx = p["rx_threads"]
            assert len(rx) == p["threads_count"]
            assert len(set(rx)) == len(rx)
            assert all(0 <= idx < hw.logical_threads for idx in rx)

    # Low-RAM 4-thread laptop caps normal profile safely
    low_ram_profiles = build_adaptive_perf_profiles(configs[1])
    assert low_ram_profiles["normal"]["threads_count"] <= 2

    # Even (physical) threads prioritized before odd SMT siblings
    assert preferred_cpu_thread_indices(8, 4) == [0, 2, 4, 6]


def test_tdp_inference_and_adaptive_xmrig_config() -> None:
    """Verify TDP heuristics and loopback-restricted XMRig config generation."""
    assert infer_cpu_tdp_watts("Intel(R) Core(TM) i5-1135G7", 4) == 65.0
    assert infer_cpu_tdp_watts("AMD Ryzen 5 5500U with Radeon Graphics", 6) == 28.0
    assert infer_cpu_tdp_watts("12th Gen Intel(R) Core(TM) i7-12700H", 14) == 45.0
    assert infer_cpu_tdp_watts("13th Gen Intel(R) Core(TM) i9-13900K", 24) == 105.0
    assert infer_cpu_tdp_watts("AMD Ryzen 7 6800HS", 8) == 45.0

    hw = HostHardwareProfile("Intel Core i5-12400", 6, 12, 16.0, "Intel UHD 730", 65.0, "Windows 11")
    cfg = build_adaptive_xmrig_config(hw)
    assert cfg["http"]["host"] == "127.0.0.1"
    assert cfg["http"]["port"] == 18080
    assert cfg["http"]["restricted"] is True
    assert len(cfg["cpu"]["rx"]) == 8


def test_lhm_adapter_supports_intel_and_nvidia_sensors() -> None:
    """Verify LhmSensorAdapter extracts Intel CPU and NVIDIA RTX GPU metrics when exposed."""
    sample_lhm = {
        "Text": "Computer",
        "Children": [
            {
                "Text": "Intel Core i7-12700H",
                "Children": [
                    {
                        "Text": "Temperatures",
                        "Children": [
                            {"Text": "CPU Package", "SensorId": "/intelcpu/0/temperature/16", "Value": "67.0 °C"}
                        ],
                    },
                    {
                        "Text": "Powers",
                        "Children": [
                            {"Text": "CPU Package", "SensorId": "/intelcpu/0/power/0", "Value": "38.5 W"}
                        ],
                    },
                ],
            },
            {
                "Text": "NVIDIA GeForce RTX 3060",
                "Children": [
                    {
                        "Text": "Load",
                        "Children": [
                            {"Text": "GPU Core", "SensorId": "/gpu-nvidia/0/load/0", "Value": "12.0 %"}
                        ],
                    },
                    {
                        "Text": "Temperatures",
                        "Children": [
                            {"Text": "GPU Hot Spot", "SensorId": "/gpu-nvidia/0/temperature/2", "Value": "54.0 °C"}
                        ],
                    },
                ],
            },
        ],
    }

    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=sample_lhm)))
    metrics = {m.metric_name: m for m in LhmSensorAdapter(http_client=client).collect(observed_at_utc="2026-11-24T12:00:00Z")}
    assert metrics["cpu_temp_c"].value == 67.0
    assert metrics["cpu_package_power_w"].value == 38.5
    assert metrics["gpu_util_percent"].value == 12.0
    assert metrics["gpu_temp_c"].value == 54.0


def test_api_exposes_host_hardware_in_health_and_executive_report(tmp_path: Path) -> None:
    """Verify /health, /api/v1/performance, and executive report reflect injected HostHardwareProfile."""
    db = SQLiteDatabase(tmp_path / "portability.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    custom_hw = HostHardwareProfile(
        cpu_model="Intel Core i7-12700H",
        physical_cores=14,
        logical_threads=20,
        total_ram_gib=32.0,
        gpu_model="NVIDIA GeForce RTX 3060 Laptop GPU",
        estimated_tdp_watts=45.0,
        os_label="Windows 11",
    )
    api = MineOpsApiService(db, repo, AppSettings(TELEMETRY_MODE="simulated"), host_hardware=custom_hw)

    health = api.handle_request("GET", "/health").body
    assert health["host_hardware"]["cpu_model"] == "Intel Core i7-12700H"
    assert health["host_hardware"]["logical_threads"] == 20

    perf = api.handle_request("GET", "/api/v1/performance").body
    assert perf["logical_threads_total"] == 20
    assert perf["profiles_summary"]["rapido"]["threads_count"] == 20

    report_html = api.handle_request("GET", "/api/v1/exports/executive-report").body
    assert "Intel Core i7-12700H" in report_html
    assert "NVIDIA GeForce RTX 3060 Laptop GPU" in report_html

    # Live host detection smoke check on current machine
    detected = detect_host_hardware()
    assert detected.logical_threads >= 1
    assert detected.total_ram_gib > 0


def test_security_scanner_flags_evm_wallet_and_workspace_is_clean(tmp_path: Path) -> None:
    """Verify secret scanner catches real EVM wallet/payout leaks while current workspace stays clean."""
    dirty = tmp_path / "leak.env"
    fake_addr = "0x" + "ab12" * 10
    dirty.write_text(f"PAYOUT_ADDRESS={fake_addr}\n", encoding="utf-8")
    findings = scan_workspace_for_secrets(tmp_path)
    rules = {f.rule_name for f in findings}
    assert "populated_payout_address" in rules
    assert "evm_wallet_address" in rules

    repo_root = Path(__file__).resolve().parents[1]
    assert scan_workspace_for_secrets(repo_root) == []
