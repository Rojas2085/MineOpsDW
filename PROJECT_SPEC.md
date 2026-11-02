# MineOps DW — Especificación Técnica del Proyecto (PROJECT_SPEC)
## Arquitectura Modular de Telemetría CPU, Minería Multi-Motor, Costos Eléctricos y Conciliación de Pagos

---

## 1. Propósito de MineOps DW

**MineOps DW** (Data Warehouse & Operations Center) es un sistema local, modular y observable diseñado para monitorizar el rendimiento físico de la CPU, supervisar procesos de minería experimental, evaluar costos energéticos en tiempo real, consultar saldos acumulados en pools de minería y rastrear el progreso de pagos hacia exchanges (específicamente Binance).

### Principios rectores
1. **Seguridad térmica y del hardware:** Prioridad absoluta a la integridad física del equipo (CPU Ryzen 5 5600GT / hardware Windows 11). Minería real estrictamente condicionada a la disponibilidad de sensores térmicos válidos y frescos.
2. **Honestidad operativa y separación de estados:** Prohibido convertir estimaciones o proyecciones en balances confirmados. Distinción explícita entre datos medidos (`measured`), estimados (`estimated`), no disponibles (`unavailable`) y simulados (`simulated`).
3. **Aislamiento de red y soberanía de datos:** La API REST y el dashboard operan exclusivamente sobre la interfaz de bucle invertido (`127.0.0.1`). No se abren puertos públicos ni se transmiten telemetría ni credenciales al exterior.
4. **No custodia y cero trading:** No se gestionan claves privadas, frases semilla ni permisos de retiro o trading. Las integraciones de exchange son de lectura pública o lectura autenticada con privilegios mínimos.

---

## 2. Arquitectura actual comprobada

A través de la inspección directa del repositorio en `master`, se verificaron los siguientes componentes existentes:

```
[ Hardware: CPU / LHM ]    [ Precios Mercado ]     [ Simulador Minero / Pool ]
         │                          │                          │
         ▼                          ▼                          ▼
 [ SensorAdapter ]         [ MarketPriceAdapter ]   [ SimulatedMinerPoolAdapter ]
 (HostResourceSensor,      (CoinGecko / Binance)     (Sesión, Hashrate, Shares)
  LhmSensorAdapter)                 │                          │
         │                          │                          │
         └──────────────────────────┼──────────────────────────┘
                                    │
                                    ▼
                     [ TelemetryCollectorService ]
                     (collector/service.py + Scheduler 10s)
                                    │
                                    ├──> [ Domain Logic (domain/) ]
                                    │    (evaluate_safety_limits, compute_energy)
                                    │
                                    ├──> [ SQLite Database (WAL mode) ]
                                    │    (mining_sessions, measurements,
                                    │     pool_shares, reward_snapshots,
                                    │     payment_events, periodic_reports)
                                    │
                                    ▼
                        [ LocalHttpServer (127.0.0.1:8765) ]
                        [ MineOpsApiService (api/server.py) ]
                                    │
                                    ▼
                        [ Dashboard UI (HTML5 / Vanilla JS) ]
```

### Componentes comprobados en código:
- **Configuración tipada (`config.py`):** Modelo `AppSettings` en Pydantic v2. Soporta `TELEMETRY_MODE` (`simulated` vs `real`), umbrales térmicos heredados (`max_cpu_temp_c = 80.0`), carga de CPU (`max_cpu_percent = 75.0`), duración máxima de sesión (`max_session_minutes = 30`), enlace loopback estricto y ofuscación de secretos.
- **Sensores de hardware (`adapters/sensors.py`):**
  - `HostResourceSensorAdapter`: CPU Total % y RAM física mediante `psutil`, con fallback nativo en Windows mediante llamadas `ctypes` (`GetSystemTimes` y `GlobalMemoryStatusEx`).
  - `LhmSensorAdapter`: Consulta JSON local a Libre Hardware Monitor (`http://127.0.0.1:8085/data.json`) para temperatura de CPU (`cpu_temp_c`), potencia de paquete (`cpu_package_power_w`) y uso de iGPU (`gpu_util_percent`). Si el servicio no responde, degrada de forma segura a `status="unavailable"` con `value=None`.
