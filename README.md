# miConte — Plataforma de Inteligencia de Contenido

**miConte** (identificador técnico: `miconte`) es una plataforma de inteligencia de contenido diseñada para ayudar a creadores y analistas de medios a comprender el rendimiento histórico de sus publicaciones, identificar patrones estadísticos rigurosos y generar recomendaciones respaldadas por datos.

En su Producto Mínimo Viable (MVP), **miConte** se enfoca exclusivamente en **YouTube**, integrándose con sus APIs oficiales y operando sobre un núcleo analítico **100% determinista e independiente de modelos de lenguaje (LLM) o protocolos externos (MCP)**.

---

## Principios Fundamentales

1. **Núcleo Estadístico Independiente:** Todo el cálculo de métricas, agregaciones, pruebas de hipótesis y series temporales funciona de forma determinista con `pandas`, `NumPy`, `SciPy` y `statsmodels`, sin requerir un LLM ni conexión a internet una vez sincronizados los datos.
2. **Independencia de MCP:** La aplicación funciona de extremo a extremo sin depender del Model Context Protocol (MCP), el cual se contempla únicamente como extensión opcional futura.
3. **LLM como Intérprete (No Calculador):** Cuando se habilite la capa de IA (mediante Ollama local o adaptadores externos), su rol se limitará estrictamente a redactar o interpretar los resultados previamente calculados por el motor estadístico. Tiene prohibido inventar métricas o inferir causalidad no demostrada.
4. **Trazabilidad de Métricas:** Cada métrica conserva su fuente (`YouTube Data API v3`, `YouTube Analytics API v2` o cálculo derivado), ventana temporal, unidad, tamaño muestral ($N$) y limitaciones (censura por la derecha, datos suprimidos por privacidad).
5. **Conservación Histórica Controlada:** Se distingue entre metadatos actuales e instantáneas (*snapshots*) temporales y series diarias en PostgreSQL (`miconte_db`).
6. **Cumplimiento Oficial:** Integración exclusiva mediante APIs oficiales de Google/YouTube respetando alcances (*scopes*) OAuth 2.0, cuotas y políticas de retención de datos.

---

## Convenciones de Identidad

| Concepto | Valor Oficial |
| :--- | :--- |
| **Nombre visible del producto** | `miConte` |
| **Nombre del repositorio** | `miconte` |
| **Identificador técnico / paquete** | `miconte` |
| **Prefijo de variables de entorno** | `MICONTE_` |
| **Base de datos local** | `miconte_db` |

---

## Stack Tecnológico

* **Backend:** Python (3.13 / 3.14 recomendado; 3.12+ soportado), FastAPI, Pydantic v2, SQLAlchemy 2.0+, Alembic, HTTPX.
* **Base de Datos:** PostgreSQL 16 / 17.
* **Motor Estadístico y Analítico:** pandas, NumPy, SciPy, statsmodels (y scikit-learn solo bajo necesidad justificada).
* **Integración Externa:** YouTube Data API v3, YouTube Analytics API v2 y, de forma condicional si se requiere para métricas masivas de alcance (impresiones/CTR), YouTube Reporting API v1 con OAuth 2.0.
* **Frontend:** Angular (v20 / v21 LTS recomendado para proyecto nuevo sobre Node.js 22 LTS; distinto del CLI v19.2.27 preinstalado en el host) y TypeScript (`>=5.8 <6.0`).
* **Capa de IA (Fase 9, posterior al núcleo determinista):** Ollama local como primera opción y adaptadores intercambiables bajo un puerto común (`LLMProviderPort`).
* **Calidad y Pruebas:** pytest, Ruff, mypy (backend); Vitest / Jasmine y Playwright (frontend).

---

## Alcance del MVP vs. Fuera de Alcance

