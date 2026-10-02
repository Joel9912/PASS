"""Detección del ejecutable de SirIL.

Busca SirIL en el PATH; si no lo encuentra, usa la ruta guardada por el
usuario en ``settings`` (clave ``siril_path``).
"""
from shutil import which

from db.connection import get_connection

SETTINGS_KEY = "siril_path"


def find_siril() -> str | None:
    """Devuelve la ruta de SirIL o ``None`` si no se encontró.

    Orden: 1) PATH del sistema, 2) ruta guardada por el usuario en ``settings``.
    """
    path = which("siril") or which("siril-cli") or which("Siril.exe")
    if path:
        return path

    row = get_connection().execute(
        "SELECT value FROM settings WHERE key = ?", (SETTINGS_KEY,)
    ).fetchone()
    if row and row["value"]:
        return row["value"]
    return None


def save_user_path(path: str) -> None:
    """Guarda la ruta que eligió el usuario (fallback cuando no está en el PATH)."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SETTINGS_KEY, path),
    )
    conn.commit()
