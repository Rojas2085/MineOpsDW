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

### Fase 6 — Integración real opcional
**Entregables:** adaptador para una fuente/minero/pool elegido por el usuario; guía de instalación verificada; límites de carga/temperatura/tiempo.
**Pruebas:** integración controlada y de baja duración, cancelación segura, reconexión, logs sin secretos.
**Aceptación:** requiere autorización expresa; el minero no se instala ni inicia automáticamente; métricas se comparan con la fuente del pool.
**Puerta:** si no hay hardware compatible, mantener el adaptador simulado y documentar la limitación.

### Fase 7 — Dashboard responsive
**Entregables:** panel izquierdo recursos, centro estado de sesión/minería, derecha precio BTC y variación; historial y filtros.
**Pruebas:** estados loading/error/empty, datos no disponibles, layout móvil/desktop, accesibilidad básica, actualización sin duplicados.
**Aceptación:** los gráficos muestran estado/calidad; no mezclan porcentajes con watts en un gráfico circular.

### Fase 8 — Reportes automáticos de 30 minutos
**Entregables:** reporte versionado con métricas, máximos, huecos, shares, precios, coste eléctrico si hay datos y estado de calidad.
**Pruebas:** ventanas exactas, reinicio del servicio, reloj alterado, huecos de datos, no duplicación y reintento.
**Aceptación:** cada reporte indica periodo, zona horaria, datos ausentes y procedencia.

### Fase 9 — Precio BTC y cálculo económico
**Entregables:** adaptador de precio de mercado, conversión USD/BOB opcional, coste eléctrico configurable.
**Pruebas:** API caída, respuesta inválida, precio stale, conversión sin dato de FX, cálculos de unidades.
**Aceptación:** valor de recompensa estimada separado de ingreso confirmado; coste eléctrico no se inventa si falta potencia/medición.

### Fase 10 — Binance de solo lectura
**Entregables:** configuración local segura, consulta de depósitos/historial si la API disponible lo permite, pantalla de conciliación.
**Pruebas:** sin clave, clave inválida, permisos insuficientes, timeout, respuesta vacía, paginación, secretos ausentes de logs.
**Aceptación:** solo lectura; no se habilitan permisos de trading/retiro; no se guarda ni muestra información innecesaria.
**Puerta:** verificar documentación oficial vigente y restricciones de cuenta/región antes de implementar.

### Fase 11 — Android (opcional)
**Entregables:** agente Kotlin para batería, temperatura solo si la API/dispositivo lo permite, memoria y estado de carga; envío autenticado al PC.
**Pruebas:** permiso denegado, pérdida de red, reconexión, ahorro de batería, datos stale, token inválido.
**Aceptación:** Android no es requisito para que el MVP de PC funcione.

### Fase 12 — Endurecimiento y entrega
**Entregables:** pruebas de regresión, backups, manual de usuario, guía de recuperación, build reproducible y checklist de seguridad.
**Pruebas:** instalación limpia, reinicio, restauración de backup, API apagada, almacenamiento lleno simulado, escaneo de secretos.
**Aceptación:** documentación de instalación, límites y errores conocidos; ninguna clave real en repo; todos los criterios críticos aprobados.

## Regla de avance
Al terminar cada fase, parar y presentar informe con pruebas. El usuario decide cuándo iniciar la siguiente.
