# Plan maestro de MineOps DW

## Alcance MVP
Aplicación local de PC para telemetría, registro histórico, estado de minería configurable, reportes de 30 minutos y dashboard. Binance será solo lectura. La app no garantiza rentabilidad ni ejecuta transferencias.

## Fases y puertas de aprobación

### Fase 0 — Descubrimiento y diseño (Completada en análisis; pendiente de aprobación del usuario)
**Decisiones iniciales acordadas y validadas:** React + TypeScript (requiere instalar Node.js LTS antes de Fase 7); Python `3.13.14` + SQLite `3.50.4` verificados; `psutil` (a instalar en `.venv` en Fase 1) junto con Libre Hardware Monitor como fuente opcional para temperatura/potencia/iGPU; minería simulada primero; Binance Pool descartado como pool de futuro por su cierre oficial anunciado para el `10/11/2026`, manteniendo Binance Exchange en modo solo lectura (`GET /sapi/v1/capital/deposit/hisrec`) y dejando la elección de pool en `undecided`.
**Entregables completados:** requisitos cerrados (`REQ-01` a `REQ-12`), inventario real del entorno Windows 11 + Ryzen 5 5600GT, matriz de sensores, comparativa verificada de pools/Binance, arquitectura detallada, riesgos, ADR 0001 actualizado y matriz requisito-prueba. Ver `docs/PHASE_0_DECISIONS.md`.
**Pruebas ejecutadas en Fase 0:** inspección segura de hardware/WMI, verificación de versiones de Python/SQLite/herramientas, verificación de ausencia de LHM y `psutil`, revisión de consistencia documental y comprobación de que no existen secretos.
**Aceptación:** decisiones documentadas con ventajas y limitaciones; sensores no comprobados marcados como `unavailable`/pendientes; ningún minero real ejecutado; esperando aprobación explícita del usuario para pasar a Fase 1.
**No hacer:** crear la aplicación completa, instalar paquetes sin autorización, elegir pool/Binance por el usuario o configurar credenciales.

### Fase 1 — Esqueleto del repositorio y calidad (Completada; pendiente de aprobación del usuario)
**Entregables completados:** estructura de paquetes en `src/mineops_dw/` (`domain`, `adapters`, `storage`, `collector`, `api`, `reporting`), configuración tipada en `src/mineops_dw/config.py` (usando `pydantic` y `python-dotenv` ya presentes en Python 3.13), sistema de logging con `SecretRedactingFilter` en `src/mineops_dw/logging_config.py`, y suite de pruebas de humo en `tests/test_smoke_phase1.py`.
**Pruebas ejecutadas:** compilación limpia con `python -m compileall src tests` y ejecución de `python -m pytest` (6 pruebas pasadas).
**Aceptación:** cualquier desarrollador puede abrir el proyecto y ejecutar los comandos documentados desde Windows sin instalar paquetes nuevos.

### Fase 2 — Modelo de dominio y almacenamiento (Completada; pendiente de aprobación del usuario)
**Entregables completados:** entidades `Measurement`, `MiningSession`, `PoolShare`, `RewardSnapshot`, `PriceSnapshot`, `PaymentEvent` y `PeriodicReport` en `src/mineops_dw/domain/models.py`; gestor SQLite en modo `WAL` con migraciones transaccionales y rollback en `src/mineops_dw/storage/database.py`; esquema inicial `0001_initial_schema.sql`; y repositorios parametrizados e idempotentes en `src/mineops_dw/storage/repositories.py`.
**Pruebas ejecutadas:** `tests/test_phase2_domain_storage.py` cubriendo CRUD, migración desde base vacía, rollback automático en fallo, integridad de claves foráneas, timestamps UTC, prohibición de `float` en finanzas e idempotencia ante duplicados.
**Aceptación:** datos persistidos y recuperables tras reinicio; ningún dato inexistente se rellena como real (`value=None` y `status='unavailable'` exigidos por dominio y `CHECK` de SQLite).

