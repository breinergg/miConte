# Requisitos del Sistema — miConte (`docs/requirements.md`)

Este documento especifica los requisitos funcionales (RF), los requisitos no funcionales (RNF) y los criterios de aceptación que rigen el diseño y construcción del MVP de **miConte**.

---

## 1. Requisitos Funcionales (RF)

### Módulo 1: Autenticación OAuth e Integración con YouTube
* **RF-01 (Configuración y Autorización OAuth 2.0):** El sistema debe permitir al propietario de un canal de YouTube autorizar a **miConte** mediante el flujo oficial OAuth 2.0 de Google utilizando alcances (*scopes*) de solo lectura (`https://www.googleapis.com/auth/youtube.readonly`, documentado en Data API v3 y en la referencia de `reports.query`, y `https://www.googleapis.com/auth/yt-analytics.readonly`, enumerado en la guía general de autorización de Analytics/Reporting; sin asumir que un único alcance basta para todos los endpoints hasta su comprobación empírica en la **Fase 2**).
* **RF-02 (Ingesta de Catálogo y Estadísticas Públicas):** El sistema debe consultar `YouTube Data API v3` para obtener los metadatos del canal (`channels.list`), la lista de publicaciones del canal (`playlistItems.list` sobre la lista `uploads`) y las métricas públicas y detalles de duración/publicación de cada video (`videos.list`).
* **RF-03 (Ingesta de Informes Analíticos Privados):** Cuando el canal cuente con autorización OAuth 2.0 válida, el sistema debe consultar `YouTube Analytics API v2` (`reports.query`) para extraer series temporales diarias y métricas agregadas de rendimiento, retención e interacción (y, si se determina necesario en la Fase 2 para métricas de alcance como impresiones/CTR, soportar la ingesta desde `YouTube Reporting API v1`).
* **RF-04 (Distinción Público vs. Privado):** El sistema debe identificar y etiquetar claramente en base de datos y en la API qué métricas provienen de fuentes públicas y cuáles provienen de informes privados autenticados, permitiendo operar en modo "Solo Público" si no se ha concedido OAuth para Analytics.

### Módulo 2: Sincronización y Persistencia Histórica (`miconte_db`)
* **RF-05 (Registro Histórico de Instantáneas y Series):** El sistema debe almacenar en PostgreSQL (`miconte_db`) tanto los metadatos actuales del canal/video como las series temporales diarias e instantáneas (*snapshots*) periódicas de rendimiento, sin sobrescribir destructivamente la evolución histórica.
* **RF-06 (Idempotencia de Sincronización):** La ejecución repetida de un proceso de sincronización para un mismo canal y rango de fechas debe ser idempotente (mediante operaciones `UPSERT` controladas por clave natural `(video_id, target_date)` o `(video_id, captured_at)`), evitando registros duplicados.
* **RF-07 (Trazabilidad de Ejecución de Sincronización):** Cada proceso de sincronización debe registrar un evento de auditoría (`sync_runs`) con marca de tiempo de inicio/fin, origen (`data_api`, `analytics_api`), estado (`success`, `partial`, `failed`), consumo estimado de cuota y errores detallados si ocurrieron.

