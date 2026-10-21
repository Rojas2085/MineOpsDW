---
trigger: always_on
description: Reglas de seguridad, datos financieros, credenciales y operaciones del sistema para MineOps DW.
---

# Seguridad y privacidad
- No solicitar ni guardar frases semilla, contraseñas ni claves privadas.
- API keys fuera del repositorio; nunca imprimirlas en logs.
- La integración Binance inicial debe ser de solo lectura y con permisos mínimos.
- No implementar trading, retiros ni transferencias automáticas en el MVP.
- No abrir puertos públicos; por defecto escuchar en `127.0.0.1`.
- Confirmar antes de instalar o ejecutar binarios de minería o lanzar cargas prolongadas.
- Usar timeout, validación, consultas parametrizadas y manejo seguro de errores.
- No borrar, sobrescribir ni migrar datos reales sin copia de seguridad y consentimiento.
