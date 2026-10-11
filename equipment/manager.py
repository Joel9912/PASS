"""CRUD de setups de equipo sobre SQLite (tabla ``equipment_setups``)."""
from db.connection import get_connection

from . import images
from .metrics import focal_efectiva
from .models import EquipmentSetup
from .validaciones import validar_setup

#: Columnas de fila + alias de JOIN (los cuatro últimos son el contrato con
#: ``planners/framing.calculate_fov``: si un alias falta, la Planificación
#: deja de calcular FOV en silencio).
_SELECT = (
    "SELECT e.id, e.name, e.category, e.location_id, e.price_eur, e.weight_kg,"
    " e.notes, e.telescope_id, e.guide_telescope_id, e.camera_id,"
    " e.guide_camera_id, e.mount_id,"
    " l.name AS location_name,"
    " t.name AS telescope_name, gt.name AS guide_telescope_name,"
    " t.focal_mm AS telescope_focal_mm, t.reducer, t.reducer_factor,"
    " t.aperture_mm AS telescope_aperture_mm,"
    " c.name AS camera_name, gc.name AS guide_camera_name,"
    " c.pixel_size_um AS camera_pixel_size_um, c.width_px AS camera_width_px,"
    " c.height_px AS camera_height_px, c.bit_depth AS camera_bit_depth,"
    " c.cooled AS camera_cooled, c.mono, c.ampglow,"
    " m.name AS mount_name"
    " FROM equipment_setups e"
    " LEFT JOIN locations l ON l.id = e.location_id"
    " LEFT JOIN telescopes t ON t.id = e.telescope_id"
    " LEFT JOIN cameras c ON c.id = e.camera_id"
    " LEFT JOIN telescopes gt ON gt.id = e.guide_telescope_id"
    " LEFT JOIN cameras gc ON gc.id = e.guide_camera_id"
    " LEFT JOIN mounts m ON m.id = e.mount_id"
)


def _fila(row) -> dict:
    """Dict de fila con ``telescope_focal_mm`` en focal **efectiva** (R2).

    El SELECT trae la focal cruda en esa misma clave (la que lee
    ``framing.calculate_fov``) y aquí se sobreescribe con
    ``metrics.focal_efectiva``: la regla del reductor vive en un solo sitio
    y el FOV sale correcto sin tocar ``planners/``. Sin óptica el alias
    llega ``None`` y sigue siendo ``None``.
    """
    d = dict(row)
    d["telescope_focal_mm"] = focal_efectiva(
        d.get("telescope_focal_mm"), bool(d.get("reducer")), d.get("reducer_factor")
    )
    return d


def create(setup: EquipmentSetup) -> int:
    """Guarda un setup y devuelve su id (lo deja en ``setup.id``).

    Contrato D-5: al insertar **re-sincroniza** ``setup.images`` —la lista es
    la verdad al guardar—: adjunta sus imágenes (copiadas a ``data/``, D-1).
    El diálogo solo edita la lista en memoria (cancelar no toca ficheros) y
    llama a ``create`` al confirmar. ``filter_ids`` se sincroniza igual con
    ``setup_filters`` (M2M, diff por conjunto).
    """
    validar_setup(setup)
    conn = get_connection()
    _validar_filtros(conn, setup.filter_ids)
    cur = conn.execute(
        "INSERT INTO equipment_setups (name, category, location_id, telescope_id,"
        " guide_telescope_id, camera_id, guide_camera_id, mount_id, price_eur,"
        " weight_kg, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            setup.name,
            setup.category,
            setup.location_id,
            setup.telescope_id,
            setup.guide_telescope_id,
            setup.camera_id,
            setup.guide_camera_id,
            setup.mount_id,
            setup.price_eur,
            setup.weight_kg,
            setup.notes,
        ),
    )
    conn.commit()
    setup.id = cur.lastrowid
    images.sync("setup", setup.id, setup.images)
    _sync_filters(setup.id, setup.filter_ids)
    return setup.id


def update(setup: EquipmentSetup) -> None:
    """Actualiza un setup existente.

    Contrato D-5: **re-sincroniza** ``setup.images`` —la lista es la verdad
    al guardar—: adjunta las que falte y quita las que sobren (``remove``),
    sin tocar el ``kind`` de las que siguen. Parte siempre de la lista que
    devuelva ``images.list_images()``; una lista vacía vacía las imágenes.
    ``filter_ids`` se sincroniza igual con ``setup_filters``.
    """
    if setup.id is None:
        raise ValueError("Equipo: falta el id (crea antes de actualizar).")
    validar_setup(setup)
    conn = get_connection()
    _validar_filtros(conn, setup.filter_ids)
    conn.execute(
        "UPDATE equipment_setups SET name = ?, category = ?, location_id = ?,"
        " telescope_id = ?, guide_telescope_id = ?, camera_id = ?,"
        " guide_camera_id = ?, mount_id = ?, price_eur = ?, weight_kg = ?,"
        " notes = ? WHERE id = ?",
        (
            setup.name,
            setup.category,
            setup.location_id,
            setup.telescope_id,
            setup.guide_telescope_id,
            setup.camera_id,
            setup.guide_camera_id,
            setup.mount_id,
            setup.price_eur,
            setup.weight_kg,
            setup.notes,
            setup.id,
        ),
    )
    conn.commit()
    images.sync("setup", setup.id, setup.images)
    _sync_filters(setup.id, setup.filter_ids)


