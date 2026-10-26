# Matriz de Compatibilidad y Validación Técnica de APIs de YouTube — miConte (`docs/youtube-api-compatibility.md`)

Este documento registra los hallazgos técnicos, la matriz de compatibilidad de campos y métricas, las reglas de combinación de dimensiones, los requisitos de autorización OAuth 2.0 y los límites de cuota verificados durante la **Fase 2: Validación Técnica de las APIs de YouTube**.

---

## 1. Definición de Estados de Verificación

Para mantener trazabilidad estricta y no confundir pruebas con respuestas controladas (*fixtures*) con consultas en vivo contra los servidores de Google, se emplean exclusivamente los siguientes estados:

* **`verified_live`**: Comprobado empíricamente con una consulta HTTP real contra los endpoints de Google utilizando credenciales válidas.
* **`verified_offline`**: Esquema de contrato, parseo, restricciones de parámetros y manejo de errores probados mediante `pytest` + `httpx.MockTransport` con cargas útiles fieles a la especificación oficial (`tests/test_youtube_phase2_validation.py`).
* **`documented_not_tested`**: Documentado en las guías oficiales vigentes de Google Developers, pero pendiente de ejecución en vivo por ausencia de credenciales OAuth / API Key locales en el entorno actual.
* **`unavailable`**: No disponible para el endpoint o combinación de dimensiones/métricas evaluada (produce `HTTP 400 Bad Request` según la especificación oficial).
* **`permission_error`**: La consulta falla con `HTTP 403 Forbidden` por alcance OAuth insuficiente o falta de propiedad sobre el canal.
* **`not_applicable`**: Fuera del alcance del MVP de **miConte** (p. ej. métricas monetarias o permisos de escritura).

> **Estado del Entorno en Fase 2:** En la inspección del entorno local (`.env`, variables `MICONTE_YOUTUBE_*`, `gcloud`) se constató que **no existen credenciales reales de Google Cloud ni tokens OAuth locales configurados**. Por tanto, todas las validaciones de parseo, paginación, lotes, duraciones ISO 8601 y clasificación de errores alcanzan el estado **`verified_offline`** (con su correspondiente especificación **`documented_not_tested`** para la ejecución en vivo), y ningún elemento se marca falsamente como `verified_live`.

---

## 2. Evaluación de APIs, Endpoints y Reglas de Consulta

### 2.1 YouTube Data API v3 (`https://www.googleapis.com/youtube/v3`)
* **Endpoints evaluados:**
  1. `GET /channels` (`part=snippet,contentDetails,statistics`):
     * Recupera metadatos del canal y el identificador de la lista de videos subidos (`contentDetails.relatedPlaylists.uploads`).
     * Soporta consulta pública mediante parámetro `key={API_KEY}&id={CHANNEL_ID}` o consulta autenticada del propio canal mediante `mine=true` con cabecera `Authorization: Bearer {ACCESS_TOKEN}`.
  2. `GET /playlistItems` (`part=contentDetails`, `playlistId={UPLOADS_PLAYLIST_ID}`, `maxResults=50`):
     * Enumera las publicaciones subidas por el canal paginando mediante `nextPageToken` $\rightarrow$ `pageToken`.
     * Límite de lote por página: `maxResults` de `1` a `50` (por defecto `5`).
  3. `GET /videos` (`part=snippet,contentDetails,statistics`, `id={CSV_UP_TO_50_IDS}`):
     * Recupera detalles y conteos públicos acumulados de hasta **50 videos en una sola llamada**.
* **Estrategia de enumeración confirmada:** La cadena `channels.list` $\rightarrow$ `playlistItems.list` $\rightarrow$ `videos.list` (en lotes de 50 IDs) evita por completo tocar el cubo restringido de `search.list` (limitado a 100 llamadas diarias).

