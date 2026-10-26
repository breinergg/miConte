# Registro de Riesgos, Permisos, Costos y Mitigaciones — miConte (`docs/risks.md`)

Este documento identifica los riesgos técnicos, estadísticos, regulatorios (permisos y cuotas de API), de seguridad y de costos operativos del proyecto **miConte**, junto con sus estrategias de mitigación.

---

## 1. Riesgos de Integración y Permisos (APIs de YouTube)

### R-01: Límites de Cuota en `YouTube Data API v3` (Cuota General vs. Cubo Independiente de `search.list`)
* **Severidad:** Alta | **Probabilidad:** Media
* **Descripción:** En la documentación oficial vigente de `YouTube Data API v3`, Google distingue entre:
  1. **Cuota diaria general del proyecto (*Project Quota Allocation*):** Por defecto **10,000 unidades por día** (reiniciadas a medianoche PT) para operaciones generales, donde `channels.list`, `playlistItems.list` y `videos.list` tienen un costo de **1 unidad por llamada/página** (hasta 50 elementos por página).
  2. **Costo por llamada y límite diario independiente de `search.list` (*Search Queries bucket*):** Según la referencia oficial de `search.list`, cada llamada tiene un costo de **1 unidad** dentro de un cubo de cuota independiente cuyo límite por defecto es de tan solo **100 llamadas a `search.list` por día** por proyecto (anteriormente expresado en el esquema antiguo como 100 unidades sobre 10,000). Cada página adicional solicitada con `pageToken` consume otra llamada de ese tope diario de 100.
  3. **Límites de frecuencia (*Rate Limits*):** Cuotas por minuto/segundo (QPM/QPS) tanto en Data API v3 como en Analytics API v2.
  Si se usara `search.list` para enumerar los videos de un canal, paginar un canal de 500 videos (10 páginas) consumiría 10 de las 100 llamadas diarias disponibles (el 10% del tope diario de búsquedas solo para listar IDs), y 100 páginas de búsqueda en todo el día agotarían por completo el límite diario del proyecto.
* **Mitigación:**
  1. **Evitar `search.list` para enumerar el catálogo del canal:** Utilizar siempre la lista de videos subidos del canal obteniendo `relatedPlaylists.uploads` vía `channels.list(part="contentDetails")` (**1 unidad**) y paginando con `playlistItems.list(maxResults=50)` (**1 unidad por página de 50 videos**).
  2. Consultar los detalles y estadísticas de videos en lotes de hasta 50 IDs mediante `videos.list(id="id1,id2,...", maxResults=50)` (**1 unidad por cada 50 videos**). Con esta estrategia, sincronizar un canal de 500 videos consume únicamente **21 unidades de la cuota general de 10,000 unidades/día** (el 0.21%) y **0 llamadas** del límite diario de 100 búsquedas de `search.list`.
  3. Registrar el consumo de cuota estimado en la tabla `sync_runs` (Fase 3 / Fase 5) e implementar *exponential backoff* ante respuestas `HTTP 429` o `403 quotaExceeded` / `rateLimitExceeded`.

### R-02: Diferencias de Exposición de Impresiones y CTR entre `YouTube Analytics API v2` y `YouTube Reporting API v1`
* **Severidad:** Media | **Probabilidad:** Alta
* **Descripción:** Aunque YouTube Studio muestra Impresiones y CTR de miniaturas, en la documentación oficial de las APIs de Google existe una separación estructural:
  * En **`YouTube Analytics API v2` (`reports.query`)** están documentadas métricas como `views`, `estimatedMinutesWatched`, `averageViewDuration`, `averageViewPercentage`, `likes`, `comments`, `shares`, `subscribersGained`, `subscribersLost` y `cardClickRate`, pero **no** están documentadas `video_thumbnail_impressions` ni `video_thumbnail_impressions_ctr` como métricas de consulta ad-hoc (invocarlas en `reports.query` puede arrojar `400 Bad Request`).
  * En **`YouTube Reporting API v1` (informes masivos asíncronos)** sí están documentadas explícitamente las métricas `video_thumbnail_impressions` y `video_thumbnail_impressions_ctr` dentro de los tipos de reporte **`channel_reach_basic_a1`** (dimensiones: `date`, `channel_id`, `video_id`, `live_or_on_demand`) y **`channel_reach_combined_a1`**.
