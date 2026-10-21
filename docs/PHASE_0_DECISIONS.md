# Fase 0 — Decisiones iniciales acordadas y validación técnica

Estado: **Fase 0 completada en análisis y diseño; pendiente de aprobación del usuario para iniciar Fase 1**. Esto no autoriza a implementar la aplicación sin confirmación explícita.

## 1. Inventario del entorno comprobado (Tarea A)

Comprobación no intrusiva realizada el `2026-10-21` sobre el equipo objetivo:

- **Sistema Operativo:** Microsoft Windows 11 Home (`10.0.26200`, Build `26200`, 64 bits).
- **Procesador:** AMD Ryzen 5 5600GT with Radeon Graphics (`6` núcleos físicos, `12` hilos lógicos, frecuencia base reportada `3600 MHz`).
- **Memoria RAM física:** `16,424,570,880` bytes (~`15.30 GiB` / `16.42 GB` nominales).
- **Gráficos integrados:** AMD Radeon(TM) Graphics (Driver `31.0.21924.61`).
- **Repositorio Git:** No inicializado (`.git` no existe actualmente en el directorio del workspace).
- **Python disponible:**
  - `python` por defecto en `PATH`: **Python 3.13.14** (AMD64) con `pip 26.2.1` y `sqlite3` integrado (motor SQLite `3.50.4`).
  - `py -0p` (Python Launcher): detecta Python `3.14` (64-bit) y Python `3.13` (64-bit). Cumple la regla `>=3.12`.
- **Paquetes Python ya presentes en el entorno `3.13`:** `pydantic 2.13.4`, `httpx 0.28.1`, `pytest 9.1.1`, `pytest-asyncio 1.4.0`, `python-dotenv 1.2.2`, `tenacity 9.1.4`, `websockets 16.1.1`, `requests 2.34.2`.
- **Herramientas y paquetes ausentes (pendientes para Fase 1+):**
  - `psutil`: **No instalado** (`ModuleNotFoundError: No module named 'psutil'`).
  - `ruff`: **No instalado** en el entorno actual.
  - `fastapi` / `uvicorn`: **No instalados** todavía.
  - `node` / `npm`: **No instalados** o no presentes en `PATH` (`CommandNotFoundException`).
  - `sqlite3.exe` (CLI standalone): No está en `PATH`, pero el módulo estándar `sqlite3` de Python (`3.50.4`) está operativo.
  - `Libre Hardware Monitor (LHM)`: **No instalado ni en ejecución** (no existe el namespace WMI `root\LibreHardwareMonitor` ni procesos activos).

### Dependencias recomendadas y versiones compatibles (para instalar en fases posteriores con autorización)
- **Backend Python (`>=3.12`, probado en `3.13.14`):**
  - `psutil>=6.0,<8.0` (telemetría base CPU, RAM y procesos).
  - `fastapi>=0.115,<1.0` y `uvicorn[standard]>=0.30,<1.0` (API REST local y documentación OpenAPI automática).
  - `pydantic>=2.10,<3.0` y `pydantic-settings>=2.6,<3.0` (validación de esquemas y configuración tipada desde `.env`).
  - `httpx>=0.27,<1.0` y `tenacity>=9.0,<10.0` (clientes HTTP con timeouts y reintentos con backoff acotado).
  - Desarrollo y calidad: `pytest>=8.0` (disponible `9.1.1`), `ruff>=0.6`.
- **Frontend Web (Fase 7):**
  - **Node.js LTS** (`v22.x LTS` recomendado, o `>=20.11 LTS`) con `npm >=10.x`.
  - `react@^18.3` o `^19.0`, `react-dom`, `typescript@^5.6`, `vite@^6.0`, `vitest` (pruebas unitarias UI).

---

## 2. Decisiones arquitectónicas y evaluación (Tarea B)

1. **Frontend:** React + TypeScript (SPA local servida en desarrollo por Vite y en producción estática o vía loopback).
2. **Sensores Windows:** `psutil` para CPU, RAM y procesos; Libre Hardware Monitor (LHM) como adaptador opcional desacoplado.
3. **Minería:** comenzar en modo simulado determinista. No instalar, configurar ni ejecutar mineros reales en Fase 0 ni sin autorización expresa.
4. **Pool/Binance:** sin decisión cerrada de proveedor. Separar adaptador de Pool (`PoolAdapter`) y adaptador de Binance (`ExchangeReadOnlyAdapter`).
5. **Almacenamiento MVP:** SQLite local (`sqlite3` estándar de Python con modo WAL e integridad referencial).
6. **API local:** servicio Python con API REST ligada exclusivamente a `127.0.0.1` por defecto.
7. **Reportes:** intervalo objetivo de 30 minutos, configurable, basado en ventanas UTC cerradas.
8. **Finanzas:** recompensas estimadas (`estimated`), saldo informado por pool (`pool_reported`), pago emitido (`payout_issued`) y depósito detectado en Binance (`confirmed` / `deposit_detected`) son estados y registros estrictamente separados.
9. **Android:** ampliación opcional posterior al MVP de PC (Fase 11).
10. **Seguridad:** cualquier integración con Binance comienza con permisos de solo lectura (`Enable Reading`); prohibido trading, retiros o transferencias automáticas.

