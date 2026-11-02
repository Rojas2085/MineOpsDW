# MineOps DW — Competencias y Convenciones Técnicas (SKILLS.md)

Este documento describe las competencias de ingeniería, patrones de diseño, convenciones de código y estándares técnicos que rigen el desarrollo y mantenimiento de **MineOps DW**.

---

## 1. Python modular y tipado estricto

- **Versión de Python:** Python $\ge 3.12$ (entorno comprobado: Python 3.13 en Windows 11).
- **Tipado estático:** Uso exhaustivo de `from __future__ import annotations`, tipos de la biblioteca estándar (`int | None`, `list[str]`, `dict[str, Any]`), y protocolos estructurales (`typing.Protocol`) para desacoplar interfaces de adaptadores.
- **Validación con Pydantic v2:**
  - Modelos inmutables (`ConfigDict(frozen=True)`).
  - Rechazo de atributos no permitidos (`extra="forbid"` o `extra="ignore"` según corresponda).
  - Separación de validadores (`@field_validator` y `@model_validator(mode="after")`).
  - Protección de secretos mediante `pydantic.SecretStr`.
- **Estructuras ligeras:** Uso de `@dataclass(frozen=True)` para resultados de ciclos, deltas de shares y estructuras internas de transporte en memoria.

---

## 2. Telemetría de hardware y bajo nivel

- **Monitorización de CPU y RAM con `psutil`:**
  - Muestreo sin bloqueo (`interval=None`) para evitar congelar el bucle de eventos o los hilos de recolección.
  - Control de fallos de importación si `psutil` no está compilado o instalado en el entorno.
- **Fallback nativo en Windows (`win32_ctypes`):**
  - Cálculo de porcentaje de CPU mediante deltas de `GetSystemTimes` (kernel time, user time e idle time).
  - Memoria RAM física total, usada y disponible mediante `GlobalMemoryStatusEx`.
  - Manejo seguro de punteros ctypes y estructuras de la API Win32.
- **Libre Hardware Monitor (LHM):**
  - Conexión HTTP loopback a `http://127.0.0.1:8085/data.json`.
  - Recorrido del árbol jerárquico JSON para extraer sensores Tctl/Tdie, CPU Package Power y carga de iGPU.
  - Degradación elegante a `status="unavailable"` con `value=None` ante caídas de servicio o sensores ausentes.

---

## 3. Integración HTTP y clientes de red

- **Cliente HTTP (`httpx`):**
  - Uso preferente de `httpx.Client` con timeouts finitos estrictos ($\le 3.0$ s para mineros locales, $\le 10.0$ s para APIs externas).
  - Inyección de dependencias (`http_client: httpx.Client | None`) para permitir pruebas unitarias 100% deterministas mediante `httpx.MockTransport`.
  - Aislamiento de excepciones: no propagar excepciones nativas de `httpx` que puedan contener encabezados o tokens de autorización en su traza (`raise AppError(...) from None`).
- **Resiliencia con `tenacity`:**
  - Políticas de reintento acotadas con backoff exponencial para servicios externos (Binance, CoinGecko, unMineable).
  - No reintentar indefinidamente peticiones de control que puedan generar condiciones de carrera o comandos duplicados.

---

## 4. Conectores de minería y protocolo común (`A-01`, `CP-01-A`, `CP-02`)

