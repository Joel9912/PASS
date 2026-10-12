"""Apilado final con SirIL: sus opciones, su CLI, su hardware.

SirIL manda: aquí solo se traducen las opciones del usuario a los
argumentos reales de su ``stack`` (validados con ``help stack`` del 1.4.4)
y se orquesta el apilado:

- Secuencia entera (OSC, mono sin rueda de filtros o un solo filtro): se
  apila DIRECTAMENTE la secuencia registrada, donde viven los datos de
  registro que necesita la ponderación ``-weight=wfwhm/nbstars``.
- Mono con varios filtros: SirIL no puede apilar «solo FILTER=R» (sus
  filtros son por métricas, no por cabecera), así que cada canal se apila
  de una secuencia propia de enlaces a los frames registrados; si son
  exactamente R, G y B se compone con ``rgbcomp``.
- Salida: solo FITS en ``data/working/apilados/<nombre>/``.

SirIL usa todos los hilos de la máquina por sí solo. Drizzle NO vive aquí:
se pide al registrar (``registration.register_pool``). Con menos de unos
5 frames el rechazo no tiene muestras: SirIL aconseja ``med``.
"""
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .registration import Registro
from .siril_runner import (
    WORKING_FOLDER,
    SirilError,
    arg_ruta,
    ejecutar_script,
    enlazar,
    limpiar_trabajo,
    ultima_secuencia,
)

#: Subcarpeta de salida de los apilados (bajo ``WORKING_FOLDER``).
APILADOS_DIR = Path("apilados")

#: Integraciones que admite ``stack`` en SirIL 1.4.4.
INTEGRACIONES = ("sum", "min", "max", "med", "mean")

#: Rechazos de píxeles (nombres completos; SirIL acepta también iniciales).
RECHAZOS = (
    "none", "percentile", "sigma", "median", "winsorized",
    "linear", "generalized", "mad",
)

#: Ponderaciones de ``-weight=`` (solo con integración mean/rej).
PONDERACIONES = ("noise", "wfwhm", "nbstars", "nbstack")

#: Normalizaciones de ``-norm=`` (solo con med/mean); None = la de SirIL.
NORMS = ("add", "addscale", "mul", "mulscale")