### Ventajas y límites de las decisiones

#### React + TypeScript
- **Ventajas:**
  - Componentes reutilizables para paneles de recursos, estado de sesión, tablas de conciliación e historial.
  - Tipado estático que permite reflejar exactamente los contratos OpenAPI del backend (incluyendo `status: 'measured' | 'estimated' | 'unavailable' | 'simulated'` y `value: number | null`), evitando tratar `null` como `0` en la UI.
  - Ecosistema maduro de pruebas de componentes y diseño responsive.
- **Limitaciones y riesgos:**
  - Requiere instalar **Node.js LTS y npm**, que actualmente no están presentes en el sistema (bloqueante para la Fase 7, pero no bloquea Fases 1 a 5 de backend).
  - Mayor complejidad de build frente a plantillas server-side (Jinja2/HTMX).
  - El navegador nunca debe conectarse directamente a SQLite ni almacenar claves API de Binance.

#### Libre Hardware Monitor (LHM) + `psutil`
- **Ventajas:**
  - `psutil` ofrece métricas multiplataforma fiables de uso de CPU, memoria RAM, swap y procesos sin requerir drivers de kernel adicionales.
  - LHM permite exponer en Windows sensores de temperatura de paquete/encapsulado (`Tctl/Tdie` en Ryzen), potencia del paquete (`CPU Package Power` en W), voltajes y sensores de la iGPU Radeon mediante su servidor web local (`http://127.0.0.1:8085/data.json`) o WMI (`root\LibreHardwareMonitor`).
  - El diseño por adaptadores permite que el sistema funcione aunque LHM no esté instalado o esté cerrado.
- **Limitaciones y riesgos:**
  - En Windows, `psutil` **no expone temperaturas de CPU/GPU ni consumo en vatios (W)** (no implementa `sensors_temperatures()` en Windows).
  - La clase WMI estándar `MSAcpi_ThermalZoneTemperature` devolvió `0` instancias en este equipo sin elevación o soporte ACPI específico.
  - LHM requiere permisos de administrador en Windows para cargar su driver de lectura de sensores de bajo nivel (SMBus/MSR) y mostrar potencia/temperatura de Ryzen 5 5600GT.
  - Nunca se debe deducir temperatura ni vatios a partir del porcentaje de uso de CPU. Si LHM no está activo, esas métricas se registran como `value=null` y `status=unavailable`.

#### Minería simulada primero
- **Ventajas:**
  - Permite validar de extremo a extremo la base de datos, el scheduler, la API REST, los reportes de 30 minutos y el dashboard sin someter el Ryzen 5 5600GT a estrés térmico ni consumo eléctrico innecesario.
  - Permite reproducir escenarios deterministas (rechazo de shares, caída de pool, desfase entre pago emitido y depósito).
- **Limitaciones:**
  - No mide hashrate real ni latencia de red real hacia un servidor Stratum.
  - Obliga a etiquetar visiblemente toda sesión y métrica simulada (`status=simulated`) para impedir confusiones con saldos reales.

---

## 3. Matriz de sensores de Windows (Tarea C)

