# Diccionario de datos inicial (Actualizado en Fase 0)

| Entidad | Campo | Tipo | Significado y restricciones |
|---|---|---|---|
| `Measurement` | `id` | `INTEGER` / `TEXT` | Identificador único de la muestra |
| `Measurement` | `session_id` | `TEXT nullable` | Referencia opcional a `MiningSession.id` si hay sesión activa |
| `Measurement` | `metric_name` | `TEXT` | Nombre estable: `cpu_percent_total`, `cpu_percent_per_core`, `cpu_freq_mhz`, `ram_usage_percent`, `ram_used_mib`, `ram_available_mib`, `miner_process_cpu_percent`, `miner_process_rss_mib`, `gpu_util_percent`, `gpu_temp_c`, `cpu_temp_c`, `cpu_package_power_w`, `energy_consumed_wh` |
| `Measurement` | `value` | `REAL nullable` | Valor observado; **`NULL` si el sensor no está disponible** |
| `Measurement` | `unit` | `TEXT` | `%`, `MiB`, `MHz`, `°C`, `W`, `Wh`, `H/s` |
| `Measurement` | `status` | `TEXT` | `measured` \| `estimated` \| `unavailable` \| `simulated` |
| `Measurement` | `source` | `TEXT` | `psutil`, `lhm_http`, `lhm_wmi`, `win32_perf`, `calculation`, `simulator:<scenario>` |
| `Measurement` | `observed_at_utc` | `TEXT ISO-8601` | Momento exacto de observación en UTC (`YYYY-MM-DDTHH:MM:SS.sssZ`) |
| `Measurement` | `quality_note` | `TEXT nullable` | Limitación, fallo de lectura o motivo por el que es `unavailable` / `estimated` |
| `MiningSession` | `id` | `TEXT` | Identificador único de sesión (prefijo `sim_` cuando sea simulada) |
| `MiningSession` | `started_at_utc` | `TEXT ISO-8601` | Inicio de la sesión en UTC |
| `MiningSession` | `ended_at_utc` | `TEXT nullable` | Fin de la sesión en UTC (`NULL` mientras continúa activa) |
| `MiningSession` | `session_state` | `TEXT` | Estado operativo: `idle` \| `running` \| `paused` \| `stopped` \| `error` |
| `MiningSession` | `data_mode` | `TEXT` | Modo de procedencia: `simulated` \| `real` |
| `MiningSession` | `miner_name` | `TEXT nullable` | Nombre del adaptador/minero (`SimulatedMinerPoolAdapter`, etc.) |
| `MiningSession` | `pool_name` | `TEXT nullable` | Pool asociado o `simulated_pool` |
| `MiningSession` | `stop_reason` | `TEXT nullable` | Motivo de pausa/parada (`user_request`, `max_duration_reached`, `max_cpu_temp_exceeded`, `max_cpu_load_exceeded`, `miner_error`) |
| `PoolShare` | `id` | `TEXT` | ID de share o clave natural idempotente |
| `PoolShare` | `session_id` | `TEXT` | Referencia a `MiningSession.id` |
| `PoolShare` | `accepted` | `BOOLEAN` | `1` (`true`) aceptada, `0` (`false`) rechazada |
| `PoolShare` | `difficulty` | `REAL nullable` | Dificultad de la share evaluada |
| `PoolShare` | `reject_reason` | `TEXT nullable` | Razón de rechazo (`stale`, `duplicate`, `low_difficulty`, `pool_disconnected`) |
| `PoolShare` | `status` | `TEXT` | `measured` (pool/minero real) \| `simulated` |
| `PoolShare` | `source` | `TEXT` | Origen del evento (`stratum`, `pool_api`, `simulator:<scenario>`) |
| `PoolShare` | `observed_at_utc` | `TEXT ISO-8601` | Timestamp UTC del evento |
| `RewardSnapshot` | `id` | `TEXT` | Identificador único o clave idempotente |
| `RewardSnapshot` | `session_id` | `TEXT nullable` | Sesión vinculada (si aplica) |
| `RewardSnapshot` | `amount_btc` | `TEXT` (`DECIMAL`) | Cantidad en BTC representada como cadena decimal exacta (ej. `"0.00000125"`) |
| `RewardSnapshot` | `reward_stage` | `TEXT` | Etapa de la recompensa: `estimated` (cálculo local) \| `pool_reported` (saldo pendiente en el pool) |
| `RewardSnapshot` | `status` | `TEXT` | Calidad del dato: `estimated` \| `measured` \| `simulated` \| `unavailable` |
| `RewardSnapshot` | `source` | `TEXT` | Fuente del cálculo o API del pool |
| `RewardSnapshot` | `observed_at_utc` | `TEXT ISO-8601` | Timestamp UTC de la instantánea |
| `PriceSnapshot` | `id` | `TEXT` | Clave única (`asset` + `quote_asset` + `observed_at_utc`) |
| `PriceSnapshot` | `asset` | `TEXT` | Activo base (`BTC`) |
| `PriceSnapshot` | `quote_asset` | `TEXT` | Moneda cotizada (`USD`, `BOB`, `USDT`) |
| `PriceSnapshot` | `price` | `TEXT nullable` | Precio cotizado en formato decimal exacto (`NULL` si `unavailable`) |
| `PriceSnapshot` | `status` | `TEXT` | `measured` \| `unavailable` \| `simulated` |
| `PriceSnapshot` | `source` | `TEXT` | Proveedor del precio o fixture |
| `PriceSnapshot` | `observed_at_utc` | `TEXT ISO-8601` | Timestamp UTC de cotización |
| `PaymentEvent` | `id` | `TEXT` | Identificador interno único |
| `PaymentEvent` | `event_type` | `TEXT` | `payout_issued` (emitido por pool) \| `deposit_detected` (visto en Binance) \| `reconciliation` |
| `PaymentEvent` | `asset` | `TEXT` | Activo (`BTC`) |
| `PaymentEvent` | `amount` | `TEXT` (`DECIMAL`) | Importe exacto reportado (sin redondeo flotante binario) |
| `PaymentEvent` | `network_fee` | `TEXT nullable` | Comisión de red reportada si existe |
| `PaymentEvent` | `settlement_status` | `TEXT` | Estado transaccional: `pending` \| `confirmed` \| `failed` \| `unknown` |
| `PaymentEvent` | `data_status` | `TEXT` | Calidad/origen: `measured` \| `simulated` |
| `PaymentEvent` | `source` | `TEXT` | `pool_api`, `binance_read_only_api`, `reconciler`, `simulator:<scenario>` |
| `PaymentEvent` | `external_reference` | `TEXT nullable` | `txId`, ID de pago del pool o referencia pública no secreta (prefijo `SIM-TX-` en simulación) |
| `PaymentEvent` | `observed_at_utc` | `TEXT ISO-8601` | Timestamp UTC en que se emitió o detectó el evento |
| `PeriodicReport` | `id` | `TEXT` | Clave idempotente de ventana (`window_start_utc` + `window_end_utc` + `data_mode`) |
| `PeriodicReport` | `window_start_utc` | `TEXT ISO-8601` | Inicio de la ventana de 30 minutos en UTC |
| `PeriodicReport` | `window_end_utc` | `TEXT ISO-8601` | Fin de la ventana de 30 minutos en UTC |
| `PeriodicReport` | `data_mode` | `TEXT` | `simulated` \| `real` |
| `PeriodicReport` | `sample_coverage_pct` | `REAL` | Porcentaje de muestras esperadas efectivamente capturadas en la ventana |
| `PeriodicReport` | `gaps_count` | `INTEGER` | Número de huecos temporales detectados en la ventana |
| `PeriodicReport` | `summary_json` | `TEXT` | Resumen estructurado con promedios, máximos, shares, precios, coste eléctrico (o `unavailable`) y notas de calidad |
| `PeriodicReport` | `generated_at_utc` | `TEXT ISO-8601` | Timestamp UTC de generación del reporte |

