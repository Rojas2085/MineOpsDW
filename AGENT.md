# MineOps DW — Reglas Operativas del Agente (AGENT.md)

Este documento define el marco de actuación, las restricciones éticas y técnicas, y los procedimientos obligatorios para cualquier agente de inteligencia artificial o desarrollador que trabaje en el repositorio **MineOps DW**.

---

## 1. Principios de trabajo fundamentales

1. **Inspeccionar antes de modificar:** Antes de escribir código o proponer cambios, examina el árbol de archivos real, revisa la configuración, lee las pruebas existentes y comprende la arquitectura comprobada.
2. **Elaborar un plan antes de implementar:** Presenta un plan técnico detallado antes de cualquier refactorización o cambio significativo, indicando los archivos afectados, los riesgos previsibles y la estrategia de prueba.
3. **Trabajar por fases pequeñas y verificables:** Divide el trabajo en entregas atómicas. No implementes múltiples subsistemas simultáneamente ni mezcles cambios de arquitectura con corrección de errores no relacionados.
4. **Preservar cambios previos y compatibilidad:** No sobrescribas código, adaptadores ni configuraciones funcionales sin identificar previamente su propósito y contar con la aprobación del usuario.
5. **No declarar funciones como implementadas sin código ejecutable:** Si una función solo existe a nivel de diseño conceptual, documentación o interfaces vacías, repórtala explícitamente como "diseñada" o "planificada", nunca como "implementada".
6. **Detenerse ante ambigüedades:** Si una decisión puede alterar la seguridad, el costo eléctrico, la arquitectura o la persistencia de datos, detén la ejecución y solicita clarificación explícita.

---

## 2. Restricciones de seguridad y privacidad

1. **Gestión de secretos y credenciales:**
   - Nunca expongas claves privadas, contraseñas, tokens de API, firmas criptográficas ni direcciones de correo en el código fuente, logs, mensajes de chat o commits de Git.
   - Utiliza siempre tipos `SecretStr` de Pydantic y asegura que el filtro `SecretRedactingFilter` esté activo en el sistema de logging.
   - Mantén los archivos `.env`, bases de datos SQLite locales y artefactos temporales fuera del control de versiones.
2. **Operaciones de minería y control de procesos (`CP-01-A`, `CP-02`, `R-01..R-05`):**
   - Queda terminantemente prohibido descargar, instalar, iniciar o controlar procesos reales de minería (XMRig, SRBMiner, etc.) sin la autorización expresa, específica e inequívoca del usuario.
   - **Prioridad de mocks:** La integración de conectores (como `XMRigApiAdapter`) se desarrollará y validará **exclusivamente mediante pruebas con dobles en memoria (`httpx.MockTransport`)**. No se realizarán conexiones a sockets reales de mineros durante el desarrollo.
   - **XMRig permanentemente pasivo y de solo lectura (`CP-01-A`):** `XMRigApiAdapter` funciona exclusivamente en modo pasivo (`GET /2/summary` según `CP-02` Opción B ajustada). Sus capacidades `pause` y `resume` permanecen en `UNVERIFIED_PASSIVELY`, su estado global de capacidades es `READ_ONLY` (cuando la observación es válida) o `UNAVAILABLE`, nunca obtiene `ControlAuthorization = GRANTED`, y los métodos `pause()` y `resume()` se rechazan localmente sin emitir peticiones HTTP ni JSON-RPC (`delivery="NOT_SENT"`, `acceptance="UNKNOWN"`, `postcondition="NOT_ATTEMPTED"`).
   - **Minero activo sin autorización (`OBSERVING_UNCONTROLLED` / `THERMAL_ALERT_UNCONTROLLED`):** Si un minero está activo con `ControlAuthorization in {NOT_GRANTED, REVOKED}`, se mantiene en observación pasiva (`OBSERVING_UNCONTROLLED`, o `THERMAL_ALERT_UNCONTROLLED` con precedencia si existe alerta térmica crítica). No se envían comandos automáticos de pausa ni de reanudación sin autorización.
   - **Asunción manual de control (`R-03`):** Para conectores que soporten control verificable (`MinerCapabilities.status == AVAILABLE`), el paso a `ControlAuthorization = GRANTED` requiere acción manual explícita del usuario y el cumplimiento simultáneo de las 7 precondiciones de `R-03` (incluyendo `process_progress in {ADVANCING, UNCHANGED_WITHIN_RESOLUTION}`). Jamás existe inicio ni reanudación automática (`A-02..A-05`).
   - No utilices comandos de terminación forzada de procesos (`taskkill /F`, `kill -9` o señales destructivas). El contrato `MinerConnector` excluye `start()`, `stop()` y `taskkill`.
   - **Puerto por defecto de XMRig (`PARAM-05`):** Se aprueba `http://127.0.0.1:18080` como URL loopback y puerto por defecto para `XMRigApiAdapter`.