* **Mitigación:**
  1. No asumir que `reports.query` entrega impresiones de miniaturas. Mantener la **validación empírica en la Fase 2 (Validación Técnica de las APIs de YouTube)** para comprobar tanto `Analytics API v2` como la programación/descarga de reportes en `Reporting API v1`.
  2. Diseñar el modelo de datos (Fase 3) y el motor estadístico (Fase 6) para que `video_thumbnail_impressions` y `video_thumbnail_impressions_ctr` registren explícitamente su fuente (`youtube_reporting_api_v1` si se ingiere el reporte masivo, o `None` con limitación documentada cuando solo se consulte `Analytics API v2`), sin bloquear el resto de métricas analíticas.

### R-03: Latencia de Consolidación (48–72 horas) y Ventanas de Observación Incompletas
* **Severidad:** Media | **Probabilidad:** Cierta (100%)
* **Descripción:** Los informes de `YouTube Analytics API v2` y `YouTube Reporting API v1` tardan entre 48 y 72 horas en publicarse y estabilizarse. Además, los videos recién publicados aún no han completado las ventanas temporales de referencia (p. ej. 24h, 72h o 7 días).
* **Mitigación:**
  1. El servicio de sincronización (Fase 5) utilizará una **ventana móvil de re-sincronización** (re-consultando los últimos 7 días en cada ejecución incremental) aplicando `UPSERT` sobre `(video_id, metric_date)`.
  2. El motor estadístico (Fase 6) distinguirá entre la **falta de una ventana completa de observación** (`incomplete_observation_window = True`, para videos cuya edad actual $\Delta t$ sea menor que la ventana evaluada) y la **censura estadística formal por la derecha** (`is_right_censored = True`, reservada para modelos de tiempo hasta un evento).

### R-04: Permisos OAuth 2.0, Discrepancias Documentales de Scopes y Verificación en Google Cloud
* **Severidad:** Media | **Probabilidad:** Media
* **Descripción:** Los endpoints privados requieren autorización OAuth 2.0 otorgada por el usuario propietario del canal (las cuentas de servicio no están soportadas para canales estándar). En la documentación oficial de `YouTube Analytics API v2` existe una diferencia entre guías: la referencia del método `reports.query` indica que requiere el alcance `https://www.googleapis.com/auth/youtube.readonly` (o equivalentes de gestión), mientras que la guía general de autorización de Analytics API y Reporting API enumera también `https://www.googleapis.com/auth/yt-analytics.readonly` para informes no monetarios.
* **Mitigación:**
  1. **No asumir que un único *scope* es suficiente para todos los endpoints sin validación:** En la **Fase 2 (Validación Técnica de las APIs de YouTube)**, comprobar empíricamente el comportamiento de `channels.list`, `reports.query` y, en su caso, `jobs.list`/`reports.list` de Reporting API probando los alcances `youtube.readonly` y `yt-analytics.readonly` tanto por separado como combinados.
  2. Para desarrollo y uso propio en el MVP, configurar la pantalla de consentimiento OAuth en modo **Testing** (hasta 100 usuarios de prueba autorizados) y solicitar únicamente alcances `readonly` (principio de mínimo privilegio).

---

## 2. Riesgos del Entorno Local y Dependencias Técnicas

### R-05: Incompatibilidad de Versiones de Python y Angular CLI Preinstaladas en el Host Local
* **Severidad:** Alta | **Probabilidad:** Confirmada (Verificado en Fase 0)
* **Descripción:** En la inspección de la máquina local se detectó que:
  * `/usr/bin/python3` es **Python 3.9.6** (versión EOL desde octubre de 2025) y `/opt/homebrew/bin/python3` es **Python 3.15.0** (versión en desarrollo/pre-lanzamiento donde paquetes con extensiones C/Fortran como `scipy`, `statsmodels`, `pandas` o `pydantic-core` pueden carecer de ruedas precompiladas estables).
  * El binario global `/usr/local/bin/ng` corresponde a **Angular CLI 19.2.27**, cuya rama mayor (Angular 19) alcanzó el fin de su soporte LTS de 18 meses en mayo de 2026 (EOL).
