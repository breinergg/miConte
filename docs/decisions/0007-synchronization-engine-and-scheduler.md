# ADR-0007: Motor de Sincronización de Datos, Histórico de Métricas y Planificador Periódico

* **Estado:** Aprobado
* **Fecha:** 2026-10-26
* **Fase:** Fase 5 — Sincronización e Histórico de Métricas

---

## Contexto

En las Fases 1 a 4 se establecieron la persistencia relacional en PostgreSQL, la validación técnica de contratos de YouTube, el modelo de datos de dominio y la integración de producción con autorización OAuth 2.0 y cifrado AES-256-GCM.

La **Fase 5** requiere implementar el motor de sincronización de datos para:
1. Actualizar el catálogo de canales y videos de creadores autorizados sin duplicaciones.
2. Capturar instantáneas públicas periódicas conservando su instante de observación temporal.
3. Ingerir métricas privadas analíticas diarias y agregadas por periodo (Analytics API v2).
4. Integrar reportes asíncronos de alcance masivo e impresiones de miniaturas (Reporting API v1).
5. Registrar cada ejecución en la tabla de auditoría `sync_runs`.
6. Permitir ejecuciones manuales y ejecuciones periódicas programadas.

---

## Decisiones Técnicas

### 1. Servicio de Sincronización de Dominio Desacoplado (`SyncService`)

Se implementa `SyncService` en la capa de servicios (`src/miconte/services/sync_service.py`), totalmente independiente de los routers de FastAPI:
* **Entrada Segura y Multiinquilino:** Toda operación exige `user_id` y `channel_id`. Se verifica que el usuario autenticado sea el propietario legítimo del canal y cuente con credenciales OAuth activas.
* **Consumo de Tokens Vía `OAuthService`:** Los adaptadores de YouTube obtienen su token de acceso mediante `OAuthService.get_valid_access_token`, garantizando que si el token expiró, se renueve automáticamente y se preserve el texto cifrado.
* **Separación de Etapas de Sincronización:**
  1. `metadata`: Actualización de metadatos del canal (`uploads_playlist_id`, título, descripción).
  2. `channel_snapshot`: Registro de instantánea pública del canal (`view_count`, `subscriber_count`, `video_count`) en el instante exacto `captured_at`.
  3. `videos_catalog`: Paginación de `uploads_playlist_id` mediante `list_playlist_items` y consulta en lotes de hasta 50 IDs con `list_videos_batch`.
  4. `video_snapshots`: Registro de instantáneas públicas de cada video (`view_count`, `like_count`, `comment_count`) en `captured_at`.
  5. `analytics_daily`: Ingesta de serie temporal diaria del canal (`dimensions=day`) para los últimos 30 días consolidados.
  6. `analytics_period`: Ingesta de métricas agregadas por video (`dimensions=video`, `sort=-views`).
  7. `reporting_reach`: Gestión de trabajos y descarga de reportes CSV de alcance (`channel_reach_basic_a1`).

---

### 2. Idempotencia y Conservación de Instantáneas Históricas

* **Catálogo de Canales y Videos:** Se actualizan mediante operaciones *upsert* sobre claves naturales (`youtube_channel_id` y `youtube_video_id`).
* **Instantáneas Públicas (`ChannelPublicSnapshot` y `VideoPublicSnapshot`):**
  * Cada observación conserva el instante `captured_at`.
  * La restricción de unicidad `(channel_id, captured_at)` y `(video_id, captured_at)` garantiza que un reintento en el mismo instante no duplique registros, mientras que observaciones en momentos futuros se agregan como nuevos puntos históricos en la serie temporal.
  * Si `like_count` o `comment_count` están ocultos o desactivados por el creador, se conservan estrictamente como `NULL`, distinguiéndolos de un valor `0`.

---

### 3. YouTube Analytics API v2: Granularidad y Validación de Dimensiones