- **Motor simulado (`adapters/mining.py`):** `SimulatedMinerPoolAdapter` determinista que emite hashrate, shares aceptadas/rechazadas, recompensas locales estimadas y eventos de pago simulados.
- **Adaptador XMRig (`adapters/xmrig.py`):** Implementado y verificado en pruebas unitarias con mocks (`test_phase13_xmrig_adapter.py`). Opera en modo **exclusivamente pasivo y de solo lectura (`CP-01-A`)** sobre loopback HTTP (`GET /2/summary` según `CP-02` Opción B ajustada), con validación estricta de host, token Bearer con `SecretStr`, rechazo local sin I/O en `pause()` y `resume()` (`delivery="NOT_SENT"`, `acceptance="UNKNOWN"`, `postcondition="NOT_ATTEMPTED"`), y separación ortogonal entre conexión, estado operativo, confianza, avance de proceso y calidad individual de métricas. Permanece desacoplado del runtime y de `MinerAdapter` (`SimulatedMinerPoolAdapter`).
- **Colector central (`collector/service.py`):** `TelemetryCollectorService` coordina la ejecución periódica de adaptadores, cálculo trapezoidal de energía en vatios-hora (`compute_energy_measurement`), evaluación de límites de seguridad (`evaluate_safety_limits`), y deduplicación de registros en SQLite.
- **Almacenamiento SQLite (`storage/`):** Base de datos SQLite en modo `WAL` con claves foráneas, migraciones SQL idempotentes (`0001_initial_schema.sql`) y repositorio `MineOpsRepository` para 7 entidades de dominio.
- **API REST y Dashboard (`api/server.py`, `api/dashboard_ui.py`):** Servidor HTTP loopback (`127.0.0.1:8765`) que expone OpenAPI 3.1, endpoints REST (`/health`, `/measurements`, `/sessions`, `/rewards`, `/payments`, `/reports`, `/collect`) y la interfaz web Cyberpunk Mining Operations Center.

---

## 3. Arquitectura modular propuesta

La evolución modular desacopla la recolección, supervisión y análisis en módulos de responsabilidad única bajo el paquete existente `src/mineops_dw/`:

```text
src/mineops_dw/
├── config.py                         # AppSettings extendido (validación Pydantic v2)
├── logging_config.py                 # Logger estructurado y SecretRedactingFilter
├── runtime.py                        # Bootstrapper y orquestación de servicios locales
├── main_collector.py                 # Orquestador desacoplado con planificadores temporizados
│
├── domain/                           # Entidades de dominio puro y reglas analíticas (sin I/O)
│   ├── models.py                     # Measurement, MiningSession, PoolShare, PaymentEvent
│   ├── telemetry.py                  # Integración de energía trapezoidal (Wh)
│   ├── thermal_policy.py             # Política térmica (parámetros PARAM-01 a PARAM-04 pendientes)
│   ├── miner_connector.py            # MinerConnector, MinerSnapshot, MinerCapabilities, CommandResult, ControlAuthorization
│   ├── payout.py                     # Modelo de balance pendiente, umbral y estado de retiro
│   └── profitability.py              # Cálculo de costo energético, ingresos brutos y margen neto
│
├── adapters/                         # Conectores de entrada/salida a hardware y servicios
│   ├── sensors.py                    # Sensores CPU/RAM (psutil, Win32 ctypes, LibreHardwareMonitor)
│   ├── mining.py                     # SimulatedMinerPoolAdapter determinista (contrato MinerAdapter)
│   ├── xmrig.py                      # Conector HTTP pasivo de solo lectura para XMRig (CP-01-A, CP-02)
│   ├── srbminer.py                   # Conector HTTP local para SRBMiner-Multi (propuesto)
│   ├── kryptex.py                    # Monitor pasivo de procesos para Kryptex (propuesto)
│   ├── binance_client.py             # Cliente público de precios Binance (ticker/24hr)
│   ├── binance.py                    # BinanceDepositReadOnlyAdapter (SAPI depósitos de lectura)
│   ├── pool_balance.py               # Conector de balance de pools (unMineable / Zergpool)
│   └── prices.py                     # Adaptador de mercado agnóstico (CoinGecko / Binance / BOB)
│
├── collectors/                       # Trabajadores especializados de recolección
│   ├── cpu_collector.py              # Recolección de CPU (%, MHz, °C, W) cada 10s
│   ├── miner_collector.py            # Consulta a API de mineros cada 5-10s
│   ├── pool_balance_collector.py     # Consulta de balance en pool cada 5-15 min
│   └── market_price_collector.py     # Actualización de precios de mercado cada 60s
│
├── services/                         # Servicios de coordinación y supervisión operativa
│   ├── telemetry_supervisor.py       # Máquina de estados del supervisor térmico y de seguridad
│   └── kpi_calculator.py             # Servicio agregador de métricas energéticas y de rentabilidad
│
├── storage/                          # Persistencia analítica y operacional
│   ├── database.py                   # SQLiteDatabase con soporte WAL y migraciones SQL
│   ├── repositories.py               # MineOpsRepository (inserción y consultas optimizadas)
│   └── migrations/                   # Scripts SQL versionados e incrementales
│
└── api/                              # Capa de presentación y transporte
    ├── server.py                     # MineOpsApiService y LocalHttpServer
    └── dashboard_ui.py               # Dashboard web HTML5/JS (Mining Operations Center)
```