### 2.2 YouTube Analytics API v2 (`https://youtubeanalytics.googleapis.com/v2/reports`)
* **Método evaluado:** `GET /v2/reports` (`reports.query`).
* **Hallazgo crítico sobre combinaciones de dimensiones (`video` vs. `day`):**
  * **Combinación NO soportada (`unavailable`):** Solicitar `dimensions=video,day` en una misma consulta a `reports.query` **no es una combinación válida** en los reportes de canal de YouTube Analytics API y devuelve `HTTP 400 Bad Request`.
  * **Patrones válidos soportados:**
    1. **Serie temporal diaria del canal completo:** `ids=channel==MINE`, `dimensions=day`, `startDate=YYYY-MM-DD`, `endDate=YYYY-MM-DD`.
    2. **Serie temporal diaria de un video específico:** `ids=channel==MINE`, `dimensions=day`, `filters=video=={VIDEO_ID}` (o lista acotada de IDs).
    3. **Ranking/Totales agregados por video en un periodo:** `ids=channel==MINE`, `dimensions=video`, `sort=-views` (parámetro `sort` obligatorio al usar `dimensions=video`), `maxResults<=200` (paginable con `startIndex`), o bien filtrando lotes de videos con `filters=video==ID1,ID2,...` sin exigir `sort`.

### 2.3 YouTube Reporting API v1 (`https://youtubereporting.googleapis.com/v1`)
* **Endpoints evaluados:**
  * `GET /v1/reportTypes` (`reportTypes.list`)
  * `POST /v1/jobs` (`jobs.create`) y `GET /v1/jobs` (`jobs.list`)
  * `GET /v1/jobs/{jobId}/reports` (`jobs.reports.list`)
* **Carácter asíncrono y regla de las 48 horas:**
  * A diferencia de `Analytics API v2`, `Reporting API v1` no ejecuta consultas en tiempo real. Primero debe crearse un trabajo recurrente (`jobs.create`) para el `reportTypeId` deseado (p. ej. `channel_reach_basic_a1`).
  * **Latencia inicial de generación:** Tras invocar `jobs.create`, YouTube tarda **hasta 48 horas** en generar el primer archivo descargable (`downloadUrl`). Por ello, el validador (`YouTubePhase2Validator.check_reporting_job_reports`) distingue explícitamente entre:
    * Reporte disponible para descarga (`status="reports_available"`).
    * Trabajo creado pero aún sin archivos generados por la ventana de 48h (`status="pending_generation"`).
    * Tipo de reporte no disponible o error de permisos (`unavailable` / `permission_error`).
* **Zona Horaria y Ventanas Temporales:**
  * **Zona horaria estándar UTC:** Las marcas de tiempo del periodo de reporte (`startTime`, `endTime`, `createTime`) están estrictamente definidas en **UTC (RFC 3339 `Z`)**, abarcando de medianoche a medianoche UTC (`00:00:00Z` a `00:00:00Z`). Los valores en la columna `date` de los archivos CSV (formato `YYYYMMDD`) representan la fecha calendario en UTC.
* **Manejo de Reportes Vacíos:**
  * YouTube emite archivos CSV vacíos (0 bytes o sin registros de datos) para días calendario en los que el canal no registró eventos de alcance (impresiones o clics). El cliente y el motor de sincronización gestionan estos archivos de forma transparente sin considerarlos fallos o corrupciones.
* **Actualizaciones Retroactivas (*Backfill* y Re-emisión de Versiones):**
  * Ocasionalmente, YouTube emite una nueva versión de un reporte para un periodo pasado para consolidar datos tardíos. Dicho reporte conserva el mismo intervalo `[startTime, endTime)` pero presenta un `createTime` posterior y un nuevo `report_id`. El motor de sincronización (`SyncService`) compara las marcas `createTime` y sustituye los datos previos mediante *upsert* sin duplicar filas en `video_daily_metrics`.

---

## 3. Matriz de Compatibilidad de Campos y Métricas