* Conforme a la validación de la Fase 2, la combinación `dimensions=video,day` devulve `HTTP 400 Bad Request` en YouTube Analytics API.
* Para series temporales diarias del canal se utiliza exclusivamente `dimensions=day`.
* Para métricas de periodo por video se utiliza `dimensions=video` con parámetro obligatorio `sort=-views`.
* Para series diarias por video individual se emplea `dimensions=day` con filtro `filters=video==<ID>`.
* Si la API retorna valores negativos en métricas de eventos acumulativos (como `likes`), se aíslan registrando `is_anomalous = True` con notas de anomalía técnica sin abortar la sincronización.

---

### 4. Orquestación Asíncrona de YouTube Reporting API v1

* `YouTubeReportingClient` gestiona los reportes masivos de alcance (`channel_reach_basic_a1`):
  1. Si no existe un job para el canal, se crea (`jobs.create`).
  2. Si no hay reportes disponibles (dentro de la ventana inicial de generación de 48 horas de YouTube), la etapa se marca como `pending_generation`. **El worker nunca se bloquea en espera activa** ni trata este estado como un error fatal.
  3. Cuando hay reportes disponibles, se descargan mediante URLs validadas contra SSRF, se parsean las columnas del CSV y se actualizan `thumbnail_impressions` y `thumbnail_ctr` en `video_daily_metrics`, registrando `reach_source = "reporting_api_v1"`.
  4. Se registran los reportes ya procesados en el historial de `sync_runs` para evitar descargas y procesamiento redundante.

---

### 5. Planificador Periódico: Enfoque para Entorno de Desarrollo vs. Producción Multiworker

Se evaluaron tres alternativas para la ejecución programada:
1. **Celery / ARQ con Redis:** Requiere infraestructura externa adicional de mensajería (Redis/RabbitMQ). Añade complejidad innecesaria para el MVP y desarrollo local.
2. **APScheduler con almacén SQL:** Introduce dependencias adicionales y riesgos de bloqueos concurrentes en SQLite/PostgreSQL si no se gestionan bloqueos distribuidos.
3. **Planificador Asíncrono en Proceso (`SyncScheduler`):**
   * Corre dentro del ciclo de vida asíncrono de FastAPI (`lifespan`).
   * Utiliza bloqueos de concurrencia `asyncio.Lock` por canal para impedir que dos sincronizaciones del mismo canal se ejecuten simultáneamente.
   * Proporciona control total para activación/desactivación manual, ajuste de intervalos y auditoría de estado vía `/api/v1/sync/scheduler/status`.
   * **Decisión:** Se adopta `SyncScheduler` nativo para el entorno actual. Se documenta formalmente que para despliegues futuros en producción con múltiples workers (Gunicorn/Uvicorn multi-proceso o réplicas en pods), se deberá adoptar un broker distribuido (Redis/ARQ o PostgreSQL Advisory Locks) para coordinar las ejecuciones entre procesos independientes.

---

### 6. Auditoría y Trazabilidad en `sync_runs`

Cada intento de sincronización genera un registro en `sync_runs`:
* **Estados del Ciclo de Vida:**
  * `pending`: Inicializada.
  * `running`: En proceso de ejecución.
  * `succeeded`: Todas las etapas completadas exitosamente.
  * `partially_succeeded`: Se completó el catálogo y snapshots, pero una etapa secundaria (como Reporting API en ventana de 48h) quedó pendiente.
  * `failed`: Fallo crítico no recuperable (autorización revocada, error de red tras reintentos).
* **Seguridad y Confidencialidad:** El campo `error_message` almacena resúmenes técnicos higienizados; nunca incluye tokens, claves de cifrado ni credenciales.

---

## Consecuencias

### Positivas
* Sincronización completa y consistente de canales, videos, estadísticas públicas y privadas.
* Idempotencia estricta ante reintentos sin riesgo de duplicar datos o violar restricciones relacionales.
* Trazabilidad completa mediante `sync_runs`.
* Respeto absoluto a las cuotas de YouTube API mediante paginación y consultas por lotes.
* Ausencia de dependencias de infraestructura pesada en desarrollo.

### Limitaciones Conocidas
* El planificador periódico actual opera en la memoria del proceso local. Requiere migración a cola distribuida al desplegar en arquitecturas multiworker.
* Las métricas de impresiones dependen de la generación asíncrona de Google (hasta 48 horas de latencia).
