"""Detección del ejecutable de SirIL.

Busca SirIL en el PATH; si no lo encuentra, usa la ruta guardada por el
usuario en ``settings`` (clave ``siril_path``).
"""
from shutil import which

from db.settings import get_setting, set_setting

SETTINGS_KEY = "siril_path"


def find_siril() -> str | None:
    """Devuelve la ruta de SirIL o ``None`` si no se encontró.

    Orden: 1) PATH del sistema, 2) ruta guardada por el usuario en ``settings``.
    """
    path = which("siril") or which("siril-cli") or which("Siril.exe")
    if path:
        return path
    return get_setting(SETTINGS_KEY)


def save_user_path(path: str) -> None:
    """Guarda la ruta que eligió el usuario (fallback cuando no está en el PATH)."""
    set_setting(SETTINGS_KEY, path)
