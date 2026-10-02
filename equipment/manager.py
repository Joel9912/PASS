"""CRUD de setups de equipo sobre SQLite (tabla ``equipment_setups``)."""
from db.connection import get_connection

from .models import EquipmentSetup


def create(setup: EquipmentSetup) -> int:
    """Guarda un setup y devuelve su id."""
    raise NotImplementedError


def update(setup: EquipmentSetup) -> None:
    """Actualiza un setup existente."""
    raise NotImplementedError


def delete(setup_id: int) -> None:
    """Elimina un setup (sus imágenes adjuntas se borran en cascada)."""
    raise NotImplementedError


def get(setup_id: int) -> EquipmentSetup | None:
    """Carga un setup por id."""
    raise NotImplementedError


def list_setups(category: str | None = None) -> list[EquipmentSetup]:
    """Lista todos los setups, opcionalmente por categoría."""
    conn = get_connection()
    if category:
        rows = conn.execute(
            "SELECT * FROM equipment_setups WHERE category = ? ORDER BY name", (category,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM equipment_setups ORDER BY name").fetchall()
    return [dict(row) for row in rows]