### Módulo 3: Motor Estadístico Determinista
* **RF-08 (Cálculo de Métricas Derivadas Seguras):** El motor estadístico debe calcular métricas derivadas estandarizadas —incluyendo CTR, Porcentaje Medio Visto (APV), Tasa de Interacción (Engagement Rate) y Velocidad Normalizada ($V_{24h}$, $V_{7d}$)— manejando explícitamente divisiones por cero, duraciones nulas y series vacías sin generar `NaN` no controlados ni excepciones.
* **RF-09 (Validación de Tamaño Muestral, Supuestos y Normalidad):** Antes de ejecutar cualquier inferencia o comparación entre cohortes de videos, el motor debe evaluar el tamaño muestral ($N$) tomando como **referencias heurísticas iniciales** (no como garantías universales de validez) los umbrales de $N \ge 10$ para intervalos de confianza/estimaciones de cohorte, $N_1, N_2 \ge 20$ para comparaciones de dos muestras y $N \ge 30$ para regresiones/series temporales. La selección del método estadístico debe depender conjuntamente del tipo de datos, el cumplimiento de supuestos distribucionales (`Shapiro-Wilk` para $N < 50$, `Kolmogorov-Smirnov` para $N \ge 50$), la varianza/incertidumbre, el tamaño del efecto y la calidad de la muestra.
* **RF-10 (Selección Automática de Estadísticos e Intervalos de Confianza):** Para distribuciones no normales (asimétricas), el motor debe reportar mediana, rango intercuartílico (IQR) y pruebas no paramétricas (`Mann-Whitney U`, `Wilcoxon`). Toda estimación puntual elegible debe acompañarse de su Intervalo de Confianza al 95% ($\text{CI}_{95\%}$) y de la medida de incertidumbre correspondiente.
* **RF-11 (Tratamiento Explícito de Datos Ausentes, Ventanas Incompletas y Censura):** El motor no debe rellenar silenciosamente datos ausentes (`None`/`NaN`) con `0`. Debe distinguir: (a) un valor cero real (p. ej. 0 comentarios), (b) una métrica ausente o suprimida por umbrales de privacidad (`data_suppressed: true`), (c) una **ventana de observación incompleta o truncada** (`incomplete_observation_window: true`, cuando un video aún no ha cumplido la edad de la ventana objetivo, p. ej. $< 72\text{ h}$ o $< 7\text{ d}$) y (d) la **censura estadística formal por la derecha** (`is_right_censored: true`, en análisis de tiempo hasta un evento donde el evento no ha ocurrido al cierre del seguimiento).

### Módulo 4: Motor de Recomendaciones Deterministas
* **RF-12 (Generación de Recomendaciones sin LLM):** El sistema debe generar recomendaciones estructuradas a partir de reglas deterministas evaluadas sobre los resultados del motor estadístico (p. ej., detección de caída significativa en retención o CTR respecto a la línea base del canal, asociación entre rangos de duración y APV, o ventanas de publicación con mayor velocidad inicial).
* **RF-13 (Metadatos de Evidencia y Lenguaje No Causal):** Cada recomendación debe incluir obligatoriamente: métrica evaluada, fuente, periodo temporal, unidad, tamaño de muestra ($N$), intervalo de confianza/valor $p$, limitaciones observadas y una redacción estrictamente descriptiva/asociativa (prohibiendo afirmaciones causales no demostradas).

### Módulo 5: API REST (FastAPI) y Frontend Web (Angular)
* **RF-14 (Exposición vía API REST Tipada):** El backend en FastAPI debe exponer endpoints documentados bajo OpenAPI para gestionar canales, disparar sincronizaciones, consultar métricas descriptivas, comparar cohortes y obtener recomendaciones deterministas.
* **RF-15 (Dashboard Analítico en Angular):** El frontend en Angular debe presentar el resumen de salud del canal, el catálogo analítico de videos, las distribuciones e intervalos de confianza, los avisos de muestra pequeña o censura temporal y las recomendaciones deterministas.

### Módulo 6: Capa de IA (Opcional y Desacoplada)
* **RF-16 (Abstracción e Interpretación con LLM):** El sistema debe definir una interfaz común (`LLMProviderPort`) con soporte inicial para **Ollama** local (y adaptadores intercambiables para APIs externas) que reciba exclusivamente el JSON estructurado de resultados estadísticos y recomendaciones deterministas para generar un resumen interpretativo, sin inventar cifras y permitiendo operar con el adaptador deshabilitado (`NoOpLLMAdapter`).

---

## 2. Requisitos No Funcionales (RNF)