@dataclass
class StackOptions:
    """Opciones de apilado expuestas al usuario (las de SirIL, tal cual).

    Por defecto manda SirIL: integración ``mean`` con rechazo ``winsorized``
    a 3σ y salida a 32 bits (la precisión acumulada lo merece). Otras
    opciones avanzadas (feather, maximize…) pasan por ``extra_args``.
    """

    integration: str = "mean"        # sum | min | max | med | mean
    rejection: str = "winsorized"    # none | percentile | sigma | ... (solo mean)
    sigma_low: float = 3.0
    sigma_high: float = 3.0
    weighting: str | None = None     # noise | wfwhm | nbstars | nbstack (solo mean)
    norm: str | None = None          # add | addscale | mul | mulscale | 'nonorm'
    fastnorm: bool = False
    bit32: bool = True
    rejmaps: bool = False
    merge_rejmaps: bool = True
    output_norm: bool = False
    rgb_equal: bool = False
    extra_args: list[str] = field(default_factory=list)

    def to_siril_args(self) -> list[str]:
        """Traduce las opciones a argumentos de ``stack`` (sin nombre ni -out=)."""
        self._validar()
        args = [self.integration]
        if self.integration == "mean":
            args.append(self.rejection)
            if self.rejection != "none":
                args.extend([str(self.sigma_low), str(self.sigma_high)])
            if self.rejmaps:
                args.append("-rejmap" if self.merge_rejmaps else "-rejmaps")
        if self.integration in ("med", "mean"):
            if self.norm == "nonorm":
                args.append("-nonorm")
            elif self.norm:
                args.append(f"-norm={self.norm}")
            if self.fastnorm:
                args.append("-fastnorm")
        if self.integration == "mean" and self.weighting:
            args.append(f"-weight={self.weighting}")
        if self.bit32:
            args.append("-32b")
        if self.output_norm:
            args.append("-output_norm")
        if self.rgb_equal:
            args.append("-rgb_equal")
        args.extend(self.extra_args)
        return args

    def _validar(self) -> None:
        """Rechaza combinaciones que SirIL no admite (mejor pronto que tarde)."""
        if self.integration not in INTEGRACIONES:
            raise ValueError(f"Integración {self.integration!r}: válidas {INTEGRACIONES}.")
        if self.rejection not in RECHAZOS:
            raise ValueError(f"Rechazo {self.rejection!r}: válidos {RECHAZOS}.")
        if self.weighting is not None and self.weighting not in PONDERACIONES:
            raise ValueError(f"Ponderación {self.weighting!r}: válidas {PONDERACIONES}.")
        if self.norm is not None and self.norm not in (*NORMS, "nonorm"):
            raise ValueError(
                f"Normalización {self.norm!r}: válidas add/addscale/mul/mulscale o nonorm."
            )
        if self.weighting is not None and self.integration != "mean":
            raise ValueError("-weight= solo aplica a integración mean (rechazo).")
        if (self.norm is not None or self.fastnorm) and self.integration not in ("med", "mean"):
            raise ValueError("-norm=/-fastnorm solo aplican a integración med o mean.")
        if self.rejmaps and (self.integration != "mean" or self.rejection == "none"):
            raise ValueError("Los mapas de rechazo exigen integración mean con rechazo.")
        if self.output_norm and self.integration not in ("med", "mean"):
            raise ValueError("-output_norm solo aplica a integración med o mean.")
        if self.rgb_equal and self.integration not in ("med", "mean"):
            raise ValueError("-rgb_equal solo aplica a integración med o mean.")


def apilar_pool(
    registro: Registro,
    nombre: str,
    *,
    aceptados: list[int] | None = None,
    opciones: StackOptions | None = None,
    progress_cb=None,
    log_cb=None,
) -> list[Path]:
    """Apila la secuencia registrada y devuelve las imágenes FITS de salida.

    - Un solo grupo (OSC, mono sin filtro, todo un mismo filtro) y sin
      descartes → se apila la secuencia completa, con nombre
      ``<nombre>.fit``.
    - Varias ``FILTER`` → una pila por grupo (``<filtro>.fit``) y, si son
      exactamente R/G/B, composición final ``<nombre>_rgb.fit``.
    - ``aceptados`` (índices 1-based que la auditoría dejó marcados) → se
      apilan solo esos; si recortan la secuencia se hace con una
      secuencia de enlaces propia (sin filas R: sin ponderación
      wfwhm/nbstars, se avisa).

    Todo acaba en ``working/apilados/<nombre>/`` (se limpia antes: nada
    viejo se mezcla con lo nuevo).
    """
    opciones = opciones or StackOptions()
    salida = WORKING_FOLDER / APILADOS_DIR / nombre
    limpiar_trabajo(salida, raiz=WORKING_FOLDER / APILADOS_DIR)

    grupos = _grupos_filtrados(registro, aceptados)
    if not grupos:
        raise SirilError("No queda ningún frame para apilar (todos descartados).")
    un_grupo = len(grupos) == 1
    # Un registro final puede haber descartado frames que la auditoría no
    # descartó: si falta algún r_*, mejor la ruta de secuencia propia, que
    # apila los que hay y avisa en vez de mandar SirIL un fichero que no existe.
    completos = not registro.transformadas or (
        len(list(registro.dir.glob("r_*.fit"))) == len(registro.frames)
    )
    if (
        un_grupo
        and sum(len(v) for v in grupos.values()) == len(registro.frames)
        and completos
    ):
        return [_apilar_secuencia(
            registro.dir, registro.seq_apilable, salida / f"{nombre}.fit",
            opciones, progress_cb, log_cb,
        )]

    apiladas = []
    if opciones.weighting in ("wfwhm", "nbstars") and log_cb:
        log_cb(
            "Ponderación wfwhm/nbstars pedida sobre secuencias de enlaces: los "
            "datos de registro (filas R) no viajan con ellas."
        )
    nombres = [_canal(filtro) for filtro in grupos]
    colision = len({nombre.casefold() for nombre in nombres}) != len(nombres)
    for numero, (filtro, indices) in enumerate(grupos.items(), start=1):
        canal = f"{numero:04d}_{_canal(filtro)}" if colision else _canal(filtro)
        carpeta = registro.dir / "secuencias" / canal
        limpiar_trabajo(carpeta, raiz=registro.dir)
        seq = _secuencia_de(registro, indices, carpeta, log_cb)
        destino = salida / (f"{nombre}.fit" if un_grupo else f"{canal}.fit")
        apiladas.append(_apilar_secuencia(
            carpeta, seq, destino, opciones, progress_cb, log_cb,
        ))
    if un_grupo:
        return apiladas
    compuesta = _componer_rgb(grupos, apiladas, salida, nombre, log_cb)
    return apiladas + ([compuesta] if compuesta else [])


