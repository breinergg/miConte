# ADR-0003: Abstracción de Proveedores LLM e Independencia de MCP

* **Estado:** Aceptado
* **Fecha:** 2026-10-24
* **Fase:** Fase 0 — Fundamentación y Arquitectura

---

## Contexto

Los principios rectores 1, 2 y 3 de **miConte** establecen que:
1. El motor estadístico debe poder funcionar sin LLM.
2. La aplicación debe funcionar sin MCP (Model Context Protocol).
3. El LLM debe interpretar resultados calculados y no inventar métricas.

Al mismo tiempo, la arquitectura contempla incorporar en una etapa posterior a la validación del núcleo determinista un LLM local mediante **Ollama** como primera alternativa, o bien conectarse a APIs externas mediante una abstracción común, sin acoplar el sistema a un proveedor único ni obligar al usuario a disponer de una GPU local o de una clave de API comercial para usar **miConte**.

---

## Decisión

1. **Patrón Puerto y Adaptador para IA (`LLMProviderPort`):**
   * Definir un protocolo Python (`typing.Protocol`) llamado `LLMProviderPort` dentro de `miconte.ai.ports` que reciba exclusivamente un objeto inmutable de entrada (`AnalyticalInterpretationRequest`) compuesto por los resultados ya calculados por `miconte.statistics` y `miconte.recommendations`.
   * Proveer tres implementaciones concretas intercambiables mediante variables de entorno (`MICONTE_LLM_PROVIDER`):
     * `none` (`NoOpLLMAdapter`): Valor por defecto del MVP inicial. Devuelve `ai_interpretation: None` e indica `status: "disabled"` sin realizar llamadas de red.
     * `ollama` (`OllamaAdapter`): Conecta mediante `HTTPX` al endpoint local de Ollama (`MICONTE_OLLAMA_BASE_URL`, por defecto `http://localhost:11434`) con un *timeout* estricto (`MICONTE_LLM_TIMEOUT_SECONDS`).
     * `external` (`ExternalAPIAdapter`): Adaptador HTTP genérico para proveedores compatibles con el estándar de chat/completions externo configurado vía `MICONTE_EXTERNAL_LLM_BASE_URL` y `MICONTE_EXTERNAL_LLM_API_KEY`.
2. **Flujo Unidireccional y Degradación Elegante (*Graceful Degradation*):**
   * El motor estadístico y el motor de recomendaciones deterministas se ejecutan **siempre primero** y su respuesta se entrega íntegra al usuario.
   * Si el adaptador de LLM está habilitado pero falla (error de red, modelo no descargado en Ollama, *timeout* o violación de reglas anti-causalidad), el sistema captura la excepción, registra el evento y devuelve la respuesta determinista completa con `ai_status = "unavailable"`.
3. **Exclusión de MCP del MVP (Reservado para Fase 11):**
   * Ningún componente del backend ni del frontend importará librerías de MCP durante las Fases 0 a 10 (MVP). En la **Fase 11 (MCP opcional y expansión a otras plataformas)**, si se decide exponer herramientas de **miConte** mediante MCP, se construirá como un adaptador de entrada independiente que invoca los mismos servicios de aplicación que consume FastAPI.

---

## Consecuencias

### Positivas
* Cambiar de Ollama local a una API externa o desactivar por completo la IA requiere únicamente cambiar una variable de entorno (`MICONTE_LLM_PROVIDER`), con **cero cambios** en `miconte.statistics`, `miconte.recommendations`, `miconte.persistence` o en el frontend Angular.
* Se elimina de raíz el riesgo de que el LLM altere o invente cálculos matemáticos, ya que los números provienen directamente de la estructura determinista adjunta en la respuesta.

### Negativas / Compromisos
* Requiere mantener un esquema JSON estructurado claro (`AnalyticalInterpretationRequest`) y validación post-generación para asegurar que el resumen textual del LLM respete la prohibición de lenguaje causal.