| Métrica (`metric_name`) | Unidad (`unit`) | Fuente prevista (`source`) | Disponibilidad comprobada en Fase 0 | Frecuencia sugerida | Limitaciones técnicas | Comportamiento si no está disponible |
|---|---|---|---|---|---|---|
| `cpu_percent_total` | `%` | `psutil.cpu_percent` (respaldo nativo: `Win32_PerfFormattedData_Counters_ProcessorInformation`) | **Verificada vía WMI nativo** (`1%` observado); **Pendiente en Python** hasta instalar `psutil` en Fase 1 | `10 s` (configurable `5-60 s`) | La primera llamada sin intervalo en `psutil` devuelve `0.0` si no se inicializa previamente. | `value=null`, `status=unavailable`, `quality_note="psutil no disponible o lectura fallida"` |
| `cpu_percent_per_core` | `%` | `psutil.cpu_percent(percpu=True)` (`12` hilos lógicos verificados) | **Hardware verificado** (`6C/12T`); librería `psutil` pendiente de instalar | `10 s` | Representa carga de planificación del SO, no eficiencia de hashrate. | `value=null`, `status=unavailable`, `quality_note="Métrica por hilo no disponible"` |
| `cpu_freq_mhz` | `MHz` | `psutil.cpu_freq()` / WMI `ProcessorFrequency` | **Verificada vía WMI** (`3600 MHz`); pendiente en `psutil` | `10 s` | En Windows `psutil.cpu_freq()` suele reportar frecuencia nominal/actual agregada, no boost instantáneo por núcleo sin LHM. | `value=null`, `status=unavailable`, `quality_note="Frecuencia de CPU no reportada"` |
| `ram_usage_percent` | `%` | `psutil.virtual_memory().percent` | **Hardware verificado** (`16,424,570,880 B`); pendiente instalar `psutil` | `10 s` | Incluye memoria reservada por el sistema y caché mapeada. | `value=null`, `status=unavailable`, `quality_note="Lectura de memoria fallida"` |
| `ram_used_mib` / `ram_available_mib` | `MiB` | `psutil.virtual_memory()` / WMI `Win32_OperatingSystem` | **Verificada en SO**; pendiente instalar `psutil` | `10 s` | La iGPU Radeon reserva parte de la RAM física como memoria de vídeo compartida/UMA. | `value=null`, `status=unavailable`, `quality_note="Lectura de RAM en MiB no disponible"` |
| `miner_process_cpu_percent` / `miner_process_rss_mib` | `%` / `MiB` | `psutil.Process(pid)` | **Pendiente** (sin proceso minero activo en Fase 0 y sin `psutil` instalado) | `10 s` (cuando haya sesión activa) | Puede lanzar `NoSuchProcess` o `AccessDenied` si el proceso termina o corre con otro usuario. | `value=null`, `status=unavailable` (o `simulated` en modo simulado), `quality_note="Proceso minero no activo o inaccesible"` |
| `gpu_util_percent` (Radeon iGPU) | `%` | Windows PerfCounters (`GPUEngine`) o `LHM` (`GPU Core` load) | **Verificada existencia de contadores `GPUEngine`** para `AMD Radeon(TM) Graphics`; LHM no instalado | `10 s` | Los contadores `GPUEngine` de Windows separan motores (`3D`, `Compute 0`, `Copy`); agregar porcentajes directamente sin normalizar puede superar `100%`. | `value=null`, `status=unavailable`, `quality_note="Sensor de carga iGPU no disponible o LHM desconectado"` |
| `gpu_temp_c` (Radeon iGPU) | `°C` | `LHM` (`http://127.0.0.1:8085/data.json` o WMI `root\LibreHardwareMonitor`) | **No disponible actualmente** (LHM no instalado) | `10 s` | Requiere LHM en ejecución con permisos adecuados; no disponible en `psutil`. | `value=null`, `status=unavailable`, `quality_note="Sensor térmico GPU no expuesto (LHM ausente)"` |
| `cpu_temp_c` (Ryzen `Tctl/Tdie`) | `°C` | `LHM` (`CPU (Tctl/Tdie)`) | **No disponible actualmente** (`MSAcpi_ThermalZoneTemperature` devolvió `0` sensores; LHM no instalado) | `5-10 s` | Windows no expone la temperatura del diodo AMD Ryzen por WMI estándar sin un driver como el de LHM. | `value=null`, `status=unavailable`, `quality_note="Sensor térmico CPU no expuesto; LHM no activo"` |
| `cpu_package_power_w` | `W` | `LHM` (`CPU Package` / `Package Power`) | **No disponible actualmente** (LHM no instalado) | `10 s` | Lectura proveniente de registros RAPL/SMU de AMD vía LHM; no mide consumo en el enchufe de pared (fuente de alimentación + placa). | `value=null`, `status=unavailable`, `quality_note="Sensor de potencia en W no disponible"` |
| `energy_consumed_wh` | `Wh` | Cálculo de dominio por integración trapezoidal de `cpu_package_power_w` en el tiempo (`Calculation`) | **Pendiente** (depende de disponer de `cpu_package_power_w` medido o simulado) | Cada muestra (`10 s`) y consolidado cada `30 min` | Si `cpu_package_power_w` es `unavailable`, **no se puede calcular energía real**. Si se calcula sobre potencia medida, se etiqueta `estimated` (por ser integración numérica de potencia de paquete, no medidor de enchufe). | `value=null`, `status=unavailable`, `quality_note="Imposible estimar Wh sin sensor de potencia (W)"` |

### Procedimiento propuesto para verificar Libre Hardware Monitor (pendiente de autorización del usuario)
1. **No instalar automáticamente.** Cuando el usuario lo autorice (en Fase 3 o antes), descargar la versión oficial de Libre Hardware Monitor desde su repositorio oficial en GitHub (`LibreHardwareMonitor/LibreHardwareMonitor`).
2. Ejecutar `LibreHardwareMonitor.exe` con permisos de administrador (necesario para leer sensores SMU de AMD Ryzen 5 5600GT) y activar **Options -> Remote Web Server -> Run** ligado solo a loopback (`127.0.0.1`, puerto `8085`) o consultar el namespace WMI `root\LibreHardwareMonitor` (`SELECT Name, SensorType, Value, Identifier FROM Sensor`).
3. Mapear los identificadores exactos de los sensores (`Identifier`, p. ej. `/amdcpu/0/temperature/2`, `/amdcpu/0/power/0`, `/gpu-amd/0/load/0`) en la configuración del adaptador `LhmSensorAdapter`.
4. Si LHM se cierra o el usuario decide no usarlo con permisos elevados, el colector degradará limpiamente esas métricas a `value=null, status="unavailable"`.