---

## 4. Componentes reutilizables

| Componente | Archivo actual | Grado de reutilización | Función dentro de la nueva arquitectura |
| :--- | :--- | :--- | :--- |
| `Measurement`, `MiningSession`, `PaymentEvent` | `domain/models.py` | **100% (Conservar)** | Modelos base inmutables con validación de unidades, procedencia y calidad. |
| `compute_energy_measurement` | `domain/telemetry.py` | **100% (Conservar)** | Integración trapezoidal de vatios a vatios-hora (Wh). |
| `evaluate_safety_limits` | `domain/telemetry.py` | **100% (Conservar)** | Vigilante catastrófico general para modo simulado y límites de host. |
| `HostResourceSensorAdapter`, `LhmSensorAdapter` | `adapters/sensors.py` | **95% (Conservar)** | Fuentes primarias de telemetría de CPU, RAM, temperatura y potencia. |
| `SimulatedMinerPoolAdapter` | `adapters/mining.py` | **100% (Conservar)** | Motor de pruebas y desarrollo sin hardware de minería. |
| `XMRigApiAdapter` | `adapters/xmrig.py` | **100% (Conservar)** | Conector HTTP loopback pasivo de solo lectura (`GET /2/summary`) conforme a `CP-01-A` y `CP-02` (Opción B ajustada). |
| `MarketPriceAdapter`, `BinanceDepositReadOnlyAdapter` | `adapters/prices.py`, `adapters/binance.py` | **90% (Adaptar)** | Consulta de precios y depósitos confirmados en Binance. |
| `SQLiteDatabase`, `MineOpsRepository` | `storage/database.py`, `storage/repositories.py` | **95% (Conservar)** | Persistencia ACID local, gestión de transacciones y WAL. |
| `SecretRedactingFilter`, `configure_logging` | `logging_config.py` | **100% (Conservar)** | Seguridad de registros y ofuscación de secretos. |
| `LocalHttpServer`, `DASHBOARD_HTML`, `DASHBOARD_JS` | `api/server.py`, `api/dashboard_ui.py` | **85% (Adaptar)** | Interfaz visual y API REST loopback. |

---

## 5. Flujos de datos

### 5.1. Flujo de telemetría física (Hardware -> Dashboard)
1. **Muestreo:** `cpu_collector` invoca cada 10 s a `HostResourceSensorAdapter` y `LhmSensorAdapter`.
2. **Validación:** Cada lectura se normaliza como `Measurement` con `metric_name`, `value`, `unit`, `status` (`measured` o `unavailable`), `source` y timestamp UTC.
3. **Integración energética:** Si existe `cpu_package_power_w` válido, se calcula el diferencial de energía consumida en vatios-hora (`Wh`) mediante integración trapezoidal contra la muestra anterior.
4. **Supervisión térmica:** La muestra de `cpu_temp_c` se somete a `ThermalWatchdogPolicy`. Si excede el umbral crítico propuesto (75.0 °C) o el sensor está obsoleto ($> 30$ s), se instruye pausa preventiva.
5. **Persistencia:** Se insertan las mediciones en la tabla `measurements` de SQLite mediante operaciones parametrizadas e idempotentes.
6. **Visualización:** El dashboard consulta `GET /api/v1/measurements` y renderiza barras de porcentaje, termómetros y potencia en paneles segregados por unidad.

### 5.2. Flujo de minería y seguimiento de pagos
1. **Consulta del minero:** `miner_collector` consulta periódicamente la API local del conector activo implementando el protocolo `MinerConnector`.
2. **Normalización de shares y hashrate:** Se extraen hashrate actual, shares aceptadas y rechazadas en un `MinerStatus` normalizado.
3. **Consulta de balance en pool:** `pool_balance_collector` consulta a intervalos largos (5–15 min) la API pública del pool configurado, siempre que `is_payout_configured` sea `True`. Si los datos de pago no están configurados, inhibe las peticiones de red y emite `status="unavailable"`.
4. **Cálculo de progreso:** Cuando el balance y el umbral están definidos, se calcula `progreso_pct = (saldo_pendiente / umbral_pago) * 100`.
5. **Consulta de precios de mercado:** `market_price_collector` obtiene el precio del activo contra USD/USDT vía endpoint público de Binance.
6. **Valorización y margen:** `kpi_calculator` evalúa el costo energético acumulado frente al valor del saldo pendiente y emite métricas de rentabilidad neta estimada.
7. **Detección de pagos:**
   - Evento de pago emitido por el pool (`payout_issued`) registrado a partir de los datos del pool.
   - Evento de depósito recibido en Binance (`deposit_detected`) verificado de forma independiente a través de `BinanceDepositReadOnlyAdapter` (requiere coincidencia de `txId`).

