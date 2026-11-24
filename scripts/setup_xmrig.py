"""Interactive explicit-consent setup wizard for optional real XMRig mining on Windows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import zipfile

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mineops_dw.domain.hardware_profile import (  # noqa: E402
    build_adaptive_perf_profiles,
    build_adaptive_xmrig_config,
    detect_host_hardware,
)

GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/xmrig/xmrig/releases/latest"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _parse_sha256sums(text: str, filename: str) -> str | None:
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1].lstrip("*") == filename:
            return parts[0].lower()
    return None


def _upsert_env_values(env_path: Path, example_path: Path, updates: dict[str, str]) -> None:
    if not env_path.exists() and example_path.exists():
        env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")

    existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        replaced = False
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                seen.add(key)
                replaced = True
        if not replaced:
            new_lines.append(line)

    for key, val in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def main() -> int:
    hw = detect_host_hardware()
    profiles = build_adaptive_perf_profiles(hw)

    print("============================================================================")
    print("  MINEOPS DW — ASISTENTE OPCIONAL PARA MINADO REAL CON XMRIG (SOLO LOOPBACK)")
    print("============================================================================")
    print(f"CPU detectada       : {hw.cpu_model}")
    print(f"Núcleos / Hilos     : {hw.physical_cores} físicos / {hw.logical_threads} lógicos")
    print(f"RAM física          : {hw.total_ram_gib} GiB")
    print(f"GPU / iGPU          : {hw.gpu_model or 'No detectada'}")
    print(f"TDP estimado        : {hw.estimated_tdp_watts:.0f} W")
    print()
    print("Perfiles adaptativos calculados para este equipo:")
    print(f"  - Bajo (Eco)   : {profiles['bajo']['threads_count']} hilos ({profiles['bajo']['rx_threads']})")
    print(f"  - Normal       : {profiles['normal']['threads_count']} hilos ({profiles['normal']['rx_threads']})")
    print(f"  - Rápido (10s) : {profiles['rapido']['threads_count']} hilos ({profiles['rapido']['rx_threads']})")
    print()
    print("AVISO: XMRig es completamente opcional; MineOps DW funciona en modo 'simulated'")
    print("sin descargar binarios externos. Si autorizas esta instalación:")
    print("  1. Se descargará el binario oficial desde GitHub (xmrig/xmrig) verificando SHA-256.")
    print("  2. La API HTTP de XMRig quedará restringida estrictamente a 127.0.0.1:18080.")
    print("  3. Windows Defender podría requerir permiso local según tu antivirus.")
    print()

    consent = input("¿Autorizas descargar y configurar XMRig oficial para este equipo? [s/N]: ").strip().lower()
    if consent not in {"s", "si", "sí", "y", "yes"}:
        print("\nInstalación cancelada por el usuario. El proyecto seguirá en modo simulado seguro.")
        return 0

    print("\n[1/4] Consultando última versión oficial de XMRig en GitHub Releases...")
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        rel_resp = client.get(
            GITHUB_LATEST_RELEASE_URL,
            headers={"Accept": "application/vnd.github+json"},
        )
        rel_resp.raise_for_status()
        release = rel_resp.json()
        assets = release.get("assets") or []

        zip_asset = next(
            (
                a
                for a in assets
                if str(a.get("name", "")).endswith("-windows-x64.zip")
                or str(a.get("name", "")).endswith("-msvc-win64.zip")
            ),
            None,
        )
        sums_asset = next((a for a in assets if str(a.get("name", "")) == "SHA256SUMS"), None)

        if zip_asset is None or sums_asset is None:
            print("[ERROR] No se encontró el paquete Windows x64 o SHA256SUMS en GitHub Releases.")
            return 1

        zip_name = str(zip_asset["name"])
        xmrig_root = ROOT / "data" / "xmrig"
        xmrig_root.mkdir(parents=True, exist_ok=True)
        zip_path = xmrig_root / zip_name

        print(f"[2/4] Descargando {zip_name} y SHA256SUMS...")
        sums_text = client.get(str(sums_asset["browser_download_url"])).text
        expected_sha = _parse_sha256sums(sums_text, zip_name)
        if not expected_sha:
            print(f"[ERROR] No se encontró el hash SHA-256 para {zip_name} en SHA256SUMS.")
            return 1

        zip_bytes = client.get(str(zip_asset["browser_download_url"])).content
        zip_path.write_bytes(zip_bytes)

    actual_sha = _sha256_file(zip_path)
    if actual_sha != expected_sha:
        zip_path.unlink(missing_ok=True)
        print("[ERROR] Verificación SHA-256 fallida. Archivo eliminado por seguridad.")
        return 1
    print(f"      SHA-256 verificado OK: {actual_sha[:16]}...")

    print("[3/4] Extrayendo XMRig y generando config.json adaptado a tu hardware...")
    extracted_dir = xmrig_root
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if member.endswith("xmrig.exe") or member.endswith("WinRing0x64.sys"):
                zf.extract(member, xmrig_root)
                if member.endswith("xmrig.exe"):
                    extracted_dir = (xmrig_root / member).parent

    print()
    coin = input("Moneda de pago para pool unMineable [USDT]: ").strip().upper() or "USDT"
    network = input("Red de pago (ej. BSC, TRX, SOL) [BSC]: ").strip().upper() or "BSC"
    address = input("Dirección pública de tu cartera (Enter para dejar en modo demo): ").strip()

    safe_addr = address or "TU_DIRECCION_PUBLICA"
    worker_slug = "worker_local"
    cfg_dict = build_adaptive_xmrig_config(
        hw,
        user_wallet_spec=f"{coin}:{safe_addr}.{worker_slug}",
    )
    cfg_path = extracted_dir / "config.json"
    cfg_path.write_text(json.dumps(cfg_dict, indent=4), encoding="utf-8")

    print("[4/4] Actualizando .env local en TELEMETRY_MODE=real...")
    env_updates = {"TELEMETRY_MODE": "real"}
    if address:
        env_updates["PAYOUT_COIN"] = coin
        env_updates["PAYOUT_NETWORK"] = network
        env_updates["PAYOUT_ADDRESS"] = address
    _upsert_env_values(ROOT / ".env", ROOT / ".env.example", env_updates)

    print()
    print("============================================================================")
    print(f"  XMRig instalado y ajustado a {hw.cpu_model} ({hw.logical_threads} hilos).")
    print(f"  Configuración guardada en: {cfg_path}")
    print("  Ahora ejecuta Iniciar_MineOps.bat para lanzar el sistema completo.")
    print("============================================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
