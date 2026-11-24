"""Resilient local XMRig supervisor used by Iniciar_MineOps.bat.

Automatically discovers the installed XMRig binary/config under data/xmrig,
adapts thread affinity (cpu.rx) to the current host hardware if needed,
and exits cleanly if no XMRig binary is installed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mineops_dw.config import load_settings  # noqa: E402
from mineops_dw.domain.hardware_profile import (  # noqa: E402
    HostHardwareProfile,
    build_adaptive_perf_profiles,
    build_adaptive_xmrig_config,
    detect_host_hardware,
    discover_xmrig_paths,
)


def _extract_xmrig_from_zip_if_needed(xmrig_root: Path) -> None:
    if not xmrig_root.is_dir():
        return
    for zpath in sorted(xmrig_root.glob("xmrig-*.zip"), reverse=True):
        try:
            with zipfile.ZipFile(zpath) as zf:
                for member in zf.namelist():
                    if member.endswith("xmrig.exe") or member.endswith("WinRing0x64.sys"):
                        target = xmrig_root / member
                        if not target.exists():
                            zf.extract(member, xmrig_root)
        except Exception:
            continue


def _ensure_adaptive_config(cfg_path: Path, hw: HostHardwareProfile) -> None:
    if not cfg_path.exists():
        settings = load_settings(env_file=ROOT / ".env")
        coin = (settings.payout_coin or "USDT").strip().upper()
        addr = (settings.payout_address or "TU_DIRECCION_PUBLICA").strip()
        worker = hw.cpu_model.split()[-1].lower() if hw.cpu_model else "worker_local"
        user_spec = f"{coin}:{addr}.{worker}"
        cfg_data = build_adaptive_xmrig_config(hw, user_wallet_spec=user_spec)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(cfg_data, indent=4), encoding="utf-8")
        return

    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        cpu_sec = raw.get("cpu")
        if not isinstance(cpu_sec, dict):
            return
        rx = cpu_sec.get("rx")
        if isinstance(rx, list) and any(
            isinstance(idx, int) and (idx < 0 or idx >= hw.logical_threads) for idx in rx
        ):
            normal_rx = build_adaptive_perf_profiles(hw)["normal"]["rx_threads"]
            cpu_sec["rx"] = list(normal_rx)
            cfg_path.write_text(json.dumps(raw, indent=4), encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    os.chdir(ROOT)
    xmrig_root = ROOT / "data" / "xmrig"
    hw = detect_host_hardware()

    exe_path, cfg_path = discover_xmrig_paths(ROOT)
    if exe_path is None:
        _extract_xmrig_from_zip_if_needed(xmrig_root)
        exe_path, cfg_path = discover_xmrig_paths(ROOT)

    if exe_path is None or not exe_path.is_file():
        return 0

    if cfg_path is None:
        cfg_path = exe_path.parent / "config.json"

    while True:
        if not exe_path.exists():
            _extract_xmrig_from_zip_if_needed(xmrig_root)
            exe_path, cfg_path = discover_xmrig_paths(ROOT)
            if exe_path is None:
                return 0
        assert cfg_path is not None
        _ensure_adaptive_config(cfg_path, hw)
        try:
            proc = subprocess.Popen(
                [str(exe_path), f"--config={cfg_path}", "--no-color"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            proc.wait()
        except Exception:
            pass
        time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
