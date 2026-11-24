@echo off
chcp 65001 >nul
title MineOps DW - Detener Sistema
cd /d "%~dp0"

echo ============================================================================
echo   MINEOPS DW - CERRANDO PROCESOS DE MINADO Y SERVIDOR LOCAL
echo ============================================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*xmrig_daemon.py*' -or $_.CommandLine -like '*-m mineops_dw*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Get-Process xmrig -ErrorAction SilentlyContinue | Stop-Process -Force; $p = Get-NetTCPConnection -LocalPort 8765,18080 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($i in $p) { Stop-Process -Id $i -Force -ErrorAction SilentlyContinue }"

echo [OK] XMRig y MineOps DW cerrados (puertos 8765 y 18080 liberados).
timeout /t 3 >nul
