# ADR-0002: Stack de Base de Datos y Acceso a Datos (SQLAlchemy 2.0 + Alembic sobre PostgreSQL)

* **Estado:** Aceptado
* **Fecha:** 2026-10-24
* **Fase:** Fase 0 — Fundamentación y Arquitectura

---

## Contexto

Durante la inspección de las skills instaladas en `.agents/skills/` en la Fase 0 se identificó una discrepancia:
* La skill genérica de terceros `fastapi` (`.agents/skills/fastapi/SKILL.md`, línea 284) sugiere preferir `SQLModel` sobre `SQLAlchemy`.
* Sin embargo, las reglas obligatorias del repositorio definidas en `AGENTS.md` (Sección 1 y Sección 2.3), el documento de contexto global de **miConte** y la skill de gobernanza propia `miconte-phase-workflow` especifican explícitamente **PostgreSQL**, **SQLAlchemy** y **Alembic**.

Además, **miConte** necesita almacenar series temporales diarias, instantáneas (*snapshots*) históricas inmutables, realizar operaciones idempotentes de sincronización (`UPSERT` nativo de PostgreSQL con `INSERT ... ON CONFLICT DO UPDATE`), índices compuestos y restricciones avanzadas documentadas en la skill `postgres-best-practices`.

---

## Decisión

1. Utilizar **PostgreSQL 16 / 17** como motor de base de datos relacional único, con el nombre de base de datos local estandarizado en **`miconte_db`**.
2. Utilizar **SQLAlchemy 2.0+** (con sintaxis moderna tipada `Mapped[...]` y `mapped_column(...)`) y **Alembic** para el acceso a datos y la gestión de migraciones de esquema, descartando `SQLModel` para evitar limitaciones en consultas analíticas complejas e índices compuestos.
3. Utilizar el adaptador **`psycopg` (v3)** para la conectividad con PostgreSQL.
4. Separar el modelo de datos histórico en tres niveles temporales cuando se implemente la persistencia inicial (Fase 1) y el modelo de dominio (Fase 3):
   * **Entidades de Catálogo Actual:** `channels` y `videos` (estado descriptivo más reciente).
   * **Instantáneas Públicas (`Snapshots`):** `video_public_snapshots` (capturas periódicas fechadas con `captured_at` de conteos acumulados de `YouTube Data API v3`, útiles para calcular velocidades como $V_{24h}$).
   * **Series Diarias Privadas:** `video_daily_metrics` (métricas por día calendario `(video_id, metric_date)` provenientes de `YouTube Analytics API v2` y, en su caso, reportes de alcance de `YouTube Reporting API v1`).

---

## Consecuencias

### Positivas
* Alineación total con `AGENTS.md`, `miconte-phase-workflow` y `postgres-best-practices`.
* Soporte completo de SQLAlchemy 2.0 para expresiones `postgresql.insert(...).on_conflict_do_update(...)`, garantizando sincronizaciones idempotentes.
* Tipado estático compatible con `mypy` sin la fricción de herencia dual Pydantic/SQLAlchemy que presenta `SQLModel` en relaciones complejas.

### Negativas / Compromisos
* Los esquemas de la API REST (Pydantic v2) y los modelos de persistencia (SQLAlchemy 2.0) se declaran en módulos separados (`miconte.schemas` y `miconte.persistence.models`), lo cual refuerza a su vez el desacoplamiento entre la base de datos y el contrato público HTTP.
