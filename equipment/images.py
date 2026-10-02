"""Imágenes adjuntas a un setup (diagramas de spot, fotos, etc.).

SOLO visuales: el programa las muestra para que el usuario las compare por su
cuenta; nunca las analiza ni las compara automáticamente.
"""
from db.connection import get_connection


def attach(setup_id: int, path: str, kind: str = "otra") -> int:
    """Adjunta una imagen a un setup (`kind`: 'spot' | 'otra')."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO equipment_images (setup_id, path, kind) VALUES (?, ?, ?)",
        (setup_id, path, kind),
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
