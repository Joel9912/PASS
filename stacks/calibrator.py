"""Calibración automática de sesiones con SirIL.

Flujo: para cada sesión, calibra sus lights usando sus propios flats/darks/bias
(o los másters si la sesión los trae) y escribe la salida en la CARPETA DE
TRABAJO: ``working_folder/calibrados/<sesion>/``.

Los originales NUNCA se tocan: la calibración produce ficheros nuevos en la
carpeta de trabajo (salida controlada de SirIL, no una copia redundante).
"""
from pathlib import Path

from .session_parser import Session

#: Carpeta de trabajo relativa a la raíz de datos del programa.
WORKING_FOLDER = Path("data") / "working"
CALIBRATED_DIR = Path("calibrados")


def calibrated_dir_for(session: Session) -> Path:
    """Devuelve la subcarpeta de calibrados de esa sesión (y la crea si falta)."""
    target = WORKING_FOLDER / CALIBRATED_DIR / session.path.name
    target.mkdir(parents=True, exist_ok=True)
    return target


def calibrate_session(session: Session) -> Path:
    """Calibra los lights de una sesión con SirIL y devuelve la carpeta de salida.

    - Si la sesión trae másters, los usa directamente.
    - Si no, genera los másters con SirIL a partir de flats/darks/bias.
    - Nunca escribe dentro de ``session.path`` (origen de solo lectura).
    """
    raise NotImplementedError