def delete(setup_id: int) -> None:
    """Elimina un setup (imágenes y filtros en cascada; sesiones desvinculadas).

    Las ``planned_sessions`` quedan desvinculadas en silencio (``ON DELETE
    SET NULL``, M-20): la confirmación del borrado debe avisar antes con
    ``count_sessions``. Las filas de imágenes y de ``setup_filters`` las
    lleva la FK en cascada; los ficheros, ``images.purge``.
    """
    conn = get_connection()
    conn.execute("DELETE FROM equipment_setups WHERE id = ?", (setup_id,))
    conn.commit()
    images.purge("setup", setup_id)


def get(setup_id: int) -> dict | None:
    """Carga un setup por id (mismos alias que ``list_setups``) o ``None``.

    Además de las claves del JOIN trae ``filter_ids`` (los filtros
    asignados hoy, ordenados): el formulario de edición necesita la
    asignación completa y ``list_setups`` no la trae — la lista solo pinta
    nombre y categoría. Sin filtros → lista vacía.
    """
    conn = get_connection()
    row = conn.execute(_SELECT + " WHERE e.id = ?", (setup_id,)).fetchone()
    if not row:
        return None
    d = _fila(row)
    filas = conn.execute(
        "SELECT filter_id FROM setup_filters WHERE setup_id = ?"
        " ORDER BY filter_id",
        (setup_id,),
    ).fetchall()
    d["filter_ids"] = [f[0] for f in filas]
    return d


def list_setups(category: str | None = None) -> list[dict]:
    """Lista todos los setups (dicts de fila), opcionalmente por categoría.

    El contrato real es **dict**, no ``EquipmentSetup``: la UI lee
    ``setup.get("id")`` y así se anota desde la auditoría (C-2). El dict
    trae además ``location_name`` (``LEFT JOIN`` a ``locations``): el nombre
    de la ubicación, o ``None`` si no la tiene —lo que la tabla del plan
    (Equipo paso 2) pinta como «ubicación» (M-17). Sin ubicación o con ella
    borrada (``ON DELETE SET NULL``) la clave siempre está: ``.get()`` sirve
    para ambos casos.

    También expone el contrato de claves de ``framing.calculate_fov``:
    ``telescope_focal_mm`` (**focal efectiva**, × factor si hay reductor;
    ver ``_fila``), ``camera_pixel_size_um``, ``camera_width_px`` y
    ``camera_height_px`` — ``None`` cuando falta la pieza. El filtro por
    categoría es a igualdad exacta: agrupar «todo el EDP» por prefijo es
    del paso 6, cuando la comparativa lo necesite.
    """
    conn = get_connection()
    sql = _SELECT + (" WHERE e.category = ?" if category else "") + " ORDER BY e.name"
    rows = conn.execute(sql, (category,) if category else ()).fetchall()
    return [_fila(row) for row in rows]


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


def count_setups_using(kind: str, entity_id: int) -> int:
    """Nº de equipos que referencian una pieza o ubicación (aviso de borrado).

    ``kind`` ∈ ``telescope`` | ``camera`` | ``mount`` | ``filter`` |
    ``location``. Cuenta **cualquier rol** (principal o guía): borrar la
    pieza deja esos equipos sin ella (``ON DELETE SET NULL``) o elimina su
    asignación de filtros — la confirmación del borrado debe avisar antes
    con este número (mismo espíritu que ``count_sessions``, M-20). ``kind``
    desconocido → ``ValueError``; id inexistente → 0.
    """
    consultas = {
        "telescope": (
            "SELECT COUNT(*) FROM equipment_setups"
            " WHERE telescope_id = ? OR guide_telescope_id = ?"
        ),
        "camera": (
            "SELECT COUNT(*) FROM equipment_setups"
            " WHERE camera_id = ? OR guide_camera_id = ?"
        ),
        "mount": "SELECT COUNT(*) FROM equipment_setups WHERE mount_id = ?",
        "filter": "SELECT COUNT(*) FROM setup_filters WHERE filter_id = ?",
        "location": "SELECT COUNT(*) FROM equipment_setups WHERE location_id = ?",
    }
    if kind not in consultas:
        raise ValueError(f"Conteo desconocido: {kind!r}.")
    params = (entity_id, entity_id) if kind in ("telescope", "camera") else (entity_id,)
    row = get_connection().execute(consultas[kind], params).fetchone()
    return int(row[0])


def _validar_filtros(conn, filter_ids: list[int]) -> None:
    """Comprueba todas las referencias antes de guardar equipo o adjuntos.

    Si un filtro ya no existe, fallar después de ``images.sync`` dejaría
    tanto la fila del equipo como sus copias de imagen confirmadas.
    """
    for filter_id in set(filter_ids):
        if conn.execute("SELECT 1 FROM filters WHERE id = ?", (filter_id,)).fetchone() is None:
            raise ValueError(f"El filtro {filter_id} no existe; equipo sin guardar.")


def _sync_filters(setup_id: int, filter_ids: list[int]) -> None:
    """Iguala ``setup_filters`` del setup con ``filter_ids`` (diff por conjunto).

    La lista es la verdad al guardar (mismo criterio D-5 que las imágenes):
    las que sobran se quitan, las que faltan se añaden y las que siguen
    quedan intactas.
    """
    conn = get_connection()
    actuales = {
        row[0]
        for row in conn.execute(
            "SELECT filter_id FROM setup_filters WHERE setup_id = ?", (setup_id,)
        )
    }
    nuevos = set(filter_ids)
    for quitar in actuales - nuevos:
        conn.execute(
            "DELETE FROM setup_filters WHERE setup_id = ? AND filter_id = ?",
            (setup_id, quitar),
        )
    for anadir in nuevos - actuales:
        conn.execute(
            "INSERT INTO setup_filters (setup_id, filter_id) VALUES (?, ?)",
            (setup_id, anadir),
        )
    conn.commit()
