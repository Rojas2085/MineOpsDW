@echo off
chcp 65001 >nul
title MineOps DW - Lanzador de 1 Clic
cd /d "%~dp0"

echo ============================================================================
echo   MINEOPS DW - INICIANDO SISTEMA DE TELEMETRIA, MINADO Y DATA WAREHOUSE
echo ============================================================================
echo.

set "PY_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY_EXE=%~dp0.venv\Scripts\python.exe"
)

echo [1/5] Verificando entorno Python y dependencias...
"%PY_EXE%" -c "import pydantic, dotenv, httpx, tenacity" >nul 2>&1
if errorlevel 1 (
  echo       Instalando dependencias iniciales en .venv local...
  python -m venv "%~dp0.venv"
  if errorlevel 1 (
    echo [ERROR] No se encontro Python 3.12+ en PATH. Instalalo antes de continuar.
    pause
    exit /b 1
  )
  set "PY_EXE=%~dp0.venv\Scripts\python.exe"
  "%PY_EXE%" -m pip install -e "%~dp0"
  if errorlevel 1 (
    echo [ERROR] No se pudieron instalar las dependencias de pyproject.toml.
    pause
    exit /b 1
  )
)

if not exist "%~dp0.env" (
  if exist "%~dp0.env.example" (
    copy /Y "%~dp0.env.example" "%~dp0.env" >nul
    echo       [INFO] Archivo .env creado desde .env.example en modo SIMULADO seguro.
    echo              Si deseas probar minado real luego, usa: Configurar_XMRig_Real.bat
  )
)

echo [2/5] Liberando puertos locales (8765 y 18080)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Process xmrig -ErrorAction SilentlyContinue | Stop-Process -Force; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*xmrig_daemon.py*' -or $_.CommandLine -like '*-m mineops_dw*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; $p = Get-NetTCPConnection -LocalPort 8765,18080 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($i in $p) { Stop-Process -Id $i -Force -ErrorAction SilentlyContinue }"

echo [3/5] Verificando modo de operacion y minero local...
"%PY_EXE%" -c "from pathlib import Path; import sys; sys.path.insert(0, 'src'); from mineops_dw.config import load_settings; from mineops_dw.domain.hardware_profile import discover_xmrig_paths; cfg = load_settings(Path('.env')); exe, _ = discover_xmrig_paths(Path('.')); sys.exit(0 if (cfg.telemetry_mode == 'real' and exe is not None) else 2)"
if %errorlevel%==0 (
  echo       Modo REAL con XMRig detectado. Iniciando motor XMRig auto-adaptado...
  start "MineOps_XMRig" /MIN "%PY_EXE%" "%~dp0scripts\xmrig_daemon.py"
) else (
  echo       Iniciando sin minero real ^(modo simulado seguro o telemetria pasiva^).
)

echo [4/5] Iniciando servidor MineOps DW (127.0.0.1:8765)...
start "MineOps_DW_Server" /MIN cmd /c "cd /d "%~dp0" && set PYTHONPATH=src&& "%PY_EXE%" -m mineops_dw"

echo [5/5] Esperando a que el servidor responda (hasta 90 s)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; for ($i=0; $i -lt 90; $i++) { try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/health' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { $ok=$true; break } } catch {}; Start-Sleep -Seconds 1 }; if ($ok) { Write-Host '      Servidor listo.' ; exit 0 } else { Write-Host '      ERROR: el servidor no respondio. Revisa la ventana MineOps_DW_Server.'; exit 1 }"
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

echo Abriendo Dashboard en http://127.0.0.1:8765/ ...
start "" "http://127.0.0.1:8765/"

echo.
echo ============================================================================
echo   SISTEMA ACTIVO EN: http://127.0.0.1:8765/
echo   Para cerrar todo el sistema usa: Detener_MineOps.bat
echo ============================================================================
timeout /t 4 >nul