---

## 4. Escenarios de minería simulada y diferenciación de datos (Tarea D)

En la Fase 5 se implementará el simulador determinista (`SimulatedMinerPoolAdapter`) sin ejecutar ningún binario real. Los escenarios obligatorios de prueba son:

1. **Ciclo de vida de sesión (`MiningSession`):**
   - `session_started`: inicio limpio con configuración de límites (`max_cpu_percent`, `max_cpu_temp_c`, `max_session_minutes`), `status="simulated"`, `session_state="running"`.
   - `session_paused`: pausa manual o preventiva ante umbral de recursos, deteniendo generación de shares simuladas sin cerrar la sesión (`session_state="paused"`).
   - `session_stopped`: parada normal por el usuario o por alcanzar `max_session_minutes` (`30 min`), registrando `ended_at_utc` (`session_state="stopped"`).
   - `session_failed`: fallo simulado (p. ej. caída abrupta del proceso minero o superación crítica de temperatura simulada `> 80 °C`), pasando a `session_state="error"` con nota de diagnóstico.
2. **Conectividad con el Pool:**
   - `pool_connected`: latencia simulada nominal (`45 ms`) y recepción de trabajos Stratum ficticios.
   - `pool_disconnected`: pérdida de conexión simulada durante $N$ segundos; el servicio registra el evento, aplica reintento con backoff y no genera shares aceptadas mientras está desconectado.
3. **Envío de Shares (`PoolShare`):**
   - `share_accepted`: generación determinista por semilla (`seed`) de shares válidas con dificultad simulada, `accepted=true`, `status="simulated"`.
   - `share_rejected`: simulación de shares rechazadas (`stale` / `duplicate` / `low difficulty`), `accepted=false`, `reject_reason` explícito, verificando que no incrementan la recompensa estimada.
4. **Flujo financiero y conciliación desacoplada (4 estados independientes):**
   - **Estado 1 — Recompensa estimada (`RewardSnapshot` con `stage="estimated"`):** cálculo teórico local a partir de las shares aceptadas simuladas. Nunca se muestra como saldo en cuenta.
   - **Estado 2 — Saldo informado por el pool (`RewardSnapshot` con `stage="pool_reported"`):** instantánea periódica simulando el saldo pendiente acumulado en el pool antes de alcanzar el umbral de retiro.
   - **Estado 3 — Pago emitido por el pool (`PaymentEvent` con `event_type="payout_issued"`):** evento que simula que el pool alcanzó el mínimo y emitió una transacción (con `external_reference` / `txid` ficticio identificable como `SIM-TX-...` y `status="pending"` o `"confirmed"` en el pool).
   - **Estado 4 — Depósito detectado en Binance (`PaymentEvent` con `event_type="deposit_detected"`):** evento independiente leído desde el `SimulatedExchangeAdapter` (con retardo simulado o diferencia por comisión de red). Permite probar tanto la conciliación exitosa como el caso de **pago emitido por el pool pero aún no reflejado en Binance**.

### Reglas estrictas de diferenciación entre datos simulados y reales
- Toda fila en SQLite y todo payload JSON incluirá `status="simulated"` (o `is_simulated=true` en `MiningSession`) y `source="simulator:<scenario_name>"`.
- Los identificadores externos simulados llevarán el prefijo obligatorio `sim_` o `SIM-` (ej. `sim_session_001`, `SIM-TX-0001`).
- Los reportes de 30 minutos y las consultas agregadas del Data Warehouse filtrarán por defecto o agruparán por separado `status="simulated"` de `status IN ('measured', 'estimated')`, prohibiendo sumar recompensas simuladas con recompensas reales.
- El Dashboard mostrará un distintivo visual permanente (`MODO SIMULADO`) cuando la fuente activa sea el simulador.

---

## 5. Investigación y comparativa de Pool y Binance (Tarea E)

Investigación realizada con documentación oficial vigente a fecha `2026-10-21`.

> [!WARNING]
> **Hallazgo crítico sobre Binance Pool (Verificado en anuncios oficiales de Binance):**
> Binance ha anunciado oficialmente la **descontinuación de Binance Pool** (junto con Pool Savings, Cloud Mining y los endpoints de API de minería) programada para el **10 de noviembre de 2026 a las 07:00 UTC**, cerrando definitivamente el acceso histórico el **24 de noviembre de 2026**. Por tanto, **no se recomienda acoplar el proyecto a Binance Pool como pool de minería**, aunque **Binance (Exchange Spot)** sigue siendo totalmente viable para recibir depósitos y consultarlos mediante la API de solo lectura (`GET /sapi/v1/capital/deposit/hisrec`).

