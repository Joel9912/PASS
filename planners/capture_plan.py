"""Plan de captura: mejores fechas y horas para un target concreto.

Una vez elegido el objeto y el lugar, el programa recorre las próximas
``date_range_days`` noches y puntúa cada una según:

- **Altura** del objeto en su culminación (cuanto más alto, mejor).
- **Separación lunar** frente al umbral de la fase de esa noche
  (:func:`planners.moon_distance.min_moon_distance`).
- **Horas de noche astronómica** disponibles.

Los pesos van en :class:`CaptureWeights` para que el usuario los ajuste
(regla del proyecto: nunca imponer métricas como verdad). Para las mejores
fechas se calcula además la malla completa (:func:`planners.transit.night_curve`)
y se clasifican las ventanas Ideal/Posible con sus rangos horarios.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.time import Time

from planners.analytical_transit import (
    hours_above_altitude,
    local_utc_offset,
    max_altitude,
    transit_utc_hours,
)
from planners.moon_distance import (
    WINDOW_IDEAL,
    WINDOW_POSSIBLE,
    capture_window_summary,
    capture_windows,
    min_moon_distance,
)
from planners.transit import night_curve, night_info

#: Nº de noches que se evalúan por defecto y nº de fechas devueltas.
DEFAULT_RANGE_DAYS = 30
DEFAULT_TOP_N = 10


@dataclass
class CaptureWeights:
    """Pesos de la puntuación de una fecha (el usuario puede cambiarlos).

    Propuesta inicial: altura 50, luna 30, noche 20. Como en el ranking,
    son un punto de partida, nunca una verdad impuesta.
    """

    altitude: float = 50.0
    moon_separation: float = 30.0
    night: float = 20.0

    @property
    def total(self) -> float:
        return abs(self.altitude) + abs(self.moon_separation) + abs(self.night)


def _moon_separation_at_transit(
    ra_hours: float,
    dec_deg: float,
    latitude: float,
    longitude: float,
    date_iso: str,
    transit_utc_hours: float,
) -> float:
    """Separación angular objeto-Luna en el instante de la culminación.

    Se calcula en el mismo marco AltAz que la curva nocturna, para que el
    valor coincida con el que muestra la gráfica (y sin mezclar frames).
    """
    location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg)
    instant = Time(date_iso) + transit_utc_hours * u.hour
    frame = AltAz(obstime=instant, location=location)
    moon_altaz = get_body("moon", instant, location).transform_to(frame)
    target_altaz = SkyCoord(
        ra=ra_hours * u.hourangle, dec=dec_deg * u.deg, frame="icrs"
    ).transform_to(frame)
    return float(target_altaz.separation(moon_altaz).to_value(u.deg))


def _moon_score(separation_deg: float, min_dist_deg: float) -> float:
    """1.0 si supera el umbral, 0.5 si está en el margen de 10°, si no 0."""
    if separation_deg >= min_dist_deg:
        return 1.0
    if separation_deg >= min_dist_deg - 10.0:
        return 0.5
    return 0.0


def _score_date(
    altitude_deg: float,
    separation_deg: float,
    min_dist_deg: float,
    night_hours: float,
    max_night_hours: float,
    weights: CaptureWeights,
) -> float:
    """Puntuación 0-100 de una fecha (ver doc del módulo para los factores)."""
    altitude_norm = min(max(altitude_deg / 90.0, 0.0), 1.0)
    moon_norm = _moon_score(separation_deg, min_dist_deg)
    night_norm = min(max(night_hours / max_night_hours, 0.0), 1.0) if max_night_hours else 0.0

    parts = (
        (weights.altitude, altitude_norm),
        (weights.moon_separation, moon_norm),
        (weights.night, night_norm),
    )
    total_weight = sum(w for w, _ in parts) or 1.0
    return 100.0 * sum(w * s for w, s in parts) / total_weight


def best_dates(
    target_ra_hours: float,
    target_dec_deg: float,
    latitude: float,
    longitude: float,
    start_date: str | None = None,
    date_range_days: int = DEFAULT_RANGE_DAYS,
    top_n: int = DEFAULT_TOP_N,
    weights: CaptureWeights | None = None,
    utc_offset_hours: float | None = None,
) -> list[dict]:
    """Mejores noches para captar ``target_ra_hours``/``target_dec_deg``.

    Para cada noche del rango calcula: culminación (analítica), separación
    lunar en la culminación, umbral de fase y horas de noche astronómica.
    Descarta las noches sin noche astronómica o en las que el objeto no
    cruza el horizonte. Ordena por puntuación y, para las ``top_n``
    mejores, añade las ventanas de captura (Ideal/Posible) con sus rangos.

    Devuelve una lista de dicts con: ``date``, ``transit_local``,
    ``max_altitude_deg``, ``moon_illumination`` (%), ``moon_separation_deg``,
    ``min_moon_distance_deg``, ``astronomical_hours``, ``hours_above_30``,
    ``score`` y ``windows``.

    ``utc_offset_hours`` (desfase de la ubicación, ver
    ``analytical_transit.local_utc_offset``) solo afecta a las horas que se
    muestran: ``transit_local`` y los rangos de ``windows``.
    """
    weights = weights or CaptureWeights()
    first = date.fromisoformat(start_date) if start_date else date.today()

    max_alt = max_altitude(latitude, target_dec_deg)
    if max_alt <= 0.0:
        return []  # el objeto no llega a salir nunca en este lugar

    candidates: list[dict] = []
    for offset in range(max(1, int(date_range_days))):
        day = (first + timedelta(days=offset)).isoformat()
        # Malla gruesa: al recorrer muchas noches solo hace falta estimar
        # las horas de noche; la malla fina se usa en las mejores fechas.
        night = night_info(latitude, longitude, day, sample_min=30)
        if night.astronomical_hours <= 0.0:
            continue  # sin noche astronómica no hay captura

        separation = _moon_separation_at_transit(
            target_ra_hours, target_dec_deg, latitude, longitude, day,
            transit_utc_hours(target_ra_hours, day, longitude),
        )
        illumination_pct = night.moon_illumination * 100.0
        min_dist = min_moon_distance(illumination_pct)

        candidates.append({
            "date": day,
            "transit_utc_hours": transit_utc_hours(target_ra_hours, day, longitude),
            "max_altitude_deg": round(max_alt, 1),
            "moon_illumination": round(illumination_pct, 1),
            "moon_separation_deg": round(separation, 1),
            "min_moon_distance_deg": round(min_dist, 1),
            "astronomical_hours": night.astronomical_hours,
            "hours_above_30": hours_above_altitude(latitude, target_dec_deg, 30.0),
            "_illumination_pct": illumination_pct,
            "_min_dist": min_dist,
        })

    if not candidates:
        return []

    max_night = max(item["astronomical_hours"] for item in candidates)
    for item in candidates:
        item["score"] = round(
            _score_date(
                item["max_altitude_deg"],
                item["moon_separation_deg"],
                item["_min_dist"],
                item["astronomical_hours"],
                max_night,
                weights,
            ),
            1,
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    top = candidates[: max(1, int(top_n))]

    # Para las mejores fechas: malla completa → ventanas Ideal/Posible
    for item in top:
        curve = night_curve(
            target_ra_hours, target_dec_deg, latitude, longitude, item["date"],
            utc_offset_hours,
        )
        windows = capture_windows(
            curve.altitudes,
            curve.moon_separations,
            curve.astro_night,
            item["_illumination_pct"],
        )
        item["windows"] = capture_window_summary(windows, curve.hours_local)
        item["transit_local"] = _format_hours(
            local_utc_offset(longitude, utc_offset_hours) + item["transit_utc_hours"]
        )
        item.pop("_illumination_pct", None)
        item.pop("_min_dist", None)

    return top


def _format_hours(hour_decimal: float) -> str:
    """18.6 → '18:36' (módulo 24)."""
    hour_decimal = hour_decimal % 24.0
    hours = int(hour_decimal)
    minutes = int(round((hour_decimal - hours) * 60.0))
    if minutes == 60:
        hours = (hours + 1) % 24
        minutes = 0
    return f"{hours:02d}:{minutes:02d}"


def window_hours(windows: dict, kind: str) -> float:
    """Horas acumuladas de una ventana (``ideal``/``possible``) en el resumen."""
    return float(windows.get(kind, {}).get("hours", 0.0))


__all__ = [
    "CaptureWeights",
    "WINDOW_IDEAL",
    "WINDOW_POSSIBLE",
    "best_dates",
    "window_hours",
]
