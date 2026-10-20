"""Catálogo personal: objetos y regiones que el usuario guarda.

Se persiste en la tabla ``personal_catalog`` (ver ``db/schema.sql``) y se usa
como fuente de la subpestaña "Catálogo personal".

Además de objetos del catálogo global, admite **regiones de interés**
(``kind='region'``): centro RA/Dec, encuadre (FOV) y teselas de mosaico
definidos por el usuario. Las regiones NO se pintan en el planetario (solo
se usan en planificación) para no ensuciar la vista estelar.
"""
from db.connection import get_connection


def add(
    object_id: str,
    catalog: str,
    notes: str = "",
    kind: str = "catalog",
    ra_hours: float | None = None,
    dec_deg: float | None = None,
    fov_major_arcmin: float | None = None,
    fov_minor_arcmin: float | None = None,
    tiles_x: int | None = None,
    tiles_y: int | None = None,
) -> bool:
    """Guarda idempotentemente e indica si insertó; los duplicados conservan los valores originales."""
    conn = get_connection()
    inserted = conn.execute(
        "INSERT OR IGNORE INTO personal_catalog (object_id, catalog, kind, notes,"
        " ra_hours, dec_deg, fov_major_arcmin, fov_minor_arcmin, tiles_x, tiles_y)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (object_id, catalog, kind, notes, ra_hours, dec_deg,
         fov_major_arcmin, fov_minor_arcmin, tiles_x, tiles_y),
    )
    conn.commit()
    return inserted.rowcount == 1


def add_region(
    name: str,
    ra_hours: float,
    dec_deg: float,
    fov_major_arcmin: float | None = None,
    fov_minor_arcmin: float | None = None,
    tiles_x: int | None = None,
    tiles_y: int | None = None,
    notes: str = "",
) -> None:
    """Crea una región de interés (mosaico o encuadre libre) guardada.

    El ``catalog`` es ``'region'``: así nunca choca con los catálogos reales
    y la región se distingue de un objeto con la misma designación. Un nombre
    regional repetido se rechaza con aviso, sin modificar la región existente.
    """
    inserted = add(
        object_id=name,
        catalog="region",
        notes=notes,
        kind="region",
        ra_hours=ra_hours,
        dec_deg=dec_deg,
        fov_major_arcmin=fov_major_arcmin,
        fov_minor_arcmin=fov_minor_arcmin,
        tiles_x=tiles_x,
        tiles_y=tiles_y,
    )
    if not inserted:
        raise ValueError("Ya existe una región con ese nombre. Se conserva la existente; elige otro nombre.")


def remove(object_id: str, catalog: str) -> None:
    """Elimina un objeto o región del catálogo personal."""
    conn = get_connection()
    conn.execute(
        "DELETE FROM personal_catalog WHERE object_id = ? AND catalog = ?",
        (object_id, catalog),
    )
    conn.commit()


def update_notes(object_id: str, catalog: str, notes: str) -> None:
    """Actualiza las notas de un elemento guardado."""
    conn = get_connection()
    conn.execute(
        "UPDATE personal_catalog SET notes = ? WHERE object_id = ? AND catalog = ?",
        (notes, object_id, catalog),
    )
    conn.commit()


def list_objects() -> list[dict]:
    """Devuelve todo lo guardado, con los datos del catálogo si lo hay.

    El LEFT JOIN aporta nombre, magnitud y coordenadas para los objetos del
    catálogo global (si ya no existe, esos campos vienen None). Las regiones
    llevan su centro y encuadre en sus propias columnas; ``ra_hours``/
    ``dec_deg`` del resultado son los del catálogo si existen y si no los de
    la región, para que la UI pueda leer siempre una coordenada.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT p.object_id, p.catalog, p.kind, p.notes, p.created_at,"
        "       p.ra_hours AS region_ra_hours, p.dec_deg AS region_dec_deg,"
        "       p.fov_major_arcmin, p.fov_minor_arcmin, p.tiles_x, p.tiles_y,"
        "       c.name, c.type, c.magnitude,"
        "       COALESCE(c.ra_hours, p.ra_hours) AS ra_hours,"
        "       COALESCE(c.dec_deg, p.dec_deg) AS dec_deg,"
        "       c.size_major_arcmin, c.size_minor_arcmin, c.constellation"
        " FROM personal_catalog p"
        " LEFT JOIN catalog c ON c.object_id = p.object_id AND c.catalog = p.catalog"
        " ORDER BY p.created_at"
    ).fetchall()
    return [dict(row) for row in rows]
