# Reglas de Proyecto y Directrices de Agente para miConte

Este archivo define las reglas obligatorias para cualquier agente de programación (Google Antigravity, Claude Code, Cursor, etc.) que trabaje en el repositorio **miConte**.

---

## 1. Contexto de Arquitectura
- **Backend:** Python con FastAPI, SQLAlchemy y Alembic.
- **Base de Datos:** PostgreSQL relacional.
- **Capa Numérica y Analítica:** pandas, NumPy, SciPy y statsmodels.
- **Frontend:** Angular y TypeScript (Signals, componentes standalone).
- **Pruebas:** pytest (backend) y Playwright / testing estándar (frontend).
- **Restricción Fundamental:** La aplicación debe funcionar sin dependencias de LLM y sin MCP. Todo cálculo estadístico debe ser determinista y offline.

---

## 2. Skills Obligatorias del Proyecto (`.agents/skills/`)
Antes de implementar, modificar o revisar código, debes consultar y aplicar las skills instaladas en `.agents/skills/`:

1. **Gobernanza y Fases:**
   - Consulta `miconte-phase-workflow` antes de iniciar o dar por terminada cualquier fase de desarrollo. No se avanza de fase sin cumplir su checklist de aceptación.
2. **Estadística y Analítica:**
   - Consulta `miconte-statistical-validation` en toda función de cálculo métrico, agregación o serie temporal. Documenta fórmulas en LaTeX, valida normalidad/muestras, trata datos ausentes explícitamente y prohíbe conclusiones causales no demostradas.
3. **Desarrollo Backend:**
   - Consulta `fastapi` para inyección de dependencias (`Annotated`), esquemas Pydantic v2 y endpoints asíncronos.
   - Consulta `postgres-best-practices` para diseño de modelos relacionales, índices y migraciones Alembic.
4. **Desarrollo Frontend:**
   - Consulta `angular-developer` para reactividad con Signals, control flow moderno y arquitectura de componentes.
   - Consulta `frontend-design` para garantizar una identidad visual cuidada, profesional y no genérica.
5. **Calidad, Pruebas y Depuración:**
   - Aplica `test-driven-development`: escribe el test que falla antes de escribir el código de producción.
   - Aplica `systematic-debugging` ante cualquier fallo de test, error de runtime o bug.
   - Aplica `verification-before-completion`: no afirmes que un cambio está listo sin ejecutar los comandos de verificación y mostrar evidencia fresca.
   - Aplica `security-review` para auditar entradas no confiables, inyecciones SQL y directivas OWASP.
