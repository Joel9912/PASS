"""CRUD de componentes globales: telescopios, cámaras, monturas y filtros.

Lecturas → dicts (contrato C-2/M-16: la UI lee dicts de fila); escrituras →
dataclasses validadas (``equipment.validaciones``). Los equipos los
referencian con rol principal o de guía: borrar un componente deja esos
setups sin referencia (``ON DELETE SET NULL``) — ``manager.count_setups_using``
es el aviso previo que la confirmación del borrado muestra.

Al borrar, las filas de imágenes las lleva la FK en cascada y los ficheros,
``images.purge`` (D-1: nada huérfano en `data/`).
"""
from db.connection import get_connection

from . import images
from .models import Camera, Filter, Mount, Telescope
from .validaciones import (
    validar_camara,
    validar_filtro,
    validar_montura,
    validar_telescopio,
)


def _listar(tabla: str) -> list[dict]:
    """Filas de ``tabla`` como dicts, ordenadas por nombre."""
    conn = get_connection()
    rows = conn.execute(f"SELECT * FROM {tabla} ORDER BY name").fetchall()
    return [dict(row) for row in rows]


def _get(tabla: str, pk: int) -> dict | None:
    """Fila ``pk`` de ``tabla`` como dict, o ``None`` si no existe."""
    conn = get_connection()
    row = conn.execute(f"SELECT * FROM {tabla} WHERE id = ?", (pk,)).fetchone()
    return dict(row) if row else None


# --- Telescopios -----------------------------------------------------------


def list_telescopes() -> list[dict]:
    """Todas las ópticas globales (dicts), ordenadas por nombre."""
    return _listar("telescopes")


def get_telescope(telescope_id: int) -> dict | None:
    """Una óptica por id (dict) o ``None`` si no existe."""
    return _get("telescopes", telescope_id)


def create_telescope(telescope: Telescope) -> int:
    """Guarda una óptica y devuelve su id (la deja en ``telescope.id``).

    Contrato D-5: re-sincroniza ``telescope.images`` — la lista es la verdad
    al guardar; el formulario solo la edita en memoria (cancelar no toca
    ficheros) y llama a éste al confirmar.
    """
    validar_telescopio(telescope)
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO telescopes (name, aperture_mm, focal_mm, optical_type,"
        " subtype, reducer, reducer_factor, price_eur, weight_kg, notes)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            telescope.name,
            telescope.aperture_mm,
            telescope.focal_mm,
            telescope.optical_type,
            telescope.subtype,
            int(telescope.reducer),
            telescope.reducer_factor,
            telescope.price_eur,
            telescope.weight_kg,
            telescope.notes,
        ),
    )
    conn.commit()
    telescope.id = cur.lastrowid
    images.sync("telescope", telescope.id, telescope.images)
    return telescope.id


def update_telescope(telescope: Telescope) -> None:
    """Actualiza una óptica existente (re-sincroniza ``.images``, contrato D-5)."""
    if telescope.id is None:
        raise ValueError("Telescopio: falta el id (crea antes de actualizar).")
    validar_telescopio(telescope)
    conn = get_connection()
    conn.execute(
        "UPDATE telescopes SET name = ?, aperture_mm = ?, focal_mm = ?,"
        " optical_type = ?, subtype = ?, reducer = ?, reducer_factor = ?,"
        " price_eur = ?, weight_kg = ?, notes = ? WHERE id = ?",
        (
            telescope.name,
            telescope.aperture_mm,
            telescope.focal_mm,
            telescope.optical_type,
            telescope.subtype,
            int(telescope.reducer),
            telescope.reducer_factor,
            telescope.price_eur,
            telescope.weight_kg,
            telescope.notes,
            telescope.id,
        ),
    )
    conn.commit()
    images.sync("telescope", telescope.id, telescope.images)


def delete_telescope(telescope_id: int) -> None:
    """Borra una óptica (los equipos quedan sin ella: ``SET NULL``).

    Las filas de ``telescope_images`` caen en cascada y los ficheros los
    purga ``images.purge``; el nº de equipos afectados lo da
    ``manager.count_setups_using("telescope", id)`` para la confirmación.
    """
    conn = get_connection()
    conn.execute("DELETE FROM telescopes WHERE id = ?", (telescope_id,))
    conn.commit()
    images.purge("telescope", telescope_id)


# --- Cámaras ---------------------------------------------------------------


def list_cameras() -> list[dict]:
    """Todas las cámaras globales (dicts), ordenadas por nombre."""
    return _listar("cameras")


def get_camera(camera_id: int) -> dict | None:
    """Una cámara por id (dict) o ``None`` si no existe."""
    return _get("cameras", camera_id)


def create_camera(camera: Camera) -> int:
    """Guarda una cámara y devuelve su id (la deja en ``camera.id``).

    Contrato D-5: re-sincroniza ``camera.images`` (gráficas de ganancia).
    """
    validar_camara(camera)
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO cameras (name, cooled, pixel_size_um, width_px, height_px,"
        " bit_depth, mono, ampglow, price_eur, weight_kg, notes)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            camera.name,
            int(camera.cooled),
            camera.pixel_size_um,
            camera.width_px,
            camera.height_px,
            camera.bit_depth,
            int(camera.mono),
            int(camera.ampglow),
            camera.price_eur,
            camera.weight_kg,
            camera.notes,
        ),
    )
    conn.commit()
    camera.id = cur.lastrowid
    images.sync("camera", camera.id, camera.images)
    return camera.id


