"""Detección del ejecutable de SirIL.

Usa la ruta que el llamante haya guardado; solo sin elección busca en PATH.
Una elección inválida debe fallar explícitamente, no cambiar de instalación.
La lectura de ``settings`` vive fuera (en
la UI): este módulo no toca la BD, porque el hilo de trabajo de SirIL no
debe usar la conexión creada en el hilo de UI (SQLite lo prohibió y ya hay
regresión de eso en `test_siril_runner.py`).
"""
import subprocess
import sys
from pathlib import Path
from shutil import which

#: Clave de ``settings`` donde la UI guarda la ruta elegida por el usuario.
SETTINGS_KEY = "siril_path"


def cli_creationflags() -> int:
    """Evita consolas hijas en Windows, también desde pythonw; no afecta a la GUI de SirIL."""
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def find_siril(ruta_guardada: str | None = None) -> str | None:
    """Ruta del binario CLI de SirIL o ``None`` si no se encontró.

    Orden: 1) ``ruta_guardada``, 2) PATH solo sin elección (``""`` cuenta
    como no guardado). La ejecución/comprobación informa de rutas inválidas.
    """
    if ruta_guardada:
        return ruta_guardada
    return which("siril-cli") or which("siril") or which("Siril.exe")


def find_siril_gui(ruta_guardada: str | None = None) -> str | None:
    """Ruta gráfica de la instalación elegida o, sin configuración, del PATH.

    El Apilador abre el FITS final en la GUI de SirIL; aquí no se mira
    ``settings``: recibe la elección desde UI. No salta a otra instalación
    si falta la compañera gráfica del CLI configurado.
    """
    if ruta_guardada:
        selected = Path(ruta_guardada)
        if not selected.is_file():
            return None
        names = {"siril-cli.exe": "siril.exe", "siril-cli": "siril"}
        gui = selected.with_name(names.get(selected.name.lower(), selected.name))
        return str(gui) if gui.is_file() else None
    return which("siril") or which("Siril.exe")


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
            creationflags=cli_creationflags(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    # SirIL imprime la versión por stdout o por stderr según el build:
    # se mira stdout primero y se cae a stderr antes de rendirse.
    lines = (result.stdout or result.stderr or "").strip().splitlines()
    return lines[0].strip() if lines else None
