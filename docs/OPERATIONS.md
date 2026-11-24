# Operación, diagnóstico, backup y recuperación (Fase 12)

## 1. Arranque local seguro
MineOps DW está diseñado para ejecutarse exclusivamente en loopback (`127.0.0.1:8765`) y en modo `simulated` por defecto:

```powershell
$env:PYTHONPATH = "src"
python -m mineops_dw
```

Una vez iniciado:
- **Dashboard Web Responsive:** `http://127.0.0.1:8765/`
- **Health Check:** `http://127.0.0.1:8765/health`
- **Supervisor Térmico y Conector (`CP-04`):** `http://127.0.0.1:8765/api/v1/supervisor/status`
- **Esquema OpenAPI 3.1:** `http://127.0.0.1:8765/openapi.json`
- **Conciliación:** `http://127.0.0.1:8765/api/v1/reconciliation`
- **Exportación Excel (.xlsx) para Power BI:** `http://127.0.0.1:8765/api/v1/exports/excel`
- **Informe Ejecutivo Gerencial (PDF / Imprimible):** `http://127.0.0.1:8765/api/v1/exports/executive-report`

### Lanzadores de 1 Clic para Windows y Auto-Adaptación Multi-PC
En la raíz del proyecto se incluyen scripts para instalar, ajustar y operar el sistema en cualquier PC Windows sin configuración manual:
- `Iniciar_MineOps.bat`: Crea `.venv` e instala dependencias si faltan, inicializa `.env` desde `.env.example` en modo `simulated` si no existe, libera puertos previos, inicia el servicio en segundo plano (`127.0.0.1:8765` y opcionalmente `127.0.0.1:18080` solo si `TELEMETRY_MODE=real` y hay binario XMRig instalado) y abre automáticamente el Dashboard en el navegador predeterminado.
- `Configurar_XMRig_Real.bat`: Asistente opcional con confirmación explícita (`s/N`) que detecta el hardware del equipo (CPU, núcleos/hilos, RAM, GPU, TDP), descarga XMRig oficial verificando SHA-256 y genera un `config.json` loopback adaptado al procesador local.
- `Detener_MineOps.bat`: Cierra limpiamente los procesos `xmrig.exe`, `xmrig_daemon.py` y el servidor Python liberando los puertos `8765` y `18080`.

## 2. Principios operativos
- Iniciar siempre primero en modo `simulated`.
- Verificar `/health` y la marca `last_collection_at_utc`.
- Ningún minero real se instala ni inicia automáticamente (`MinerExecutionGuard`).
- Si un sensor térmico (`cpu_temp_c`) o de potencia (`cpu_package_power_w`) no está disponible (por ejemplo, si Libre Hardware Monitor no está abierto), el sistema registra `value=null` y `status="unavailable"` sin detener la colección ni inventar valores.
- Mantener copias de seguridad antes de migraciones o cambios de configuración.

## 3. Diagnóstico básico
1. **Revisar logs libres de secretos:** Todos los logs pasan por `SecretRedactingFilter` (`[REDACTED]`).
2. **Confirmar binding local:** `bound_host` en `/health` debe ser `127.0.0.1`.
3. **Sensores Windows:** Si `psutil` no está instalado, `HostResourceSensorAdapter` utiliza automáticamente `win32_ctypes` (`GlobalMemoryStatusEx` y `GetSystemTimes`) para medir RAM y CPU reales.
4. **Fallo o ausencia de Binance:** Si `BINANCE_READ_ONLY_API_KEY` está vacío, `BinanceDepositReadOnlyAdapter` opera en estado `disconnected` y el resto del panel funciona con normalidad.

## 4. Procedimiento de Backup y Recuperación verificada
Para crear una copia de seguridad en caliente (compatible con SQLite `WAL`):

```powershell
$env:PYTHONPATH = "src"
python -c "from mineops_dw.storage import create_sqlite_backup; create_sqlite_backup('data/mineops_dw.sqlite3', 'data/backups/mineops_backup.sqlite3')"
```

Para restaurar una copia de seguridad en una ruta de prueba verificando `PRAGMA integrity_check`:

```powershell
$env:PYTHONPATH = "src"
python -c "from mineops_dw.storage import restore_sqlite_backup; restore_sqlite_backup('data/backups/mineops_backup.sqlite3', 'data/restored_test.sqlite3')"
```

> Nota: `restore_sqlite_backup` nunca sobrescribe una base existente salvo que se indique explícitamente `allow_overwrite=True`, y aun en ese caso genera automáticamente una copia preventiva `.pre_restore.bak`.

## 6. Entorno aislado de pruebas con APIs y sockets reales
Para ejecutar pruebas reales contra sensores del host Windows 11 (`HostResourceSensorAdapter`), Libre Hardware Monitor (`http://127.0.0.1:8085/data.json`), servidores TCP loopback reales (`LocalHttpServer`, `XMRigApiAdapter`, `SRBMinerApiAdapter`, `ThermalSupervisor`), inspección real de procesos (`KryptexProcessAdapter`) y las APIs públicas en vivo de Binance (`GET https://api.binance.com/api/v3/ticker/24hr` y `/api/v3/ticker/price`) usando una base SQLite temporal aislada (sin tocar `data/mineops_dw.sqlite3`):

```powershell
# Diagnóstico CLI completo en JSON (incluyendo HTTPS real contra api.binance.com)
$env:PYTHONPATH = "src"; python -m tests.live_api_environment

# Suite pytest de integración con sockets TCP reales y APIs reales en Internet
$env:MINEOPS_RUN_LIVE_API_TESTS = "1"; $env:PYTHONPATH = "src"; python -m pytest tests/test_live_real_apis.py -v
```

