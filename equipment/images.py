"""Imágenes adjuntas a una entidad de equipo (setups, componentes, ubicaciones).

SOLO visuales: el programa las muestra para que el usuario las compare por su
cuenta; nunca las analiza ni las compara automáticamente.

La API es polymórfica por ``entity_kind`` («setup», «telescope», «camera»,
«location») con un mapa cerrado de tablas: sin SQL dinámico fuera de él.
"""
import shutil
from pathlib import Path

from db.connection import DATA_DIR, get_connection

#: Destino de las copias (decisión D-1 de la auditoría): el programa vive
#: con sus propios datos en `data/` y la ruta persistida no depende de que
#: el original siga donde el usuario lo eligió. Los tests lo redirigen.
IMAGES_ROOT = DATA_DIR / "equipment_images"

#: entidad → (tabla, columna FK, kind por defecto al adjuntar).
_ENTIDADES: dict[str, tuple[str, str, str]] = {
    "setup": ("equipment_images", "setup_id", "otra"),
    "telescope": ("telescope_images", "telescope_id", "chart"),
    "camera": ("camera_images", "camera_id", "ganancia"),
    "location": ("location_images", "location_id", "mapa_lp"),
}


def _entidad(entity_kind: str) -> tuple[str, str, str]:
    """(tabla, fk, kind por defecto) de una entidad; ``ValueError`` si no existe.

    Es la única puerta al SQL de este módulo: un ``entity_kind`` desconocido
    nunca llega a construir una consulta.
    """
    try:
        return _ENTIDADES[entity_kind]
    except KeyError:
        raise ValueError(f"Entidad de imagen desconocida: {entity_kind!r}.") from None


def _copy_to_data(entity_kind: str, entity_id: int, path: str) -> str:
    """Copia ``path`` a ``IMAGES_ROOT/<entity_kind>/<entity_id>/``.

    Devuelve la ruta a guardar. Si el original ya está en el destino
    (re-adjuntar) no se copia; si el original falta o la copia falla, se
    devuelve la ruta tal cual — mejor una ruta frágil que no poder adjuntar
    la imagen.
    """
    origin = Path(path)
    target_dir = IMAGES_ROOT / entity_kind / str(entity_id)
    try:
        target = target_dir / origin.name
        if origin.resolve() != target.resolve():
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
        return str(target)
    except OSError:
        return path


def _borrar_si_propia(path: str) -> None:
    """Borra ``path`` solo si está bajo ``IMAGES_ROOT`` (copias del programa).

    Los originales del usuario y las rutas frágiles persistidas sin copiar
    (D-1) no se tocan: fuera de `data/` no es «nuestro» fichero.
    """
    try:
        candidata = Path(path)
        if candidata.is_relative_to(IMAGES_ROOT):
            candidata.unlink(missing_ok=True)
    except OSError:
        pass  # un fichero que no se puede borrar no debe romper el guardado


def attach(entity_kind: str, entity_id: int, path: str, kind: str | None = None) -> int:
    """Adjunta una imagen a una entidad y devuelve su id.

    El fichero se **copia** a `data/equipment_images/<entidad>/<id>/` (D-1):
    la imagen guardada sobrevive aunque el usuario mueva o borre el
    original. Si la copia no es posible, se persiste la ruta original.
    ``kind`` por defecto es el de la entidad ('otra', 'chart', 'ganancia',
    'mapa_lp').
    """
    tabla, fk, kind_defecto = _entidad(entity_kind)
    conn = get_connection()
    cur = conn.execute(
        f"INSERT INTO {tabla} ({fk}, path, kind) VALUES (?, ?, ?)",
        (entity_id, _copy_to_data(entity_kind, entity_id, path), kind or kind_defecto),
    )
    conn.commit()
    return cur.lastrowid


def list_images(entity_kind: str, entity_id: int) -> list[dict]:
    """Imágenes (``path``, ``kind``) de una entidad, en orden de adjunte."""
    tabla, fk, _ = _entidad(entity_kind)
    conn = get_connection()
    rows = conn.execute(
        f"SELECT path, kind FROM {tabla} WHERE {fk} = ? ORDER BY id", (entity_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def remove(entity_kind: str, entity_id: int, path: str) -> None:
    """Quita una imagen de una entidad: borra la fila y su copia propia.

    Solo se borran ficheros bajo ``IMAGES_ROOT``: los originales del usuario
    no se tocan (semántica D-1).
    """
    tabla, fk, _ = _entidad(entity_kind)
    conn = get_connection()
    conn.execute(
        f"DELETE FROM {tabla} WHERE {fk} = ? AND path = ?", (entity_id, path)
    )
    conn.commit()
    _borrar_si_propia(path)


def sync(entity_kind: str, entity_id: int, paths: list[str]) -> None:
    """Re-sincroniza las imágenes de una entidad con ``paths`` (contrato D-5).

    La lista es la verdad al guardar: primero ``remove`` de las que sobran y
    luego ``attach`` de las que faltan; las que siguen quedan intactas (con
    su ``kind``). Parte siempre de la lista que devuelva ``list_images()``:
    no mezcles origen y copia en la misma lista.
    """
    guardadas = [img["path"] for img in list_images(entity_kind, entity_id)]
    for sobra in guardadas:
        if sobra not in paths:
            remove(entity_kind, entity_id, sobra)
    for falta in paths:
        if falta not in guardadas:
            attach(entity_kind, entity_id, falta)


def purge(entity_kind: str, entity_id: int) -> None:
    """Borra los ficheros copiados de una entidad (las filas ya las lleva la FK).

    Se llama al borrar el padre (telescopio, cámara, ubicación, setup): la
    FK ``ON DELETE CASCADE`` se queda con las filas, pero de los ficheros de
    `data/` se encarga éste (D-1: no dejar huérfanos).
    """
    _entidad(entity_kind)  # valida la entidad aunque no se use la tabla
    shutil.rmtree(IMAGES_ROOT / entity_kind / str(entity_id), ignore_errors=True)
