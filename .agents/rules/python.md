---
trigger: glob
globs: "*.py, **/*.py"
description: Convenciones de Python para MineOps DW.
---

# Python
- Compatibilidad objetivo: Python 3.12+ salvo que se apruebe otra versión.
- Usar anotaciones de tipo en funciones públicas.
- Mantener I/O, lógica de dominio y adaptadores externos separados.
- Usar `logging`, no `print`, en código de producción.
- Añadir pruebas para errores, límites y ausencia de sensores.
- Usar `datetime` con UTC y timestamps conscientes de zona horaria.
- No atrapar excepciones genéricas sin registrarlas ni traducirlas de forma segura.
- No bloquear el hilo de API con trabajos de muestreo o llamadas externas lentas.