> [!IMPORTANT]
> **Realidad técnica del hardware (`Ryzen 5 5600GT` + `Radeon iGPU`):**
> Los pools de Bitcoin puros (`SHA-256`, como Braiins Pool, ViaBTC o F2Pool) están diseñados para equipos **ASIC** (que operan en decenas o cientos de `TH/s`). Una CPU moderna en `SHA-256` produce apenas unos pocos `MH/s` (millones de veces menos), por lo que un pool `SHA-256` para ASIC descartará la conexión por baja dificultad o jamás alcanzará el umbral mínimo de pago (`0.0002` a `0.005 BTC`).
> Si en la Fase 6 el usuario desea realizar una prueba experimental real con su CPU recibiendo pagos en BTC, existen plataformas que permiten minar algoritmos aptos para CPU (como `RandomX`) y liquidar en `BTC` (p. ej. NiceHash o unMineable), o bien usar un minero CPU en un pool de pruebas/testnet. Esta elección queda **estrictamente en manos del usuario**.

### Tabla comparativa de opciones verificadas

| Proveedor / Rol | Hardware y Algoritmo requerido | Compatibilidad con objetivo experimental (Ryzen 5 5600GT) | Requisitos de registro | Mínimos de pago y comisiones | Frecuencia y método de liquidación | API disponible | Verificación de depósitos en Binance | Restricciones o aspectos pendientes de confirmar |
|---|---|---|---|---|---|---|---|---|
| **Binance Exchange (Solo Recepción / Conciliación)** | N/A (Exchange receptor de depósitos en `BTC` On-Chain o `Lightning Network`) | **Alta** para la Fase 10 (conciliación de depósitos en solo lectura). | Cuenta en Binance con verificación KYC activa y creación de API Key con permiso único `Enable Reading`. | Sin comisión por depósito en Binance; el mínimo de depósito en Lightning Network se muestra dinámicamente al generar el invoice. | Acreditación tras confirmaciones de bloques (BTC On-Chain) o instantánea vía factura `BOLT11` (Lightning). | **Verificada:** `GET /sapi/v1/capital/deposit/hisrec` (`USER_DATA`, firma HMAC-SHA256, permiso **Read-Only**). | **Sí (Nativa)** para depósitos On-Chain (`txId`, `amount`, `status`). *Pendiente confirmar si los depósitos vía Lightning aparecen en `/capital/deposit/hisrec` en la región del usuario.* | Disponibilidad sujeta a jurisdicción/región del usuario. No requiere permisos de trading ni retiro. |
| **Binance Pool** *(Pool de minería)* | ASIC (`SHA-256`) | **No viable / Desaconsejado** (requiere ASIC y el servicio cierra en nov. 2026). | Cuenta Binance y Mining Account. | Liquidación diaria en Funding Wallet; comisión histórica FPPS ~`4%`. | FPPS diario (02:00–10:00 UTC) directo a Funding Wallet. | `GET /sapi/v1/mining/payment/list` (programada para apagarse el `2026-11-10`). | Pago interno a Funding Wallet (no pasa por `/capital/deposit/hisrec` sino por `/mining/payment/list`). | **Servicio en cierre oficial el 10/11/2026.** Descartar como pool objetivo salvo para lectura histórica si el usuario ya tuviera datos previos. |
| **Braiins Pool** *(Pool BTC tradicional)* | ASIC (`SHA-256`) | **Baja en CPU** (la dificultad mínima de Stratum para ASIC impide generar shares útiles con un Ryzen 5 5600GT). | Cuenta web en Braiins Pool y configuración de dirección BTC o Lightning. | **Comisión:** `2.5%` FPPS (`0%` con Braiins OS). **Mínimo On-Chain:** `0.0002 BTC` (con fee `0.0001 BTC` si es `< 0.005 BTC`; gratis `>= 0.005 BTC`). **Lightning:** desde `1 sat` gratis (máx. `0.005 BTC`). | FPPS; liquidación diaria al superar el umbral configurado. | **Verificada:** JSON API de solo lectura autenticada por cabecera `Pool-Auth-Token` (límite ~1 req / 5 s). | **Sí** si se retira On-Chain a la dirección de depósito BTC de Binance (los retiros Lightning automáticos requieren LNURL/dirección compatible; Binance usa invoices por monto). | Sin un ASIC, una CPU no alcanzará el mínimo On-Chain y probablemente no supere el filtro de dificultad de share. |
| **ViaBTC** *(Pool BTC tradicional)* | ASIC (`SHA-256`) | **Baja en CPU** (orientado a ASIC). | Cuenta en ViaBTC; API Key + Secret opcional con whitelist de IP. | **Comisión:** `4%` PPS+ / `2%` PPLNS. **Mínimo auto-retiro:** `0.001 BTC` (sin fee de retiro on-chain en auto-withdrawal). | PPS+ liquidado por hora; auto-retiro diario una vez alcanzado `0.001 BTC`. | **Verificada:** API REST documentada en GitHub Wiki oficial (`viabtc/viapool_api`). | **Sí** para auto-retiros On-Chain (`>= 0.001 BTC`) hacia dirección de depósito BTC de Binance. | Un equipo CPU nunca acumulará `0.001 BTC` en `SHA-256`. |
| **F2Pool** *(Pool BTC tradicional)* | ASIC (`SHA-256`) | **Baja en CPU** (orientado a ASIC). | Cuenta en F2Pool y configuración de dirección de pago. | **Comisión:** `4%` FPPS / `2%` PPLNS. **Mínimo estándar:** `0.005 BTC` (retiro manual o Lightning desde `0.0005 BTC`). | Diario automático al alcanzar `0.005 BTC`; manual/Lightning disponible desde `0.0005 BTC`. | **Verificada:** API v2 (`https://api.f2pool.com/v2/...`) para saldos, estados y pagos. | **Sí** enviando el pago On-Chain a la dirección BTC de Binance. | Umbral muy alto (`0.005 BTC`) e inviable para pruebas con CPU. |
| **NiceHash** *(Mercado de hashrate compatible con CPU, pago en BTC)* | Permite **CPU (`RandomX`)** con mineros estándar (p. ej. XMRig) pero **paga en `BTC`**. | **Alta para experimento técnico en CPU** si el usuario desea ver shares reales con su Ryzen 5 5600GT y saldo nominado en BTC. | Cuenta en NiceHash (requiere KYC según jurisdicción) y dirección de minería interna. | **Comisión minera:** `2%`. **Mínimo acreditación:** `0.00001 BTC` (`1,000 sats`) al monedero interno cada 4 horas. Retiro externo sujeto a mínimos y fees de red o Lightning. | Pagos internos en BTC cada 4 horas (si acumula `>= 1,000 sats`). Retiro manual/externo por BTC On-Chain o Lightning. | **Verificada:** NiceHash API v2 (`https://api2.nicehash.com/main/api/v2/...`) con claves de lectura para rigs, balances y pagos. | **Sí**, al retirar desde NiceHash hacia Binance (vía BTC On-Chain o mediante factura Lightning generada en Binance). | *Nota conceptual:* La CPU ejecuta `RandomX` (no `SHA-256`), vendiendo potencia de cómputo a cambio de BTC. Requiere decisión del usuario sobre si prefiere `SHA-256` puro testimonial o CPU->BTC vía NiceHash/unMineable. |
| **unMineable** *(Pool multi-algoritmo con conversión a BTC)* | Permite **CPU (`RandomX` / `GhostRider`)** liquidando en **`BTC`**. | **Media/Alta para pruebas de integración en CPU** sin registro complejo. | No requiere cuenta con contraseña para consultar estadísticas; usa la dirección de la moneda destino (`BTC`). | **Comisión:** `1%` (`0.75%` con código). **Mínimo de pago en BTC:** dinámico según red seleccionada (para red BTC nativa suele rondar `0.00015 - 0.0005 BTC`). | Pago automático diario una vez alcanzado el umbral mínimo de la red elegida. | **Verificada:** API pública JSON (`https://api.unmineable.com/v4/address/{address}?coin=BTC`). | **Sí**, si se configura como dirección de pago la dirección de depósito de Binance y se alcanza el umbral mínimo. | Con una sola CPU Ryzen 5 5600GT, alcanzar `0.00015+ BTC` aún tomaría semanas/meses de ejecución continua, por lo que no se recomienda para pruebas cortas de 30 minutos. |

