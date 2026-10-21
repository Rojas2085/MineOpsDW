# ADR 0001: Arquitectura inicial local y modular

- **Estado:** Validada técnicamente en Fase 0 (pendiente de aprobación final del usuario).
- **Fecha:** `2026-10-21`

## Contexto
El sistema MineOps DW debe ejecutarse en un PC con Windows 11 Home (AMD Ryzen 5 5600GT, 16 GB RAM, gráficos integrados Radeon), recoger métricas de hardware heterogéneas, tolerar sensores de temperatura/potencia ausentes sin inventar datos, mantener un historial analítico local con reportes cada 30 minutos, simular sesiones de minería de forma determinista y permitir conciliar pagos con depósitos en Binance en modo de solo lectura.

## Decisión propuesta y validada
1. **Backend y colector en Python (`>=3.12`, verificado `3.13.14`):** servicio modular con separación estricta entre `Domain`, `Storage`, `Adapters`, `Collector`, `Scheduler`, `Reporting` y `API`.
2. **Almacenamiento inicial en SQLite (`3.50.4`):** base local en modo `WAL` con migraciones SQL versionadas, timestamps en UTC e importes financieros como cadenas decimales exactas (`Decimal`).
3. **API REST local (FastAPI + OpenAPI):** ligada por defecto exclusivamente a `127.0.0.1:8765`, sirviendo como única puerta de acceso a los datos para el frontend.
4. **Frontend en React + TypeScript:** SPA desacoplada que consume la API local y representa explícitamente los estados de calidad (`measured`, `estimated`, `unavailable`, `simulated`).
5. **Adaptadores de telemetría y fuentes externas:**
   - `PsutilSensorAdapter` para CPU, RAM y procesos.
   - `LhmSensorAdapter` opcional (vía JSON HTTP local `127.0.0.1:8085` o WMI `root\LibreHardwareMonitor`) para temperaturas, potencia del paquete (`W`) e iGPU Radeon. Si no está disponible, se registra `value=null` y `status="unavailable"`.
   - `SimulatedMinerPoolAdapter` determinista como modo inicial por defecto.
   - `PoolAdapter` desacoplado (teniendo en cuenta que Binance Pool cierra el `2026-11-10` y que los pools `SHA-256` requieren ASIC).
   - `ExchangeReadOnlyAdapter` para consultar el historial de depósitos en Binance (`GET /sapi/v1/capital/deposit/hisrec`) usando exclusivamente permisos `Enable Reading`.

## Alternativas consideradas
- **Aplicación monolítica sin API REST (UI acoplada a SQLite):** descartada porque impide reutilizar el backend para el futuro agente Android (Fase 11) y dificulta las pruebas de contrato e integración.
- **Base de datos de servidor (PostgreSQL / TimescaleDB):** descartada para el MVP por añadir sobrecarga operativa innecesaria en un único PC local con muestreo cada 10 segundos y reportes cada 30 minutos.
- **Uso de Binance Pool como único pool integrado:** descartado tras verificar el anuncio oficial de cierre de Binance Pool para el `10 de noviembre de 2026`.
- **Estimación sintética de temperatura o vatios a partir del `%` de uso de CPU:** descartada por vulnerar las reglas de exactitud de datos del proyecto.

## Consecuencias
- **Ventajas:** alta mantenibilidad, seguridad por defecto (`127.0.0.1`, solo lectura en exchange), tolerancia a fallos de sensores o red, y capacidad de probar todo el sistema en modo simulado sin estrés térmico ni cuentas externas.
- **Costes y requisitos:** requiere inicializar un entorno virtual Python (`.venv`) con `psutil`/`fastapi`/`ruff` en la Fase 1 e instalar Node.js LTS antes de abordar el Dashboard en la Fase 7.