* **Mitigación:**
  1. En la **Fase 1 (Entorno y Persistencia Inicial)**, aprovisionar el entorno virtual del backend con una versión estable soportada de Python (**Python 3.13** —o **3.14** verificando ruedas binarias ARM64—, manteniendo rango compatible `>=3.12,<3.15`), sin utilizar Python 3.9 ni Python 3.15.
  2. En la **Fase 8 (Interfaz Web)**, generar y mantener el proyecto frontend con una versión en soporte activo/LTS vigente (**Angular 21 LTS** o **Angular 20 LTS** / **22**, ejecutando `npx @angular/cli@21` sobre el Node.js `v22.23.1` LTS ya instalado) en lugar de usar la versión global EOL `19.2.27`.

### R-06: Ausencia de Cliente/Servidor PostgreSQL Nativo en `PATH`
* **Severidad:** Baja | **Probabilidad:** Confirmada (Verificado en Fase 0)
* **Descripción:** El binario `psql` no se encuentra instalado en el host local, pero **Docker (`Docker.app`) sí está instalado**.
* **Mitigación:**
  1. Proveer en la **Fase 1 (Entorno y Persistencia Inicial)** la configuración para levantar **PostgreSQL 16/17 (`miconte_db`)** mediante Docker con volumen persistente local o instancia local gestionada.

---

## 3. Riesgos Estadísticos y de Inteligencia Artificial

### R-07: Conclusiones Inválidas por Muestras Pequeñas, Supuestos Incumplidos o Distribuciones Asimétricas
* **Severidad:** Alta | **Probabilidad:** Alta (si no se controla)
* **Descripción:** Los canales nuevos o de nicho tienen pocos videos, y las vistas siguen distribuciones fuertemente asimétricas o de cola pesada donde un único video viral distorsiona la media aritmética. Además, aplicar umbrales fijos ($N \ge 10$, $N \ge 20$, $N \ge 30$) de forma ciega no garantiza validez ni potencia estadística si los supuestos del método no se cumplen.
* **Mitigación:**
  1. Tratar los umbrales $N \ge 10$, $N_1, N_2 \ge 20$ y $N \ge 30$ únicamente como **referencias heurísticas iniciales sujetas a justificación metodológica**, nunca como garantías universales.
  2. En la **Fase 6 (Motor Estadístico)**, condicionar la selección de métodos al tipo de dato, verificación de normalidad (`Shapiro-Wilk` / `Kolmogorov-Smirnov`), tamaño del efecto, incertidumbre ($\text{CI}_{95\%}$) y calidad de la muestra, priorizando **Mediana**, **IQR** y pruebas no paramétricas (`Mann-Whitney U`, `Wilcoxon`) ante asimetría.
  3. Prohibir estrictamente presentar correlaciones observacionales como relaciones causales.

### R-08: Alucinación Numérica o Afirmación Causal por Parte del LLM
* **Severidad:** Alta | **Probabilidad:** Media (en Fase 9)
* **Descripción:** Un modelo de lenguaje puede inventar porcentajes que no existen en la base de datos o redactar frases causales prohibidas ("cambiar la duración a 12 minutos hizo que tus vistas subieran").
* **Mitigación:**
  1. El LLM (incorporado recién en la **Fase 9: Capa de IA Intercambiable**) jamás calcula métricas; solo recibe el JSON final ya calculado por `miconte.statistics` (Fase 6) y `miconte.recommendations` (Fase 7).
  2. La respuesta de la API separa siempre en campos distintos los datos deterministas (`deterministic_data`) de la narrativa opcional (`ai_interpretation`).
  3. El *prompt* del sistema incluye reglas estrictas de vocabulario no causal y un filtro de post-procesamiento valida que el texto generado no contenga términos causales prohibidos ni contradiga la disponibilidad de datos.

