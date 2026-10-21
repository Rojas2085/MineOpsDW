# Integración Binance — diseño y límites

## Objetivo
Conciliar depósitos detectados con los pagos reportados por el pool. No controlar activos del usuario.

## Orden de implementación
1. Diseñar interfaz `ExchangeReadOnlyAdapter`.
2. Implementar fixture simulado.
3. Confirmar endpoint oficial vigente, autenticación, permisos, paginación, límites y disponibilidad regional.
4. Consultar solo los datos necesarios para depósitos/historial.
5. Presentar eventos como “detectado por API” y conservar referencia externa.
6. Probar errores, permisos insuficientes, respuesta vacía y paginación.

## Seguridad
- API key separada, guardada fuera del repo.
- Crear clave con permisos mínimos de lectura.
- No activar retiros, trading ni transferencias.
- No solicitar frase semilla, contraseña ni clave privada.
- No registrar firma, API key ni secret.
- Nunca tratar un saldo del pool como depósito de Binance.
- Si no se puede verificar el endpoint oficial o el acceso permitido, dejar el adaptador desconectado y documentar el bloqueo.

## Conciliación
Comparar asset, importe, estado, timestamp y referencia externa cuando estén disponibles. No asumir que un pago es el mismo evento solo por coincidir el importe.
