# Diccionario de Datos y Catálogo de Métricas — miConte (`docs/data-dictionary.md`)

Este documento establece el catálogo inicial de entidades, dimensiones, métricas brutas y métricas derivadas de **miConte**, cumpliendo con los Principios 4 y 5 del proyecto y con las directrices de `miconte-statistical-validation`.

> **Nota importante de Fase 0:** Este diccionario define los contratos semánticos y matemáticos. El esquema físico definitivo de tablas de dominio en `miconte_db` se cerrará en la **Fase 3 (Modelo de Datos y Backend de Dominio)**, tras completar la **Fase 1 (Entorno y Persistencia Inicial)** y la **Fase 2 (Validación Técnica de las APIs de YouTube)**, una vez comprobada empíricamente la respuesta exacta de cada endpoint.

---

## 1. Metadatos Obligatorios de Trazabilidad por Métrica

Toda métrica expuesta por el motor estadístico y por la API REST de **miConte** debe ir acompañada de su sobre de metadatos (`MetricEnvelope`):

| Campo | Tipo | Descripción | Ejemplo |
| :--- | :--- | :--- | :--- |
| `metric_key` | `str` | Identificador técnico canónico en `miconte`. | `"average_percentage_viewed"` |
| `value` | `float \| int \| None` | Valor numérico calculado o `None` si está ausente/suprimido. | `0.482` |
| `unit` | `str` | Unidad de medida (`count`, `ratio`, `percentage`, `seconds`, `minutes`, `dimensionless`). | `"ratio"` |
| `source` | `str` | Origen exacto del dato (`youtube_data_api_v3`, `youtube_analytics_api_v2`, `youtube_reporting_api_v1`, `derived_deterministic`). | `"derived_deterministic"` |
| `visibility` | `str` | Nivel de autorización requerido (`public`, `private_oauth`). | `"private_oauth"` |
| `period_start` | `date \| datetime` | Inicio de la ventana temporal evaluada (ISO 8601 UTC). | `"2026-09-01"` |
| `period_end` | `date \| datetime` | Fin de la ventana temporal evaluada (ISO 8601 UTC). | `"2026-10-01"` |
| `sample_size` | `int` | Tamaño muestral ($N$) utilizado en la agregación o inferencia. | `24` |
| `ci_95` | `tuple[float, float] \| None` | Intervalo de confianza al 95% ($\text{CI}_{95\%}$) cuando la muestra y los supuestos lo justifican. | `[0.421, 0.543]` |
| `incomplete_observation_window` | `bool` | Indica si la publicación aún no ha cumplido la ventana temporal completa de observación (p. ej. edad $< 72\text{ h}$ para métricas de 72h). | `false` |
| `is_right_censored` | `bool` | Reservado para censura estadística formal por la derecha en análisis de tiempo hasta un evento (*time-to-event*). | `false` |
| `data_suppressed` | `bool` | Indica si YouTube omitió el dato por umbrales de privacidad o bajo volumen. | `false` |
| `limitations` | `list[str]` | Lista de advertencias metodológicas aplicables a la lectura del dato. | `["Distribución asimétrica; se recomienda usar mediana e IQR"]` |

---

## 2. Catálogo de Métricas Brutas (Ingesta Oficial de YouTube)

### 2.1 Métricas y Atributos Públicos (`YouTube Data API v3`)
* **Alcance OAuth / Credencial:** API Key o `youtube.readonly`.
* **Naturaleza:** Instantánea acumulada en el momento de la consulta (`captured_at`).

| Identificador `miconte` | Campo en YouTube API | Recurso API | Unidad | Dominio | Descripción y Limitaciones |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `channel_subscriber_count` | `statistics.subscriberCount` | `channels.list` | `count` | $[0, \infty)$ | Total de suscriptores públicos. **Limitación:** YouTube redondea este valor a tres cifras significativas en la API pública. |
| `channel_video_count` | `statistics.videoCount` | `channels.list` | `count` | $[0, \infty)$ | Total de videos públicos subidos al canal. |
| `channel_view_count` | `statistics.viewCount` | `channels.list` | `count` | $[0, \infty)$ | Visualizaciones totales acumuladas del canal. |
| `video_published_at` | `snippet.publishedAt` | `videos.list` | `datetime` | ISO 8601 UTC | Fecha y hora exacta en que el video se hizo público. Base para calcular la edad del video. |
| `video_duration_seconds` | `contentDetails.duration` | `videos.list` | `seconds` | $[0, \infty)$ | Duración del video (convertida desde formato ISO 8601 `PT#M#S` a segundos enteros). |
| `video_view_count_snapshot` | `statistics.viewCount` | `videos.list` | `count` | $[0, \infty)$ | Visualizaciones acumuladas en el instante `captured_at`. Si la edad del video es menor a la ventana evaluada (p. ej. $< 72\text{ h}$), presenta una ventana de observación incompleta (`incomplete_observation_window = True`). |
| `video_like_count_snapshot` | `statistics.likeCount` | `videos.list` | `count` | $[0, \infty)$ | Conteo acumulado de "Me gusta" públicos. Puede ser `None` si el creador ocultó los likes. |
| `video_comment_count_snapshot` | `statistics.commentCount` | `videos.list` | `count` | $[0, \infty)$ | Conteo acumulado de comentarios. Puede ser `None` si los comentarios están desactivados. |