| Métrica / Campo (`miconte`) | Campo Oficial en API | API y Endpoint / Reporte | Tipo y Unidad | Dimensiones y Filtros Compatibles | Autenticación y Scope Documentado | Restricciones de Acceso y Cuota | Estado de Verificación | Evidencia / Referencia Oficial | Limitaciones y Observaciones para Fase 3 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `channel_id` | `id` | `Data API v3` (`channels.list`) | `str` (ID) | `id={CHANNEL_ID}` o `mine=true` | Pública: `API Key`<br>OAuth (`mine=true`): `youtube.readonly` | 1 unidad / llamada (Pool general 10,000 u/día) | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/v3/docs/channels/list` | Clave natural externa del canal (`UC...`). |
| `uploads_playlist_id` | `contentDetails.relatedPlaylists.uploads` | `Data API v3` (`channels.list`) | `str` (ID) | `part=contentDetails` | Pública: `API Key`<br>OAuth: `youtube.readonly` | 1 unidad / llamada (incluida en la misma llamada de `channels.list`) | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/v3/docs/channels#contentDetails.relatedPlaylists.uploads` | Indispensable para enumerar videos sin usar `search.list`. |
| `channel_view_count` | `statistics.viewCount` | `Data API v3` (`channels.list`) | `int` (`count`) | `part=statistics` | Pública: `API Key`<br>OAuth: `youtube.readonly` | 1 unidad / llamada | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/v3/docs/channels#statistics.viewCount` | Viene como `string` numérico en el JSON; se convierte a `int` (`BIGINT` en DB). |
| `channel_subscriber_count` | `statistics.subscriberCount` | `Data API v3` (`channels.list`) | `int \| None` (`count`) | `part=statistics` | Pública: `API Key`<br>OAuth: `youtube.readonly` | 1 unidad / llamada | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/v3/docs/channels#statistics.subscriberCount` | Redondeado a 3 cifras significativas por YouTube. Si `hiddenSubscriberCount=true`, debe guardarse como `NULL`. |
| `channel_video_count` | `statistics.videoCount` | `Data API v3` (`channels.list`) | `int` (`count`) | `part=statistics` | Pública: `API Key`<br>OAuth: `youtube.readonly` | 1 unidad / llamada | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/v3/docs/channels#statistics.videoCount` | Conteo de videos públicos del canal. |
| `playlist_video_id` | `contentDetails.videoId` | `Data API v3` (`playlistItems.list`) | `str` (ID) | `playlistId={UPLOADS_ID}`, `maxResults<=50`, `pageToken` | Pública: `API Key`<br>OAuth: `youtube.readonly` | 1 unidad / página de hasta 50 videos | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/v3/docs/playlistItems/list` | Paginación validada en `test_list_upload_video_ids_handles_pagination`. |
| `video_published_at` | `snippet.publishedAt` | `Data API v3` (`videos.list`) | `datetime` (ISO 8601 UTC) | `id={CSV_50_IDS}`, `part=snippet` | Pública: `API Key`<br>OAuth: `youtube.readonly` | 1 unidad / lote de hasta 50 IDs | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/v3/docs/videos/list` | Almacenar como `TIMESTAMPTZ` en PostgreSQL. |
| `video_duration_seconds` | `contentDetails.duration` | `Data API v3` (`videos.list`) | `int` (`seconds`) | `id={CSV_50_IDS}`, `part=contentDetails` | Pública: `API Key`<br>OAuth: `youtube.readonly` | 1 unidad / lote de hasta 50 IDs | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/v3/docs/videos#contentDetails.duration` | Formato original ISO 8601 (`PT#H#M#S`). Conversión validada en `parse_iso8601_duration_to_seconds`. |
| `video_view_count_snapshot` | `statistics.viewCount` | `Data API v3` (`videos.list`) | `int` (`count`) | `id={CSV_50_IDS}`, `part=statistics` | Pública: `API Key`<br>OAuth: `youtube.readonly` | 1 unidad / lote de hasta 50 IDs | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/v3/docs/videos#statistics.viewCount` | Instantánea acumulada en `captured_at`. |
| `video_like_count_snapshot` | `statistics.likeCount` | `Data API v3` (`videos.list`) | `int \| None` (`count`) | `id={CSV_50_IDS}`, `part=statistics` | Pública: `API Key`<br>OAuth: `youtube.readonly` | 1 unidad / lote de hasta 50 IDs | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/v3/docs/videos#statistics.likeCount` | **Campo opcional:** Ausente en el JSON si el creador oculta los likes. Debe ser columna `NULLABLE` en Fase 3. |
| `video_comment_count_snapshot` | `statistics.commentCount` | `Data API v3` (`videos.list`) | `int \| None` (`count`) | `id={CSV_50_IDS}`, `part=statistics` | Pública: `API Key`<br>OAuth: `youtube.readonly` | 1 unidad / lote de hasta 50 IDs | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/v3/docs/videos#statistics.commentCount` | **Campo opcional:** Ausente si los comentarios están desactivados. Debe ser `NULLABLE` en Fase 3. |
| `views` (serie/agregado) | `views` | `Analytics API v2` (`reports.query`) | `int` (`count`) | `dimensions=day` (con o sin `filters=video==ID`) o `dimensions=video` (`sort` req.) | OAuth 2.0 propietario (`youtube.readonly` + `yt-analytics.readonly`) | Cuota Analytics API (~100,000 consultas/día) | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/analytics/metrics#views` | Latencia de consolidación de 48–72 horas. |
| `estimated_minutes_watched` | `estimatedMinutesWatched` | `Analytics API v2` (`reports.query`) | `int` (`minutes`) | `dimensions=day` o `dimensions=video` | OAuth 2.0 propietario (`youtube.readonly` + `yt-analytics.readonly`) | Cuota Analytics API | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/analytics/metrics#estimatedMinutesWatched` | Puede consultarse en el mismo informe junto con `views`, retención e interacciones. |
| `average_view_duration_sec` | `averageViewDuration` | `Analytics API v2` (`reports.query`) | `int` (`seconds`) | `dimensions=day` o `dimensions=video` | OAuth 2.0 propietario (`youtube.readonly` + `yt-analytics.readonly`) | Cuota Analytics API | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/analytics/metrics#averageViewDuration` | Duración media en segundos por visualización. |
| `average_view_percentage` | `averageViewPercentage` | `Analytics API v2` (`reports.query`) | `float` (`percentage`) | `dimensions=day` o `dimensions=video` | OAuth 2.0 propietario (`youtube.readonly` + `yt-analytics.readonly`) | Cuota Analytics API | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/analytics/metrics#averageViewPercentage` | Puede superar `100.0` si hay repeticiones (*rewatches*). |
| `likes`, `comments`, `shares` | `likes`, `comments`, `shares` | `Analytics API v2` (`reports.query`) | `int` (`count`) | `dimensions=day` o `dimensions=video` | OAuth 2.0 propietario (`youtube.readonly` + `yt-analytics.readonly`) | Cuota Analytics API | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/analytics/metrics#likes` | Métrica de actividad del periodo: número de veces que los usuarios indicaron que les gustó un video otorgando una calificación positiva (no es saldo neto). Si una respuesta de la API llegara a contener un valor negativo, debe aislarse y tratarse como anomalía técnica sujeta a investigación. |
| `subscribers_gained`, `subscribers_lost` | `subscribersGained`, `subscribersLost` | `Analytics API v2` (`reports.query`) | `int` (`count`) | `dimensions=day` o `dimensions=video` | OAuth 2.0 propietario (`youtube.readonly` + `yt-analytics.readonly`) | Cuota Analytics API | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/analytics/metrics#subscribersGained` | Compatibles en el mismo reporte de actividad básica. |
| Combinación `dimensions=video,day` | `video,day` | `Analytics API v2` (`reports.query`) | N/A | Inválida cuando se solicitan ambas como dimensiones simultáneas | OAuth 2.0 | Devuelve `HTTP 400 Bad Request` | `unavailable` (Validado y bloqueado en código) | `developers.google.com/youtube/analytics/v1/channel_reports` | Para serie diaria por video debe usarse `dimensions=day` con `filters=video==VIDEO_ID`. |
| `video_thumbnail_impressions` en `reports.query` | N/A en `reports.query` | `Analytics API v2` (`reports.query`) | N/A | No expuesta en el endpoint ad-hoc `reports.query` | OAuth 2.0 | Devuelve `HTTP 400 Bad Request` | `unavailable` | `developers.google.com/youtube/analytics/metrics` | No está disponible en `Analytics API v2`; requiere `Reporting API v1`. |
| `video_thumbnail_impressions` | `video_thumbnail_impressions` | `Reporting API v1` (`channel_reach_basic_a1` / `channel_reach_combined_a1`) | `int` (`count`) | Columnas fijas del CSV: `date`, `channel_id`, `video_id`, `live_or_on_demand` | OAuth 2.0 propietario (`yt-analytics.readonly` / `youtube.readonly`) | Proceso asíncrono (hasta 48h tras `jobs.create`) | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/reporting/v1/reports/channel_reports#video-reach-reports` | Solo disponible vía descarga de reporte masivo CSV tras crear el job de alcance. |
| `video_thumbnail_impressions_ctr` | `video_thumbnail_impressions_ctr` | `Reporting API v1` (`channel_reach_basic_a1` / `channel_reach_combined_a1`) | `float` (`ratio` $[0,1]$) | Columnas fijas del CSV: `date`, `channel_id`, `video_id`, `live_or_on_demand` | OAuth 2.0 propietario (`yt-analytics.readonly` / `youtube.readonly`) | Proceso asíncrono (hasta 48h tras `jobs.create`) | `verified_offline` / `documented_not_tested` | `developers.google.com/youtube/reporting/v1/reports/channel_reports#video-reach-reports` | Anulable (`NULL`) en el modelo de dominio de Fase 3 cuando solo se sincronice `Analytics API v2`. |
| Métricas monetarias (`estimatedRevenue`, `cpm`) | `estimatedRevenue`, etc. | `Analytics API v2` / `Reporting API v1` | `float` (`currency`) | N/A | `yt-analytics-monetary.readonly` | Requiere permiso monetario | `not_applicable` | `developers.google.com/youtube/analytics/metrics` | Fuera del alcance del MVP. |

