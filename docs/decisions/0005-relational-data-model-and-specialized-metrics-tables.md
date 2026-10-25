# ADR-0005: Modelo de Datos Relacional y Tablas Especializadas por Granularidad

## Estado
Aprobado

## Fecha
2026-10-24

## Contexto
Durante la Fase 2 (**Validación Técnica de las APIs de YouTube**) se confirmaron las siguientes restricciones estructurales en las fuentes oficiales de datos:
1. `YouTube Data API v3` entrega conteos públicos instantáneos acumulados (`videos.list`), donde `likeCount` y `commentCount` se omiten cuando el creador los oculta o desactiva.
2. `YouTube Analytics API v2` entrega series diarias privadas mediante `reports.query` con `dimensions=day`. No admite la combinación simultánea `dimensions=video,day` en una sola consulta de canal.
3. Las métricas de alcance como impresiones de miniaturas (`video_thumbnail_impressions`) y su CTR no están expuestas en `Analytics API v2` (`reports.query`) y solo están documentadas en los reportes masivos asíncronos de `Reporting API v1` (`channel_reach_basic_a1`).
4. La métrica `likes` de `Analytics API v2` es un conteo de eventos positivos de usuario en el periodo analítico (dominio esperado $\ge 0$), no un saldo neto firmado.
5. El sistema miConte es multi-usuario y debe garantizar la separación estricta de datos entre usuarios y canales, así como alimentar de manera determinista y vectorizada al motor estadístico en `pandas.DataFrame`.

Debemos decidir cómo estructurar el almacenamiento de métricas en PostgreSQL: si mediante una estructura genérica común (modelo EAV o clave-valor) o mediante tablas relacionales especializadas por granularidad y fuente.

---

## Decisión

Se adopta una **arquitectura de tablas relacionales fuertemente tipadas y especializadas por granularidad y fuente**, complementada con un registro auditable de ejecuciones analíticas.

### 1. Comparativa Arquitectónica: Tablas Especializadas vs. Estructura Común (EAV)

#### Alternativa Evaluada: Estructura Genérica / EAV (`entity_type`, `entity_id`, `metric_key`, `metric_value`, `date`)
* **Ventajas:**
  * Facilidad para añadir nuevas métricas sin modificar el esquema con migraciones DDL.
* **Desventajas Críticas para miConte:**
  * **Pérdida de integridad de tipos:** Todos los valores deben almacenarse como cadenas de texto o números genéricos, perdiendo la distinción entre enteros de conteo (`BIGINT`), segundos (`INTEGER`), porcentajes (`DOUBLE PRECISION`) y fechas (`DATE`).
  * **Degradación severa del rendimiento analítico:** Obtener la serie temporal de 10 métricas de un video para alimentar un `DataFrame` de pandas requeriría múltiples auto-uniones (`JOIN`) o pivoteos costosos en SQL.
  * **Imposibilidad de aplicar restricciones relacionales nativas:** No se pueden definir restricciones `CHECK (duration_seconds >= 0)` ni validar reglas cruzadas a nivel de fila.
  * **Multiplicación del volumen de filas:** Una fila con 10 métricas se convierte en 10 filas en la base de datos, incrementando drásticamente el tamaño de índices y tablas.

#### Opción Elegida: Tablas Relacionales Especializadas
* **Ventajas:**
  * **Tipado estricto y precisión nativa:** Cada métrica utiliza el tipo de datos óptimo en PostgreSQL (`BIGINT`, `INTEGER`, `DOUBLE PRECISION`, `DATE`, `TIMESTAMPTZ`).
  * **Carga vectorizada directa hacia `pandas`:** Una simple consulta `SELECT * FROM video_daily_metrics WHERE video_id = ...` se traduce directamente a un `DataFrame` sin transformaciones intermedias ni sobrecarga de memoria.
  * **Restricciones de integridad directas:** Validaciones a nivel de base de datos como no negatividad de vistas, duraciones y conteos de eventos.
  * **Separación nítida de fuentes y naturalezas:** Las capturas públicas acumuladas no se mezclan con las series de actividad diaria ni con los totales de ventana agregada.
* **Desventajas asumidas:**
  * Incorporar una métrica futura requerirá una migración Alembic. Esto es deseable en miConte, ya que garantiza gobierno de datos y evolución controlada del contrato.

---

### 2. Entidades y Esquema de Tablas

