"""Pool global de lights calibrados: SOLO REFERENCIAS, cero copias.

Tras calibrar cada sesión, sus lights calibrados se añaden al pool como rutas
hacia ``data/working/calibrados/<sesion>-<hash>/``. El pool no duplica ningún
fichero; todas las etapas siguientes (registro, métricas, apilado) trabajan
sobre estas referencias. La pestaña Resumen consume también el tiempo total
acumulado.

Invariantes:

- Solo se referencia lo que vive bajo la carpeta de trabajo de calibrados:
  el pool jamás apunta a una sesión original (así no se tocan por error).
- La sesión se identifica por su **ruta de origen**: dos homónimas de raíces
  distintas no se funden ni se sustituyen la una a la otra.
- Re-añadir una sesión la sustituye: recalibrar no duplica entradas.
"""
from dataclasses import dataclass, field
from pathlib import Path

from .calibrator import CALIBRATED_DIR, list_calibrated, output_matches_source
from .session_parser import exposure_de, filtro_de
from .siril_runner import WORKING_FOLDER


@dataclass
class LightRef:
    """Referencia a un light calibrado, con lo mínimo para las etapas siguientes."""

    ruta: Path                   # pp_light_*.fit dentro de la carpeta de trabajo
    sesion: str                  # ruta de origen de su sesión (identidad única)
    filtro: str | None           # cabecera FILTER (None: sin filtro, típico en OSC)
    exposicion_s: float | None   # EXPOSURE/EXPTIME de la cabecera


def nombre_sesion(ref: LightRef) -> str:
    """Carpeta de la sesión: lo único usable en ficheros y en la tabla.

    ``ref.sesion`` guarda la ruta completa para no fundir dos sesiones
    homónimas de raíces distintas; esa ruta jamás entra en un nombre de
    fichero (colisionaría con separadores y `:` de Windows).
    """
    return Path(ref.sesion).name


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


def pool_desde_calibradas(
    calibradas: list[dict] | None = None, *, root: Path | None = None
) -> GlobalPool:
    """Reconstruye el pool desde la tabla ``calibrated_sessions`` (sin recalibrar).

    Las sesiones cuya carpeta calibrada ya no existe se ignoran (dato
    obsoleto en la BD, no un error: el usuario pudo limpiar la carpeta); lo
    mismo hace con una salida que no encaja con su origen o que dos filas
    reclaman a la vez (legado ambiguo: no se atribuye a nadie). Con
    ``calibradas=None`` se leen las filas guardadas; ``root`` por defecto es
    la carpeta de calibrados de trabajo.
    """
    pool = GlobalPool(root=root) if root else GlobalPool()
    filas = calibradas if calibradas is not None else list_calibrated()
    repeticiones: dict[Path, int] = {}
    for fila in filas:
        salida = Path(fila["calibrated_dir"]).resolve()
        repeticiones[salida] = repeticiones.get(salida, 0) + 1
    for fila in filas:
        calibrada = Path(fila["calibrated_dir"])
        if (
            calibrada.is_dir()
            and repeticiones[calibrada.resolve()] == 1
            and output_matches_source(
                Path(fila["session_dir"]), calibrada, root=pool.root
            )
        ):
            pool.add_session(
                str(Path(fila["session_dir"]).resolve()), calibrada / "light"
            )
    return pool
