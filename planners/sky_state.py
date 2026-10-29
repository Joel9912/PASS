"""Contexto solar/lunar puntual para ilustraciones: modelo local e IERS, sin descargas ni posiciones decorativas falsas."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, angular_separation, get_body
from astropy.time import Time

from .astronomy_status import AstronomyStatus, astronomy_status
from .ephemeris import EphemerisModel, model_scope
from .planning_dates import planning_date
from .timezones import local_boundary, local_moment, utc_moment
from .transit import (
    _NEW_MOON_JD,
    ASTRO_TWILIGHT_DEG,
    SUN_HORIZON_DEG,
    SYNODIC_PERIOD_DAYS,
)


@dataclass(frozen=True)
class SkyState:
    """Datos reales del instante; el renderer decide una composición explícitamente decorativa."""

    moment: datetime
    sun_altitude: float
    rising: bool
    illumination: float
    waxing: bool
    accuracy: AstronomyStatus

    @property
    def title(self) -> str:
        """Usa horizontes ya existentes, sin fijar horarios locales arbitrarios."""
        if self.sun_altitude <= ASTRO_TWILIGHT_DEG:
            return "Bajo las estrellas"
        if self.sun_altitude < SUN_HORIZON_DEG:
            return "La luz del amanecer" if self.rising else "El cielo al anochecer"
        return "Luz de la mañana" if self.rising else "La calma de la tarde"


def observe_sky(latitude: float, longitude: float, moment: datetime, *, model: EphemerisModel | None = None) -> SkyState:
    """Calcula contexto puntual en un worker con selección local propia, sin compartir SQLite.

    Iluminación por elongación, igual que el modelo aproximado vigente de tránsito.
    Las dos muestras solares solo indican el sentido de cambio, no simulan trayectorias en el dibujo.
    """
    if not all(math.isfinite(value) for value in (latitude, longitude)) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Coordenadas de ubicación inválidas.")
    now = utc_moment(moment)
    planning_date(now.date().isoformat())
    times = Time([now, now + timedelta(minutes=1)])
    location = EarthLocation(lat=latitude*u.deg, lon=longitude*u.deg)
    with model_scope(model):
        sun = get_body("sun", times, location)
        altitudes = sun.transform_to(AltAz(obstime=times, location=location)).alt.to_value(u.deg)
        moon = get_body("moon", times[0], location)
        elongation = angular_separation(moon.ra, moon.dec, sun[0].ra, sun[0].dec).to_value(u.rad)
        illumination = float((1 - np.cos(elongation)) / 2)
        waxing = bool((float(times[0].jd) - _NEW_MOON_JD) % SYNODIC_PERIOD_DAYS < SYNODIC_PERIOD_DAYS / 2)
        accuracy = astronomy_status(times)
    if not all(math.isfinite(value) for value in (*altitudes, illumination)):
        raise ValueError("El contexto astronómico contiene datos no finitos.")
    return SkyState(now, float(altitudes[0]), bool(altitudes[1] > altitudes[0]), illumination, waxing, accuracy)


def location_clock(location: dict):
    """Transporta zona IANA/fijo/heredado de una ubicación sin inferirla por el sistema operativo."""
    return location.get("timezone_id") or location.get("utc_offset_hours")


def civil_to_utc(value: datetime, location: dict) -> datetime:
    """Interpreta el control civil en su ubicación y rechaza horas DST ambiguas/inexistentes."""
    clock = location_clock(location)
    naive = value.replace(tzinfo=None)
    if isinstance(clock, str):
        return local_boundary(naive, clock)
    tz = local_moment(datetime.now(UTC), location["longitude"], clock).tzinfo
    return naive.replace(tzinfo=tz).astimezone(UTC)
