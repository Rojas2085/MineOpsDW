@echo off
chcp 65001 >nul
title MineOps DW - Configurar XMRig Real (Opcional)
cd /d "%~dp0"

set "PY_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY_EXE=%~dp0.venv\Scripts\python.exe"
)

"%PY_EXE%" -c "import httpx" >nul 2>&1
if errorlevel 1 (
  echo Preparando entorno Python local (.venv) antes de iniciar el asistente...
  python -m venv "%~dp0.venv"
  set "PY_EXE=%~dp0.venv\Scripts\python.exe"
  "%PY_EXE%" -m pip install -e "%~dp0"
)

"%PY_EXE%" "%~dp0scripts\setup_xmrig.py"
echo.
pause
