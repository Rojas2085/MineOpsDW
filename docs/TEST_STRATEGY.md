# Estrategia de pruebas (Actualizada en Fase 0)

## Pirámide de pruebas
- **Unitarias:** modelos de dominio, validación de rangos y unidades, políticas de parada térmica/CPU/duración, integración trapezoidal de energía (`Wh`), cálculo de costes y conciliación con `Decimal`.
- **Integración:** repositorios SQLite y migraciones sobre bases temporales, servicio de colección con adaptadores combinados (presentes y ausentes), API REST con `TestClient` y generación de reportes de 30 minutos.
- **Contrato:** validación de esquemas para payloads de sensores (`psutil`, JSON/WMI de Libre Hardware Monitor), respuestas de pool, precios de mercado y endpoint `GET /sapi/v1/capital/deposit/hisrec` de Binance.
- **End-to-end (Simulado):** ciclo completo determinista (inicio de sesión simulada -> muestreo -> shares aceptadas/rechazadas -> corte de reporte de 30 min -> pago emitido simulado -> depósito detectado simulado -> consulta desde API/UI).
- **Manuales y controladas:** verificación visual responsive del dashboard en `127.0.0.1`, comprobación de permisos de sensores en Windows 11 y (solo si se autoriza Fase 6) prueba térmica de corta duración.

## Matriz de casos obligatorios de telemetría y conciliación
1. **Sensor presente (`measured`):** persiste valor numérico, unidad explícita, fuente y `observed_at_utc` en UTC.
2. **Sensor ausente (`unavailable`):** persiste `value=None`, `status="unavailable"` y `quality_note` descriptiva; nunca devuelve `0` ni estima temperatura/potencia a partir de `%` de uso.
3. **Fallo o timeout de un sensor:** el error se registra en log y el colector continúa guardando el resto de las métricas del ciclo.
4. **Valor fuera de rango físico:** por ejemplo `% < 0`, `% > 100` o potencia negativa; se rechaza o registra como inválido (`unavailable` con nota de error de rango) sin falsear las medias.
5. **Fuente desactualizada (`stale`):** si una API de precios o el servidor web de LHM devuelve datos cuya antigüedad supera el umbral configurado, se marca como `unavailable` con nota `stale_source`.
6. **Idempotencia e integridad en SQLite:** reintentar la inserción de la misma `PoolShare`, `PaymentEvent` o `PeriodicReport` no duplica registros ni altera saldos.
7. **Alteración del reloj o reinicio del servicio:** las ventanas de reporte de 30 minutos se calculan en UTC y detectan huecos (`gaps_count`) sin rellenar los intervalos vacíos con valores ficticios.
8. **Separación de los 4 estados financieros:** ninguna prueba ni consulta mezcla `estimated` (cálculo local), `pool_reported` (saldo en pool), `payout_issued` (enviado por pool) y `deposit_detected` (recibido en Binance).
9. **Binance sin credenciales (`disconnected`):** cuando `BINANCE_READ_ONLY_API_KEY` está vacío, el adaptador reporta estado `disconnected` y toda la suite y el dashboard operan sin errores.
10. **Redacción de secretos en logs:** pruebas específicas inyectan claves ficticias en excepciones HTTP para comprobar que el filtro de logging las reemplaza por `[REDACTED]`.
11. **Aislamiento de simulación:** ninguna prueba automatizada ejecuta binarios de minería ni abre conexiones reales a pools.

## Trazabilidad con requisitos
La relación completa entre cada requisito (`REQ-01` a `REQ-12`), su componente responsable, riesgo principal, prueba prevista y criterio de aceptación se encuentra documentada en la sección **6. Matriz de requisitos y pruebas** de `docs/PHASE_0_DECISIONS.md`.

## Comandos de verificación esperados (a partir de Fase 1 en `.venv`)
- `python -m pytest` (verificado `pytest 9.1.1` disponible en Python `3.13.14`)
- `python -m ruff check .` (tras instalar `ruff` en `.venv` en Fase 1)
- `python -m ruff format --check .`
- `python -m compileall src`
- Frontend (a partir de Fase 7, tras instalar Node.js LTS): `npm test` y `npm run build`