def exportar_apilados(salidas: list[Path], carpeta: Path) -> list[Path]:
    """Copia solo los FITS finales a la carpeta madre sin sobrescribir nada.

    Comprueba todos los nombres antes de copiar; si falla una copia, quita
    únicamente los archivos creados en esta operación (working permanece).
    """
    if not carpeta.is_dir() or carpeta.is_symlink() or carpeta.is_junction():
        raise SirilError(f"Carpeta madre no disponible o enlazada: {carpeta}")
    destinos = [carpeta / salida.name for salida in salidas]
    if len(set(destinos)) != len(destinos) or any(p.exists() or p.is_symlink() for p in destinos):
        raise SirilError("Ya existe una salida con ese nombre en la carpeta madre; no se reemplazó.")
    creados = []
    try:
        for origen, destino in zip(salidas, destinos, strict=True):
            with origen.open("rb") as entrada, destino.open("xb") as salida:
                creados.append(destino)
                shutil.copyfileobj(entrada, salida)
    except OSError as exc:
        for destino in creados:
            destino.unlink(missing_ok=True)
        raise SirilError(f"No se pudo exportar el apilado a {carpeta}: {exc}") from exc
    return destinos


# ------------------------------------------------------------------ internas
def _grupos_por_filtro(registro: Registro) -> dict[str | None, list[int]]:
    """Índices de la secuencia agrupados por filtro (canal de apilado)."""
    grupos: dict[str | None, list[int]] = {}
    for indice, ref in enumerate(registro.frames, start=1):
        grupos.setdefault(ref.filtro, []).append(indice)
    return grupos


def _grupos_filtrados(
    registro: Registro, aceptados: list[int] | None
) -> dict[str | None, list[int]]:
    """Grupos por filtro con solo los índices aceptados (None = todos)."""
    grupos = _grupos_por_filtro(registro)
    if aceptados is None:
        return grupos
    conjunto = set(aceptados)
    limite = len(registro.frames)
    recortados = {
        filtro: [i for i in indices if i in conjunto and 1 <= i <= limite]
        for filtro, indices in grupos.items()
    }
    return {filtro: indices for filtro, indices in recortados.items() if indices}


def _canal(filtro: str | None) -> str:
    """Nombre de carpeta/fichero de un canal (filtros con signos raros)."""
    if not filtro:
        return "sin_filtro"
    return re.sub(r"\W+", "_", filtro).strip("_") or "sin_filtro"