- **Protocolo común `MinerConnector` y coexistencia con `MinerAdapter`:**
  - `MinerConnector` ([`src/mineops_dw/domain/miner_connector.py`](file:///c:/Users/rojoh/OneDrive/Desktop/MineOpsDW_Antigravity_Starter/src/mineops_dw/domain/miner_connector.py)) coexiste con `MinerAdapter` (`SimulatedMinerPoolAdapter`) y expone únicamente:
    ```python
    class MinerConnector(Protocol):
        def get_snapshot(self) -> MinerSnapshot: ...
        def get_capabilities(self) -> MinerCapabilities: ...
        def pause(self) -> CommandResult: ...
        def resume(self) -> CommandResult: ...
    ```
  - Excluye `start()`, `stop()` y terminación de procesos (`taskkill`).
  - Separa explícitamente `ConnectionStatus`, `MinerOperationalState`, `StateConfidence`, `process_progress`, `MinerCapabilities` (`AVAILABLE`, `READ_ONLY`, `UNAVAILABLE`), `ControlAuthorization` (`NOT_GRANTED`, `GRANTED`, `REVOKED`) y `CommandResult`.
- **XMRig en modo permanentemente pasivo con Mocks Exclusivos (`CP-01-A` y `CP-02` Opción B ajustada):**
  - Implementación en [`XMRigApiAdapter`](file:///c:/Users/rojoh/OneDrive/Desktop/MineOpsDW_Antigravity_Starter/src/mineops_dw/adapters/xmrig.py), probada **exclusivamente con mocks deterministas en memoria (`httpx.MockTransport`)**. Prohibido conectarse a mineros reales durante las pruebas.
  - Consulta exclusivamente `GET /2/summary`.
  - Validación estructural conservadora (`CP-02` Opción B ajustada): exige en la raíz del JSON `version` (`str` no vacío), `kind == "miner"` y `paused` (`bool` estricto). `uptime` no es obligatorio para reconocer el estado operativo (`RUNNING` o `PAUSED`), pero su ausencia o insuficiencia de muestras deja `process_progress = "UNKNOWN"`. Las métricas secundarias (`hashrate`, `results`) mantienen su `TelemetryQuality` individual sin invalidar el estado operativo ni usarse jamás para inferir actividad.
  - `pause` y `resume` permanecen como `UNVERIFIED_PASSIVELY` (`restricted` no se usa como prueba suficiente), `MinerCapabilities.status` es `READ_ONLY` cuando la observación funciona (o `UNAVAILABLE` si falla), y XMRig no puede obtener `ControlAuthorization = GRANTED`.
  - `pause()` y `resume()` se rechazan localmente sin I/O de red devolviendo `CommandResult` con `delivery="NOT_SENT"`, `acceptance="UNKNOWN"`, `postcondition="NOT_ATTEMPTED"`.
  - Restricción estricta de loopback: solo se admiten direcciones `127.0.0.1`, `localhost` o `::1` con puerto explícito. Prohibidas terminantemente URLs remotas.
  - **Puerto loopback por defecto (`PARAM-05`):** Se aprueba `http://127.0.0.1:18080` como origen loopback por defecto de `XMRigApiAdapter`.
- **Otros motores (SRBMiner-Multi, Kryptex) y conectores controlables futuros:**
  - El diseño pasivo de XMRig (`CP-01-A`) no altera el contrato general `MinerConnector` ni impide que futuros conectores controlables implementen control supervisado bajo las reglas `R-01` a `R-05`.

---

## 5. Integraciones financieras y de pools

- **Configuración de pago vacía por defecto:**
  - `payout_coin`, `payout_address` y `payout_network` se mantienen como cadenas vacías por defecto.
  - Mientras no estén definidos, los colectores de balance de pool inhiben las llamadas de red y emiten `status="unavailable"`, evitando errores de URL o peticiones a endpoints malformados.
- **API pública de Binance (Mercado):**
  - Uso exclusivo de endpoints públicos sin autenticación (`/api/v3/ticker/24hr`, `/api/v3/ticker/price`) para valorización de activos en USD/USDT.
  - Validación del par de negociación (`symbol`). Manejo explícito de la distinción entre USD fiat y stablecoins (USDT/USDC).
- **Binance Spot SAPI (Depósitos):**
  - Endpoint de solo lectura `/sapi/v1/capital/deposit/hisrec`.
  - Autenticación con firma HMAC SHA256 sobre timestamp UTC.
  - Prohibición absoluta de scopes de retiro, trading o transferencia.
- **APIs de Pools (unMineable, Zergpool):**
  - *unMineable:* Consulta de balances pendientes mediante endpoint público por dirección de billetera, únicamente si `is_payout_configured` es `True`. Respeto estricto del límite de consultas ($\ge 5$ minutos entre peticiones).
  - *Zergpool:* Requiere comprobación documental de endpoints válidos antes de su desarrollo. No se aceptan endpoints especulativos.

---

## 6. Cálculos energéticos y rentabilidad

- **Integración energética trapezoidal:**
  - Cálculo de vatios-hora (Wh) a partir de muestras consecutivas de potencia instantánea en vatios (W):
    $$\text{Wh} = \frac{P_0 + P_1}{2} \times \frac{\Delta t}{3600}$$
  - Si falta alguna muestra de potencia, el resultado del tramo se marca obligatoriamente como `unavailable`.
- **Cálculo de costo y margen neto:**
  - Conversión de Wh a kWh acumulados y valorización según tarifa eléctrica ($/kWh).
  - Comparación contra ingresos brutos estimados reportados por el pool para determinar el margen neto.
  - Si falta cualquier entrada requerida (costo o ingreso), el margen neto se reporta como no disponible, nunca como cero.

---

## 7. Persistencia, repositorios y base de datos

- **SQLite nativo (WAL Mode):**
  - Uso de `sqlite3` de la biblioteca estándar de Python con modo `PRAGMA journal_mode = WAL;` y `PRAGMA foreign_keys = ON;`.
  - Transacciones atómicas explícitas (`BEGIN IMMEDIATE;` y `COMMIT;` o `ROLLBACK;`).
  - Migraciones SQL versionadas mediante scripts `.sql` numerados aplicados en orden léxico.
  - Idempotencia garantizada por claves primarias y restricciones únicas (`UNIQUE (metric_name, source, observed_at_utc)`).
- **Propuesta futura de migración:**
  - La migración para seguimiento histórico de balances de pool (`0002_payout_and_multicoin.sql`) se mantiene como **propuesta futura**, sin ejecutarse ni alterar el esquema actual de SQLite.
- **Posición respecto a SQLAlchemy:**
  - El código actual utiliza `sqlite3` puro con `MineOpsRepository`.
  - No se introducirá SQLAlchemy a menos que una fase futura lo justifique formalmente, se evalúe el impacto en dependencias y el usuario lo autorice explícitamente.

---

## 8. Seguridad, logging y marcas de tiempo

- **UTC canónico:**
  - Todos los timestamps internos y de base de datos se generan y almacenan en formato UTC ISO-8601 con sufijo `Z` (`YYYY-MM-DDTHH:MM:SS.fffZ`).
  - Prohibido almacenar timestamps ingenuos (*naive*) o con zonas horarias locales sin normalizar.
- **Ofuscación de credenciales:**
  - Filtro `SecretRedactingFilter` adjunto al logger raíz del proyecto.
  - Reemplazo automático por `[REDACTED]` de cualquier clave API, secreto, token o patrón sensible antes de emitir líneas a consola o archivo.
- **Supervisión térmica y control de datos obsoletos (`PARAM-01` a `PARAM-04`):**
  - Muestras de temperatura con más de `30` segundos de desfase (`PARAM-04`) se consideran caducadas (`STALE`) y disparan la protección preventiva.
  - **Umbrales aprobados:** `75.0 °C` como disparo crítico (`PARAM-01`), `60.0 °C` como recuperación (`PARAM-02`) y `120` segundos de estabilidad continua (`PARAM-03`) en `AppSettings` y `ThermalSupervisor`.

---

## 9. Pruebas automatizadas y aseguramiento de calidad

- **Aislamiento en pruebas:**
  - Las pruebas de red y minería se ejecutan exclusivamente con dobles de prueba (`httpx.MockTransport`), simulando códigos 200, 4xx, 5xx, timeouts y respuestas malformadas.
  - No se permiten llamadas a la red real ni a puertos locales en la suite de pruebas unitarias estándar.
- **Herramientas de verificación:**
  - `pytest`: Suite de pruebas unitarias y de integración.
  - `ruff`: Análisis estático de código, linting y formateo consistente.
  - `mypy`: Verificación estricta de tipos sin excepciones ignoradas arbitrariamente.
