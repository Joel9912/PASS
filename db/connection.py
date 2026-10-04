"""Conexión SQLite única para PAS.S (sin dependencias externas)."""
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
    "locations": (
        # Desfase horario para pasar efemérides de UTC a hora de reloj.
        "utc_offset_hours REAL",
    ),
    "equipment_setups": (
        "camera_pixel_size_um REAL",
        "camera_width_px INTEGER",
        "camera_height_px INTEGER",
    ),
    "personal_catalog": (
        "kind TEXT NOT NULL DEFAULT 'catalog'",
        "ra_hours REAL",
        "dec_deg REAL",
        "fov_major_arcmin REAL",
        "fov_minor_arcmin REAL",
        "tiles_x INTEGER",
        "tiles_y INTEGER",
        # Estaba en el esquema y se inserta, pero no en la migración: una
        # base creada antes no recibía la columna (M-21 de la auditoría).
        "notes TEXT",
    ),
    "planned_sessions": (
        "target_kind TEXT NOT NULL DEFAULT 'catalog'",
        "ra_hours REAL",
        "dec_deg REAL",
        "fov_major_arcmin REAL",
        "fov_minor_arcmin REAL",
        "tiles_x INTEGER",
        "tiles_y INTEGER",
        "notes TEXT",
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
        _connection = sqlite3.connect(DB_PATH)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA foreign_keys = ON")
        _apply_schema(_connection)
    return _connection


def _apply_schema(conn: sqlite3.Connection) -> None:
    """Aplica `schema.sql` (idempotente: todo usa IF NOT EXISTS).

    Así una base creada con un esquema antiguo recibe las tablas nuevas;
    las columnas añadidas a tablas ya existentes se migran después.
    """
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate_columns(conn)
    conn.commit()


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


def init_db(conn: sqlite3.Connection | None = None) -> None:
    """Aplica el esquema de `schema.sql` (idempotente)."""
    target = conn if conn is not None else get_connection()
    target.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate_columns(target)
    target.commit()


def close_connection() -> None:
    """Cierra la conexión global si existe."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None
