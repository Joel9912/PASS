"""Conexión SQLite única para PASS (sin dependencias externas)."""
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
    las columnas añadidas a tablas ya existentes se migran después y las
    obsoletas de la v1 se quitan (``_drop_legacy_columns``).
    """
    _check_legacy_data(conn)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate_columns(conn)
    _drop_legacy_columns(conn)
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
    """Impide borrar componentes v1 poblados sin una migración de datos acordada.

    Se ejecuta antes de aplicar el esquema: abrir una BD antigua con valores
    embebidos no debe descartarlos silenciosamente al hacer ``DROP COLUMN``.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(equipment_setups)")}
    for name in _LEGACY_SETUP_COLUMNS:
        if name in existing and conn.execute(
            f'SELECT 1 FROM equipment_setups WHERE "{name}" IS NOT NULL LIMIT 1'
        ).fetchone():
            raise sqlite3.DatabaseError(
                "La base contiene datos de equipo v1 sin migrar; se conservan "
                "sin abrir hasta definir su migración."
            )


def _drop_legacy_columns(conn: sqlite3.Connection) -> None:
    """Quita de ``equipment_setups`` las columnas embebidas de la v1 (idempotente).

    SQLite solo admite ``DROP COLUMN`` desde la 3.35 y sin «IF NOT EXISTS»,
    así que se comprueba con ``PRAGMA table_info`` antes de alterar. Las
    tablas de equipo estaban vacías en la base real (el CRUD era stub: no
    existía forma de insertar sin ``create()``), así que no hay datos que
    perder.
    """
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(equipment_setups)")}
    except sqlite3.Error:
        return
    for name in _LEGACY_SETUP_COLUMNS:
        if name in existing:
            conn.execute(f"ALTER TABLE equipment_setups DROP COLUMN {name}")


def init_db(conn: sqlite3.Connection | None = None) -> None:
    """Aplica el esquema de `schema.sql` (idempotente)."""
    _apply_schema(conn if conn is not None else get_connection())