---

## 4. Validación de OAuth 2.0 y Permisos por API

1. **YouTube Data API v3:**
   * **Con API Key (`key=...`):** Permite consultar cualquier canal público (`channels.list` con `id=...`), su lista pública de videos subidos (`playlistItems.list`) y las estadísticas públicas de sus videos (`videos.list`). No permite usar `mine=true`.
   * **Con OAuth 2.0 (`https://www.googleapis.com/auth/youtube.readonly`):** Permite además identificar automáticamente el canal del usuario autenticado mediante `channels.list(mine=true)`.
2. **YouTube Analytics API v2 (`reports.query`):**
   * **Requisito obligatorio:** OAuth 2.0 de usuario propietario del canal (las cuentas de servicio estándar sin delegación devuelven error `403 Forbidden`).
   * **Discrepancia documental registrada:**
     * La página de referencia específica de `reports.query` (`developers.google.com/youtube/analytics/reference/reports/query`) lista bajo la sección *Authorization* los alcances `https://www.googleapis.com/auth/youtube.readonly`, `https://www.googleapis.com/auth/youtube` y `https://www.googleapis.com/auth/youtubepartner`.
     * La guía general de autorización de Analytics y Reporting (`developers.google.com/youtube/reporting/guides/authorization`) enumera `https://www.googleapis.com/auth/yt-analytics.readonly` para todos los informes no monetarios.
   * **Decisión técnica para Fase 3 / Fase 4:** Al solicitar autorización OAuth 2.0 de solo lectura en **miConte**, se solicitarán **ambos alcances simultáneamente** (`youtube.readonly` y `yt-analytics.readonly`). Ambos son estrictamente de solo lectura (`readonly`), no piden permisos de escritura ni monetización, y cubrirán tanto `Data API v3` (`mine=true`) como `Analytics API v2` (`reports.query`) y `Reporting API v1` sin ambigüedad.