### Incluido en el MVP
* Conexión oficial con YouTube (estadísticas públicas vía Data API v3 e informes privados del canal propietario vía Analytics API v2 con OAuth 2.0).
* Sincronización y almacenamiento histórico controlado en PostgreSQL (`miconte_db`).
* Motor estadístico determinista (métricas derivadas como CTR, APV, Engagement Rate, Velocidad Normalizada $V_{24h}$, pruebas no paramétricas/paramétricas con validación de normalidad e intervalos de confianza al 95%).
* Motor de recomendaciones deterministas basadas en reglas y umbrales estadísticos auditables.
* API REST documentada con FastAPI y dashboard web interactivo en Angular.
* Capa opcional y desacoplada de interpretación vía LLM (Ollama / API externa) con degradación elegante (*graceful degradation*).

### Expresamente Fuera del MVP
* Integración con TikTok, Instagram u otras redes sociales (el diseño desacoplado permitirá añadirlas en el futuro sin reescribir el núcleo).
* Servidores o clientes MCP como requisito funcional.
* Entrenamiento de modelos propios de *deep learning* o *machine learning* complejo sin respaldo muestral.
* Analítica predictiva avanzada no justificada por el tamaño de muestra ($N$) del canal.
* Arquitectura de microservicios, colas distribuidas complejas o Kubernetes.

---

## Estructura de Documentación (Fase 0)

Toda la fundamentación técnica, funcional y arquitectónica de **miConte** se encuentra en el directorio [`docs/`](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs):

* [Visión del Producto (`docs/product-overview.md`)](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/product-overview.md): Problema, usuarios objetivo, casos de uso, objetivos y límites del MVP.
* [Requisitos (`docs/requirements.md`)](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/requirements.md): Requisitos funcionales (RF), no funcionales (RNF) y criterios de aceptación.
* [Arquitectura (`docs/architecture.md`)](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/architecture.md): Diseño de monolito modular, responsabilidades, grafo de dependencias y validación del stack.
* [Diccionario de Datos (`docs/data-dictionary.md`)](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/data-dictionary.md): Catálogo de métricas públicas, privadas y derivadas, fórmulas matemáticas, unidades y tratamiento de datos ausentes/censurados.
* [Hoja de Ruta (`docs/roadmap.md`)](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/roadmap.md): Planificación por fases secuenciales, entregables y puertas de verificación (*gates*).
* [Riesgos y Mitigaciones (`docs/risks.md`)](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/risks.md): Análisis de cuotas de YouTube, permisos OAuth, compatibilidad de entorno local, seguridad y costos.
* [Matriz de Compatibilidad de YouTube API (`docs/youtube-api-compatibility.md`)](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/youtube-api-compatibility.md): Validación técnica de endpoints, combinaciones de dimensiones, alcances OAuth y cuotas (Fase 2).
* [Cumplimiento de Políticas de YouTube API (`docs/youtube-api-policy-compliance.md`)](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/youtube-api-policy-compliance.md): Marco normativo oficial, plazos diferenciados de eliminación (7 días para solicitud del usuario; revocación de credenciales inmediata + eliminación de datos de API máx. 7 días al desconectar en miConte, máx. 30 días ante revocación desde Google), verificación periódica (>30 días de retención), política de métricas derivadas y prohibición de agregación entre canales sin reconocimiento oficial de Content Owner bajo acuerdos de licencia.
* **Decisiones de Arquitectura (`docs/decisions/`):**
  * [ADR-0001: Arquitectura de Monolito Modular y Aislamiento del Motor Estadístico](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/decisions/0001-modular-monolith-and-statistical-isolation.md)
  * [ADR-0002: Stack de Base de Datos y Acceso a Datos (SQLAlchemy 2.0 + Alembic)](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/decisions/0002-database-and-orm-stack.md)
  * [ADR-0003: Abstracción de Proveedores LLM e Independencia de MCP](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/decisions/0003-llm-abstraction-and-mcp-independence.md)
  * [ADR-0004: Estrategia de Integración con APIs Oficiales de YouTube](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/decisions/0004-youtube-official-apis-integration-strategy.md)
  * [ADR-0005: Modelo de Datos de Dominio, Series Temporales y Gobernanza Relacional](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/decisions/0005-domain-data-model-and-relational-governance.md)
  * [ADR-0006: Cifrado Autenticado de Tokens OAuth (AES-256-GCM) y Ciclo de Vida OAuth 2.0](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/decisions/0006-token-cryptography-and-oauth-lifecycle.md)
  * [ADR-0007: Motor de Sincronización de Datos, Histórico de Métricas y Planificador Periódico](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docs/decisions/0007-synchronization-engine-and-scheduler.md)