def update_camera(camera: Camera) -> None:
    """Actualiza una cámara existente (re-sincroniza ``.images``, contrato D-5)."""
    if camera.id is None:
        raise ValueError("Cámara: falta el id (crea antes de actualizar).")
    validar_camara(camera)
    conn = get_connection()
    conn.execute(
        "UPDATE cameras SET name = ?, cooled = ?, pixel_size_um = ?, width_px = ?,"
        " height_px = ?, bit_depth = ?, mono = ?, ampglow = ?, price_eur = ?,"
        " weight_kg = ?, notes = ? WHERE id = ?",
        (
            camera.name,
            int(camera.cooled),
            camera.pixel_size_um,
            camera.width_px,
            camera.height_px,
            camera.bit_depth,
            int(camera.mono),
            int(camera.ampglow),
            camera.price_eur,
            camera.weight_kg,
            camera.notes,
            camera.id,
        ),
    )
    conn.commit()
    images.sync("camera", camera.id, camera.images)


def delete_camera(camera_id: int) -> None:
    """Borra una cámara (los equipos quedan sin ella: ``SET NULL``).

    Filas de ``camera_images`` en cascada y ficheros con ``images.purge``;
    el nº de equipos afectados, ``manager.count_setups_using("camera", id)``.
    """
    conn = get_connection()
    conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
    conn.commit()
    images.purge("camera", camera_id)


# --- Monturas --------------------------------------------------------------


def list_mounts() -> list[dict]:
    """Todas las monturas globales (dicts), ordenadas por nombre."""
    return _listar("mounts")


def get_mount(mount_id: int) -> dict | None:
    """Una montura por id (dict) o ``None`` si no existe."""
    return _get("mounts", mount_id)


def create_mount(mount: Mount) -> int:
    """Guarda una montura y devuelve su id (la deja en ``mount.id``)."""
    validar_montura(mount)
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO mounts (name, mount_type, payload_kg, price_eur, weight_kg,"
        " notes) VALUES (?, ?, ?, ?, ?, ?)",
        (
            mount.name,
            mount.mount_type,
            mount.payload_kg,
            mount.price_eur,
            mount.weight_kg,
            mount.notes,
        ),
    )
    conn.commit()
    mount.id = cur.lastrowid
    return mount.id


def update_mount(mount: Mount) -> None:
    """Actualiza una montura existente."""
    if mount.id is None:
        raise ValueError("Montura: falta el id (crea antes de actualizar).")
    validar_montura(mount)
    conn = get_connection()
    conn.execute(
        "UPDATE mounts SET name = ?, mount_type = ?, payload_kg = ?, price_eur = ?,"
        " weight_kg = ?, notes = ? WHERE id = ?",
        (
            mount.name,
            mount.mount_type,
            mount.payload_kg,
            mount.price_eur,
            mount.weight_kg,
            mount.notes,
            mount.id,
        ),
    )
    conn.commit()


def delete_mount(mount_id: int) -> None:
    """Borra una montura (los equipos quedan sin ella: ``SET NULL``).

    El nº de equipos afectados lo da
    ``manager.count_setups_using("mount", id)`` para la confirmación.
    """
    conn = get_connection()
    conn.execute("DELETE FROM mounts WHERE id = ?", (mount_id,))
    conn.commit()


# --- Filtros ---------------------------------------------------------------


def list_filters() -> list[dict]:
    """Todos los filtros globales (dicts), ordenados por nombre."""
    return _listar("filters")


def get_filter(filter_id: int) -> dict | None:
    """Un filtro por id (dict) o ``None`` si no existe."""
    return _get("filters", filter_id)


def create_filter(filt: Filter) -> int:
    """Guarda un filtro y devuelve su id (lo deja en ``filt.id``)."""
    validar_filtro(filt)
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO filters (name, filter_type, price_eur, notes)"
        " VALUES (?, ?, ?, ?)",
        (filt.name, filt.filter_type, filt.price_eur, filt.notes),
    )
    conn.commit()
    filt.id = cur.lastrowid
    return filt.id


def update_filter(filt: Filter) -> None:
    """Actualiza un filtro existente (sus asignaciones M2M no se tocan)."""
    if filt.id is None:
        raise ValueError("Filtro: falta el id (crea antes de actualizar).")
    validar_filtro(filt)
    conn = get_connection()
    conn.execute(
        "UPDATE filters SET name = ?, filter_type = ?, price_eur = ?, notes = ?"
        " WHERE id = ?",
        (filt.name, filt.filter_type, filt.price_eur, filt.notes, filt.id),
    )
    conn.commit()


def delete_filter(filter_id: int) -> None:
    """Borra un filtro (sus asignaciones ``setup_filters`` caen en cascada).

    El nº de equipos que lo llevan lo da
    ``manager.count_setups_using("filter", id)`` para la confirmación.
    """
    conn = get_connection()
    conn.execute("DELETE FROM filters WHERE id = ?", (filter_id,))
    conn.commit()
