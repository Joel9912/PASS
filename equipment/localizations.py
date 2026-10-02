"""CRUD de localizaciones geográficas (tabla ``locations``)."""
from db.connection import get_connection

from .models import Location


def create(location: Location) -> int:
    """Guarda una localización y devuelve su id."""
    raise NotImplementedError


def list_locations() -> list[Location]:
    """Lista todas las localizaciones del usuario."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM locations ORDER BY name").fetchall()
    return [dict(row) for row in rows]


def delete(location_id: int) -> None:
    """Elimina una localización (los setups que la usan quedan sin ella)."""
    conn = get_connection()
    conn.execute("DELETE FROM locations WHERE id = ?", (location_id,))
    conn.commit()