### Fase 3 — Telemetría del PC (Completada; pendiente de aprobación del usuario)
**Entregables completados:** `HostResourceSensorAdapter` (con soporte `psutil` y respaldo nativo `win32_ctypes` en Windows 11 para RAM/CPU cuando `psutil` no está instalado) y `LhmSensorAdapter` para Libre Hardware Monitor (`http://127.0.0.1:8085/data.json`) en `src/mineops_dw/adapters/sensors.py`; cálculo de energía por integración trapezoidal (`compute_energy_measurement`) y evaluador de seguridad (`evaluate_safety_limits`) en `src/mineops_dw/domain/telemetry.py`.
**Pruebas ejecutadas:** `tests/test_phase3_telemetry.py` verificando sensor presente, sensor ausente, fallo de sensor, timeout HTTP, rechazo de rango inválido (`>100%`), permisos insuficientes (`PermissionError`), cálculo de Wh y baja sobrecarga en Windows.
**Aceptación:** cada métrica tiene unidad, fuente, estado y timestamp UTC; la ausencia de un sensor o de LHM se registra como `unavailable` sin romper el agente.

### Fase 4 — Servicio de colección y API local (Completada; pendiente de aprobación del usuario)
**Entregables completados:** `TelemetryCollectorService` y `PeriodicCollectorScheduler` en `src/mineops_dw/collector/service.py`; `MineOpsApiService` (con generación de especificación OpenAPI `3.1.0` en `/openapi.json`, endpoint `/health`, autenticación `X-MineOps-Token` y bloqueo de binding público por defecto) y `LocalHttpServer` (`127.0.0.1`) en `src/mineops_dw/api/server.py`.
**Pruebas ejecutadas:** `tests/test_phase4_collector_api.py` probando endpoints, esquema OpenAPI, valores inválidos (`400`), no autorización (`401`), parada automática por límite térmico, persistencia tras colección y concurrencia sobre loopback.
**Aceptación:** el dashboard puede consultar todos los datos vía API REST local sin acceder directamente a SQLite.

### Fase 5 — Adaptador de minería/pool en modo simulado (Completada; pendiente de aprobación del usuario)
**Entregables completados:** interfaces `MinerAdapter` y `PoolAdapter`, y simulador determinista `SimulatedMinerPoolAdapter` en `src/mineops_dw/adapters/mining.py` con soporte completo de estados de sesión (`running`, `paused`, `stopped`, `error`), desconexión/reconexión de pool, shares aceptadas/rechazadas y separación entre recompensa estimada (`estimated`), saldo del pool (`pool_reported`) y pago emitido (`payout_issued`).
**Pruebas ejecutadas:** `tests/test_phase5_simulated_mining.py` probando pérdida de conexión, shares aceptadas/rechazadas, reconexión, idempotencia de sincronización en SQLite, reproducibilidad por semilla y separación de estados financieros.
**Aceptación:** flujo completo probado y persistido sin instalar ni ejecutar ningún minero real.

### Fase 6 — Integración real opcional (Completada con puerta de hardware; pendiente de aprobación del usuario)
**Entregables completados:** `MinerExecutionGuard` (que impide iniciar o instalar mineros reales sin autorización expresa y aplica la puerta de hardware al no existir un ASIC `SHA-256` en el Ryzen 5 5600GT) y `ReadOnlyHttpPoolAdapter` en `src/mineops_dw/adapters/pool_http.py` para consulta HTTP de solo lectura con reintentos acotados y logs libres de secretos.
**Pruebas ejecutadas:** `tests/test_phase6_pool_guard.py` verificando el bloqueo por defecto de ejecución real, modo desconectado, reconexión tras fallo transitorio y redacción de tokens en logs.
**Aceptación:** ningún minero real se instala ni inicia automáticamente; se mantiene el adaptador simulado activo por la puerta de hardware documentada.