* **RNF-01 (Independencia de LLM y MCP):** El 100% de las rutas críticas del negocio (ingesta, persistencia, cálculo estadístico, recomendaciones deterministas y visualización en UI) deben funcionar con `MICONTE_LLM_ENABLED=false` y sin ningún componente MCP instalado o en ejecución.
* **RNF-02 (Reproducibilidad y Determinismo Matemático):** Dado un mismo conjunto de datos de entrada en `miconte_db` y una semilla fija (`random_state`) para procedimientos de *bootstrapping*, el motor estadístico debe producir exactamente los mismos resultados numéricos en cualquier ejecución.
* **RNF-03 (Aislamiento Arquitectónico del Motor Estadístico):** El paquete del motor estadístico (`miconte.analytics` / `services/statistics`) no debe importar `fastapi`, `sqlalchemy` ni clientes HTTP de LLM. Debe recibir estructuras de datos puras (`DataFrames`, `ndarrays` o `dataclasses`/modelos de dominio) para garantizar su comprobación unitaria offline en milisegundos.
* **RNF-04 (Seguridad y Protección de Credenciales):**
  * Ninguna clave de API, secreto de cliente OAuth ni token de acceso/refresco puede almacenarse en texto plano en el repositorio.
  * Toda configuración sensible debe inyectarse mediante variables de entorno con prefijo `MICONTE_`.
  * Los tokens OAuth 2.0 almacenados en `miconte_db` deben cifrarse en reposo (p. ej. mediante `Fernet` / AES simétrico derivado de `MICONTE_SECRET_KEY`).
  * Todas las consultas a base de datos deben usar parámetros vinculados vía SQLAlchemy ORM/Core (cero interpolación de cadenas SQL).
* **RNF-05 (Respeto de Cuotas y Resiliencia ante APIs de Google):** El cliente de integración con YouTube debe implementar control de presupuesto diario de cuota (*quota budget*), paginación eficiente (máximo de 50 IDs por llamada en `videos.list` y `playlistItems.list`) y reintentos con *exponential backoff* ante errores transitorios (`HTTP 429` / `5xx`).
* **RNF-06 (Calidad, Tipado y Cobertura de Pruebas):**
  * El código Python debe pasar validación estática con `ruff` y chequeo de tipos con `mypy`.
  * El código TypeScript/Angular debe compilar en modo estricto (`strict: true`) sin errores (`ng build`).
  * Toda fórmula estadística debe contar con pruebas unitarias en `pytest` que verifiquen casos nominales, bordes (ceros, vacíos, $N=1$) y restricciones de dominio.