3. **Seguridad térmica y protección de hardware (`PARAM-01` a `PARAM-04`):**
   - La CPU Ryzen 5 5600GT y el hardware local no deben ser sometidos a cargas térmicas no supervisadas.
   - La supervisión real requiere una lectura térmica válida (`TelemetryQuality == VALID`) en cada métrica térmica obligatoria.
   - **Parámetros térmicos aprobados (`PARAM-01` a `PARAM-04`):** Se aprueban por defecto en `AppSettings` y `ThermalSupervisor`: temperatura crítica `75.0 °C` (`PARAM-01`), temperatura de recuperación `60.0 °C` (`PARAM-02`), ventana de estabilidad continua `120 s` (`PARAM-03`) y antigüedad máxima de telemetría `30 s` (`PARAM-04`), conservando `max_cpu_temp_c = 80.0 °C` para compatibilidad con límites generales de host.
4. **Operaciones financieras, exchanges y pools:**
   - No automatices compras, ventas, órdenes de trading, transferencias ni retiros en Binance ni en ningún otro exchange o pool.
   - Las integraciones con Binance se limitan estrictamente a endpoints públicos de mercado y endpoints de lectura de depósitos (`GET /sapi/v1/capital/deposit/hisrec`).
   - **Configuración de retiro vacía por defecto:** Los campos `payout_coin`, `payout_address` y `payout_network` se mantendrán vacíos hasta que el usuario los defina explícitamente. No se ejecutarán consultas HTTP a pools si los parámetros de pago no están configurados.

---

## 3. Integridad de datos y persistencia

1. **Invariantes de calidad de telemetría:**
   - Todo dato debe estar catalogado como `measured`, `estimated`, `unavailable` o `simulated`.
   - Cuando un sensor no esté disponible o la lectura sea inválida, el campo `value` debe ser `None` (nunca sustituirlo por `0.0` o valores inventados) y acompañarse de una `quality_note` explicativa.
   - Prohibido inferir depósitos de Binance o saldo confirmado a partir de estimaciones teóricas de hashrate o del saldo pendiente de un pool.
2. **Persistencia y base de datos:**
   - No modifiques archivos SQLite existentes (`data/mineops_dw.sqlite3`) ni ejecutes migraciones que destruyan datos.
   - Cualquier extensión del esquema (como la propuesta de `0002_payout_and_multicoin.sql`) se mantiene como **propuesta futura**, sin ejecutarla ni aplicarla en la fase actual.
   - Emplea siempre consultas parametrizadas para evitar cualquier vector de inyección SQL.
3. **Verificación de pruebas:**
   - Nunca declares una prueba como aprobada si no fue ejecutada efectivamente en el entorno. Informa siempre el comando exacto y un resumen de la salida.
   - Si una prueba no puede ejecutarse por restricciones del entorno, permisos o dependencias ausentes, documenta la causa claramente en el informe técnico.

---

## 4. Protocolo de parada obligatoria

El agente debe detenerse y devolver el control al usuario cuando:
- Concluya una fase documental o de auditoría antes de iniciar la codificación.
- Se requiera instalar nuevas dependencias o modificar `pyproject.toml`.
- Se detecte una discrepancia técnica entre la documentación de un servicio externo (Binance, unMineable, XMRig) y el código propuesto.
- Una orden de control de minero no logre verificar su poscondición en el endpoint correspondiente.
- Se identifique un riesgo para la estabilidad térmica o la integridad de los datos persistentes.