1. **Usuarios y Seguridad (`users`, `oauth_connections`):**
   * Separación multi-usuario mediante claves foráneas directas.
   * **Distinción Crítica sobre Tokens OAuth y Criptografía:**
     * **Estado en Fase 3 (Columnas para Ciphertext):** La tabla `oauth_connections` define columnas de texto (`encrypted_access_token`, `encrypted_refresh_token`) específicamente destinadas a alojar datos cifrados (*ciphertext*). **La existencia de estas columnas en el esquema relacional no garantiza por sí sola que los datos almacenados estén cifrados.**
     * **Diferenciación entre Esquema, Servicio Criptográfico y Gestión de Claves:** El modelo de la Fase 3 únicamente provee los campos de persistencia. La implementación efectiva del servicio de cifrado/descifrado y la protección y gestión segura de las claves criptográficas (p. ej. mediante KMS o variables de entorno aisladas) corresponden a capas de aplicación que **no están implementadas en la Fase 3**.
     * **Requisito Obligatorio para Fase 4:** Queda estrictamente prohibido almacenar tokens OAuth reales hasta que la **Fase 4** implemente, audite y verifique el mecanismo criptográfico. La implementación futura deberá:
       - Utilizar **cifrado autenticado** (como **AES-GCM**) mediante una biblioteca criptográfica activamente mantenida (p. ej. `cryptography`).
       - Mantener las **claves criptográficas completamente separadas** de los tokens almacenados y fuera de la base de datos.
       - Prohibir estrictamente el registro de tokens o claves en registros (*logs*) o trazas de depuración.
       - Comprobar mediante pruebas exhaustivas el cifrado, el descifrado autorizado, la **detección de manipulaciones (*tamper detection*)** y el manejo seguro de errores.
       - Impedir en todo momento el almacenamiento de tokens en texto plano.
2. **Catálogo (`channels`, `videos`):**
   * Metadatos descriptivos estables. Claves externas únicas de YouTube (`youtube_channel_id`, `youtube_video_id`).
   * `channels.uploads_playlist_id` obligatorio para soportar la estrategia de enumeración sin `search.list`.
   * `videos.duration_seconds` entero no negativo con restricción `CHECK (duration_seconds >= 0)`.
3. **Instantáneas Públicas (`channel_public_snapshots`, `video_public_snapshots`):**
   * Registran el conteo acumulado observable en el instante `captured_at`.
   * Campos anulables (`like_count`, `comment_count`) para preservar la distinción nítida entre **ausencia** (`NULL`, creador ocultó o desactivó la interacción) y **cero** (`0`, interacción activa pero sin registros).
   * Restricción de unicidad compuesta: `(video_id, captured_at)` y `(channel_id, captured_at)`.
4. **Métricas Analíticas Privadas por Periodo:**
   * **`channel_daily_metrics`:** Serie diaria agregada del canal procedente de `Analytics API v2` (`dimensions=day`). Unicidad: `(channel_id, metric_date)`.
   * **`video_daily_metrics`:** Serie diaria por video obtenida con `dimensions=day` y `filters=video==ID`. Unicidad: `(video_id, metric_date)`.
   * **`video_period_metrics`:** Totales agregados por video en ventanas específicas (`startDate` a `endDate`) procedentes de consultas de ranking (`dimensions=video`). Unicidad: `(video_id, start_date, end_date)`.
5. **Aislamiento de Anomalías en Métricas:**
   * La métrica `likes` tiene dominio esperado $\ge 0$.
   * Para evitar que valores negativos o anómalos provenientes de upstream corrompan silenciosamente la base de datos o provoquen fallos catastróficos no controlados, las tablas de métricas incorporan una bandera `is_anomalous` y un campo `anomaly_notes`, con la restricción `CHECK (likes >= 0 OR is_anomalous = TRUE)`.
   * Esto permite almacenar de forma auditable y aislada cualquier anomalía detectada, impidiendo su mezcla inadvertida en análisis estadísticos estándar.
6. **Métricas de Alcance Opcionales (Impresiones y CTR):**
   * `thumbnail_impressions` (`BIGINT NULL`) y `thumbnail_ctr` (`DOUBLE PRECISION NULL`) se modelan como campos estrictamente anulables acompañados de `reach_source` (`VARCHAR(32) NULL`).
   * El sistema puede operar plenamente cuando solo se dispone de `Analytics API v2` o cuando los reportes de `Reporting API v1` no han concluido su ventana de generación de 48 horas.
7. **Auditoría de Ingesta y Análisis (`sync_runs`, `analysis_runs`, `recommendations`):**
   * Registro del ciclo de vida de sincronizaciones y ejecuciones del motor estadístico.
   * `recommendations` registra diagnósticos deterministas y lenguaje descriptivo no causal vinculado a la ejecución que lo originó.

---

## Consecuencias

* **Positivas:**
  * Estructura relacional limpia, reproducible y optimizada para consultas analíticas con PostgreSQL 16+.
  * Cumplimiento estricto de las limitaciones empíricas y documentales validadas en la Fase 2.
  * Garantía de separación de usuarios y trazabilidad completa de datos.
  * Migraciones incrementales controladas mediante Alembic.
* **Negativas / Compromisos:**
  * El esquema no es libre de esquema (*schemaless*); cualquier métrica nueva requerirá actualizar los modelos SQLAlchemy y generar una migración Alembic.
  * Las columnas `encrypted_*` en `oauth_connections` son receptáculos a nivel de esquema para texto cifrado (*ciphertext*); no garantizan confidencialidad por sí solas hasta que la Fase 4 implemente el servicio criptográfico autenticado y la gestión segura de claves.