---

## 6. Fuentes de datos y limitaciones

| Fuente | Endpoint / Protocolo | Datos proporcionados | Limitaciones y riesgos |
| :--- | :--- | :--- | :--- |
| **psutil** | API nativa del SO / Python | Carga de CPU (%), RAM usada/disponible (MiB). | No provee temperatura ni potencia de CPU en Windows sin drivers de terceros. |
| **Win32 ctypes** | `GetSystemTimes`, `GlobalMemoryStatusEx` | Carga de CPU (%) por delta de tiempos, RAM física (MiB). | Fallback cuando `psutil` no está presente. No expone frecuencia ni temperatura. |
| **Libre Hardware Monitor** | `http://127.0.0.1:8085/data.json` (loopback) | Temperatura Tctl/Tdie (°C), CPU Package Power (W), carga iGPU (%). | Requiere que LHM se ejecute previamente con privilegios de administrador. Si se cierra, los sensores pasan a `unavailable`. |
| **XMRig** | `http://127.0.0.1:18080` (`GET /2/summary` loopback, `PARAM-05` pendiente) | Hashrate 10s/60s/15m (H/s), shares buenas/totales, `uptime`, estado `paused`. | Debe ser iniciado manualmente por el usuario. **Modo permanentemente pasivo y de solo lectura (`CP-01-A`):** `pause()` y `resume()` se rechazan localmente sin I/O de red. Prohibida la terminación forzada del proceso. **Nota de puerto (`PARAM-05`):** Se mantiene pendiente de definición definitiva entre 18080 y 8080, sin conectarse al servicio real. |
| **SRBMiner-Multi** | `http://127.0.0.1:21550` (HTTP loopback propuesto) | Hashrate, algoritmos activos, shares aceptadas/rechazadas. | *Pendiente de verificación:* Su API debe habilitarse con parámetros de línea de comandos. No se asume el mismo esquema que XMRig. |
| **Kryptex Desktop** | Detección pasiva por PID (`psutil`) | Detección de proceso en ejecución. | *Limitación estricta:* Detectar el binario no prueba hashrate, algoritmo ni saldo. Campos no expuestos se declaran `unavailable`. |
| **Binance Market API** | `https://api.binance.com/api/v3/ticker/24hr` | Precio último, precio ponderado 24h, variación porcentual. | Endpoint público de solo lectura. No garantiza soporte de depósito ni paridad 1:1 entre USD y USDT. |
| **Binance Spot SAPI** | `https://api.binance.com/sapi/v1/capital/deposit/hisrec` | Historial de depósitos confirmados (txId, monto, moneda). | Requiere credenciales de solo lectura. Prohibido otorgar permisos de retiro o trading. |
| **unMineable API** | `https://api.unmineable.com/v4/address/{ADDR}?coin={COIN}` | Saldo no pagado (`balance`), umbral de pago (`payment_threshold`). | Sujeto a límites de peticiones. Si los campos de pago están vacíos, no se emite ninguna petición de red. |
| **Zergpool API** | *Propuesto / No verificado* | Saldo acumulado por wallet. | *Incertidumbre:* No implementar hasta verificar documentalmente contrato, moneda y estructura de URL. |

---

## 7. Fórmulas de consumo eléctrico y rentabilidad

### 7.1. Consumo energético
Para mediciones continuas de potencia del paquete de CPU con intervalo de muestreo $\Delta t$ (en segundos):

$$\text{Energía}_{\text{tramo}} (\text{Wh}) = \frac{P_{t-1} + P_t}{2} \times \frac{\Delta t}{3600}$$

$$\text{Energía Acumulada} (\text{kWh}) = \sum \frac{\text{Energía}_{\text{tramo}} (\text{Wh})}{1000}$$

#### Fallback por TDP (Estimación teórica de ingeniería)
Si el sensor de potencia en vatios (`cpu_package_power_w`) no está disponible pero se configura el TDP de diseño de la CPU ($\text{TDP}_{\text{watts}}$, ej. 65 W para Ryzen 5 5600GT):

$$P_{\text{estimada}} (\text{W}) = \text{TDP}_{\text{watts}} \times \left( \frac{\text{CPU \%}}{100} \right) \times \kappa$$

*Donde $\kappa$ es un factor de corrección empírico (default 1.0).*
- **Regla de integridad:** Toda medición derivada de esta fórmula se registra obligatoriamente con `status = "estimated"` y `source = "calculation:tdp_fallback"`. Jamás se etiqueta como `measured`.

### 7.2. Costo eléctrico
Dado un valor de tarifa eléctrica configurado en dólares por kilovatio-hora ($T_{\text{usd/kWh}}$):