def _secuencia_de(registro: Registro, indices: list[int], carpeta: Path, log_cb) -> str:
    """Secuencia de enlaces a los frames registrados (``r_*``) de un grupo.

    Se re-enlazan los nombres ya registrados en una carpeta propia y SirIL
    los renumera con ``link``. Los frames que SirIL descartó al registrar
    no tienen ``r_*``: se apilan los que hay (con aviso) y, si no queda
    ninguno, se falla claro. Al crear un .seq nuevo se pierden los datos
    de registro (las filas R), así que la ponderación wfwhm/nbstars solo
    vale para apilar la secuencia entera sin recortar.
    """
    fuentes = [registro.dir / f"{registro.seq_apilable}{i:05d}.fit" for i in indices]
    existentes = [fuente for fuente in fuentes if fuente.exists()]
    if not existentes:
        raise SirilError(
            f"Ningún frame del grupo tiene salida registrada ({registro.seq_apilable}*): "
            "SirIL los descartó todos al registrar."
        )
    if len(existentes) < len(fuentes) and log_cb:
        log_cb(
            f"{len(fuentes) - len(existentes)} de {len(fuentes)} frames del grupo "
            "no tienen transformadas registradas (descartados por SirIL): se "
            f"apilan solo los {len(existentes)} existentes."
        )
    for fuente in existentes:
        enlazar(fuente, carpeta / fuente.name)
    res = ejecutar_script(["link canal"], cwd=carpeta, log_cb=log_cb)
    if not res.ok:
        raise SirilError(f"No se pudo crear la secuencia del canal: {res.motivo}")
    return ultima_secuencia(carpeta, "canal")


def _apilar_secuencia(
    dir_seq: Path, seq: str, salida: Path, opciones: StackOptions,
    progress_cb, log_cb,
) -> Path:
    """Una corrida de ``stack`` con ``-out=`` y doble confirmación de salida."""
    arg_out = arg_ruta(f"-out={salida}")
    comando = f"stack {seq} {' '.join(opciones.to_siril_args())} {arg_out}"
    res = ejecutar_script([comando], cwd=dir_seq, progress_cb=progress_cb,
                          log_cb=log_cb, esperados=[salida])
    if not res.ok or not salida.exists():
        raise SirilError(f"El apilado falló: {res.motivo}")
    if opciones.rejmaps and log_cb:
        log_cb(
            "Los mapas de rechazo de SirIL, si se generaron, permanecen "
            f"junto a la secuencia en {dir_seq}; no forman parte del FITS final."
        )
    return salida


def _componer_rgb(
    grupos: dict[str | None, list[int]], apiladas: list[Path],
    salida: Path, nombre: str, log_cb,
) -> Path | None:
    """``rgbcomp`` si los 3 canales son inequívocamente R, G y B.

    Para otros tripletes (Ha/OIII/SII, HOO…) el orden de composición es
    decisión del usuario: se dejan las pilas por canal y se avisa. Con 2 o
    4+ filtros tampoco se compone (SirIL compone RGB o LRGB, nada más).
    """
    if len(apiladas) != 3:
        if log_cb:
            log_cb(
                f"{len(apiladas)} canales apilados por separado: SirIL solo "
                "compone RGB/LRGB, sin composición automática."
            )
        return None
    canales = {
        (filtro or "").upper(): path
        for filtro, path in zip(grupos, apiladas, strict=True)
    }
    if "" in canales or not set(canales) <= {"R", "G", "B"}:
        if log_cb:
            log_cb(
                "Tres canales que no son R/G/B: el orden de la composición "
                f"lo decide el usuario; las pilas están en {salida}."
            )
        return None
    compuesta = salida / f"{nombre}_rgb.fit"
    args = " ".join(arg_ruta(p.name) for p in (canales["R"], canales["G"], canales["B"]))
    res = ejecutar_script(
        [f"rgbcomp {args} {arg_ruta(f'-out={compuesta.name}')}"],
        cwd=salida, log_cb=log_cb, esperados=[compuesta],
    )
    if not res.ok or not compuesta.exists():
        raise SirilError(f"La composición RGB falló: {res.motivo}")
    return compuesta