---

## 4. Riesgos de Seguridad y Costos Operativos

### R-09: Exposición de Credenciales OAuth 2.0 o Secretos de API
* **Severidad:** Crítica | **Probabilidad:** Mitigada (Controles activos de Fase 4)
* **Descripción:** Filtración de `client_secret`, API Keys o tokens OAuth (`access_token`, `refresh_token`) de los canales conectados en logs, respuestas de API, volcados de base de datos o commits de Git.
* **Estado de Mitigación Implementado en Fase 4 (ADR-0006):**
  1. **Servicio Criptográfico Operativo:** Se implementó `TokenEncryptionService` (`miconte.security.crypto`) utilizando **AES-256-GCM** (cifrado simétrico autenticado de 256 bits vía `cryptography`).
  2. **Nonces Únicos y Formato Versionado:** Cada operación genera un nonce CSPRNG de 96 bits (`os.urandom(12)`) y almacena el ciphertext bajo la envoltura `v1:<key_id>:<nonce>:<ciphertext+tag>`, soportando rotación de claves sin alterar el esquema de la base de datos.
  3. **Vinculación de Contexto por AAD:** Se vincula cada token al contexto `user_id:platform:external_channel_id:credential_kind`, impidiendo trasplantes de credenciales entre usuarios o canales.
  4. **Detección de Modificación (*Tamper Detection*):** Modificaciones de un solo bit en el ciphertext o en el AAD provocan un fallo inmediato de autenticación (`DecryptionError`).
  5. **Separación de Claves:** La clave maestra se inyecta por entorno (`MICONTE_TOKEN_ENCRYPTION_KEY`), nunca en la base de datos ni en Git.
  6. **Protección en Logs y API REST:** Las excepciones sanitizadas nunca exponen material criptográfico sensible. Los endpoints `/api/v1/oauth/youtube/*` nunca devuelven tokens al frontend en sus respuestas.
  7. **Preservación de Refresh Tokens:** `OAuthService` preserva el `refresh_token` previo si Google omite emitirlo en consentimientos subsiguientes, garantizando continuidad sin exponer credenciales en plano.

### R-10: Costos Operativos Inesperados (Cloud, APIs de Terceros y LLMs)
* **Severidad:** Baja | **Probabilidad:** Baja
* **Descripción:** El uso de bases de datos gestionadas en la nube o APIs comerciales de LLM podría generar costos recurrentes para el creador o desarrollador.
* **Mitigación:**
  1. **Costo \$0 en el MVP:** PostgreSQL (`miconte_db`) se ejecuta localmente; las APIs oficiales de YouTube (`Data API v3`, `Analytics API v2` y `Reporting API v1`) son gratuitas dentro de la cuota estándar de Google Cloud; y el motor estadístico/recomendador no consume tokens de IA.
  2. En la **Fase 9**, la primera opción de IA es **Ollama ejecutado localmente** (costo \$0 por token), manteniendo los adaptadores de APIs externas apagados por defecto.

---

## 5. Riesgos del Motor de Sincronización (Fase 5 / ADR-0007)

### R-11: Carreras Concurrenciales y Sincronizaciones Duplicadas
* **Severidad:** Media | **Probabilidad:** Media (si no se controla)
* **Descripción:** Una sincronización periódica programada y una invocación manual simultánea para el mismo canal podrían generar sobreescrituras en base de datos o llamadas redundantes a las APIs de YouTube.
* **Mitigación Implementada (ADR-0007):**
  1. **Bloqueo Asíncrono por Canal (`asyncio.Lock`):** `SyncScheduler` mantiene un bloqueo por cada `channel_id`. Si se intenta una sincronización concurrente sobre el mismo canal, se rechaza de inmediato con `RuntimeError: already in progress` (`HTTP 409 Conflict`).
  2. **Idempotencia Estricta:** Las restricciones de unicidad compuestas en PostgreSQL (`channel_id, captured_at`, `video_id, captured_at`, `channel_id, metric_date`, `video_id, metric_date`) garantizan que dos operaciones concurrentes nunca creen filas duplicadas.
  3. **Requisito Multiworker:** Para despliegues horizontales futuros en producción con múltiples workers de Uvicorn/Gunicorn, se requerirá un mecanismo distribuido (PostgreSQL Advisory Locks o Redis) para coordinar los bloqueos entre procesos independientes.

