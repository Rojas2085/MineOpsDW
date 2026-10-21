---
name: mineops-development
description: Flujo de trabajo para implementar una fase de MineOps DW con plan, cambios mínimos, pruebas, revisión y documentación.
---

# Skill: desarrollo por fases

## Cuándo usar
Cada vez que se solicite implementar, corregir o refactorizar una fase o componente de MineOps DW.

## Procedimiento
1. Identifica la fase activa y sus criterios de aceptación.
2. Lee las instrucciones del repositorio y los documentos afectados.
3. Inspecciona el estado actual: árbol de archivos, Git, dependencias y pruebas.
4. Propón un plan con:
   - objetivo;
   - archivos que se crearán/modificarán;
   - dependencias nuevas y por qué;
   - riesgos y mitigaciones;
   - comandos de validación.
5. Espera confirmación si el cambio altera arquitectura, seguridad, datos persistidos o permisos.
6. Implementa una porción vertical pequeña que pueda ejecutarse.
7. Añade pruebas junto con el código.
8. Ejecuta primero las pruebas enfocadas y luego la suite aplicable.
9. Revisa errores, cobertura útil, tipos, logs, secretos y `git diff`.
10. Actualiza documentos, ejemplos y variables de entorno.
11. Entrega el informe final y detente; no empieces la fase siguiente.

## Informe requerido
- Cambios realizados.
- Archivos afectados.
- Comandos ejecutados y resultado real.
- Criterios de aceptación cumplidos/no cumplidos.
- Limitaciones y riesgos restantes.
- Recomendación de siguiente paso, sin ejecutarlo.

## Prohibiciones
- No afirmar que el código funciona sin ejecutar pruebas.
- No esconder pruebas fallidas ni eliminar pruebas para conseguir verde.
- No introducir dependencias innecesarias.
- No cambiar formatos de datos sin migración y prueba.
- No mezclar datos simulados con datos reales.