* **RNF-07 (Simplicidad Operativa):** La arquitectura debe ejecutarse localmente como un monolito modular en Python + SPA Angular + instancia PostgreSQL (`miconte_db`), sin requerir orquestadores complejos ni servicios en la nube de pago obligatorios.
* **RNF-08 (Cumplimiento de Políticas de YouTube API, Retención Diferenciada y Plazos Específicos):**
  * **Categorización de Retención y Verificación Periódica (>30 Días):**
    1. *Estadísticas privadas autorizadas (>30 días):* Retenidas para análisis longitudinal del creador mientras subsista la autorización válida, con verificación periódica (al menos cada 30 días) de credenciales activas y de disponibilidad pública de los videos en YouTube.
    2. *Estadísticas públicas no autorizadas por el propietario:* Sujetas a la regla estricta de actualizar o eliminar en un plazo máximo de 30 días calendario sin refresco contra la API.
    3. *Metadatos descriptivos de catálogo:* Sujetos a actualización o eliminación en 30 días y comprobación periódica de disponibilidad de recursos.
  * **Plazos Específicos de Eliminación según Evento Detonante:**
    1. *Solicitudes de eliminación del usuario / baja:* Eliminación definitiva e irreversible de todos los datos del usuario lo antes posible y en un plazo máximo e improrrogable de **7 días calendario** (la regla de 30 días no aplica bajo ninguna circunstancia a solicitudes de eliminación del usuario).
    2. *Desconexión de consentimiento en miConte (`/disconnect`):* Purga **inmediata** de tokens en `oauth_connections`, revocación remota y cese de llamadas; eliminación de datos de API obtenidos bajo ese consentimiento lo antes posible y en un máximo de **7 días calendario** (automática, sin segunda solicitud del usuario).
    3. *Revocación en configuración de Google:* Cese e invalidación de credenciales **inmediatamente tras detección o notificación**; eliminación de datos de API relacionados lo antes posible y en un máximo de **30 días calendario desde la revocación del consentimiento** (la detección tardía no reinicia ni amplía ese plazo).
    4. *Imposibilidad de renovar o verificar autorización:* Cese inmediato y ventana de **30 días** para renovación o eliminación definitiva de datos de API no verificados.
  * **Prohibición de Combinar Datos y Reglas Estrictas de Agregación:** Queda prohibido combinar, consolidar o agregar datos de API procedentes de distintos propietarios de contenido (el consentimiento individual no constituye una excepción). La agregación solo se permite entre canales que estén bajo el **mismo Propietario de Contenido (*Content Owner*) reconocido por YouTube conforme a sus acuerdos de licencia aplicables** (la vinculación en miConte **no** presupone este requisito) y sus resultados deben restringirse exclusivamente a dicho propietario.
  * **Rotulado de Métricas Derivadas:** Toda métrica derivada calculada por miConte debe distinguirse expresamente de las métricas oficiales de YouTube (`source: "miconte_derived"` vs `source: "youtube_official"`).
  * **Condición Previa para Fase 6:** Los métodos del motor estadístico se validan con datos sintéticos en la Fase 6; el uso de datos reales de la API para generar métricas derivadas en producción exige la previa verificación oficial de Google Cloud.

---

## 3. Matriz de Criterios de Aceptación del MVP

| ID | Criterio de Aceptación | Método de Verificación |
| :--- | :--- | :--- |
| **CA-MVP-01** | El motor estadístico ejecuta todas sus pruebas unitarias sin red, sin base de datos activa, sin FastAPI y sin Ollama. | `pytest tests/unit/statistics -v` en entorno sin red (sandbox). |
| **CA-MVP-02** | Cada métrica expuesta en la API incluye metadatos de `source`, `period`, `unit`, `sample_size` y `limitations`. | Inspección de esquemas Pydantic de respuesta y tests de contrato con `HTTPX`. |
| **CA-MVP-03** | Las migraciones de base de datos en `miconte_db` se aplican y revierten limpiamente sin intervención manual. | Ejecución de `alembic upgrade head` y `alembic downgrade -1`. |
| **CA-MVP-04** | La aplicación web y la API funcionan de principio a fin con el proveedor de LLM deshabilitado (`MICONTE_LLM_PROVIDER=none`). | Pruebas de integración de API y de extremo a extremo con Playwright. |
| **CA-MVP-05** | Cuando se activa un proveedor de LLM (Ollama o mock en tests), si el proveedor falla o tarda más del *timeout*, la API devuelve igualmente las métricas y recomendaciones deterministas con un indicador de estado de IA degradado. | Test de integración simulando caída/timeout de Ollama (`HTTPX` mock). |
| **CA-MVP-06** | Ninguna recomendación ni etiqueta de la interfaz utiliza vocabulario causal prohibido ("causó", "provocó", "es la razón de"). | Revisión de plantillas de recomendación y pruebas de regresión sobre el catálogo de reglas. |
| **CA-MVP-07** | El sistema impone aislamiento multi-inquilino absoluto (sin agregaciones cruzadas entre propietarios distintos) y garantiza la eliminación definitiva de datos dentro de 7 días calendario ante solicitud del usuario. | Auditoría de endpoints, pruebas de aislamiento IDOR y verificación documental con `docs/youtube-api-policy-compliance.md`. |
