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

### Fase 1 — Esqueleto del repositorio y calidad
**Entregables:** estructura de paquetes, configuración de Python, logging, configuración tipada, CI local/documentada, pruebas de humo.
**Pruebas:** instalación limpia en entorno virtual; importación de módulos; lint/type-check si se configuran; suite de pruebas vacía/semilla.
**Aceptación:** una persona puede clonar/abrir el proyecto y ejecutar los comandos documentados desde Windows.

### Fase 2 — Modelo de dominio y almacenamiento
**Entregables:** entidades Measurement, MiningSession, PoolShare, RewardSnapshot, PriceSnapshot, PaymentEvent; SQLite y migraciones versionadas.
**Pruebas:** CRUD, migración desde base vacía, rollback en fallo, integridad de claves, timestamps UTC, duplicados/idempotencia.
**Aceptación:** datos persistidos y recuperables tras reinicio; ningún dato inexistente se rellena como real.

### Fase 3 — Telemetría del PC
**Entregables:** adaptador CPU/RAM/procesos; GPU si hay fuente compatible; temperatura/potencia por sensores disponibles; estado de calidad.
**Pruebas:** sensor presente/ausente, fallo de sensor, timeout, rango inválido, permisos insuficientes, uso de CPU del colector.
**Aceptación:** cada métrica tiene unidad, fuente, estado y timestamp; ausencia de sensor no rompe el agente.
**Nota:** no asumir que la GPU integrada o la placa exponen sensores a todas las bibliotecas.

### Fase 4 — Servicio de colección y API local
**Entregables:** servicio de muestreo configurable, API REST, OpenAPI, endpoint health, autenticación local si se habilita acceso fuera de loopback.
**Pruebas:** endpoints, esquema, valores inválidos, timeout, persistencia, concurrencia básica, no exposición pública por defecto.
**Aceptación:** dashboard puede leer datos sin acceder directamente a SQLite.

### Fase 5 — Adaptador de minería/pool en modo simulado
**Entregables:** interfaz MinerAdapter/PoolAdapter; proveedor simulado determinista; estados de sesión; shares y recompensas etiquetadas.
**Pruebas:** conexión ausente, share aceptada/rechazada, pool caído, reconexión, datos duplicados, saldo estimado separado del confirmado.
**Aceptación:** flujo completo probado sin instalar ni ejecutar un minero real.

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
