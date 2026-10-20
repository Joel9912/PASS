"""Conexión SQLite única para PASS (sin dependencias externas)."""
import math
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "pass.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_connection: sqlite3.Connection | None = None

#: Migración de columnas para bases creadas con un esquema anterior.
#: SQLite no admite ``ADD COLUMN IF NOT EXISTS``, así que se comprueba con
#: ``PRAGMA table_info`` antes de alterar cada tabla.
_MIGRATIONS: dict[str, tuple[str, ...]] = {
    "catalog_editions": ("schema_version INTEGER NOT NULL DEFAULT 1",),
    "locations": (
        # Desfase horario para pasar efemérides de UTC a hora de reloj.
        "utc_offset_hours REAL",
        # Bloque de sitio de la pestaña Equipo (JSON con las 8 direcciones).
        "obstacles TEXT",
        "lp TEXT",
        # Bortle es obligatorio en el formulario, no en la columna: SQLite
        # no admite ADD COLUMN NOT NULL sin default y no queremos inventarlo.
        "bortle INTEGER",
        "sqm REAL",
        # Seeing típico de la ubicación (FWHM en ″): alimenta el rango de
        # muestreo del equipo; sin dato no se inventa.
        "seeing_arcsec REAL",
        "consider_lp INTEGER NOT NULL DEFAULT 1",
    ),
    "equipment_setups": (
        "category TEXT NOT NULL DEFAULT 'general'",
        "location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL",
        "notes TEXT",
        "created_at TEXT",
        "legacy_components_migrated INTEGER NOT NULL DEFAULT 0",
        # Componentes globales (pestaña Equipo v2): el equipo pasa a
        # referenciarlos. El executescript del esquema corre antes, así que
        # las tablas a las que apuntan ya existen al hacer el ADD COLUMN.
        "telescope_id INTEGER REFERENCES telescopes(id) ON DELETE SET NULL",
        "guide_telescope_id INTEGER REFERENCES telescopes(id) ON DELETE SET NULL",
        "camera_id INTEGER REFERENCES cameras(id) ON DELETE SET NULL",
        "guide_camera_id INTEGER REFERENCES cameras(id) ON DELETE SET NULL",
        "mount_id INTEGER REFERENCES mounts(id) ON DELETE SET NULL",
        # Precio/peso de la comparativa (D-3): añadidos antes del paso 6
        # para que el esquema se migre una sola vez.
        "price_eur REAL",
        "weight_kg REAL",
    ),
    "personal_catalog": (
        "pass_object_id TEXT",
        "kind TEXT NOT NULL DEFAULT 'catalog'",
        "ra_hours REAL",
        "dec_deg REAL",
        "fov_major_arcmin REAL",
        "fov_minor_arcmin REAL",
        "tiles_x INTEGER",
        "tiles_y INTEGER",
        # Estaba en el esquema y se inserta, pero no en la migración: una
        # base creada antes no recibía la columna.
        "notes TEXT",
    ),
    "planned_sessions": (
        "pass_object_id TEXT",
        "target_kind TEXT NOT NULL DEFAULT 'catalog'",
        "ra_hours REAL",
        "dec_deg REAL",
        "fov_major_arcmin REAL",
        "fov_minor_arcmin REAL",
        "tiles_x INTEGER",
        "tiles_y INTEGER",
        "notes TEXT",
    ),
    # Precio/peso por pieza (la cabecera del equipo los suma en vivo y los
    # persiste en `equipment_setups` al guardar — D-3).
    "telescopes": (
        "price_eur REAL",
        "weight_kg REAL",
    ),
    "cameras": (
        "price_eur REAL",
        "weight_kg REAL",
    ),
    "mounts": (
        "price_eur REAL",
        "weight_kg REAL",
    ),
    "filters": (
        # Solo precio: el peso de los filtros se ignora en los totales.
        "price_eur REAL",
    ),
}


