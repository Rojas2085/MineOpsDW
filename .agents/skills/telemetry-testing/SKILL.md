---
name: telemetry-testing
description: Diseña y ejecuta pruebas de telemetría, sensores, minería, almacenamiento y conciliación de datos de MineOps DW.
---

# Skill: pruebas de telemetría y datos

## Objetivo
Verificar que cada métrica tiene procedencia, unidad, timestamp y estado de calidad; que los fallos de sensores no producen datos inventados y que los reportes son reproducibles.

## Modelo mínimo de una medición
- `metric_name`: nombre estable.
- `value`: valor numérico o nulo.
- `unit`: unidad explícita.
- `status`: `measured`, `estimated`, `unavailable` o `simulated`.
- `source`: sensor, API, pool, cálculo o fixture.
- `observed_at_utc`: timestamp UTC ISO-8601.
- `quality_note`: opcional, explica límites o ausencia.

## Casos obligatorios
1. Sensor presente: dato con unidad, fuente y timestamp.
2. Sensor ausente: `value=null`, `status=unavailable`, razón explícita.
3. Sensor que falla: error registrado sin detener toda la colección.
4. Valor fuera de rango: rechazar o marcar inválido; nunca corregir silenciosamente.
5. Fuente desactualizada: marcar stale o no disponible.
6. Reintento de API: backoff limitado y timeout.
7. Datos duplicados: idempotencia por identificador o clave natural.
8. Tiempo del sistema cambiado: ordenar por timestamps UTC y conservar observación original.
9. Recompensa estimada: nunca se etiqueta como pago confirmado.
10. Binance sin credenciales: modo desconectado y pruebas siguen funcionando.
11. Logs: no contienen API keys, tokens ni datos sensibles.
12. Reporte de 30 minutos: incluye huecos y calidad de datos; no rellena datos inexistentes con valores ficticios.

## Salida
Genera fixtures deterministas, pruebas unitarias y una breve tabla con caso, resultado esperado, resultado observado y estado.
