# ADR-0004: Estrategia de Integración con APIs Oficiales de YouTube, Permisos OAuth y Gestión de Cuotas

* **Estado:** Aceptado (sujeto a validación empírica en Fase 2)
* **Fecha:** 2026-10-24
* **Fase:** Fase 0 — Fundamentación y Arquitectura

---

## Contexto

**miConte** se integra inicialmente de forma exclusiva con YouTube respetando sus APIs oficiales y sus permisos (Principio 6). El ecosistema oficial de Google Developers para YouTube se divide en tres servicios con propósitos, métodos de autorización, exposición de métricas y límites de cuota diferentes:

1. **YouTube Data API v3 (`youtube/v3`):** Provee metadatos de canales (`channels.list`), elementos de listas de reproducción (`playlistItems.list`), detalles de videos (`snippet`, `contentDetails`) y conteos estadísticos públicos acumulados (`statistics`: `viewCount`, `likeCount`, `commentCount`). Opera con una asignación de cuota por defecto de **10,000 unidades diarias por proyecto** en Google Cloud.
2. **YouTube Analytics API v2 (`youtubeAnalytics/v2`):** Provee consultas síncronas (`reports.query`) de informes agregados y series temporales diarias de métricas privadas del canal (`views`, `estimatedMinutesWatched`, `averageViewDuration`, `averageViewPercentage`, `likes`, `comments`, `shares`, `subscribersGained`, `subscribersLost`, `cardClickRate`). Requiere obligatoriamente **OAuth 2.0 de usuario** otorgado por el propietario del canal.
3. **YouTube Reporting API v1 (`youtubereporting/v1`):** Provee trabajos asíncronos de informes masivos descargables en CSV (`jobs.create`, `jobs.list`, `jobs.reports.list`). En la documentación oficial de Google, las métricas de alcance de miniaturas (`video_thumbnail_impressions` y `video_thumbnail_impressions_ctr`) están definidas dentro de los informes masivos **`channel_reach_basic_a1`** y **`channel_reach_combined_a1`** de esta API, y no como métricas estándar de consulta ad-hoc en `Analytics API v2` (`reports.query`).

---

## Decisión

1. **Separación de Clientes Especializados bajo un Puerto de Plataforma (`ContentPlatformPort`):**
   * `YouTubeDataClient`: Encargado de consultar `channels.list`, `playlistItems.list` y `videos.list` en `YouTube Data API v3`.
   * `YouTubeAnalyticsClient`: Encargado de consultar `reports.query` en `YouTube Analytics API v2` utilizando tokens OAuth 2.0 de usuario.
   * `YouTubeReportingClient` *(Condicional, según validación empírica en Fase 2)*: Mecanismo complementario para gestionar y descargar reportes `channel_reach_basic_a1` si se confirma que es la vía oficial necesaria para ingerir `video_thumbnail_impressions` y `video_thumbnail_impressions_ctr`.
2. **Principio de Mínimo Privilegio en OAuth 2.0 y Discrepancia Documental de Scopes:**
   * En la documentación oficial de Google para consultas no monetarias se observa que:
     * Para `YouTube Data API v3` se documenta `https://www.googleapis.com/auth/youtube.readonly`.
     * Para `YouTube Analytics API v2`, la referencia específica del método `reports.query` indica que requiere `https://www.googleapis.com/auth/youtube.readonly` (o alcances superiores como `youtube` / `youtubepartner`), mientras que la guía general de autorización de YouTube Analytics y de `YouTube Reporting API v1` enumera también `https://www.googleapis.com/auth/yt-analytics.readonly`.
   * Prohibir el uso de alcances de escritura, borrado o subida de videos (`youtube.force-ssl`, `youtube.upload`).
   * **No concluir que un único *scope* es suficiente para todos los endpoints sin validación:** Se mantiene la prueba empírica en la **Fase 2 (Validación Técnica de las APIs de YouTube)** para verificar qué alcance o combinación de alcances (`youtube.readonly` y `yt-analytics.readonly`) exige realmente cada endpoint.
3. **Distinción de Cuotas y Optimización en `YouTube Data API v3`:**
   * Distinguir en el diseño y en la auditoría (`sync_runs`) tres conceptos independientes según la documentación oficial vigente:
     1. **Cuota diaria general del proyecto vs. cubo independiente de búsqueda:** Los proyectos disponen por defecto de **10,000 unidades/día** para operaciones generales en `YouTube Data API v3`, y de un **límite diario independiente de 100 llamadas/día** para el cubo de búsqueda (`search.list`).
     2. **Costo por llamada/página:** Tanto `channels.list`, `playlistItems.list` (hasta 50 ítems) y `videos.list` (hasta 50 IDs por lote) como `search.list` tienen un costo documentado de **1 unidad por llamada/página** dentro de su respectivo cubo de cuota (a diferencia del esquema histórico antiguo donde `search.list` descontaba 100 unidades del pool de 10,000).
     3. **Límites de frecuencia (*Rate Limits*):** Límites de peticiones por minuto/segundo (QPM/QPS) y límite diario de consultas en `Analytics API v2`.
   * Evitar `search.list` para enumerar las publicaciones del canal: listar un canal de 500 videos (10 páginas) mediante `search.list` consumiría **10 llamadas (el 10% del límite diario independiente de 100 búsquedas del proyecto)**. En cambio, utilizar la secuencia `channels.list(part="contentDetails,snippet,statistics")` (1 unidad) $\rightarrow$ extraer `relatedPlaylists.uploads` $\rightarrow$ `playlistItems.list(maxResults=50)` (10 llamadas = 10 unidades) $\rightarrow$ `videos.list(id=batch_50_ids, part="snippet,contentDetails,statistics")` (10 llamadas = 10 unidades) consume únicamente **21 unidades de la cuota general de 10,000 unidades/día (0.21%)** y **0 llamadas** del límite diario de búsqueda.
4. **Puerta de Validación Empírica en la Fase 2 antes del Modelo de Dominio (Fase 3):**
   * Antes de cerrar el esquema definitivo de dominio en la **Fase 3** y la integración de producción en la **Fase 4**, ejecutar en la **Fase 2** las pruebas de validación técnica contra las APIs de YouTube para verificar empíricamente permisos, combinaciones válidas de dimensiones/métricas y disponibilidad de impresiones/CTR.

---

## Consecuencias

### Positivas
* Consumo de cuota mínimo y predecible en `YouTube Data API v3`: 21 unidades de la cuota general de 10,000 unidades/día (0.21%) y 0 llamadas del límite diario de búsqueda para un canal de 500 videos, frente a consumir 10 de las 100 llamadas diarias del cubo independiente de `search.list`.
* Capacidad de operar en **Modo Público** (`Data API v3`) y **Modo Propietario Autenticado** (`Data API v3` + `Analytics API v2` + reporte de alcance si aplica).
* No se acopla el diseño a suposiciones no verificadas sobre la disponibilidad de `video_thumbnail_impressions` en `reports.query`.

### Negativas / Compromisos
* Requiere ejecutar la validación empírica en la **Fase 2** con credenciales de un proyecto Google Cloud para confirmar el comportamiento exacto de cada endpoint antes de construir los adaptadores de producción en la **Fase 4**.