### R-12: Latencia de 48h de Reporting API y Desincronización Temporal
* **Severidad:** Media | **Probabilidad:** Alta
* **Descripción:** `YouTube Reporting API v1` no genera reportes en tiempo real tras la creación del trabajo (`channel_reach_basic_a1`), tardando hasta 48 horas en emitir el primer archivo CSV.
* **Mitigación Implementada:**
  1. `SyncService` comprueba la existencia del trabajo y sus reportes. Si no hay archivos disponibles, registra la etapa como `pending` sin bloquear el worker ni marcar la sincronización como fallida (`partially_succeeded`).
  2. Cuando el reporte esté disponible en ciclos posteriores, se descarga de forma segura y se actualizan retroactivamente las métricas de alcance en `video_daily_metrics`.
  3. Se registran los identificadores de reportes ya ingeridos para evitar descargas redundantes.

---

## 6. Riesgos Regulatorios y Políticas de YouTube API (Fase 5 / Fase 6)

### R-13: Cumplimiento de Políticas de Términos de Servicio de YouTube API y Métricas Derivadas
* **Severidad:** Alta | **Probabilidad:** Media (requiere trámite formal ante Google)
* **Descripción:** El uso de datos de YouTube para calcular métricas derivadas (CTR, engagement rates, velocidad $V_{24h}$) y la retención histórica en PostgreSQL (`miconte_db`) están sujetos a estrictas obligaciones regulatorias bajo los [Términos de Servicio de YouTube API (Sección III.E)](https://developers.google.com/youtube/terms/api-services-terms-of-service) y las Políticas para Desarrolladores de YouTube. El incumplimiento o despliegue no verificado puede resultar en revocación de credenciales OAuth, bloqueo de cuota o sanciones de plataforma.
* **Detalle Completo:** Consultar el documento oficial [`docs/youtube-api-policy-compliance.md`](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/youtube-api-policy-compliance.md).
* **Mitigaciones y Principios Aplicados:**
  1. **Distinción Explícita de Métricas:** Se exige distinguir claramente en todo momento las métricas suministradas directamente por YouTube (`source: "youtube_official"`) de las métricas calculadas por miConte (`source: "miconte_derived"`), impidiendo presentar cálculos derivados como cifras oficiales de YouTube.
  2. **Reglas de Retención y Purga de Datos (Regla de 30 Días):** Los datos no se almacenan por más de 30 días sin actualización. Si el usuario se desconecta a través de `/api/v1/oauth/youtube/disconnect`, los tokens se eliminan inmediatamente de `oauth_connections`.
  3. **Aislamiento Multi-Inquilino Absoluto:** Está terminantemente prohibido agregar o cruzar datos analíticos confidenciales entre canales de distintos creadores para crear inteligencia competitiva o rankings compartidos sin consentimiento. Cada usuario únicamente accede a sus propios canales.
  4. **Preservación de Auditoría de Anomalías:** Si una anomalía o dato inesperado (como recuentos negativos de likes) es suprimido de las métricas normales o convertido a `None` para proteger la consistencia estadística, la evidencia del dato observado y el motivo de la anomalía se preservan en el registro de auditoría (`sync_runs`).
  5. **Declaración de Estado y Condición Previa para Fase 6:** miConte **NO** se encuentra formalmente autorizado ni auditado en producción por Google Cloud a la fecha. La verificación OAuth y la auditoría de cumplimiento son un requisito previo formal indispensable antes de operar con datos reales de producción en la **Fase 6**.