---

## Entorno de Desarrollo Local (Fase 1)

### 1. Requisitos Previos e Instalación Reproducible del Entorno Python (`uv.lock`)

En macOS (Apple Silicon `arm64`), el proyecto utiliza **Python 3.15.1** (fijado en [`.python-version`](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/.python-version)) y el archivo de bloqueo determinista [`uv.lock`](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/uv.lock) gestionado con **`uv`**, además de **Docker Desktop** para ejecutar PostgreSQL (`miconte_db`).

#### Opción A (Recomendada — Instalación 100% reproducible con `uv.lock`):
```bash
# 1. Instalar o verificar Python 3.15.1 (definido en .python-version) y sincronizar .venv desde uv.lock
uv sync --extra dev --frozen

# 2. Activar el entorno virtual
source .venv/bin/activate

# 3. Crear archivo local de variables de entorno (excluido de Git)
cp .env.example .env
```

#### Opción B (Alternativa con `venv` + `pip` si aún no tienes `uv` en tu PATH global):
```bash
# 1. Crear un entorno inicial, instalar uv y sincronizar exactamente contra uv.lock
/opt/homebrew/bin/python3 -m venv .venv
.venv/bin/pip install uv
.venv/bin/uv python install 3.15.1
.venv/bin/uv venv --python 3.15.1 --clear .venv
.venv/bin/uv sync --extra dev --frozen

# 2. Crear archivo local de variables de entorno
cp .env.example .env
```

### 2. Variables de Entorno (`MICONTE_`)

Todas las variables de configuración utilizan el prefijo obligatorio `MICONTE_` y están documentadas en [`.env.example`](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/.env.example):

| Variable | Valor por defecto (desarrollo) | Descripción |
| :--- | :--- | :--- |
| `MICONTE_ENVIRONMENT` | `development` | Entorno (`development`, `testing`, `production`). |
| `MICONTE_APP_NAME` | `miConte` | Nombre visible de la aplicación. |
| `MICONTE_API_HOST` | `127.0.0.1` | Host de escucha del servidor FastAPI. |
| `MICONTE_API_PORT` | `8000` | Puerto del servidor FastAPI. |
| `MICONTE_POSTGRES_USER` | `miconte_user` | Usuario de PostgreSQL. |
| `MICONTE_POSTGRES_PASSWORD` | `miconte_dev_password_change_me` | Contraseña local de PostgreSQL (protegida con `SecretStr`). |
| `MICONTE_POSTGRES_DB` | `miconte_db` | Nombre de la base de datos local. |
| `MICONTE_POSTGRES_HOST` | `127.0.0.1` | Host de PostgreSQL. |
| `MICONTE_POSTGRES_PORT` | `5432` | Puerto expuesto de PostgreSQL. |
| `MICONTE_DATABASE_URL` | `postgresql+psycopg://...` | Cadena de conexión SQLAlchemy 2.x con driver `psycopg` v3. |
| `MICONTE_TOKEN_ENCRYPTION_KEY` | *(hex 64 chars)* | Clave maestra AES-256-GCM para cifrado autenticado de tokens OAuth. |
| `MICONTE_TOKEN_ENCRYPTION_KEY_ID` | `k1` | Identificador de versión de la clave de cifrado (soporte para rotación). |
| `MICONTE_OAUTH_STATE_SECRET` | *(string secreto)* | Secreto para firma HMAC-SHA256 del parámetro state anti-CSRF en OAuth. |
| `MICONTE_YOUTUBE_CLIENT_ID` | *(opcional)* | Client ID de Google Cloud OAuth 2.0 Web Application. |
| `MICONTE_YOUTUBE_CLIENT_SECRET` | *(opcional)* | Client Secret de Google Cloud OAuth 2.0 (protegido con `SecretStr`). |
| `MICONTE_YOUTUBE_REDIRECT_URI` | `http://.../callback` | URI de redirección OAuth registrada en Google Cloud Console. |
| `MICONTE_YOUTUBE_API_KEY` | *(opcional)* | API Key pública para llamadas sin autenticar a Data API v3. |
| `MICONTE_SYNC_INTERVAL_HOURS` | `24` | Intervalo en horas para el planificador periódico en segundo plano. |
| `MICONTE_SYNC_ENABLED` | `true` | Habilitar o deshabilitar la ejecución automática del planificador. |
| `MICONTE_SYNC_MAX_VIDEOS_PER_CHANNEL` | `200` | Límite máximo de videos recientes a procesar por canal en cada corrida. |
| `MICONTE_SYNC_ANALYTICS_DAYS` | `30` | Ventana histórica de días hacia atrás para métricas diarias de Analytics. |