### Fase 7 — Dashboard responsive (Completada; pendiente de aprobación del usuario)
**Entregables completados:** código fuente React + TypeScript tipado en `frontend/` (`package.json`, `tsconfig.json`, `src/types/api.ts`, `src/App.tsx`) y dashboard web responsive servido directamente en `http://127.0.0.1:8765/` (`src/mineops_dw/api/dashboard_ui.py`), con panel izquierdo de recursos, panel central de sesión/minería con los 4 estados financieros separados, y panel derecho de precio BTC, variación, historial y filtros.
**Pruebas ejecutadas:** `tests/test_phase7_dashboard.py` verificando estados `loading`/`error`/`empty`/`unavailable`, layout responsive móvil/desktop, atributos de accesibilidad (`aria-live`), actualización con deduplicación y separación estricta de unidades (`%`, `MiB`, `°C`, `W`/`Wh`).
**Aceptación:** los gráficos y tarjetas muestran insignias de estado/calidad (`measured`, `estimated`, `unavailable`, `simulated`) y nunca mezclan porcentajes con vatios.

### Fase 8 — Reportes automáticos de 30 minutos (Completada; pendiente de aprobación del usuario)
**Entregables completados:** `PeriodicReportGenerator` y `align_window_utc` en `src/mineops_dw/reporting/generator.py` con soporte de ventanas exactas de 30 minutos en UTC, detección de huecos (`gaps_count`), cobertura (`sample_coverage_pct`), estadísticas por métrica sin rellenar ausentes con ceros, coste eléctrico condicional a datos reales/simulados de energía, persistencia idempotente en SQLite y exportación a JSON/CSV.
**Pruebas ejecutadas:** `tests/test_phase8_reporting.py` verificando ventanas exactas, reloj alterado, huecos de datos, no duplicación ante reinicio/reintento y exportación JSON/CSV.
**Aceptación:** cada reporte indica periodo, zona horaria (`UTC`), datos ausentes (`unavailable`) y procedencia (`sources`).

### Fase 9 — Precio BTC y cálculo económico (Completada; pendiente de aprobación del usuario)
**Entregables completados:** `MarketPriceAdapter` en `src/mineops_dw/adapters/prices.py` con detección de cotización desactualizada (`stale`) y conversión USD/BOB opcional condicionada a dato de FX; y `evaluate_economics` en `src/mineops_dw/domain/economics.py` con conversión exacta `Wh -> kWh` en `Decimal` y separación estricta entre valor estimado, saldo en pool e ingreso confirmado en Binance.
**Pruebas ejecutadas:** `tests/test_phase9_prices_economics.py` verificando API caída, respuesta inválida, precio `stale`, conversión sin dato de FX, cálculos de unidades y coste eléctrico `unavailable` cuando falta potencia.
**Aceptación:** valor de recompensa estimada separado del ingreso confirmado; el coste eléctrico jamás se inventa si falta medición de potencia/energía.

### Fase 10 — Binance de solo lectura (Completada; pendiente de aprobación del usuario)
**Entregables completados:** `BinanceDepositReadOnlyAdapter` en `src/mineops_dw/adapters/binance.py` (firmado HMAC-SHA256 sobre `GET /sapi/v1/capital/deposit/hisrec`, sin ningún endpoint de retiro/trading, modo `disconnected` sin credenciales y redacción de secretos/firmas), motor de conciliación `reconcile_payouts_and_deposits` en `src/mineops_dw/domain/reconciliation.py` y endpoint `GET /api/v1/reconciliation`.
**Pruebas ejecutadas:** `tests/test_phase10_binance_reconciliation.py` cubriendo modo sin clave (`disconnected`), clave inválida/permisos insuficientes (`401`), timeout, respuesta vacía, paginación, conciliación estricta por `txId` + monto + timestamp y ausencia total de secretos en logs.
**Aceptación:** estrictamente solo lectura; no se habilitan permisos de trading ni retiro; no se guarda ni expone información sensible.