### 2.2 Métricas Privadas de Serie Temporal (`YouTube Analytics API v2` vs. `YouTube Reporting API v1`)
* **Alcances OAuth documentados:** La referencia del método `reports.query` indica `https://www.googleapis.com/auth/youtube.readonly`, mientras que la guía general de autorización de Analytics/Reporting enumera también `https://www.googleapis.com/auth/yt-analytics.readonly` (no monetario). La suficiencia de cada alcance por endpoint se validará empíricamente en la **Fase 2**.
* **Limitación general:** Latencia de consolidación de 48 a 72 horas.

#### A. Métricas Documentadas en `YouTube Analytics API v2` (`reports.query`)
* **Dimensiones habituales:** `day`, `video`, `channel`, `insightTrafficSourceType`, `deviceType`, `subscribedStatus` (sujetas a las combinaciones válidas por tipo de informe en la documentación de `reports.query`, a verificar empíricamente en la **Fase 2**).

| Identificador `miconte` | Métrica en Analytics API | Unidad | Dominio | Descripción y Limitaciones |
| :--- | :--- | :--- | :--- | :--- |
| `daily_views` | `views` | `count` | $[0, \infty)$ | Visualizaciones registradas en la fecha o ventana consultada. |
| `estimated_minutes_watched` | `estimatedMinutesWatched` | `minutes` | $[0, \infty)$ | Minutos totales estimados de visualización acumulados en el periodo. |
| `average_view_duration_sec` | `averageViewDuration` | `seconds` | $[0, \infty)$ | Duración media en segundos de las reproducciones durante el periodo. |
| `average_view_percentage` | `averageViewPercentage` | `percentage` | $[0, 100+]$ | Porcentaje promedio de un video visto durante una reproducción (puede superar 100% si hay repeticiones/bucles). |
| `likes_count` | `likes` | `count` | $[0, \infty)$ | Número de veces que los usuarios indicaron que les gustó un video dándole una calificación positiva en el periodo analítico (métrica de actividad, no es saldo neto). Si una respuesta presentase un valor negativo, se aislará como anomalía técnica sujeta a investigación. |
| `comments_count` | `comments` | `count` | $[0, \infty)$ | Comentarios recibidos en el periodo. |
| `shares_count` | `shares` | `count` | $[0, \infty)$ | Veces que el contenido fue compartido mediante el botón Compartir de YouTube. |
| `subscribers_gained` | `subscribersGained` | `count` | $[0, \infty)$ | Suscriptores ganados atribuidos al video o canal en el periodo. |
| `subscribers_lost` | `subscribersLost` | `count` | $[0, \infty)$ | Suscriptores perdidos atribuidos al video o canal en el periodo. |
| `card_click_rate` | `cardClickRate` | `ratio` | $[0, 1]$ | Tasa de clics en tarjetas interactivas mostradas durante el video (distinta del CTR de miniatura). |

#### B. Métricas de Alcance e Impresiones Documentadas en `YouTube Reporting API v1` (Informes Masivos)
* **Distinción crítica de disponibilidad:** En la documentación oficial de Google, las métricas de impresiones de miniatura y su CTR (`video_thumbnail_impressions` y `video_thumbnail_impressions_ctr`) están definidas dentro de los informes masivos asíncronos de **`YouTube Reporting API v1`**:
  * Informe **`channel_reach_basic_a1`**: Dimensiones `(date, channel_id, video_id, live_or_on_demand)` $\rightarrow$ Métricas `video_thumbnail_impressions`, `video_thumbnail_impressions_ctr`.
  * Informe **`channel_reach_combined_a1`**: Dimensiones `(date, channel_id, video_id, live_or_on_demand, subscribed_status, traffic_source_type, device_type)` $\rightarrow$ Métricas `video_thumbnail_impressions`, `video_thumbnail_impressions_ctr`.
