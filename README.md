# MineOps DW — Planificación y kit inicial para Google Antigravity

Proyecto de monitorización experimental de minería, telemetría de hardware, Data Warehouse, panel local y conciliación de pagos.

## Cómo empezar
1. Extrae esta carpeta y ábrela como workspace en Google Antigravity.
2. Lee `AGENTS.md`, `docs/PROJECT_PLAN.md` y `docs/ARCHITECTURE.md`.
3. Pide al agente que trabaje **solo en Fase 0** y que presente plan y pruebas antes de implementar.
4. Revisa el diff y los resultados de pruebas antes de aprobar cada fase.
5. No compartas claves API, contraseñas, frases semilla ni archivos `.env`.

## Estructura
- `AGENTS.md`: reglas permanentes del proyecto.
- `.agents/agents/mineops-developer/agent.md`: definición del agente especializado.
- `.agents/skills/mineops-development/SKILL.md`: flujo reutilizable de desarrollo.
- `.agents/skills/telemetry-testing/SKILL.md`: flujo de pruebas de telemetría.
- `.agents/rules/security.md`: reglas de seguridad.
- `.agents/rules/python.md`: reglas para Python.
- `docs/PROJECT_PLAN.md`: fases, entregables y criterios de aceptación.
- `docs/ARCHITECTURE.md`: arquitectura objetivo.
- `docs/DATA_DICTIONARY.md`: diccionario de datos inicial.
- `docs/TEST_STRATEGY.md`: estrategia de pruebas.
- `docs/ADR/0001-initial-architecture.md`: decisión arquitectónica.
- `docs/OPERATIONS.md`: operación y recuperación.
- `docs/BINANCE_INTEGRATION.md`: límites y diseño de integración Binance.
- `docs/DEFINITION_OF_DONE.md`: definición de terminado.
- `docs/PHASE_CHECKLIST.md`: lista de control por fase.
- `prompts/PHASE_0_PROMPT.md`: primer prompt para Antigravity.
- `pyproject.toml`: configuración mínima de herramientas Python.
- `.env.example`: variables ficticias, sin secretos.
- `.gitignore`: exclusiones de secretos y datos locales.

## Principios
- Datos reales, estimados y no disponibles deben distinguirse explícitamente.
- No afirmar rentabilidad de minería BTC en CPU/GPU integrada.
- Binance empieza en modo de solo lectura; no habilitar retiros desde una API.
- No ejecutar ni instalar mineros automáticamente sin aprobación explícita.
- Cada fase debe dejar pruebas ejecutadas y documentación actualizada.

## Ejecución de pruebas y validación (Fase 1)
Desde PowerShell en la raíz del proyecto:

```powershell
python -m compileall src tests
python -m pytest
```
