"""Fechas de captura y orden de revisión, sin inferir horas por nombres de archivo."""

from datetime import UTC, datetime

from astropy.io import fits

from .global_pool import LightRef


def capture_dates(frames: list[LightRef]) -> dict[str, datetime | None]:
    """Lee solo cabeceras FITS en modo lectura; fechas ausentes/incompatibles quedan desconocidas."""
    return {str(ref.ruta): _capture_date(ref) for ref in frames}


def _capture_date(ref: LightRef) -> datetime | None:
    """Interpreta DATE-OBS con UTC explícito o el predeterminado FITS, sin adivinar otros sistemas."""
    try:
        header = fits.getheader(ref.ruta)
        system = header.get("TIMESYS", "UTC")
        value = header.get("DATE-OBS")
        if not isinstance(system, str) or system.strip().upper() != "UTC":
            return None
        if not isinstance(value, str):
            return None
        value = value.strip()
        if not any(separator in value for separator in ("T", " ")):
            return None
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.astimezone(UTC)
    except (OSError, ValueError, OverflowError):
        return None


def chronological_indices(frames: list[LightRef], dates: dict[str, datetime | None]) -> list[int]:
    """Agrupa sesiones por identidad/primera captura y ordena tomas por hora, con desconocidas al final.

    Los empates y grupos sin fechas conservan orden de registro; una sesión
    sin fecha conocida va después de las sesiones fechadas.
    """
    first = {}
    starts = {}
    for index, ref in enumerate(frames, 1):
        first.setdefault(ref.sesion, index)
        moment = dates.get(str(ref.ruta))
        if moment is not None:
            starts[ref.sesion] = min(starts.get(ref.sesion, moment), moment)
    last = datetime.max.replace(tzinfo=UTC)

    def key(index: int) -> tuple:
        """Mantiene contiguos los grupos y no convierte una fecha desconocida en la hora cero."""
        ref = frames[index - 1]
        start, moment = starts.get(ref.sesion), dates.get(str(ref.ruta))
        return (start is None, start or last, first[ref.sesion], moment is None, moment or last, index)

    return sorted(range(1, len(frames) + 1), key=key)
