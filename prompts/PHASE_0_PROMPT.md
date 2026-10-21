# Prompt para Google Antigravity — Fase 0 solamente (decisiones actualizadas)

Lee primero `AGENTS.md`, `.agents/agents/mineops-developer/agent.md`, `docs/PROJECT_PLAN.md`, `docs/ARCHITECTURE.md`, `docs/DATA_DICTIONARY.md`, `docs/PHASE_0_DECISIONS.md` y `docs/ADR/0001-initial-architecture.md`.

## Decisiones acordadas para validar
- Frontend: React + TypeScript.
- Sensores: probar Libre Hardware Monitor (LHM) como fuente opcional; usar `psutil` para CPU, RAM y procesos.
- Minería: modo simulado primero.
- Pool/Binance: pendiente de verificar compatibilidad.
- Propuesta backend: Python con API REST local.
- Propuesta de almacenamiento: SQLite.
- Reportes cada 30 minutos.
- Binance, si se incorpora, empieza con permisos de solo lectura.
- Android queda como ampliación opcional posterior.

## Tarea actual
Trabaja SOLO en Fase 0. No programes la aplicación ni empieces Fase 1.

1. Inspecciona el workspace y las versiones de herramientas instaladas de forma segura. No instales paquetes ni ejecutes cargas intensivas.
2. Valida si la arquitectura propuesta es viable y documenta dependencias/versiones recomendadas.
3. Investiga o inspecciona la disponibilidad de sensores mediante LHM solo si ya está instalado o si el usuario autoriza instalarlo. No inventes resultados. Si no puedes comprobar un sensor, marca su estado como pendiente.
4. Define la matriz de sensores: métrica, unidad, fuente, disponibilidad observada, frecuencia sugerida y comportamiento si falta.
5. Define los escenarios deterministas de minería simulada y los contratos de datos.
6. Compara pools candidatos y Binance solo con documentación oficial vigente. No elijas proveedor por el usuario; registra mínimos, comisiones, hardware requerido, disponibilidad y método de pago cuando estén verificados.
7. Crea/actualiza una matriz requisito -> componente -> prueba -> criterio de aceptación.
8. Actualiza `docs/PHASE_0_DECISIONS.md`, `docs/ARCHITECTURE.md`, `docs/PROJECT_PLAN.md` y el ADR si corresponde. Muestra el diff.
9. No crees la aplicación, no instales ni ejecutes software de minería, no configures Binance, no solicites credenciales y no generes claves.
10. Devuelve ventajas, limitaciones, riesgos, preguntas pendientes, comandos ejecutados y resultados reales. Distingue comprobaciones hechas de propuestas.

Detente al terminar Fase 0 y espera aprobación explícita antes de empezar Fase 1.
