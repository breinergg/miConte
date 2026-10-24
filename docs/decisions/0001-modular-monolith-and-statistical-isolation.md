# ADR-0001: Arquitectura de Monolito Modular y Aislamiento del Motor Estadístico

* **Estado:** Aceptado
* **Fecha:** 2026-10-24
* **Fase:** Fase 0 — Fundamentación y Arquitectura

---

## Contexto

**miConte** requiere integrar APIs oficiales de YouTube, almacenar datos históricos en PostgreSQL (`miconte_db`), ejecutar análisis estadísticos rigurosos (`pandas`, `NumPy`, `SciPy`, `statsmodels`), generar recomendaciones deterministas, exponer una API REST en FastAPI, ofrecer una interfaz web en Angular y permitir en una fase posterior la interpretación de resultados mediante un LLM (Ollama local o API externa).

Existen dos riesgos arquitectónicos opuestos:
1. **Sobre-ingeniería (Microservicios prematuros):** Dividir el sistema en múltiples servicios desplegables independientes con colas de mensajes y contenedores distribuidos añadiría complejidad innecesaria (violando el Principio 9).
2. **Acoplamiento espagueti:** Escribir los cálculos estadísticos dentro de los controladores de FastAPI, mezclados con consultas SQLAlchemy o llamadas a un LLM, impediría probar el motor estadístico de forma aislada y determinista (violando los Principios 1, 2, 3 y 8).

---

## Decisión

1. Adoptar una arquitectura de **Monolito Modular** para el backend bajo el paquete raíz `miconte`.
2. Establecer una frontera de aislamiento estricta alrededor de los paquetes de dominio analítico:
   * `miconte.statistics` (Motor Estadístico)
   * `miconte.recommendations` (Motor de Recomendaciones Deterministas)
3. Prohibir por regla arquitectónica y verificación en tests/linting que `miconte.statistics` y `miconte.recommendations` importen `fastapi`, `sqlalchemy`, `httpx`, clientes de YouTube, librerías de LLM o SDKs de MCP.
4. La comunicación hacia el motor estadístico se realizará exclusivamente mediante estructuras de datos en memoria (`pandas.DataFrame`, `numpy.ndarray` o `dataclasses` / esquemas puros de dominio) construidas por la capa de aplicación a partir de los repositorios.

---

## Consecuencias

### Positivas
* El motor estadístico y el motor de recomendaciones pueden probarse unitariamente en `pytest` en milisegundos, 100% offline, sin levantar PostgreSQL, FastAPI ni Ollama.
* Se garantiza por diseño el cumplimiento de los Principios 1 y 2 (funcionamiento sin LLM y sin MCP).
* Despliegue local simple (un único proceso backend ASGI + base de datos PostgreSQL `miconte_db` + SPA Angular).
* Si en el futuro se incorporan datos de TikTok o Instagram, solo se añade un nuevo adaptador de ingesta que alimenta las tablas históricas y los mismos `DataFrames` de entrada al motor estadístico.

### Negativas / Compromisos
* Requiere disciplina en la conversión de modelos ORM de SQLAlchemy a estructuras de dominio/DataFrames en la frontera de los repositorios.