3. **YouTube Reporting API v1:**
   * Requiere OAuth 2.0 con `https://www.googleapis.com/auth/yt-analytics.readonly` (acompañado de `youtube.readonly`).

---

## 5. Cuotas y Estrategia de Consulta Validada

| API / Método | Cubo de Cuota (*Quota Bucket*) | Límite Diario por Defecto | Costo por Llamada / Página | Uso en `miConte` |
| :--- | :--- | :--- | :--- | :--- |
| `Data API v3` — `channels.list` | Pool general de `YouTube Data API v3` | 10,000 unidades / día | **1 unidad** | 1 llamada por sincronización para obtener metadatos del canal y `uploads_playlist_id`. |
| `Data API v3` — `playlistItems.list` | Pool general de `YouTube Data API v3` | 10,000 unidades / día | **1 unidad** (hasta 50 videos/página) | 1 llamada por cada 50 videos para enumerar IDs de publicaciones. |
| `Data API v3` — `videos.list` | Pool general de `YouTube Data API v3` | 10,000 unidades / día | **1 unidad** (lote de hasta 50 IDs) | 1 llamada por cada 50 videos para obtener duración ISO 8601 y conteos públicos. |
| `Data API v3` — `search.list` | Cubo independiente *Search Queries* | **100 llamadas / día** | **1 unidad** (del cubo de 100 búsquedas) | **Descartado para enumeración de catálogo** (agotaría el cubo de 100 búsquedas diarias). |
| `Analytics API v2` — `reports.query` | Cuota de `YouTube Analytics API` | ~100,000 consultas / día | **1 consulta** | Consultas agregadas por periodo (`dimensions=video`, `sort=-views`, `maxResults=200`) y series diarias (`dimensions=day`). |
| `Reporting API v1` — `jobs.*` | Cuota de `YouTube Reporting API` | Alta capacidad (descarga de CSV diario) | **1 llamada** | Opcional/Asíncrono para reportes `channel_reach_basic_a1` (impresiones y CTR). |