def get_connection() -> sqlite3.Connection:
    """Devuelve la conexión única; se crea bajo demanda en `data/pass.db`.

    En la primera conexión se aplica el esquema si la base está vacía,
    de modo que todos los módulos pueden usarla sin pasos previos.
    """
    global _connection
    if _connection is None:
        DATA_DIR.mkdir(exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            _apply_schema(conn)
        except Exception:
            conn.rollback()
            conn.close()
            raise
        _connection = conn
    return _connection


def _apply_schema(conn: sqlite3.Connection) -> None:
    """Aplica `schema.sql` (idempotente: todo usa IF NOT EXISTS).

    Así una base creada con un esquema antiguo recibe las tablas nuevas;
    Migra piezas v1 conservando sus columnas pobladas como original y elimina
    solo columnas legacy vacías. Esquema y datos se confirman conjuntamente;
    si el llamante ya tenía una transacción, conserva su control sobre ella.
    """
    _check_legacy_data(conn)
    conn.execute("SAVEPOINT pass_schema")
    try:
        statement = ""
        for line in SCHEMA_PATH.read_text(encoding="utf-8").splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                conn.execute(statement)
                statement = ""
        if statement.strip():
            conn.execute(statement)
        _migrate_columns(conn)
        _migrate_legacy_equipment(conn)
        _drop_legacy_columns(conn)
        conn.execute("RELEASE SAVEPOINT pass_schema")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK TO SAVEPOINT pass_schema")
            conn.execute("RELEASE SAVEPOINT pass_schema")
        raise


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Añade a las tablas existentes las columnas que les falten (ALTER TABLE)."""
    for table, definitions in _MIGRATIONS.items():
        try:
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.Error:
            continue
        if not existing:
            continue  # la tabla no existe: el esquema la creará completa
        for definition in definitions:
            name = definition.split()[0]
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
                existing.add(name)


#: Columnas embebidas de la v1 de `equipment_setups`: la pestaña Equipo v2
#: las movió a sus tablas (`telescopes`, `cameras`, `mounts`). Están fuera
#: de `_MIGRATIONS` a propósito: si quedaran ahí, una base fresca las
#: recibiría de nuevo por ADD COLUMN y quedaría esquema huérfano.
_LEGACY_SETUP_COLUMNS = (
    "telescope_name",
    "telescope_aperture_mm",
    "telescope_focal_mm",
    "camera_name",
    "camera_cooled",
    "camera_resolution",
    "camera_bit_depth",
    "camera_pixel_size_um",
    "camera_width_px",
    "camera_height_px",
    "mount_name",
)


def _check_legacy_data(conn: sqlite3.Connection) -> None:
    """Rechaza conflictos antes de modificar esquema: una asignación actual nunca se pisa ni fusiona."""
    for row in _legacy_rows(conn):
        for kind in ("telescope", "camera", "mount"):
            if row.get(f"{kind}_id") is not None and _has_legacy_piece(row, kind):
                raise sqlite3.DatabaseError(
                    f"Migración de equipo v1: conflicto en equipo #{row['id']} ({kind}); "
                    "ya tiene una pieza asignada. Se conservan los datos sin modificar; "
                    "resuelve la asignación antes de migrar.")


def _legacy_rows(conn: sqlite3.Connection) -> list[dict]:
    """Lee filas pendientes por nombre de columna sin exigir row_factory al llamante."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(equipment_setups)")}
    if not existing.intersection(_LEGACY_SETUP_COLUMNS):
        return []
    cursor = conn.execute("SELECT * FROM equipment_setups")
    names = [column[0] for column in cursor.description]
    rows = [dict(zip(names, values, strict=True)) for values in cursor]
    return [row for row in rows if not row.get("legacy_components_migrated")]


def _has_legacy_piece(row: dict, kind: str) -> bool:
    """Distingue valores de pieza de una casilla no marcada por defecto, que no crea una cámara."""
    fields = [name for name in _LEGACY_SETUP_COLUMNS
              if name.startswith(kind + "_") and name != "camera_cooled"]
    return any(row.get(name) not in (None, "") for name in fields) or (
        kind == "camera" and row.get("camera_cooled") not in (None, 0))


def _migrate_legacy_equipment(conn: sqlite3.Connection) -> None:
    """Crea piezas por equipo, conserva legacy y marca el traslado para no duplicar ni resucitar borradas.

    No deduce dimensiones de textos de resolución ni reparte precios/pesos
    del equipo. Las casillas sin marcar significan No, según acuerdo del usuario.
    """
    fields = {
        "telescope": ("name", "aperture_mm", "focal_mm"),
        "camera": ("name", "cooled", "pixel_size_um", "width_px", "height_px", "bit_depth"),
        "mount": ("name",),
    }
    tables = {"telescope": "telescopes", "camera": "cameras", "mount": "mounts"}
    labels = {"telescope": "Telescopio", "camera": "Cámara", "mount": "Montura"}
    for row in _legacy_rows(conn):
        for kind, attributes in fields.items():
            if not _has_legacy_piece(row, kind):
                continue
            values = {name: row.get(f"{kind}_{name}") for name in attributes}
            for name, value in values.items():
                if name in ("name", "cooled") or value is None:
                    continue
                if (not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
                    or (name in ("width_px", "height_px", "bit_depth") and int(value) != value)):
                    raise sqlite3.DatabaseError(
                        f"Datos de equipo v1 inválidos: #{row['id']}, {kind}_{name}; se conservan sin migrar.")
            if "cooled" in values:
                if values["cooled"] not in (None, 0, 1):
                    raise sqlite3.DatabaseError(f"Datos de equipo v1 inválidos: #{row['id']}, camera_cooled.")
                values["cooled"] = values["cooled"] or 0
            if not isinstance(values["name"], str) or not values["name"].strip():
                values["name"] = f"{labels[kind]} sin nombre · equipo v1 #{row['id']}"
            values["notes"] = f"Migrado del equipo v1 #{row['id']}; valores originales conservados en el equipo."
            if kind == "camera" and row.get("camera_resolution") is not None:
                values["notes"] += f"\nResolución v1 (texto original): {row['camera_resolution']}"
            columns = ", ".join(values)
            placeholders = ", ".join("?" for _ in values)
            inserted = conn.execute(f"INSERT INTO {tables[kind]} ({columns}) VALUES ({placeholders})", tuple(values.values()))
            conn.execute(f"UPDATE equipment_setups SET {kind}_id=? WHERE id=?", (inserted.lastrowid, row["id"]))
        conn.execute("UPDATE equipment_setups SET legacy_components_migrated=1 WHERE id=?", (row["id"],))


def _drop_legacy_columns(conn: sqlite3.Connection) -> None:
    """Retira solo legacy vacío; si hay valores originales los conserva íntegros para trazabilidad."""
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(equipment_setups)")}
    except sqlite3.Error:
        return
    legacy = existing.intersection(_LEGACY_SETUP_COLUMNS)
    if legacy:
        populated = " OR ".join(f'"{name}" IS NOT NULL' for name in sorted(legacy))
        if conn.execute(f"SELECT 1 FROM equipment_setups WHERE {populated} LIMIT 1").fetchone():
            return
    for name in _LEGACY_SETUP_COLUMNS:
        if name in existing:
            conn.execute(f"ALTER TABLE equipment_setups DROP COLUMN {name}")


def init_db(conn: sqlite3.Connection | None = None) -> None:
    """Aplica el esquema de `schema.sql` (idempotente)."""
    _apply_schema(conn if conn is not None else get_connection())
