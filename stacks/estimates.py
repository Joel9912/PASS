"""Estimaciones informativas de SirIL: cabeceras readonly y tiempos medidos, nunca reservas ni garantías."""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from astropy.io import fits

from .global_pool import LightRef
from .stacker import StackOptions


@dataclass(frozen=True)
class FrameGeometry:
    """Dimensiones observadas de una referencia; CFA produce tres canales al registrar para apilar."""

    path: str
    width: int
    height: int
    channels: int
    cfa: bool
    filter: str | None


@dataclass(frozen=True)
class ProcessingEstimate:
    """Volúmenes condicionales a conservar dimensiones; las áreas finales las decide el registro de SirIL."""

    selected: int
    unknown: int
    working_bytes: int
    export_bytes: int
    work_pixels: int
    signature: tuple
    seconds: float | None = None


@dataclass(frozen=True)
class TimingSample:
    """Una corrida completa comparable; no se extrapola entre algoritmos o argumentos distintos."""

    signature: tuple
    work_pixels: int
    seconds: float


def read_geometry(frames: Sequence[LightRef], checkpoint: Callable[[], None] | None = None) -> dict[str, FrameGeometry]:
    """Lee solo la cabecera de cada light; no infiere resolución/color a partir de otra sesión o toma."""
    result = {}
    for frame in frames:
        if checkpoint:
            checkpoint()
        try:
            header = fits.getheader(frame.ruta)
            width, height = header.get("NAXIS1"), header.get("NAXIS2")
            axes = header.get("NAXIS")
            if (type(width) is not int or type(height) is not int or min(width, height) <= 0
                    or axes not in (2, 3) or (axes == 3 and header.get("NAXIS3") != 3)):
                continue
            cfa = axes == 2 and str(header.get("BAYERPAT", "")).strip().upper() in {
                "RGGB", "BGGR", "GRBG", "GBRG",
            }
            key = str(frame.ruta.absolute())
            result[key] = FrameGeometry(key, width, height, 3 if axes == 3 or cfa else 1, cfa, frame.filtro)
        except (OSError, ValueError, TypeError):
            continue
    return result


def estimate_processing(
    frames: Sequence[LightRef], geometry: dict[str, FrameGeometry], *,
    drizzle: bool = False, scale: float = 1.0, framing: str = "min",
    kernel: str = "square", pixfrac: float = 1.0, flat: bool = False,
    options: StackOptions | None = None, sample: TimingSample | None = None,
) -> ProcessingEstimate:
    """Estima archivos nuevos y extrapola una medida comparable, sin ejecutar SirIL ni alterar decisiones.

    No cuenta como copia los enlaces a calibrados. Registros/debayer se modelan
    a 32 bits; incluye másters, mapas de rechazo y su exportación. El encuadre
    real, temporales internos, compresión y caché de SirIL pueden cambiar el
    volumen. No es una comprobación de espacio libre ni un máximo de memoria.
    """
    if type(scale) not in (int, float) or not math.isfinite(scale) or not 0 < scale <= 20:
        raise ValueError("Escala de estimación inválida.")
    options = options or StackOptions()
    args = tuple(options.to_siril_args())
    factor = float(scale) if drizzle else 1.0
    selected = [geometry.get(str(frame.ruta.absolute())) for frame in frames]
    known = [item for item in selected if item is not None]
    unknown = len(frames) - len(known)
    signature = (drizzle, framing, kernel if drizzle else None, pixfrac if drizzle else None,
                 flat if drizzle else False, args, tuple(sorted({(g.channels, g.cfa) for g in known})))
    groups = {}
    working = work = 0
    for item in known:
        width, height = math.ceil(item.width * factor), math.ceil(item.height * factor)
        pixels = width * height * item.channels
        source_pixels = item.width * item.height * item.channels
        working += pixels * 4
        work += pixels + source_pixels
        if item.cfa and not drizzle:
            working += source_pixels * 4
        groups.setdefault(item.filter, []).append((width, height, item.channels))
    master_bytes = 0
    bytes_per_sample = 4 if options.bit32 else 2
    for items in groups.values():
        pixels = max(i[0] for i in items) * max(i[1] for i in items) * max(i[2] for i in items)
        master_bytes += pixels * bytes_per_sample
        work += pixels * len(items)
        if options.rejmaps:
            working += pixels * 4 * (1 if options.merge_rejmaps else 2)
    # Solo la composición inequívoca R/G/B que también realiza stacker.py.
    if len(groups) == 3 and {str(key).upper() for key in groups} == {"R", "G", "B"}:
        width = max(item[0] for items in groups.values() for item in items)
        height = max(item[1] for items in groups.values() for item in items)
        master_bytes += width * height * 3 * 4
        work += width * height * 3
    working += master_bytes
    seconds = None
    if (not unknown and work and sample is not None and sample.signature == signature
            and type(sample.work_pixels) is int and sample.work_pixels > 0
            and type(sample.seconds) in (int, float) and math.isfinite(sample.seconds) and sample.seconds > 0):
        seconds = sample.seconds * work / sample.work_pixels
    return ProcessingEstimate(len(frames), unknown, working, master_bytes, work, signature, seconds)


def format_estimate(estimate: ProcessingEstimate) -> str:
    """Resumen legible y explícitamente aproximado, también cuando no hay datos o tomas utilizables."""
    if not estimate.selected:
        return "0 tomas seleccionadas · no se ejecutará el apilado."
    if estimate.unknown:
        return (f"{estimate.selected} tomas · estimación incompleta: faltan dimensiones de "
                f"{estimate.unknown}; espacio y tiempo totales desconocidos.")

    def size(value):
        """Unidades binarias para que una previsión de disco no parezca bytes decimales exactos."""
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if value < 1024 or unit == "TiB":
                return f"{value:.1f} {unit}"
            value /= 1024

    duration = (f"≈ {estimate.seconds / 60:.1f} min según corrida comparable"
                if estimate.seconds is not None else "desconocido hasta medir una corrida comparable")
    return (f"{estimate.selected} tomas · trabajo adicional ≈ {size(estimate.working_bytes)}"
            f" + exportación ≈ {size(estimate.export_bytes)} · tiempo {duration}.")