$$\text{Costo Eléctrico} (\text{USD}) = \text{Energía Acumulada} (\text{kWh}) \times T_{\text{usd/kWh}}$$

### 7.3. Rentabilidad y Margen Neto
$$\text{Ingreso Estimado} (\text{USD}) = \text{Saldo Pendiente Pool} (\text{Cripto}) \times \text{Precio Mercado} (\text{USD/Cripto})$$

$$\text{Margen Neto Estimado} (\text{USD}) = \text{Ingreso Estimado} (\text{USD}) - \text{Costo Eléctrico} (\text{USD}) - \text{Comisiones Estimadas} (\text{USD})$$

- Si falta el sensor de potencia o el precio de mercado, el KPI de margen neto reporta explícitamente `status = "unavailable"` con nota de calidad explicativa; nunca se asume cero de costo o ingreso.

---

## 8. Modelo de persistencia

Se conserva **SQLite en modo WAL** como motor primario, garantizando concurrencia óptima entre el orquestador de recolección (escritura) y la API REST / Dashboard (lectura).

### Tablas existentes conservadas
1. `mining_sessions`: Registro de sesiones (`id`, `started_at_utc`, `ended_at_utc`, `session_state`, `data_mode`, `miner_name`, `pool_name`, `stop_reason`).
2. `measurements`: Series temporales de hardware (`cpu_percent_total`, `cpu_temp_c`, `cpu_package_power_w`, `energy_consumed_wh`, etc.).
3. `pool_shares`: Registro de shares (`accepted`, `difficulty`, `reject_reason`, `status`, `source`).
4. `reward_snapshots`: Instantáneas de recompensa (`amount_btc`, `reward_stage`, `status`).
5. `price_snapshots`: Registro de precios de mercado (`asset`, `quote_asset`, `price`, `status`).
6. `payment_events`: Eventos de liquidación (`payout_issued`, `deposit_detected`, `reconciliation`).
7. `periodic_reports`: Reportes analíticos cerrados por ventana temporal de 30 minutos.

### Propuesta aditiva futura (Sin ejecución en la fase actual)
Sin romper la compatibilidad actual ni modificar el esquema de base de datos prematuramente, se mantiene como propuesta documental aditiva para una fase futura aprobada (`0002_payout_and_multicoin.sql`):
- Tabla `payout_progress_snapshots`: Para almacenar el seguimiento histórico de balances de pool (`pool_name`, `coin`, `wallet_address`, `pending_balance`, `payout_threshold`, `progress_pct`, `observed_at_utc`).
- Columna `asset` en `reward_snapshots` (default `'BTC'` para retrocompatibilidad con registros previos).

---

## 9. Contratos comunes, dimensiones ortogonales y gobernanza de control (`CP-01-A` y `CP-02`)

