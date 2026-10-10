"""Detección del ejecutable de SirIL.

Busca SirIL en el PATH; si no está, se devuelve la ruta que el llamante
haya guardado para el usuario. La lectura de ``settings`` vive fuera (en
la UI): este módulo no toca la BD, porque el hilo de trabajo de SirIL no
debe usar la conexión creada en el hilo de UI (SQLite lo prohibió y ya hay
regresión de eso en `test_siril_runner.py`).
"""
import subprocess
from shutil import which

#: Clave de ``settings`` donde la UI guarda la ruta elegida por el usuario.
SETTINGS_KEY = "siril_path"


def find_siril(ruta_guardada: str | None = None) -> str | None:
    """Ruta del binario CLI de SirIL o ``None`` si no se encontró.

    Orden: 1) PATH del sistema, 2) ``ruta_guardada`` (lo que el llamante
    leyó de settings; ``""`` cuenta como no guardado).
    """
    # Prioriza la variante CLI: el ejecutable gráfico no siempre admite
    # guiones por stdin. Conserva la preferencia del PATH sobre lo guardado.
    path = which("siril-cli") or which("siril") or which("Siril.exe")
    if path:
        return path
    return ruta_guardada or None


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