---

## 6. Recomendaciones Directas para el Diseño del Modelo de Datos en la Fase 3

A partir de la evidencia técnica y las restricciones verificadas en esta Fase 2, el diseño del esquema relacional en PostgreSQL (`miconte_db`) durante la **Fase 3 (Modelo de Datos y Backend de Dominio)** deberá cumplir las siguientes reglas:

1. **Separación de Tablas por Granularidad y Fuente:**
   * **`channels`**: Identificador externo `youtube_channel_id` (`VARCHAR(64) UNIQUE`), `title`, `custom_url`, `uploads_playlist_id` (obligatorio para sincronización sin `search.list`), `published_at` (`TIMESTAMPTZ`) y conteos actuales.
   * **`videos`**: Identificador externo `youtube_video_id` (`VARCHAR(32) UNIQUE`), `channel_id` (FK), `title`, `published_at` (`TIMESTAMPTZ`), `duration_iso` (`VARCHAR(32)`) y `duration_seconds` (`INTEGER NOT NULL CHECK (duration_seconds >= 0)`).
   * **`video_public_snapshots`**: Capturas puntuales procedentes de `videos.list` con clave compuesta `(video_id, captured_at)`, donde `view_count` es `BIGINT NOT NULL`, pero **`like_count` y `comment_count` deben ser `BIGINT NULL`** (ya que `videos.list` omite ambos campos cuando el creador desactiva likes o comentarios).
   * **`video_daily_metrics`** y **`channel_daily_metrics`**: Series temporales por día calendario (`metric_date DATE`) procedentes de `Analytics API v2` (`dimensions=day`). Dado que `dimensions=video,day` no está soportado masivamente en una sola llamada de `reports.query`, se recomienda distinguir entre:
     * La serie diaria global del canal (`channel_daily_metrics`: 1 sola llamada a `reports.query` con `dimensions=day`).
     * Los totales por ventana/periodo o serie diaria por video (`video_daily_metrics` / `video_period_metrics`), donde `likes` registra la actividad de calificaciones positivas en el periodo (`INTEGER` / `BIGINT` con valor esperado $\ge 0$). Si en una respuesta de la API llegara a detectarse un valor negativo imprevisto, no debe considerarse un saldo ordinario de pérdida neta de likes, sino registrarse y aislarse como anomalía que requiere investigación técnica.
