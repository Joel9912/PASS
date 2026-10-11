# db/

## Qué es
Capa de persistencia de PASS: conexión única a **SQLite** (módulo `sqlite3` de la librería estándar, sin dependencias externas) y esquema en SQL.

## Estado actual
- `connection.py` — conexión única (`get_connection`; aplica `schema.sql` completo en la primera conexión, idempotente) y `init_db()`. Base en `data/pass.db` (no versionada); un fallo de esquema cierra la conexión sin publicarla globalmente.
  - Si una base v1 aún tiene valores en las columnas embebidas de `equipment_setups`, detiene la migración **antes** de modificar el esquema; esos datos requieren una migración acordada, nunca se borran por `DROP COLUMN` silenciosamente.
  - **`_MIGRATIONS`**: dict `tabla → columnas` que se aplica con `PRAGMA table_info` + `ALTER TABLE` (SQLite no admite `ADD COLUMN IF NOT EXISTS`). Hoy cubre `locations`, `equipment_setups`, `personal_catalog`, `planned_sessions` y las 4 piezas (`telescopes`, `cameras`, `mounts`, `filters` — precio/peso por pieza).
- `settings.py` — helpers `get_setting(key, default)` / `set_setting(key, value)` sobre la tabla `settings` (upsert + commit). Punto único para la configuración persistente: API keys del clima, ruta de SirIL (`siril_path`), carpeta base de proyectos, etc.
- `schema.sql` — tablas: `locations` (con `utc_offset_hours`, desfase horario, y `seeing_arcsec` — seeing típico ″), componentes (`telescopes`, `cameras`, `mounts` con `price_eur`/`weight_kg` por pieza y `filters` solo con `price_eur`), `equipment_setups` (columnas de FOV, `price_eur`/`weight_kg` — D-3 — y `notes`), `equipment_images`, `personal_catalog` (con `kind`, `ra_hours`/`dec_deg`, FOV, teselas de región y `notes` — M-21), `planned_sessions` (con `target_kind`, encuadre, `notes` y `status`), `calibrated_sessions` (ruta de origen única, salida, frames/exposición; creada con `IF NOT EXISTS` sin perder bases anteriores), `settings`, `catalog` (objetos deep-sky) y `stars`.
- Sin ORM: consultas directas con `sqlite3`.

## Qué hacer aquí
- Aquí SOLO vive la capa de datos: conexión, esquema y migraciones.
- Al añadir una tabla: editar `schema.sql` (siempre `IF NOT EXISTS`) y documentarla aquí.
- Al añadir una columna: **ambas cosas** — la columna en `schema.sql` (bases nuevas) y una entrada en `_MIGRATIONS` (bases existentes) — y documentarlo aquí.
- El resto de carpetas acceden a datos vía `db.connection.get_connection()`; no abran sus propias conexiones.
- Fecha/hora se guardan en TEXT con formato `datetime('now')` (UTC).

## Planes futuros
- Migraciones versionadas con número de revisión si el esquema crece más.
- Persistencia adicional de resultados finales si el flujo la requiere (el calibrado ya se guarda).
- **Bajos de la auditoría de código**: índices en columnas filtradas/ordenadas (`catalog.catalog`, `planned_sessions.session_date`…; 15k filas, coste hoy en ms); `_migrate_columns` traga el error de `PRAGMA` en vez de avisar; `init_db()` duplica `_apply_schema()` y no tiene llamantes (unificar o borrar).
