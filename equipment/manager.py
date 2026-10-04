"""CRUD de setups de equipo sobre SQLite (tabla ``equipment_setups``)."""
from db.connection import get_connection

from .models import EquipmentSetup


def create(setup: EquipmentSetup) -> int:
    """Guarda un setup y devuelve su id.

    Contrato D-5: al insertar **re-sincroniza** ``setup.images`` —la lista es
    la verdad al guardar—: adjunta sus imágenes (copiadas a ``data/``, D-1).
    El diálogo solo edita la lista en memoria (cancelar no toca ficheros) y
    llama a ``create`` al confirmar.
    """
    raise NotImplementedError


def update(setup: EquipmentSetup) -> None:
    """Actualiza un setup existente.

    Contrato D-5: **re-sincroniza** ``setup.images`` —la lista es la verdad
    al guardar—: adjunta las que falte y quita las que sobren (``remove``),
    sin tocar el ``kind`` de las que siguen. Parte siempre de la lista que
    devuelva ``images.list_images()``; una lista vacía vacía las imágenes.
    """
    raise NotImplementedError


def delete(setup_id: int) -> None:
    """Elimina un setup (sus imágenes adjuntas se borran en cascada).

    Al borrarse, las ``planned_sessions`` que apuntaban a él quedan
    desvinculadas en silencio (``ON DELETE SET NULL``, M-20): la confirmación
    del borrado debe avisar antes con ``count_sessions``.
    """
    raise NotImplementedError


def get(setup_id: int) -> dict | None:
    """Carga un setup por id (dict de fila, como ya espera la UI)."""
    raise NotImplementedError


def list_setups(category: str | None = None) -> list[dict]:
    """Lista todos los setups (dicts de fila), opcionalmente por categoría.

    El contrato real es **dict**, no ``EquipmentSetup``: la UI lee
    ``setup.get("id")`` y así se anota desde la auditoría (C-2). El dict
    trae además ``location_name`` (``LEFT JOIN`` a ``locations``): el nombre
    de la ubicación, o ``None`` si no la tiene —lo que la tabla del plan
    (Equipo paso 2) pinta como «ubicación» (M-17). Sin ubicación o con ella
    borrada (``ON DELETE SET NULL``) la clave siempre está: ``.get()`` sirve
    para ambos casos.
    """
    conn = get_connection()
    sql = (
        "SELECT e.*, l.name AS location_name FROM equipment_setups e"
        " LEFT JOIN locations l ON l.id = e.location_id"
        + (" WHERE e.category = ?" if category else "")
        + " ORDER BY e.name"
    )
    rows = conn.execute(sql, (category,) if category else ()).fetchall()
    return [dict(row) for row in rows]


def count_sessions(setup_id: int) -> int:
    """Nº de sesiones planificadas que apuntan a este setup (aviso de M-20).

    El esquema desvincula esas sesiones con ``ON DELETE SET NULL`` al borrar
    el setup; este conteo es lo que la confirmación del borrado debe mostrar
    para que no pase en silencio. Con ``setup_id`` inexistente devuelve 0.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM planned_sessions WHERE setup_id = ?", (setup_id,)
    ).fetchone()
    return int(row[0])
