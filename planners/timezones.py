"""Hora civil offline: zona IANA explícita o desfase fijo; nunca deduce fronteras ni usa el huso del ordenador."""

import math
import re
from datetime import UTC, datetime, timedelta, timezone
from functools import lru_cache
from importlib.resources import files
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import tzdata

# Se conserva el argumento histórico utc_offset_hours: número=fijo,
# texto=zona IANA, None=aproximación heredada explícita por longitud.
Clock = float | str | None


@lru_cache(maxsize=128)
def zone(key: str) -> ZoneInfo:
    """Carga solo la versión distribuida de tzdata, sin fallback al sistema ni modificación global de ZoneInfo."""
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_+/-]+", key) or any(part in ("", ".", "..") for part in key.split("/")):
        raise ValueError("Zona horaria IANA inválida.")
    try:
        with files("tzdata.zoneinfo").joinpath(*key.split("/")).open("rb") as stream:
            return ZoneInfo.from_file(stream, key=key)
    except (OSError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError(f"Zona horaria no disponible: {key}.") from exc


@lru_cache(maxsize=1)
def zone_names() -> tuple[str, ...]:
    """Enumera zonas de la misma distribución utilizada en los cálculos, sin red ni detección geográfica."""
    return tuple(sorted(files("tzdata").joinpath("zones").read_text(encoding="utf-8").splitlines()))


def utc_moment(value: datetime | str) -> datetime:
    """ISO sin offset es UTC; para presentación civil, :60 ocupa el último microsegundo representable de ese minuto.

    datetime no representa segundos intercalares. Este adaptador solo convierte
    el reloj; las mallas y duraciones físicas mantienen Time de Astropy.
    """
    if isinstance(value, str) and value[17:19] == "60":
        value = datetime.fromisoformat(value[:17] + "59" + value[19:]).replace(microsecond=999999)
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def local_moment(value: datetime | str, longitude: float, clock: Clock) -> datetime:
    """Convierte un instante real con las reglas de ese instante o el desfase fijo elegido."""
    moment = utc_moment(value)
    if isinstance(clock, str):
        return moment.astimezone(zone(clock))
    offset = round(longitude / 15) if clock is None else clock
    if type(offset) not in (int, float) or not math.isfinite(offset) or not -12 <= offset <= 14:
        raise ValueError("Desfase horario inválido: debe estar entre -12 y 14 horas.")
    return moment.astimezone(timezone(timedelta(hours=offset)))


def local_hours(value: datetime | str, longitude: float, clock: Clock) -> float:
    """Hora decimal de reloj de un instante; no sirve para restar duraciones durante un cambio horario."""
    moment = local_moment(value, longitude, clock)
    return moment.hour + moment.minute / 60 + moment.second / 3600 + moment.microsecond / 3_600_000_000


def local_boundary(value: datetime, key: str) -> datetime:
    """Resuelve un límite civil inequívoco; rechaza horas inexistentes o repetidas en vez de elegir fold silenciosamente."""
    candidates = set()
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone(key), fold=fold).astimezone(UTC)
        if candidate.astimezone(zone(key)).replace(tzinfo=None) == value:
            candidates.add(candidate)
    if len(candidates) != 1:
        raise ValueError(f"Límite local ambiguo o inexistente en {key}: {value.isoformat()}.")
    return candidates.pop()


def clock_label(value: datetime | str, longitude: float, clock: Clock) -> str:
    """Etiqueta inequívoca con desfase para zonas; conserva HH:MM para el modo fijo."""
    moment = local_moment(value, longitude, clock)
    text = moment.strftime("%H:%M")
    if isinstance(clock, str):
        offset = moment.strftime("%z")
        text += f" UTC{offset[:3]}:{offset[3:5]}"
    return text


def rules_label() -> str:
    """Expone la revisión de las reglas, sin prometer certeza legislativa futura ni precisión histórica uniforme."""
    return f"tzdata {tzdata.__version__}; reglas conocidas, sujetas a cambios legales y cobertura histórica."
