"""Imágenes adjuntas a un setup (diagramas de spot, fotos, etc.).

SOLO visuales: el programa las muestra para que el usuario las compare por su
cuenta; nunca las analiza ni las compara automáticamente.
"""
import shutil
from pathlib import Path

from db.connection import DATA_DIR, get_connection

#: Destino de las copias (decisión D-1 de la auditoría): el programa vive
#: con sus propios datos en `data/` y la ruta persistida no depende de que
#: el original siga donde el usuario lo eligió. Los tests lo redirigen.
IMAGES_ROOT = DATA_DIR / "equipment_images"


def _copy_to_data(setup_id: int, path: str) -> str:
    """Copia ``path`` a ``IMAGES_ROOT/<setup_id>/`` y devuelve la ruta a guardar.

    Si el original ya está en el destino (re-adjuntar) no se copia; si el
    original falta o la copia falla, se devuelve la ruta tal cual — mejor
    una ruta frágil que no poder adjuntar la imagen.
    """
    origin = Path(path)
    target_dir = IMAGES_ROOT / str(setup_id)
    try:
        target = target_dir / origin.name
        if origin.resolve() != target.resolve():
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
        return str(target)
    except OSError:
        return path


def attach(setup_id: int, path: str, kind: str = "otra") -> int:
    """Adjunta una imagen a un setup (`kind`: 'spot' | 'otra').

    El fichero se **copia** a `data/equipment_images/<setup_id>/` (D-1):
    la imagen guardada sobrevive aunque el usuario mueva o borre el
    original. Si la copia no es posible, se persiste la ruta original.
    """
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO equipment_images (setup_id, path, kind) VALUES (?, ?, ?)",
        (setup_id, _copy_to_data(setup_id, path), kind),
    )
    conn.commit()
    return cur.lastrowid


def list_images(setup_id: int) -> list[dict]:
    """Lista las imágenes adjuntas de un setup."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT path, kind FROM equipment_images WHERE setup_id = ?", (setup_id,)
    ).fetchall()
    return [dict(row) for row in rows]