*Decisión actual:* Se mantiene el proveedor externo en estado `undecided` hasta que el usuario elija qué camino desea para la Fase 6 (mantener solo modo simulado, conectar a API pública/lectura, o qué tipo de pool/algoritmo prefiere).

---

## 6. Matriz de requisitos y pruebas (Tarea F)

| ID | Requisito | Componente responsable | Riesgo principal | Prueba prevista (Tipo y alcance) | Resultado esperado | Criterio de aceptación |
|---|---|---|---|---|---|---|
| **REQ-01** | Muestreo de CPU, RAM y procesos con unidad, fuente, estado y timestamp UTC | `Collector` + `PsutilSensorAdapter` | Que `psutil` no esté instalado o un proceso termine a mitad de lectura (`NoSuchProcess`). | Unitaria (mocks de `psutil`) e Integración en Windows con `psutil` real instalado en Fase 3. | Genera objetos `Measurement` con `status="measured"`, `unit` explícita (`%`, `MiB`, `MHz`) y `observed_at_utc` en ISO-8601 UTC. | 100% de métricas base incluyen unidad, fuente y timestamp UTC; fallos aislados no detienen el colector. |
| **REQ-02** | Lectura opcional de temperatura, potencia (W) e iGPU mediante LHM sin inventar datos ausentes | `LhmSensorAdapter` + `Collector` | Que LHM no esté instalado, no tenga permisos de administrador o no exponga un sensor específico en el Ryzen 5 5600GT. | Unitaria e Integración con fixture JSON de LHM y prueba con LHM apagado/ausente. | Cuando LHM no responde, emite `Measurement(value=None, status="unavailable", quality_note=...)`. | Ninguna métrica ausente se rellena con `0` ni con cálculos inventados a partir de `%` de CPU. |
| **REQ-03** | Límites de seguridad configurables (`MAX_CPU_PERCENT`, `MAX_CPU_TEMP_C`, `MAX_SESSION_MINUTES`) | `Domain` (Safety Policy) + `Scheduler` | Sobrecalentamiento o sesiones olvidadas corriendo indefinidamente. | Unitaria de reglas de dominio con valores en el límite, por encima y con sensor térmico `unavailable`. | Dispara transición automática de la sesión a `paused` o `stopped` y registra alerta en log. | La sesión se pausa/detiene automáticamente al superar cualquier umbral configurado. |
| **REQ-04** | Almacenamiento histórico local e idempotente en SQLite con migraciones versionadas | `Storage` (SQLite Repositories + Migrator) | Corrupción de base, bloqueo por concurrencia API/Collector o duplicación de shares/eventos tras reintento. | Integración sobre SQLite en archivo temporal: migración desde cero, inserción duplicada y reinicio de conexión. | Modo `WAL` activo, claves únicas naturales respetadas, rechaza o ignora duplicados de forma idempotente, conserva precisión decimal en importes. | Datos persistidos y recuperables tras reinicio; `0` duplicados ante reintentos del mismo evento. |
| **REQ-05** | API REST local documentada con OpenAPI y restringida a loopback | `API` (FastAPI) | Exposición accidental a la red local/Internet o bloqueo del event loop por lecturas lentas. | Integración con cliente de pruebas (`TestClient`/`httpx`): validación de esquemas, timeouts, `/health` y binding por defecto. | Servidor escucha en `127.0.0.1:8765`, expone `/openapi.json` y responde en `< 500 ms` leyendo desde Storage sin bloquear por I/O externo. | El dashboard consume todo desde la API sin tocar SQLite; binding por defecto verificado en `127.0.0.1`. |
| **REQ-06** | Simulación determinista de minería, conectividad de pool y ciclo de pagos | `SimulatedMinerPoolAdapter` | Confusión entre recompensas simuladas y BTC real, o pruebas no deterministas. | Unitaria y End-to-End simulada cubriendo inicio, pausa, parada, fallo, desconexión de pool y shares aceptadas/rechazadas. | Reproducción exacta por semilla (`seed`); cada registro lleva `status="simulated"` y prefijos `SIM-`. | Flujo completo verificable sin instalar ni ejecutar ningún minero real. |
| **REQ-07** | Separación estricta de estados financieros: estimado, saldo de pool, pago emitido y depósito en Binance | `Domain` + `Storage` + `API` | Presentar una estimación o un saldo pendiente de pool como BTC recibido en Binance. | Unitaria de dominio y Contrato de API verificando que los 4 estados se almacenan y consultan en campos/tablas diferenciados. | La API y los modelos separan `estimated_reward`, `pool_balance_pending`, `payout_issued` y `deposit_detected`. | Ningún cálculo ni endpoint suma o equipara recompensas estimadas con depósitos confirmados. |
| **REQ-08** | Generación automática de reportes cada 30 minutos con control de huecos y calidad | `Reporting` + `Scheduler` | Que un reinicio del servicio o cambio de reloj del sistema duplique reportes o rellene huecos con ceros. | Unitaria e Integración con reloj inyectado (`freezegun`/clock mock), huecos de muestreo y reinicio simulado. | Genera reporte JSON/CSV por ventana UTC de 30 min indicando cobertura (`%` muestras válidas), huecos detectados, máximos/promedios y calidad. | Reportes idempotentes por ventana temporal; documentan explícitamente datos ausentes (`unavailable`). |
| **REQ-09** | Consulta de precio BTC (USD/BOB) y cálculo de coste eléctrico condicionado a medición de potencia | `PriceAdapter` + `Domain` (Economics) | Caída de API de precios o cálculo ficticio de coste eléctrico cuando falta el sensor de vatios (`W`). | Unitaria y Contrato con mocks HTTP (éxito, timeout, respuesta inválida, dato `stale` y potencia `unavailable`). | Si la API de precios falla, marca precio como `stale`/`unavailable` sin detener el sistema; si `power_w` es `null`, el coste eléctrico es `unavailable`. | El coste eléctrico nunca se inventa si no existe potencia medida o configurada explícitamente como estimación etiquetada. |
| **REQ-10** | Conciliación de depósitos con Binance en modo estricto de solo lectura | `ExchangeReadOnlyAdapter` + `ReconciliationService` | Filtración de `API_KEY`/`SECRET` en logs, exceso de permisos o fallo cuando no hay credenciales configuradas. | Unitaria y Contrato con payloads de `GET /sapi/v1/capital/deposit/hisrec`: sin claves (modo `disconnected`), clave inválida, paginación e inspección de logs. | Sin credenciales el sistema opera en estado `disconnected` sin errores fatales; con fixture válido concilia por `txId`/red/monto/ventana temporal. | Solo lectura; ningún método de retiro/trading existe en el código; `0` secretos en logs, excepciones o Git. |
| **REQ-11** | Dashboard web responsive (recursos, sesión/minería, precio BTC, historial y conciliación) | `Dashboard` (React + TypeScript) | Mezclar unidades incompatibles en un mismo gráfico (ej. `%` con `W`) o mostrar `0` cuando el valor es `null`. | Pruebas de componentes UI (estados `loading`, `error`, `empty`, `unavailable`, `simulated`) y verificación responsive desktop/móvil. | Los gráficos separan unidades (`%`, `°C`, `W`, `BTC`), muestran insignias de calidad (`measured`, `simulated`, `unavailable`) y ocultan/avisan ante datos nulos. | UI accesible solo en localhost por defecto; representa fielmente el estado de calidad de cada métrica. |
| **REQ-12** | Higiene de seguridad, prevención de fugas de secretos y parada limpia | Transversal (`Config`, `Logging`, `Git`) | Commits accidentales de `.env`, bases `.db` o procesos huérfanos tras cerrar el servicio. | Prueba automatizada del filtro de logging (`SecretRedactingFilter`), revisión de `.gitignore` y prueba de apagado (`SIGTERM`/`SIGINT`). | Cualquier cadena con patrón de clave/token se redacta como `[REDACTED]` en logs; el cierre libera conexiones SQLite y detiene timers. | `.gitignore` protege `.env`, `*.db` y `logs/`; `git diff` limpio de secretos y datos personales. |