### Fase 11 — Android (opcional) (Completada; pendiente de aprobación del usuario)
**Entregables completados:** agente Kotlin de referencia en `android/MineOpsAndroidAgent.kt` y servicio de ingesta autenticada `AndroidTelemetryIngestionService` en `src/mineops_dw/adapters/android.py` para batería, temperatura (solo si el dispositivo la expone), memoria y estado de carga.
**Pruebas ejecutadas:** `tests/test_phase11_android_optional.py` probando permiso denegado, pérdida de red/reconexión, modo ahorro de batería, datos `stale` y rechazo de token inválido.
**Aceptación:** Android funciona como módulo totalmente desacoplado y no es requisito para que el MVP de PC opere.

### Fase 12 — Endurecimiento y entrega (Completada)
**Entregables completados:** backup en caliente y restauración con verificación de integridad (`PRAGMA integrity_check`) y protección contra sobrescritura en `src/mineops_dw/storage/backup.py`; escáner automatizado de secretos en `src/mineops_dw/security_scanner.py`; punto de entrada en vivo en `src/mineops_dw/runtime.py`; manual operativo en `docs/OPERATIONS.md` y suite de regresión completa.
**Pruebas ejecutadas:** `tests/test_phase12_hardening_delivery.py` cubriendo backup/restauración, protección de sobrescritura, almacenamiento lleno simulado (`StorageCapacityError`) y escaneo de secretos en todo el repositorio (`0` fugas).
**Aceptación:** documentación de instalación, operación, límites y recuperación actualizada; ninguna clave real en el repositorio; todos los criterios críticos aprobados.

### Fases 13 a 16 — Conectores de Minería (`MinerConnector`), Supervisor Térmico (`CP-01-A`..`CP-04`, `PARAM-01`..`06`) y Rentabilidad con Mocks (Completadas)
**Entregables completados:**
- Contratos ortogonales `MinerConnector`, `MinerSnapshot`, `MinerCapabilities`, `CommandResult` y `ControlAuthorization` (con las 7 precondiciones de `R-03`, incluyendo `process_progress`) en `src/mineops_dw/domain/miner_connector.py`.
- Adaptadores pasivos de solo lectura probados exclusivamente con mocks: `XMRigApiAdapter` (`CP-01-A` y `CP-02` Opción B ajustada en `src/mineops_dw/adapters/xmrig.py`), `KryptexProcessAdapter` (`src/mineops_dw/adapters/kryptex.py`) y `SRBMinerApiAdapter` (`src/mineops_dw/adapters/srbminer.py`).
- Configuración aprobada `PARAM-01` a `PARAM-06` (`75.0 °C`, `60.0 °C`, `120 s`, `30 s`, `http://127.0.0.1:18080`, y `payout_* = ""`) en `src/mineops_dw/config.py` y `.env.example`.
- Motor `ThermalSupervisor` (`src/mineops_dw/domain/thermal_supervisor.py`) con precedencia de `THERMAL_ALERT_UNCONTROLLED` bajo `NOT_GRANTED`/`REVOKED`, histéresis de `75 °C` / `60 °C` / `120 s`, cero reanudación automática, cero reintentos automáticos en pausas inciertas y detección de `EXTERNAL_OVERRIDE_CONFLICT`.
- Fallback de potencia por TDP (`estimate_power_from_tdp` con `status="estimated"`), `UnmineablePoolBalanceAdapter` (inhibido cuando `PARAM-06` está vacío), `BinancePublicMarketClient` (`/api/v3/ticker/24hr`), `compute_profitability_kpi` (`ProfitabilityKpi`) y endpoint `GET /api/v1/supervisor/status`.
**Pruebas ejecutadas:** `tests/test_phase13_xmrig_adapter.py`, `tests/test_phase14_thermal_supervisor_and_config.py`, `tests/test_phase15_tdp_pool_and_profitability.py` y `tests/test_phase16_kryptex_and_dashboard_kpis.py` (84 pruebas automatizadas en total, 100% aprobadas con mocks en memoria).

## Regla de avance
Al terminar cada fase, parar y presentar informe con pruebas. El usuario decide cuándo iniciar la siguiente.