## Reglas de calidad e integridad de datos
- **Prohibición de ceros falsos:** Nunca usar `0` o `0.0` como sustituto de un sensor ausente o una API caída; usar siempre `value = NULL` y `status = 'unavailable'`.
- **Unidades obligatorias:** Toda fila en `Measurement` requiere una unidad explícita y estandarizada.
- **Precisión financiera:** Los importes de criptomonedas (`BTC`) y divisas (`USD`, `BOB`) se almacenan y serializan como cadenas decimales (`TEXT` validado con `Decimal` en Python), nunca como `FLOAT` IEEE-754 para evitar errores de redondeo en la conciliación.
- **Separación de modos:** El campo `status = 'simulated'` (y `data_mode = 'simulated'`) impide mezclar pruebas del simulador con telemetría o pagos reales.
- **Normalización temporal:** Toda marca temporal persistida debe estar en UTC (`ISO-8601`).
- **Cero secretos:** Nunca almacenar API keys, firmas HMAC, tokens ni rutas privadas del usuario en ninguna entidad.

## Modelos de dominio en memoria para conectores y supervisión (`CP-01-A` y `CP-02`)
*(Estructuras efímeras en memoria definidas en `src/mineops_dw/domain/miner_connector.py`; no modifican el esquema SQLite actual)*