### 3. Gestión de PostgreSQL (`miconte_db`) con Docker Compose

El archivo [`docker-compose.yml`](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/docker-compose.yml) levanta `postgres:16-alpine` con persistencia en el volumen nombrado `miconte_pgdata` y comprobación de salud automática (`pg_isready`):

```bash
# Iniciar PostgreSQL en segundo plano
docker compose up -d

# Comprobar el estado y el healthcheck del contenedor
docker compose ps

# Consultar los registros (logs) del contenedor
docker compose logs -f postgres

# Detener el contenedor conservando los datos del volumen miconte_pgdata
docker compose stop

# Detener y eliminar el contenedor (sin borrar el volumen de datos)
docker compose down
```

### 4. Arranque de FastAPI y Endpoints de Salud

```bash
# Iniciar el servidor de desarrollo con recarga automática
.venv/bin/fastapi dev src/miconte/main.py
# Alternativa con uvicorn directo:
# .venv/bin/uvicorn miconte.main:app --host 127.0.0.1 --port 8000 --reload
```

Endpoints de verificación disponibles:
* `GET http://127.0.0.1:8000/api/v1/health`: Comprueba que la aplicación **miConte** está disponible (`HTTP 200`).
* `GET http://127.0.0.1:8000/api/v1/health/db`: Ejecuta una consulta real (`SELECT 1`) contra `miconte_db` en PostgreSQL y distingue entre base de datos disponible (`HTTP 200`, `database: "available"`) y dependencia no disponible (`HTTP 503`, `status: "degraded"`, `database: "unavailable"`), sin exponer credenciales ni cadenas de conexión.

### 5. Migraciones con Alembic (Preparación para Fases Futuras)

Alembic está configurado en [`alembic.ini`](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/alembic.ini) y [`alembic/env.py`](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/alembic/env.py) leyendo dinámicamente `MICONTE_DATABASE_URL` y el `Base.metadata` de [`src/miconte/persistence/base.py`](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/src/miconte/persistence/base.py). En la Fase 1 no se crean todavía las tablas de dominio; en la Fase 3 se operará con:

```bash
# Consultar revisión actual en miconte_db
.venv/bin/alembic current

# Generar una nueva migración (en Fase 3+)
.venv/bin/alembic revision --autogenerate -m "descripcion_del_cambio"

# Aplicar migraciones pendientes
.venv/bin/alembic upgrade head

# Revertir la última migración
.venv/bin/alembic downgrade -1
```

### 6. Ejecución de Pruebas, Linter y Chequeo de Tipos

```bash
# Ejecutar toda la suite de pruebas (unitarias + integración real con PostgreSQL)
.venv/bin/pytest -v

# Ejecutar únicamente pruebas unitarias (sin requerir PostgreSQL activo)
.venv/bin/pytest -m "not integration" -v

# Ejecutar únicamente la prueba real de persistencia contra PostgreSQL
.venv/bin/pytest -m integration -v

# Ejecutar linter Ruff y chequeo estricto de tipos con mypy
.venv/bin/ruff check .
.venv/bin/mypy
```

### 7. Posibles Problemas de Instalación Reproducible y Solución

