"""Automatic host hardware detection and adaptive XMRig thread/profile tuning."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
import platform
import re
import sys
from typing import Any


@dataclass(frozen=True)
class HostHardwareProfile:
    """Detected hardware capabilities of the current host machine."""

    cpu_model: str
    physical_cores: int
    logical_threads: int
    total_ram_gib: float
    gpu_model: str | None
    estimated_tdp_watts: float
    os_label: str


def infer_cpu_tdp_watts(cpu_model: str, physical_cores: int) -> float:
    """Infer a reasonable default CPU package TDP (W) when hardware power sensors are absent."""
    lowered = cpu_model.lower()
    if re.search(r"(?:^|[-\s])\d{4,5}u\b", lowered) or " u " in lowered or lowered.endswith(" u"):
        return 28.0
    if re.search(r"(?:^|[-\s])\d{4,5}(?:h|hs|hx|p)\b", lowered):
        return 45.0
    if (
        "ryzen 9" in lowered
        or "core i9" in lowered
        or "threadripper" in lowered
        or physical_cores >= 12
    ):
        return 105.0
    if physical_cores <= 2:
        return 35.0
    return 65.0


def _detect_cpu_model() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                cleaned = " ".join(str(val).split())
                if cleaned:
                    return cleaned
        except Exception:
            pass
    proc = " ".join(platform.processor().split())
    return proc or "Generic CPU"


def _detect_win32_physical_cores() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        class _SYSTEM_LOGICAL_PROCESSOR_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("ProcessorMask", ctypes.c_size_t),
                ("Relationship", ctypes.c_int),
                ("Reserved", ctypes.c_ulonglong * 2),
            ]

        kernel32 = ctypes.windll.kernel32
        buf_len = ctypes.c_ulong(0)
        kernel32.GetLogicalProcessorInformation(None, ctypes.byref(buf_len))
        if buf_len.value == 0:
            return None
        elem_size = ctypes.sizeof(_SYSTEM_LOGICAL_PROCESSOR_INFORMATION)
        count = buf_len.value // elem_size
        if count <= 0:
            return None
        arr = (_SYSTEM_LOGICAL_PROCESSOR_INFORMATION * count)()
        ok = kernel32.GetLogicalProcessorInformation(arr, ctypes.byref(buf_len))
        if not ok:
            return None
        actual_count = buf_len.value // elem_size
        cores = sum(1 for i in range(actual_count) if arr[i].Relationship == 0)
        return cores if cores > 0 else None
    except Exception:
        return None


def _detect_ram_gib() -> float:
    try:
        import psutil  # type: ignore[import-not-found]

        return round(float(psutil.virtual_memory().total) / float(1024**3), 2)
    except Exception:
        pass

    if sys.platform == "win32":
        try:
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

            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)) and stat.ullTotalPhys > 0:
                return round(float(stat.ullTotalPhys) / float(1024**3), 2)
        except Exception:
            pass
    return 8.0


def _detect_gpu_model() -> str | None:
    if sys.platform != "win32":
        return None
    skip_tokens = ("microsoft basic display", "remote desktop", "parsec", "virtual")
    fallback_desc: str | None = None
    try:
        import winreg

        base_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        for idx in range(8):
            subkey = f"{base_path}\\{idx:04d}"
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, "DriverDesc")
                    desc = " ".join(str(val).split())
                    if not desc:
                        continue
                    if any(tok in desc.lower() for tok in skip_tokens):
                        if fallback_desc is None:
                            fallback_desc = desc
                        continue
                    return desc
            except FileNotFoundError:
                continue
            except Exception:
                continue
    except Exception:
        return None
    return fallback_desc


def detect_host_hardware() -> HostHardwareProfile:
    """Detect CPU model, core/thread counts, RAM GiB, GPU model, and estimated TDP."""
    cpu_model = _detect_cpu_model()
    logical_threads: int | None = None
    physical_cores: int | None = None

    try:
        import psutil  # type: ignore[import-not-found]

        logical_threads = psutil.cpu_count(logical=True)
        physical_cores = psutil.cpu_count(logical=False)
    except Exception:
        pass

    if not logical_threads or logical_threads < 1:
        logical_threads = max(1, os.cpu_count() or 4)

    if not physical_cores or physical_cores < 1:
        physical_cores = _detect_win32_physical_cores()
    if not physical_cores or physical_cores < 1:
        physical_cores = max(1, logical_threads // 2 if logical_threads >= 4 else logical_threads)
    physical_cores = min(physical_cores, logical_threads)

    total_ram_gib = _detect_ram_gib()
    gpu_model = _detect_gpu_model()
    estimated_tdp = infer_cpu_tdp_watts(cpu_model, physical_cores)
    os_label = f"{platform.system()} {platform.release()}".strip()

    return HostHardwareProfile(
        cpu_model=cpu_model,
        physical_cores=physical_cores,
        logical_threads=logical_threads,
        total_ram_gib=total_ram_gib,
        gpu_model=gpu_model,
        estimated_tdp_watts=estimated_tdp,
        os_label=os_label,
    )


def preferred_cpu_thread_indices(logical_threads: int, count: int) -> list[int]:
    """Select CPU thread indices prioritizing even indices (physical cores) before SMT siblings."""
    total = max(1, logical_threads)
    n = max(1, min(total, count))
    even = [i for i in range(0, total, 2)]
    odd = [i for i in range(1, total, 2)]
    ordered = even + odd
    return ordered[:n]


def build_adaptive_perf_profiles(hw: HostHardwareProfile) -> dict[str, dict[str, Any]]:
    """Build Bajo, Normal, and Rápido CPU/XMRig profiles scaled to the host CPU and RAM."""
    total_t = max(1, hw.logical_threads)
    if total_t == 1:
        bajo_n, normal_n, rapido_n = 1, 1, 1
    elif total_t == 2:
        bajo_n, normal_n, rapido_n = 1, 1, 2
    else:
        bajo_n = max(1, int(round(total_t / 3.0)))
        normal_n = max(bajo_n + 1, min(total_t, int(round((total_t * 2.0) / 3.0))))
        if hw.total_ram_gib < 6.0:
            ram_cap = max(1, min(total_t // 2, int((hw.total_ram_gib - 2.2) / 0.28)))
            normal_n = max(bajo_n, min(normal_n, ram_cap))
        rapido_n = total_t

    bajo_threads = preferred_cpu_thread_indices(total_t, bajo_n)
    normal_threads = preferred_cpu_thread_indices(total_t, normal_n)
    rapido_threads = list(range(total_t))

    return {
        "bajo": {
            "mode": "bajo",
            "label": "Bajo (Eco / Menor Desgaste)",
            "description": (
                f"Rebaja la velocidad de minado ({bajo_n} de {total_t} hilos CPU, prioridad 1) "
                "y reduce el desgaste de componentes."
            ),
            "rx_threads": bajo_threads,
            "threads_count": bajo_n,
            "priority": 1,
            "yield": True,
            "relative_speed_pct": round((bajo_n / total_t) * 100.0, 1),
        },
        "normal": {
            "mode": "normal",
            "label": "Normal (Estado Actual Equilibrado)",
            "description": (
                f"Estado equilibrado adaptado al equipo ({normal_n} de {total_t} hilos CPU, prioridad 2)."
            ),
            "rx_threads": normal_threads,
            "threads_count": normal_n,
            "priority": 2,
            "yield": True,
            "relative_speed_pct": round((normal_n / total_t) * 100.0, 1),
        },
        "rapido": {
            "mode": "rapido",
            "label": "Rápido (Boost Máximo — 10s)",
            "description": (
                f"Da todos los recursos al minado ({rapido_n} de {total_t} hilos CPU, prioridad 3); "
                "vuelve automáticamente tras 10s a Normal o Bajo."
            ),
            "rx_threads": rapido_threads,
            "threads_count": rapido_n,
            "priority": 3,
            "yield": False,
            "relative_speed_pct": 100.0,
        },
    }


def discover_xmrig_paths(root_dir: Path) -> tuple[Path | None, Path | None]:
    """Find installed xmrig binary and config.json across data/xmrig or versioned subfolders."""
    xmrig_root = root_dir / "data" / "xmrig"
    exe_names = ("xmrig.exe", "xmrig") if sys.platform == "win32" else ("xmrig", "xmrig.exe")

    found_exe: Path | None = None
    found_cfg: Path | None = None

    if xmrig_root.is_dir():
        candidates: list[Path] = [xmrig_root]
        subdirs = sorted(
            [p for p in xmrig_root.iterdir() if p.is_dir()],
            key=lambda p: p.name,
            reverse=True,
        )
        candidates.extend(subdirs)

        for folder in candidates:
            if found_exe is None:
                for exe_name in exe_names:
                    candidate_exe = folder / exe_name
                    if candidate_exe.is_file():
                        found_exe = candidate_exe
                        break
            if found_cfg is None:
                candidate_cfg = folder / "config.json"
                if candidate_cfg.is_file():
                    found_cfg = candidate_cfg
            if found_exe is not None and found_cfg is not None:
                break

    if found_cfg is None and found_exe is not None:
        found_cfg = found_exe.parent / "config.json"

    return found_exe, found_cfg


def build_adaptive_xmrig_config(
    hw: HostHardwareProfile,
    *,
    pool_url: str = "rx.unmineable.com:3333",
    user_wallet_spec: str = "USDT:TU_DIRECCION_PUBLICA.worker_local",
    http_port: int = 18080,
) -> dict[str, Any]:
    """Generate a safe loopback-only XMRig config tuned to the host hardware."""
    normal_profile = build_adaptive_perf_profiles(hw)["normal"]
    return {
        "autosave": False,
        "cpu": {
            "enabled": True,
            "huge-pages": True,
            "rx": list(normal_profile["rx_threads"]),
            "priority": int(normal_profile["priority"]),
            "yield": bool(normal_profile["yield"]),
        },
        "opencl": False,
        "cuda": False,
        "http": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": http_port,
            "access-token": None,
            "restricted": True,
        },
        "pools": [
            {
                "algo": "rx/0",
                "coin": None,
                "url": pool_url,
                "user": user_wallet_spec,
                "pass": "x",
                "keepalive": True,
                "tls": False,
            }
        ],
    }