* **No declaradas como disponibles en `reports.query`:** Estas dos métricas no deben asumirse como consultables de forma síncrona mediante `YouTube Analytics API v2` (`reports.query`). Su validación empírica y el mecanismo exacto de ingesta quedan sujetos a comprobación en la **Fase 2**.

| Identificador `miconte` | Métrica en Reporting API (`channel_reach_*`) | Unidad | Dominio | Estado y Condición de Disponibilidad |
| :--- | :--- | :--- | :--- | :--- |
| `video_thumbnail_impressions` | `video_thumbnail_impressions` | `count` | $[0, \infty)$ | **Pendiente de validación empírica (Fase 2).** Documentada en `YouTube Reporting API` (`channel_reach_basic_a1` / `channel_reach_combined_a1`), no en `Analytics API v2` `reports.query`. |
| `video_thumbnail_impressions_ctr` | `video_thumbnail_impressions_ctr` | `ratio` | $[0.0, 1.0]$ | **Pendiente de validación empírica (Fase 2).** Tasa de clics de impresiones de miniatura que derivaron en visualización, documentada en `YouTube Reporting API`. |

---

## 3. Catálogo de Métricas Derivadas Deterministas (`miconte.statistics`)

Todas las métricas siguientes son calculadas de forma determinista por el motor estadístico de **miConte** y cumplen estrictamente las fórmulas de `miconte-statistical-validation`.

### 3.1 Click-Through Rate ($\text{CTR}$)
* **Fórmula Matemática:**
  $$\text{CTR} = \begin{cases} \frac{\text{clicks}}{\text{impressions}} & \text{si } \text{impressions} > 0 \\ 0.0 & \text{si } \text{impressions} = 0 \end{cases}$$
* **Unidad y Dominio:** `ratio` en $[0.0, 1.0]$ (o porcentaje en $[0.0, 100.0]$ en presentación UI).
* **Manejo de Casos Borde:** Si `impressions` es `None` (no disponible en la fuente), devuelve `None` con `limitations=["Impresiones no disponibles para este periodo/fuente"]`. Si `impressions == 0`, devuelve exactamente `0.0` (nunca `NaN` ni excepción `ZeroDivisionError`).

### 3.2 Porcentaje Medio Visto / Retención Relativa ($\text{APV}$)
* **Fórmula Matemática:**
  $$\text{APV} = \begin{cases} \frac{\text{Average Watch Time (s)}}{\text{Video Duration (s)}} & \text{si } \text{Video Duration} > 0 \\ 0.0 & \text{si } \text{Video Duration} \le 0 \end{cases}$$
* **Unidad y Dominio:** `ratio` en $[0.0, \infty)$ (acotado habitualmente a $[0.0, 1.0]$, pudiendo exceder $1.0$ en videos cortos con repetición).
* **Manejo de Casos Borde:** Si `Video Duration <= 0` (por ejemplo, transmisiones en vivo aún no procesadas), devuelve `0.0` y marca la limitación correspondiente.

### 3.3 Tasa de Interacción ($\text{ER}$ — Engagement Rate)
* **Fórmula Matemática:**
  $$\text{ER} = \frac{\text{likes} + \text{comments} + \text{shares}}{\max(\text{views}, 1)}$$
* **Unidad y Dominio:** `ratio` en $[0.0, \infty)$.
* **Variante Pública ($\text{ER}_{\text{public}}$):** Cuando solo se dispone de `YouTube Data API v3` (donde `shares` no es público), se calcula explícitamente como:
  $$\text{ER}_{\text{public}} = \frac{\text{likes} + \text{comments}}{\max(\text{views}, 1)}$$
  conservando un `metric_key` distinto (`"public_engagement_rate"`) para no mezclar definiciones incompatibles.

### 3.4 Velocidad Normalizada a 24 Horas ($V_{24h}$) y $k$ Días ($V_{kd}$)
* **Fórmula Matemática:**
  $$V_{24h} = \frac{\text{Views}_{24h}}{\text{Median}(\text{Views}_{24h} \text{ del canal en línea base})}$$