---

## 7. Riesgos identificados y preguntas para decisión del usuario

### Riesgos técnicos principales
1. **Ausencia de Node.js / npm en el entorno actual:** Bloquea la creación y compilación del frontend React + TypeScript cuando se llegue a la Fase 7 (no bloquea las Fases 1 a 5 de backend Python).
2. **Entorno Python sin `psutil` ni `ruff` instalados aún:** Se deben instalar dentro de un entorno virtual local (`.venv`) en la Fase 1.
3. **Workspace sin repositorio Git inicializado:** Actualmente no existe `.git`, lo que impide ejecutar `git diff` nativo hasta inicializar el repositorio en el workspace.
4. **Cierre oficial de Binance Pool (`2026-11-10`):** Impide usar Binance Pool como pool de minería a futuro, aunque no afecta usar **Binance Exchange** para recibir depósitos y conciliarlos por API.
5. **Incompatibilidad práctica entre CPU (`Ryzen 5 5600GT`) y pools `SHA-256` de ASIC:** Conectar la CPU a un pool de Bitcoin estándar no generará pagos reales por la enorme dificultad de share pensado para TH/s.
6. **Sensores térmicos y de potencia en Windows 11:** Sin Libre Hardware Monitor ejecutándose con permisos de administrador, Windows no expone la temperatura del diodo Ryzen ni los vatios del paquete a aplicaciones de usuario estándar.