1. **Demonio de Docker detenido (`failed to connect to the docker API`):** Asegúrate de abrir `Docker.app` (`open -a Docker`) y esperar a que el motor de Docker indique que está en ejecución antes de correr `docker compose up -d`.
2. **Versión de Python del sistema (`/usr/bin/python3` 3.9.6):** No uses el Python preinstalado por Apple en `/usr/bin/python3`. El repositorio incluye [`.python-version`](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/.python-version) apuntando a **Python 3.15.1** (que incorpora las correcciones de seguridad y mantenimiento de octubre de 2026 sobre `3.15.0`) y [`uv.lock`](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/uv.lock) para garantizar instalaciones idénticas bit a bit (`uv sync --extra dev --frozen`).
3. **Conflicto en el puerto `5432`:** Si tienes otra instancia local de PostgreSQL ocupando el puerto `5432`, ajusta `MICONTE_POSTGRES_PORT` y el puerto en `MICONTE_DATABASE_URL` dentro de tu archivo `.env`.

### 8. Motor de Sincronización y Planificador en Segundo Plano (Fase 5)

miConte dispone de un motor de sincronización (`SyncService`) y un planificador asíncrono en segundo plano (`SyncScheduler`, lifespan de FastAPI) para mantener actualizados los metadatos de canales y videos, registrar instantáneas históricas inmutables y almacenar series diarias de YouTube Analytics y Reporting API v1.

#### Endpoints de la API REST (`/api/v1/sync`):

* `GET /api/v1/sync/channels`: Lista los canales autorizados para el usuario autenticado que están disponibles para sincronización.
* `POST /api/v1/sync/channels/{channel_id}/trigger`: Dispara una sincronización manual inmediata (admite payload opcional `{ "stages": ["metadata", "public_snapshots", "analytics_daily", ...] }`). Retorna `HTTP 200` con el resumen tipado del `SyncRunResultDTO`.
* `GET /api/v1/sync/channels/{channel_id}/runs`: Consulta el historial de ejecuciones de sincronización registradas en `sync_runs` para el canal indicado.
* `GET /api/v1/sync/runs/{run_id}`: Consulta el detalle auditado de una corrida de sincronización específica por su UUID.
* `GET /api/v1/sync/scheduler/status`: Consulta el estado operativo del planificador en memoria (`running`, `is_enabled`, `interval_hours`, bloqueos por canal y canales con sincronización vencida).

Todos los endpoints exigen autenticación vía `CurrentUserDep` y verifican la pertenencia del canal al usuario autenticado, previniendo accesos indebidos (IDOR).

---

## Estado Actual del Proyecto

* **Fase 0 — Fundamentación y Arquitectura:** Completada y aprobada.
* **Fase 1 — Entorno y Persistencia Inicial:** Completada y aprobada.
* **Fase 2 — Validación Técnica de las APIs de YouTube:** Completada y aprobada.
* **Fase 3 — Modelo de Datos y Backend de Dominio:** Completada y aprobada.
* **Fase 4 — Integración de Producción con YouTube:** Completada y aprobada (adaptadores oficiales `YouTubeDataClient`, `YouTubeAnalyticsClient`, `YouTubeReportingClient`, servicio criptográfico `TokenEncryptionService` con AES-256-GCM y AAD, flujo OAuth 2.0 Web Server con state anti-CSRF).
* **Fase Actual:** **Fase 5 — Sincronización e Histórico de Métricas** (Completada: motor de sincronización `SyncService`, planificador `SyncScheduler`, ingestión incremental Data API v3, Analytics API v2 y Reporting API v1, snapshots inmutables preservados por `captured_at`, auditoría completa en `sync_runs`, aislamiento IDOR por usuario autenticado, ADR-0007 documentado; 98 pruebas automatizadas aprobadas con 100% de éxito).
* **Próxima Fase:** **Fase 6 — Motor Estadístico Determinista** (Métricas derivadas CTR, APV, Engagement Rate, $V_{24h}$, pruebas de normalidad, contrastes de hipótesis no paramétricos/paramétricos, intervalos de confianza bootstrap al 95%, detección determinista de anomalías y series temporales sin LLM).