* **Unidad y Dominio:** `dimensionless` (múltiplo respecto a la mediana histórica del canal) en $[0.0, \infty)$. Un valor de $1.5$ significa un rendimiento un $50\%$ superior a la mediana histórica de las primeras 24 horas del canal.
* **Manejo de Casos Borde:** Requiere al menos $N \ge 10$ videos históricos con captura a las 24h (o serie diaria equivalente para $V_{7d}$) y que la mediana basal sea $> 0$. En caso contrario, devuelve `None` indicando insuficiencia muestral.

### 3.5 Conversión Neta de Suscriptores por 1,000 Vistas ($\text{NSC}_{1k}$)
* **Fórmula Matemática:**
  $$\text{NSC}_{1k} = \frac{\text{subscribersGained} - \text{subscribersLost}}{\max(\text{views}, 1)} \times 1000$$
* **Unidad y Dominio:** `subscribers_per_1k_views` en $(-\infty, \infty)$.

---

## 4. Criterios Estadísticos, Referencias de Muestra y Selección de Métodos

Para cualquier cohorte de videos $X = \{x_1, x_2, \dots, x_N\}$, el motor estadístico aplica un marco metodológico riguroso que evita reglas ciegas o conclusiones causales injustificadas:

1. **Umbrales de Tamaño Muestral como Referencias Iniciales (No Garantías Universales):**
   * Los valores **$N \ge 10$** (para intervalos de confianza y estimaciones puntuales de cohorte), **$N_1, N_2 \ge 20$** (para pruebas de comparación de dos muestras) y **$N \ge 30$** (para modelos de regresión y descomposición de series temporales) se adoptan en **miConte** como **referencias heurísticas iniciales mínimas sujetas a justificación metodológica**, y **nunca como garantías universales de validez o potencia estadística**.
   * En distribuciones fuertemente asimétricas o de cola pesada (*heavy-tailed*, frecuentes en métricas de visualizaciones), incluso muestras con $N \ge 30$ pueden presentar alta varianza, baja potencia estadística o sensibilidad extrema a valores atípicos (*outliers*).
   * Cuando $N < 10$, el sistema se limita a reportar estadística descriptiva básica (valores observados, mínimo, máximo y mediana) sin emitir intervalos de confianza asintóticos ni valores $p$.

2. **Criterios de Selección de Métodos Estadísticos:**
   La elección del estimador, del intervalo de confianza y de la prueba de hipótesis en `miconte.statistics` debe depender conjuntamente de:
   * **El tipo y naturaleza de los datos:** Conteos discretos, proporciones/tasas acotadas en $[0, 1]$, duraciones continuas o series temporales autocorrelacionadas.
   * **El cumplimiento de los supuestos del modelo:** Evaluación de normalidad (`scipy.stats.shapiro` para $N < 50$; `scipy.stats.kstest` para $N \ge 50$), homocedasticidad e independencia de las observaciones (atendiendo a la dependencia temporal entre videos consecutivos de un mismo canal).
   * **El tamaño del efecto y la incertidumbre:** Reportar siempre magnitudes de efecto (p. ej. diferencia de medianas, razón de tasas, $r$ de rangos biseriados o $d$ de Cohen cuando proceda) junto con su Intervalo de Confianza al 95% ($\text{CI}_{95\%}$ vía *bootstrap* percentil/BCa o error estándar cuando se justifique):
     $$\text{CI}_{95\%} = \hat{\mu} \pm 1.96 \cdot \frac{s}{\sqrt{N}} \quad \text{(aplicable solo bajo aproximación normal validada)}$$
   * **La calidad y representatividad de la muestra:** Presencia de datos suprimidos, cambios drásticos en el formato del canal o mezcla de formatos heterogéneos (*Shorts* vs. videos largos vs. transmisiones en directo).

3. **Prohibición de Conclusiones Causales a partir de Correlaciones:**
   * Los datos históricos de YouTube son **observacionales**, no experimentales. Ninguna correlación, diferencia de medianas entre cohortes ni regresión temporal demuestra causalidad debido a variables de confusión no controladas (algoritmo de recomendación, tendencia externa, crecimiento de suscriptores).
   * Tanto el motor determinista como la interfaz y la capa opcional de IA deben expresar los resultados estrictamente como **asociaciones observadas en la muestra** ("se asocia con", "coincide con"), nunca como relaciones causa-efecto ("provocó", "causó").

---

## 5. Datos Ausentes (`Missing`), Ventana de Observación Incompleta y Censura Estadística

Es obligatorio distinguir conceptual y técnicamente tres fenómenos diferentes en las métricas temporales de YouTube:

