"""Fechas de captura y orden de revisión, sin inferir horas por nombres de archivo."""

import math
from datetime import UTC, datetime, timedelta, timezone

from astropy.io import fits

from .global_pool import LightRef


def capture_dates(frames: list[LightRef], sites: dict | None = None) -> dict[str, datetime | None]:
    """Lee solo cabeceras FITS en modo lectura; fechas ausentes/incompatibles quedan desconocidas."""
    return {str(ref.ruta): _capture_date(ref, sites) for ref in frames}


def _capture_date(ref: LightRef, sites: dict | None = None) -> datetime | None:
    """Interpreta DATE-OBS con UTC explícito o el predeterminado FITS, sin adivinar otros sistemas."""
    try:
        header = fits.getheader(ref.ruta)
        if sites is not None:
            sites[str(ref.ruta)] = _site(header)
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


def _site(header) -> tuple[float, float] | None:
    """Lee coordenadas geográficas numéricas; no confunde el objeto celeste con el observatorio."""
    for latitude, longitude in (("OBSGEO-B", "OBSGEO-L"), ("SITELAT", "SITELONG")):
        try:
            lat, lon = float(header[latitude]), float(header[longitude])
            if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
        except (KeyError, TypeError, ValueError):
            continue
    return None


def local_capture_time(moment: datetime, site: tuple | None, locations: list[dict],
                       default: dict | None) -> tuple[datetime, str]:
    """Convierte solo para presentar: sitio FITS coincidente o ubicación alternativa explícita.

    Usa el desfase guardado o la aproximación por longitud de PASS, etiquetada
    como tal, sin inventar reglas de verano. Un sitio FITS no reconocido
    conserva UTC para no atribuirle otro.
    """
    location = default if site is None else None
    source = "Ubicación alternativa seleccionada" if default is not None else "Sin ubicación alternativa"
    if site is not None:
        matches = [loc for loc in locations
                   if loc.get("latitude") is not None and loc.get("longitude") is not None
                   and abs(loc["latitude"] - site[0]) < 0.001
                   and abs(loc["longitude"] - site[1]) < 0.001]
        offsets = {(loc.get("timezone_id"), loc.get("utc_offset_hours")) for loc in matches}
        if len(offsets) == 1 and matches:
            location = matches[0]
            source = "Ubicación de captura FITS coincidente"
        else:
            source = "Posición FITS sin desfase inequívoco guardado"
    if location is not None:
        if location.get("timezone_id") is not None:
            from planners.timezones import local_moment, rules_label

            try:
                local = local_moment(moment, location.get("longitude") or 0, location["timezone_id"])
                return local, f"{source}: {location['name']}. {location['timezone_id']}; {rules_label()}"
            except ValueError as exc:
                return moment.astimezone(UTC), f"{source}: {exc}; se muestra UTC, no se aplica otro desfase."
        offset = location.get("utc_offset_hours")
        approximate = False
        longitude = location.get("longitude")
        if offset is None and isinstance(longitude, (int, float)) and math.isfinite(longitude) and -180 <= longitude <= 180:
            offset = round(longitude / 15)
            approximate = True
        if isinstance(offset, (int, float)) and math.isfinite(offset) and -12 <= offset <= 14:
            try:
                return moment.astimezone(timezone(timedelta(hours=offset))), (
                    f"{source}: {location['name']}. UTC{offset:+g}; "
                    + ("desfase aproximado por longitud (modo automático de la ubicación), " if approximate
                       else "desfase fijo configurado, ") +
                    "sin ajuste histórico automático de horario de verano.")
            except (OverflowError, ValueError):
                pass
        source += ": sin desfase válido configurado"
    return moment.astimezone(UTC), source + "; se muestra UTC."


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
