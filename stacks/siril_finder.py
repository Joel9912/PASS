"""Detección del ejecutable de SirIL.

Busca SirIL en el PATH; si no lo encuentra, usa la ruta guardada por el
usuario en ``settings`` (clave ``siril_path``).
"""
import subprocess
from shutil import which

from db.settings import get_setting, set_setting

SETTINGS_KEY = "siril_path"


def find_siril() -> str | None:
    """Devuelve la ruta de SirIL o ``None`` si no se encontró.

    Orden: 1) PATH del sistema, 2) ruta guardada por el usuario en ``settings``.
    """
    # Nombres del binario según instalación: 'siril'/'siril-cli' (PATH de Unix)
    # y 'Siril.exe' (instalador de Windows); se prueban los tres por ese orden.
    path = which("siril") or which("siril-cli") or which("Siril.exe")
    if path:
        return path
    return get_setting(SETTINGS_KEY) or None   # "" cuenta como no guardado


def save_user_path(path: str) -> None:
    """Guarda la ruta que eligió el usuario (fallback cuando no está en el PATH)."""
    set_setting(SETTINGS_KEY, path)


def siril_version(path: str) -> str | None:
    """Primera línea de ``siril --version``; ``None`` si no se pudo ejecutar.

    Permite mostrar «detectado y operativo» con la versión real en la
    pantalla de Configuración; nunca lanza (SirIL puede fallar o tardar).
    """
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    # SirIL imprime la versión por stdout o por stderr según el build:
    # se mira stdout primero y se cae a stderr antes de rendirse.
    lines = (result.stdout or result.stderr or "").strip().splitlines()
    return lines[0].strip() if lines else None