### 9.1. Contrato común `MinerConnector` y separación respecto a `MinerAdapter` (`A-01`, `XMR-01`)
`MinerConnector` ([`src/mineops_dw/domain/miner_connector.py`](file:///c:/Users/rojoh/OneDrive/Desktop/MineOpsDW_Antigravity_Starter/src/mineops_dw/domain/miner_connector.py)) coexiste de forma independiente junto a `MinerAdapter` ([`SimulatedMinerPoolAdapter`](file:///c:/Users/rojoh/OneDrive/Desktop/MineOpsDW_Antigravity_Starter/src/mineops_dw/adapters/mining.py)) sin alterar el simulador determinista ni el esquema SQLite actual:

```python
class MinerConnector(Protocol):
    def get_snapshot(self) -> MinerSnapshot: ...
    def get_capabilities(self) -> MinerCapabilities: ...
    def pause(self) -> CommandResult: ...
    def resume(self) -> CommandResult: ...
```

- **Exclusiones estrictas (`A-01`):** `MinerConnector` **no** incluye `start()`, `stop()` ni terminación forzada de procesos (`taskkill` / `kill`).
- **Modelos de contrato:**
  - `MinerSnapshot`: Instantánea inmutable con dimensiones separadas de conexión, estado operativo, confianza, avance de proceso y observaciones individuales (`MetricObservation`) con calidad y frescura propias.
  - `MinerCapabilities`: Separa `ConnectionStatus`, `LocalClientReadiness`, evidencia en caché de sesión y `ServerCapabilityEvidence` (`CONFIRMED_AVAILABLE`, `CONFIRMED_UNAVAILABLE`, `UNVERIFIED_PASSIVELY`) para `observe`, `state_verification`, `pause` y `resume`, más el estado agregado `status` (`AVAILABLE`, `READ_ONLY`, `UNAVAILABLE`).
  - `CommandResult` (`R-02`): Resultado estructurado e inmutable con `delivery` (`NOT_SENT`, `RESPONSE_RECEIVED`, `UNKNOWN`), `acceptance` (`ACCEPTED`, `REJECTED`, `UNKNOWN`), `postcondition` (`VERIFIED`, `FAILED`, `NOT_ATTEMPTED`, `UNKNOWN`), `pre_snapshot`, `post_snapshot`, `authorization_generation` (`int >= 0`), `revoked_during_execution` (`bool`) y `causal_attribution` (`UNDETERMINED`, `NOT_APPLICABLE`). `postcondition = VERIFIED` confirma la observación del estado destino, nunca causalidad exclusiva.

### 9.2. Separación ortogonal de dimensiones de estado (`A-06`)
1. **`ControlAuthorizationState`:** `NOT_GRANTED` | `GRANTED` | `REVOKED` (efímero en memoria por sesión; inicia en `NOT_GRANTED` con `authorization_generation = 0`).
2. **`ConnectionStatus`:** `REACHABLE` | `UNREACHABLE` | `DEGRADED`.
3. **`MinerOperationalState`:** `RUNNING` | `PAUSED` | `STOPPED` | `STARTING` | `STOPPING` | `UNKNOWN` (no incluye `DEGRADED`; un fallo de red produce `UNKNOWN`, jamás `STOPPED` por inferencia).
4. **`StateConfidence`:** `CONFIRMED` | `INFERRED` | `UNKNOWN` (`XMRigApiAdapter` solo emite `CONFIRMED` o `UNKNOWN`).
5. **`ProcessProgressState` (`process_progress`):** `ADVANCING` | `UNCHANGED_WITHIN_RESOLUTION` | `STALLED_SUSPECTED` | `UNKNOWN`.
6. **`SupervisorMode`:**
   - `PASSIVE_IDLE`: Minero detenido o ausente sin supervisión activa.
   - `OBSERVING_UNCONTROLLED`: Minero activo sin autorización de control (`NOT_GRANTED` o `REVOKED`) y sin alerta térmica crítica.
   - `ACTIVE_SUPERVISION`: Supervisión activa con `ControlAuthorization == GRANTED`.
   - `DEGRADED_WAIT`: Espera degradada bajo `GRANTED` (incluyendo razón explícita `UNCERTAIN_PAUSE_STILL_RUNNING_CRITICAL_THERMAL`).
   - `THERMAL_ALERT_UNCONTROLLED`: Alerta térmica crítica cuando el minero corre bajo `NOT_GRANTED` o `REVOKED` (tiene precedencia sobre `DEGRADED_WAIT` y se registra por flanco de transición).
   - `EXTERNAL_OVERRIDE_CONFLICT`: Conflicto por cambio de estado externo contrario a la postura supervisada (`R-05`).
7. **`DataOrigin`:** `REAL` | `SIMULATED` | `UNKNOWN`.
8. **`TelemetryQuality` (por métrica) y `SourceFreshness`:** `VALID` | `STALE` | `UNAVAILABLE` | `INVALID` | `SUSPECT`, junto con `VERIFIED_FRESH` | `VERIFIED_STALE` | `UNVERIFIABLE_NO_SOURCE_TIMESTAMP`.

### 9.3. Reglas de `ControlAuthorization`, concurrencia y precondiciones (`A-02..A-05`, `R-01..R-05`)
- **Pausa térmica vs. reanudación (`A-02..A-05`):** Solo `pause()` puede dispararse automáticamente por emergencia térmica cuando `ControlAuthorization == GRANTED`. **No existe inicio ni reanudación automática**; `resume()` requiere siempre acción manual explícita del usuario.
- **Logical Dispatch Commit (`R-01`):** Frontera atómica en memoria entre el compromiso de envío de un comando y la revocación de `ControlAuthorization`, sin bloquear la interfaz en I/O de red, sin comandos compensatorios al revocar y sin reintentos automáticos de comandos con resultado incierto (`UNKNOWN`).
- **7 Precondiciones obligatorias de `R-03` para conceder `ControlAuthorization = GRANTED`:**
  1. Acción manual explícita del usuario en la sesión actual.
  2. Ausencia de comandos en vuelo o con resultado incierto no reconciliado (`XMR-05-A`).
  3. `get_snapshot()` reciente con `ConnectionStatus == REACHABLE` y `DataOrigin` consistente con la sesión.
  4. `MinerOperationalState in {RUNNING, PAUSED}` con `StateConfidence == CONFIRMED` y `operational_state_quality == VALID` (`STOPPED`, `STARTING`, `STOPPING` y `UNKNOWN` bloquean).
  5. `get_capabilities().status == AVAILABLE`.
  6. `TelemetryQuality == VALID` en cada métrica térmica obligatoria (métricas secundarias pueden degradarse individualmente sin bloquear).
  7. `process_progress in {ADVANCING, UNCHANGED_WITHIN_RESOLUTION}` (`STALLED_SUSPECTED` y `UNKNOWN` bloquean sin corromper la calidad individual de las métricas).

### 9.4. Decisiones aprobadas para `XMRigApiAdapter` (`CP-01-A` y `CP-02` Opción B ajustada)
- **`CP-01-A` (XMRig permanentemente pasivo y de solo lectura):**
  - `XMRigApiAdapter` implementa exclusivamente capacidades de observación pasiva verificadas con mocks (`httpx.MockTransport`).
  - `pause` y `resume` permanecen siempre en `UNVERIFIED_PASSIVELY`; el campo `restricted` del JSON no se interpreta como prueba suficiente de disponibilidad o indisponibilidad de control.
  - Cuando la observación de `GET /2/summary` es válida, `MinerCapabilities.status == READ_ONLY` (y `UNAVAILABLE` cuando falla).
  - En consecuencia, XMRig no satisface la precondición 5 de `R-03` y **nunca puede obtener `ControlAuthorization = GRANTED`**.
  - `pause()` y `resume()` permanecen en el contrato común pero en `XMRigApiAdapter` se rechazan localmente sin realizar I/O HTTP ni JSON-RPC, devolviendo `delivery="NOT_SENT"`, `acceptance="UNKNOWN"` y `postcondition="NOT_ATTEMPTED"`.
- **`CP-02` (Opción B ajustada — Reconocimiento estructural conservador):**
  - Se utiliza únicamente `GET /2/summary`.
  - Se valida estructuralmente en la raíz del JSON: `version` (`str` no vacío tras `strip()`), `kind == "miner"` y `paused` (`bool` estricto: `type(paused) is bool`).
  - `uptime` **no** es obligatorio para reconocer el estado operativo (`RUNNING` o `PAUSED`); si `uptime` falta, es inválido o solo hay una muestra inicial, `process_progress = UNKNOWN` sin invalidar el estado operativo reconocido.
  - La ausencia o invalidez de `hashrate` o `results` afecta únicamente la `TelemetryQuality` de sus métricas individuales y jamás invalida el estado operativo ni se usa para inferir actividad.
  - Esquemas desconocidos, incompatibles o inválidos se rechazan conservadoramente (`operational_state = UNKNOWN`, `operational_state_quality = INVALID`).

### 9.5. Parámetros operativos aprobados (`PARAM-01` a `PARAM-06`)
Los siguientes parámetros han sido aprobados por el usuario y configurados por defecto en [`AppSettings`](file:///c:/Users/rojoh/OneDrive/Desktop/MineOpsDW_Antigravity_Starter/src/mineops_dw/config.py) y [`ThermalSupervisor`](file:///c:/Users/rojoh/OneDrive/Desktop/MineOpsDW_Antigravity_Starter/src/mineops_dw/domain/thermal_supervisor.py) (preservando `max_cpu_temp_c = 80.0 °C` por retrocompatibilidad con Fases 1–12):
- `PARAM-01` (`thermal_critical_temp_c`): **`75.0 °C`** (temperatura crítica de alerta/disparo térmico por defecto).
- `PARAM-02` (`thermal_recovery_temp_c`): **`60.0 °C`** (temperatura de recuperación térmica por defecto).
- `PARAM-03` (`thermal_stability_window_seconds`): **`120` segundos** continuos $\le 60.0\ ^\circ\text{C}$.
- `PARAM-04` (`thermal_max_staleness_seconds`): **`30` segundos** de antigüedad máxima permitida de telemetría térmica.
- `PARAM-05` (`xmrig_api_url`): **`http://127.0.0.1:18080`** (URL loopback y puerto por defecto para `XMRigApiAdapter`).
- `PARAM-06` (`payout_coin`, `payout_address`, `payout_network`): **Vacíos por defecto (`""`)**, inhibiendo consultas de red a pools mientras `is_payout_configured` sea `False`.

---

## 10. Configuración del retiro (Payout)

En `AppSettings` ([`src/mineops_dw/config.py`](file:///c:/Users/rojoh/OneDrive/Desktop/MineOpsDW_Antigravity_Starter/src/mineops_dw/config.py)), los parámetros de liquidación se mantendrán **sin configurar por defecto**:
- `payout_coin: str = ""`
- `payout_address: str = ""`
- `payout_network: str = ""`

### Reglas de negocio:
- El sistema permanecerá en estado `unconfigured` hasta que el usuario defina explícitamente estos tres valores.
- Mientras estén vacíos, `pool_balance_collector` inhibe cualquier petición de red y reporta `status="unavailable"`, evitando llamadas a URLs malformadas.
- En el dashboard, la tarjeta de retiro indicará: *"Configuración de pago: Pendiente de definición por el usuario"*.

---

## 11. Diferencias entre simulación, medición real y estimación

| Dimensión | Medición Real (`measured`) | Estimación (`estimated`) | Simulación (`simulated`) | No Disponible (`unavailable`) |
| :--- | :--- | :--- | :--- | :--- |
| **Definición** | Dato obtenido directamente de un sensor físico o API externa conectada. | Valor derivado de fórmulas matemáticas o extrapolaciones teóricas. | Dato sintético generado deterministamente para pruebas de software. | Métrica esperada cuyo sensor o fuente está apagado, ausente o fuera de rango. |
| **Valor (`value`)** | Numérico observado. | Numérico calculado. | Numérico sintético. | Estrictamente `None` (nunca 0.0). |
| **Ejemplos** | `cpu_percent_total` vía GetSystemTimes; `hashrate_hs` reportado por XMRig. | `energy_consumed_wh` por integración; potencia inferida por TDP; margen neto. | `sim_session_live_001`; shares generadas por `SimulatedMinerPoolAdapter`. | `cpu_temp_c` con LHM cerrado; saldo con pool fuera de línea o sin configurar. |
| **Visualización** | Badge verde neón (`badge-measured`). | Badge azul eléctrico (`badge-estimated`). | Badge ámbar (`badge-simulated`) persistente. | Badge gris tenue (`badge-unavailable`), texto "N/D". |

---

## 12. Plan de migración incremental

El proyecto se refactorizará en 12 fases atómicas, verificables e incrementales:

1. **Fase 1 — Documentación y contratos:** Creación y actualización de `PROJECT_SPEC.md`, `AGENT.md`, `SKILLS.md` y alineación con las decisiones del usuario.
2. **Fase 2 — Configuración ampliada:** Extensión segura de `AppSettings` en `config.py` con parámetros de pago vacíos por defecto y umbrales térmicos propuestos, sin tocar `.env`.
3. **Fase 3 — Dominio y Contrato Común `MinerConnector`:** Modelos inmutables `MinerStatus`, `MinerConnector`, `ThermalWatchdogPolicy` (con `OBSERVING_UNCONTROLLED`), `PayoutProgress` y `ProfitabilityKpi`.
4. **Fase 4 — Colector de CPU y fallback TDP:** Modularización de `cpu_collector.py` preservando los adaptadores probados de `sensors.py` e invariante de calidad `estimated`.
5. **Fase 5 — Integración de XMRig mediante Mocks:** Adaptación de `XMRigApiAdapter` al contrato común `MinerConnector`, priorizado y probado **exclusivamente con mocks** en memoria.
6. **Fase 6 — Cliente público de Binance:** `binance_client.py` para consulta de precios de mercado (ticker 24h) sin claves privadas.
7. **Fase 7 — Seguimiento de balance en pool:** `pool_balance.py` con integración unMineable, respetando la inhibición cuando los datos de retiro están vacíos.
8. **Fase 8 — Cálculo de energía y rentabilidad:** Servicio `kpi_calculator.py` para métricas eléctricas y márgenes netos (reporta `unavailable` ante entradas ausentes).
9. **Fase 9 — Persistencia y repositorios:** Extensión aditiva de repositorios SQLite para balances de pool sin alterar tablas existentes ni ejecutar migraciones prematuras.
10. **Fase 10 — Orquestador desacoplado:** `main_collector.py` coordinando tareas con frecuencias independientes y parada limpia con `threading.Event`.
11. **Fase 11 — Integración API y Dashboard:** Exposición de endpoints del supervisor y visualización del estado `OBSERVING_UNCONTROLLED` y progreso de pago.
12. **Fase 12 — Pruebas integradas de regresión:** Verificación automatizada con mocks de extremo a extremo y congelación de release (100% de tests previos aprobados).

---

## 13. Criterios de aceptación y definición de hecho (DoD)

Una fase se considerará completada únicamente cuando:
1. Se ejecuten todas las pruebas automatizadas pertinentes y los comandos y resultados figuren en el informe.
2. Ninguna prueba de fases previas (Fases 1–13) presente regresiones o fallos.
3. No se hayan modificado esquemas de base de datos ni archivos `.env` sin autorización previa.
4. Ningún dato simulado se reporte como real o estimado, y ningún saldo de pool se identifique como depósito en Binance.
5. El código cumpla con los estándares de estilo (`ruff check` / `mypy` estricto), sin tipos `Any` no controlados ni variables de entorno sin validar.
6. La documentación técnica refleje con exactitud los cambios implementados y el `git diff` se mantenga limpio y libre de secretos.
