"""Parser de sesiones: detecta qué contiene cada sesión de captura.

Para cada carpeta de sesión (p. ej. `2026-10-01_andromeda/`) identifica:
- subcarpetas de frames: ``lights``, ``flats``, ``darks``, ``bias``, ``dark_flats``
- carpeta de másters: ``masters/`` (master flat, master bias, master dark, ...)
Devuelve la estructura para que el calibrador sepa con qué calibrar cada sesión.
"""
from dataclasses import dataclass, field
from pathlib import Path

#: Subcarpetas de frames que reconoce el programa.
FRAME_KINDS = ("lights", "flats", "darks", "bias", "dark_flats")


@dataclass
class Session:
    """Estructura detectada de una sesión de captura."""

    path: Path
    frames: dict[str, list[Path]] = field(default_factory=dict)  # tipo -> ficheros
    masters: dict[str, Path] = field(default_factory=dict)       # tipo -> fichero maestro

    @property
    def n_lights(self) -> int:
        """Nº de frames de luz detectados (0 si la sesión no tiene ``lights/``)."""
        return len(self.frames.get("lights", []))


def parse_session(session_dir: Path) -> Session:
    """Detecta frames y másters de una sesión sin modificar nada (solo lectura)."""
    raise NotImplementedError


def parse_sessions(root_dir: Path) -> list[Session]:
    """Detecta todas las sesiones dentro de un directorio raíz."""
    raise NotImplementedError