2. **Columnas de Impresiones y CTR Anulables con Fuente Explícita:**
   * `thumbnail_impressions` (`BIGINT NULL`) y `thumbnail_ctr` (`DOUBLE PRECISION NULL`) deben ser **anulables (`NULL`)** y estar acompañadas de un campo de trazabilidad (`reach_source`: `'reporting_api_v1' | NULL`), dado que `Analytics API v2` (`reports.query`) no las entrega y `Reporting API v1` tiene una demora inicial de hasta 48 horas tras crear el trabajo `channel_reach_basic_a1`.

---

## 7. Estado de Implementación en Fase 4 (Adaptadores de Producción y OAuth)

Durante la **Fase 4 (Integración de Producción con YouTube)** se construyeron y verificaron los adaptadores HTTP definitivos y el subsistema de autorización:

1. **`YouTubeDataClient` (`miconte.integrations.youtube.data_v3`):**
   * Implementa `get_channel` (`mine=true` o por ID), `list_playlist_items` (paginación hasta 50 ítems) y `list_videos_batch` (lotes automáticos de 50 IDs, parseo de duración ISO 8601 a segundos y preservación de `like_count`/`comment_count` como `None` cuando el creador los oculta).
   * Estado de verificación: `verified_offline` (10 tests específicos en `test_youtube_clients.py`).
2. **`YouTubeAnalyticsClient` (`miconte.integrations.youtube.analytics_v2`):**
   * Implementa `query_report` para consultas a `reports.query`. Incluye validación local preventiva que rechaza la combinación no admitida `dimensions=video,day` antes del envío por red, evitando desperdiciar llamadas. Normaliza encabezados y filas en `AnalyticsReportDTO`.
   * Estado de verificación: `verified_offline`.
3. **`YouTubeReportingClient` (`miconte.integrations.youtube.reporting_v1`):**
   * Implementa consulta de tipos de reporte, creación y listado de trabajos masivos, y descarga y parseo de archivos CSV para `channel_reach_basic_a1` (validando encabezados y columnas de impresiones y CTR).
   * Estado de verificación: `verified_offline`.
4. **Flujo OAuth 2.0 y Servicio Criptográfico (`miconte.security`, `miconte.services`):**
   * Generación de URL de consentimiento con parámetro `state` firmado con HMAC-SHA256 (anti-CSRF).
   * Verificación de scopes mínimos requeridos (`youtube.readonly` y `yt-analytics.readonly`).
   * Cifrado autenticado AES-256-GCM antes de la persistencia en `oauth_connections` con AAD context-bound (`user_id:platform:channel_id:credential_kind`).
   * Regla de preservación de `refresh_token` en re-autorizaciones.
   * Renovación automática de tokens de acceso expirados sin exponer credenciales al frontend.
   * Estado de verificación: `verified_offline` (8 tests en `test_crypto.py` y 7 tests en `test_oauth_flow.py`).
5. **Estado de Pruebas en Vivo (`verified_live`):**
   * Al no disponer de credenciales OAuth de Google Cloud configuradas en el entorno local (`MICONTE_YOUTUBE_CLIENT_ID` vacío), la prueba controlada en vivo permanece en estado **`pending` / `documented_not_tested`**. No se fabricaron resultados artificiales, preservando la integridad del registro de evidencia.
