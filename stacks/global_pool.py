"""Pool global de lights calibrados: SOLO REFERENCIAS, cero copias.

Tras calibrar cada sesión, sus lights calibrados se añaden al pool como rutas
hacia ``data/working/calibrados/<sesion>/``. El pool no duplica ningún fichero;
todas las etapas siguientes (registro, métricas, apilado) trabajan sobre estas
referencias.
"""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GlobalPool:
    """Referencias agrupadas a los lights calibrados de todas las sesiones."""

    root: Path
    entries: list[Path] = field(default_factory=list)  # rutas a ficheros calibrados

    def add_session(self, session_name: str, lights_dir: Path) -> int:
        """Añade los lights calibrados de una sesión como referencias (sin copiar).

        Devuelve el número de ficheros referenciados.
        """
        raise NotImplementedError

    def total_exposure_s(self, exposure_per_frame_s: float | None = None) -> float:
        """Tiempo de exposición total del pool (lo consume la pestaña Resumen)."""
        raise NotImplementedError