1. **Datos Ausentes o Suprimidos (`None` / `data_suppressed = True`):**
   * Un valor `None` o `np.nan` proveniente de una ventana donde YouTube aún no consolidó analíticas (últimas 48–72h), donde el creador desactivó interacciones o donde la API omitió el desglose por umbrales de privacidad nunca se rellena silenciosamente con `0.0`.
2. **Falta de una Ventana Completa de Observación (`incomplete_observation_window = True`):**
   * Ocurre cuando se evalúa una métrica definida sobre un horizonte fijo $T$ (por ejemplo, vistas en los primeros 7 días $V_{7d}$ o estabilización inicial de 72 horas), pero el video tiene una edad actual $\Delta t = t_{\text{actual}} - t_{\text{publicación}} < T$.
   * Esto **no es censura estadística aleatoria**, sino una **observación incompleta por ventana temporal aún en curso (exposición parcial)**. Estos videos se etiquetan con `incomplete_observation_window = True` y se excluyen del cálculo de la línea base histórica del horizonte $T$ hasta que cumplan $\Delta t \ge T$.
3. **Censura Estadística Formal por la Derecha (`is_right_censored = True`):**
   * Se reserva para análisis formales de **tiempo hasta un evento** (*survival / time-to-event analysis*, por ejemplo, el tiempo transcurrido hasta que un video alcanza un umbral de $K$ visualizaciones o hasta que su velocidad diaria cae por debajo de un nivel basal), en los cuales el evento de interés aún no ha ocurrido al finalizar el periodo de seguimiento. En dichos modelos no se descarta la observación, sino que se incorpora su tiempo de exposición truncado mediante estimadores específicos de supervivencia si se implementan.

---

## 6. Mapeo Físico del Esquema Relacional en PostgreSQL (`miconte_db` — Fase 3)

Implementado mediante SQLAlchemy 2.0 y gestionado con migraciones incrementales de Alembic (`alembic/versions/465c43158ab0_phase3_domain_schema.py`), conforme a ADR-0005:

| Tabla PostgreSQL | Granularidad / Entidad | Clave Primaria | Clave de Integridad / Unicidad | Restricciones de Dominio y Nulabilidad |
| :--- | :--- | :--- | :--- | :--- |
| `users` | Usuario de la plataforma | `id UUID` | `UNIQUE(email)` | `hashed_password NOT NULL`, `is_active BOOLEAN` |
| `oauth_connections` | Credenciales de autorización | `id UUID` | `UNIQUE(user_id, platform, external_channel_id)` | Campos para ciphertext (`encrypted_*`); servicio criptográfico requerido en Fase 4. `FK(users.id CASCADE)` |
| `channels` | Catálogo de canal conectado | `id UUID` | `UNIQUE(youtube_channel_id)` | `uploads_playlist_id NOT NULL`, `FK(users.id CASCADE)` |
| `channel_public_snapshots` | Captura puntual de canal | `id UUID` | `UNIQUE(channel_id, captured_at)` | `view_count >= 0`, `subscriber_count NULL` (oculto vs 0) |
| `videos` | Catálogo de videos publicados | `id UUID` | `UNIQUE(youtube_video_id)` | `duration_seconds >= 0`, `FK(channels.id CASCADE)` |
| `video_public_snapshots` | Captura puntual de video | `id UUID` | `UNIQUE(video_id, captured_at)` | `like_count NULL` y `comment_count NULL` (oculto vs 0) |
| `channel_daily_metrics` | Serie diaria de canal | `id UUID` | `UNIQUE(channel_id, metric_date)` | `CHECK (likes >= 0 OR is_anomalous = TRUE)` |
| `video_daily_metrics` | Serie diaria por video | `id UUID` | `UNIQUE(video_id, metric_date)` | `thumbnail_impressions NULL`, `thumbnail_ctr NULL [0,1]` |
| `video_period_metrics` | Agregado por ventana | `id UUID` | `UNIQUE(video_id, start_date, end_date)` | `CHECK (start_date <= end_date)`, `likes >= 0` |
| `sync_runs` | Auditoría de sincronización | `id UUID` | N/A (`ix_sync_runs_channel_started`) | `records_processed >= 0`, `FK(channels.id CASCADE)` |
| `analysis_runs` | Ejecución de motor analítico | `id UUID` | N/A (`ix_analysis_runs_channel_started`) | `parameters JSONB`, `sample_size_n >= 0`, `summary JSONB` |
| `recommendations` | Diagnósticos deterministas | `id UUID` | N/A (`ix_recommendations_channel_created`) | `description` no causal, `metrics_evidence JSONB` |