| Modelo / Tipo | Campos / Valores principales | Significado y restricciones |
|---|---|---|
| `MinerOperationalState` | `RUNNING` \| `PAUSED` \| `STOPPED` \| `STARTING` \| `STOPPING` \| `UNKNOWN` | Estado operativo del minero; excluye `DEGRADED`. Un fallo de red produce `UNKNOWN`, nunca `STOPPED` por inferencia. |
| `ConnectionStatus` | `REACHABLE` \| `UNREACHABLE` \| `DEGRADED` | Estado del transporte HTTP loopback hacia el conector. |
| `StateConfidence` | `CONFIRMED` \| `INFERRED` \| `UNKNOWN` | Nivel de certeza del estado operativo (`XMRigApiAdapter` solo emite `CONFIRMED` o `UNKNOWN`). |
| `ProcessProgressState` | `ADVANCING` \| `UNCHANGED_WITHIN_RESOLUTION` \| `STALLED_SUSPECTED` \| `UNKNOWN` | Evidencia de avance temporal del proceso (`uptime`); `STALLED_SUSPECTED` y `UNKNOWN` bloquean `R-03` sin corromper la calidad individual de métricas. |
| `TelemetryQuality` | `VALID` \| `STALE` \| `UNAVAILABLE` \| `INVALID` \| `SUSPECT` | Calidad individual de cada observación (`MetricObservation`). |
| `SourceFreshness` | `VERIFIED_FRESH` \| `VERIFIED_STALE` \| `UNVERIFIABLE_NO_SOURCE_TIMESTAMP` | Frescura verificable en origen (`UNVERIFIABLE_NO_SOURCE_TIMESTAMP` en `GET /2/summary` de XMRig). |
| `MinerCapabilities` | `status` (`AVAILABLE` \| `READ_ONLY` \| `UNAVAILABLE`), `connection_status`, `local_readiness`, `observe`, `state_verification`, `pause`, `resume` | Evidencia de capacidades del conector. En XMRig (`CP-01-A`), `pause` y `resume` son `UNVERIFIED_PASSIVELY` y `status` es `READ_ONLY` (o `UNAVAILABLE`). |
| `ControlAuthorization` | `state` (`NOT_GRANTED` \| `GRANTED` \| `REVOKED`), `authorization_generation` (`int >= 0`) | Estado efímero en memoria por sesión que gobierna el permiso de pausa térmica supervisada (`R-01..R-05`). |
| `CommandResult` | `delivery`, `acceptance`, `postcondition`, `pre_snapshot`, `post_snapshot`, `authorization_generation`, `revoked_during_execution`, `causal_attribution` | Resultado estructurado e inmutable de `pause()` y `resume()` (`R-02`). |
| `SupervisorMode` | `PASSIVE_IDLE` \| `OBSERVING_UNCONTROLLED` \| `ACTIVE_SUPERVISION` \| `DEGRADED_WAIT` \| `THERMAL_ALERT_UNCONTROLLED` \| `EXTERNAL_OVERRIDE_CONFLICT` | Modo operativo del supervisor térmico; `THERMAL_ALERT_UNCONTROLLED` tiene precedencia sobre `DEGRADED_WAIT` cuando no existe autorización activa. |
