# Operación, diagnóstico y recuperación

## Principios
- Iniciar primero en modo simulado.
- Verificar `health` y la antigüedad de las últimas mediciones.
- No iniciar un minero real por defecto.
- Mantener backups de la base antes de migraciones.
- Si un sensor no está disponible, revisar permisos, compatibilidad y documentación; no reemplazarlo con un número inventado.

## Diagnóstico básico
1. Revisar logs filtrados de secretos.
2. Confirmar que API está ligada a `127.0.0.1`.
3. Comprobar espacio libre en disco.
4. Comprobar última muestra y estado de calidad.
5. Verificar que scheduler no ha generado reportes duplicados.
6. Para fallo de Binance, mantener el resto del panel operativo y mostrar “desconectado”.

## Recuperación
- Detener el servicio de forma limpia.
- Copiar la base y archivos de configuración sin secretos.
- Restaurar backup en una ruta de prueba.
- Ejecutar migraciones y pruebas antes de volver a producción.