### Decisiones pendientes del usuario (para aprobar el paso a Fase 1)
1. **Inicialización de Git y entorno virtual Python (`.venv`) en Fase 1:** ¿Autorizas que en la Fase 1 inicialicemos el repositorio Git local (`git init`) y creemos un entorno virtual `.venv` instalando las dependencias base de Python (`psutil`, `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `httpx`, `pytest`, `ruff`)?
2. **Instalación de Node.js LTS:** ¿Deseas instalar Node.js LTS (v22.x) más adelante antes de la Fase 7 (Dashboard), o prefieres dejarlo preparado desde la Fase 1?
3. **Libre Hardware Monitor (LHM):** ¿Autorizas probar LHM cuando lleguemos a la Fase 3 (Telemetría del PC), o prefieres que el MVP funcione inicialmente solo con `psutil` + contadores nativos de Windows y reporte temperatura/potencia como `unavailable`?
4. **Orientación futura para Fase 6 (Minería experimental real opcional):** Sabiendo que Binance Pool cierra en noviembre de 2026 y que los pools `SHA-256` requieren ASIC, ¿prefieres mantener el proyecto en **modo simulado + telemetría real del PC**, o evaluar en Fase 6 una alternativa compatible con CPU (como minería CPU con pago en BTC vía NiceHash, o un pool de pruebas/testnet)?

---

## 8. Entregables de Fase 0
- [x] Inventario de entorno y versiones relevantes.
- [x] Arquitectura MVP validada y documentada.
- [x] Matriz de requisitos, componentes, pruebas y criterios de aceptación.
- [x] Matriz de sensores con fuentes y disponibilidad comprobada.
- [x] Comparativa de opciones de pool/Binance con fuentes oficiales, sin elección prematura.
- [x] Decisión del frontend React + TypeScript registrada con sus requisitos (Node.js pendiente).
- [x] Escenarios simulados definidos y reglas de separación de datos establecidas.
- [x] Riesgos, límites y exclusiones documentados.
- [x] No se ha implementado la aplicación ni ejecutado un minero real.

## Puerta de aprobación
Fase 0 ha concluido su análisis y actualización documental. El agente se detiene aquí y espera la aprobación explícita del usuario y respuesta a las preguntas de decisión antes de iniciar la Fase 1.
