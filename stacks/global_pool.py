"""Pool global de lights calibrados: SOLO REFERENCIAS, cero copias.

Tras calibrar cada sesión, sus lights calibrados se añaden al pool como rutas
hacia ``data/working/calibrados/<sesion>/``. El pool no duplica ningún fichero;
todas las etapas siguientes (registro, métricas, apilado) trabajan sobre estas
referencias. La pestaña Resumen consume también el tiempo total acumulado.

Invariantes:

- Solo se referencia lo que vive bajo la carpeta de trabajo de calibrados:
  el pool jamás apunta a una sesión original (así no se tocan por error).
- Re-añadir una sesión la sustituye: recalibrar no duplica entradas.
"""
from dataclasses import dataclass, field
from pathlib import Path

from .calibrator import CALIBRATED_DIR, list_calibrated
from .session_parser import exposure_de, filtro_de
from .siril_runner import WORKING_FOLDER


@dataclass
class LightRef:
    """Referencia a un light calibrado, con lo mínimo para las etapas siguientes."""

    ruta: Path                   # pp_light_*.fit dentro de la carpeta de trabajo
    sesion: str                  # nombre de la sesión de origen
    filtro: str | None           # cabecera FILTER (None: sin filtro, típico en OSC)
    exposicion_s: float | None   # EXPOSURE/EXPTIME de la cabecera


@dataclass
class GlobalPool:
    """Referencias agrupadas a los lights calibrados de todas las sesiones."""

    root: Path = WORKING_FOLDER / CALIBRATED_DIR  # donde vive todo lo referenciable
    entries: list[LightRef] = field(default_factory=list)

    def add_session(self, session_name: str, lights_dir: Path) -> int:
        """Añade los lights calibrados de una sesión como referencias (sin copiar).

        Devuelve el número de ficheros referenciados (0 si la carpeta está
        vacía o no existe). Re-añadir la misma sesión la sustituye.
        """
        if not lights_dir.resolve().is_relative_to(self.root.resolve()):
            raise ValueError(
                f"{lights_dir} está fuera de {self.root}: el pool solo "
                "referencia la carpeta de trabajo (nunca los originales)."
            )
        self.entries = [e for e in self.entries if e.sesion != session_name]
        referencias = [
            LightRef(
                ruta=fichero,
                sesion=session_name,
                filtro=filtro_de(fichero),
                exposicion_s=exposure_de(fichero),
            )
            for fichero in sorted(lights_dir.glob("pp_*.fit*"))
            if fichero.is_file()
        ]
        self.entries.extend(referencias)
        return len(referencias)

    def total_exposure_s(self, exposure_per_frame_s: float | None = None) -> float:
        """Tiempo de exposición total del pool (lo consume la pestaña Resumen).

        Con ``exposure_per_frame_s`` se multiplica el nº de frames (tiempo
        planificado); sin él se suman los EXPOSURE de las cabeceras (los
        frames sin cabecera no aportan tiempo).
        """
        if exposure_per_frame_s is not None:
            return len(self.entries) * exposure_per_frame_s
        return sum(ref.exposicion_s or 0.0 for ref in self.entries)

    def por_filtro(self) -> dict[str | None, list[LightRef]]:
        """Agrupa las referencias por filtro (lo consume el apilado por canal).

        Sesiones mono+filtros: una pila por clave y después ``rgbcomp``;
        en OSC todo cae en un grupo (None si el FITS no trae FILTER).
        """
        grupos: dict[str | None, list[LightRef]] = {}
        for ref in self.entries:
            grupos.setdefault(ref.filtro, []).append(ref)
        return grupos


def pool_desde_calibradas(
    calibradas: list[dict] | None = None, *, root: Path | None = None
) -> GlobalPool:
    """Reconstruye el pool desde la tabla ``calibrated_sessions`` (sin recalibrar).

    Las sesiones cuya carpeta calibrada ya no existe se ignoran (dato
    obsoleto en la BD, no un error: el usuario pudo limpiar la carpeta).
    Con ``calibradas=None`` se leen las filas guardadas; ``root`` por defecto
    es la carpeta de calibrados de trabajo.
    """
    pool = GlobalPool(root=root) if root else GlobalPool()
    for fila in calibradas if calibradas is not None else list_calibrated():
        calibrada = Path(fila["calibrated_dir"])
        if calibrada.is_dir():
            pool.add_session(calibrada.name, calibrada / "light")
    return pool
