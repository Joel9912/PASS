"""Tránsito, luna y noche astronómica con astropy.

Cálculos para la subpestaña "Ventana" del Planificador: cuándo culmina un
objeto, a qué altura llega, qué tan separado está la luna esa noche y
cuántas horas de noche astronómica (sol a -18°) hay.

Todo trabaja en UTC internamente; la UI convierte a hora local si quiere.
Las posiciones usan la efeméride interna de astropy (sin red) y IERS en modo
offline con precisión suficiente para planificar (~1', no para guiar un
telescopio).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from astropy import units as u
from astropy.coordinates import (
    AltAz,
    EarthLocation,
    SkyCoord,
    angular_separation,
    get_body,
    get_sun,
)
from astropy.time import Time
from astropy.utils import iers

from .analytical_transit import local_utc_offset

# Offline: nada de descargar tablas IERS al importar (arranque rápido y sin red).
iers.conf.auto_download = False
try:
    iers.conf.iers_degraded_accuracy = "ignore"
except AttributeError:  # astropy puede renombrar la opción entre versiones
    pass

#: Pasos de muestreo de la noche (minutos) y duración de la ventana analizada.
SAMPLE_MIN = 10
NIGHT_HOURS = 16.0

#: Umbral de noche astronómica (sol bajo -18°).
ASTRO_TWILIGHT_DEG = -18.0

#: Altitud del sol en el ocaso/amanecer (radio solar + refracción, ~-0°50').
SUN_HORIZON_DEG = -0.833

#: Período sinódico de la luna (días entre lunas nuevas iguales).
SYNODIC_PERIOD_DAYS = 29.530588

#: Luna nueva de referencia: 2000-01-06 18:14 UTC (JD 2451550.26).
#: Con él se calcula la edad lunar con solo el período sinódico.
_NEW_MOON_JD = 2451550.26


@dataclass
class NightInfo:
    """Resumen de una noche astronómica para un lugar y fecha."""

    astronomical_dusk: str | None  # inicio de noche astronómica (ISO, UTC)
    astronomical_dawn: str | None  # final de noche astronómica (ISO, UTC)
    astronomical_hours: float      # horas con sol a -18° o menos
    moon_phase: float              # 0 = nueva, 1 = llena (fracción iluminada)
    moon_illumination: float       # misma escala que moon_phase
    sunset: str | None = None      # puesta de sol (ISO, UTC)
    sunrise: str | None = None     # salida de sol (ISO, UTC)
    moon_age_days: float = 0.0     # días desde luna nueva (0..29.53)
    waxing: bool = True            # True = creciente (lit en el este/N.)


@dataclass
class TransitInfo:
    """Tránsito de un objeto durante la noche de ``date_iso``."""

    transit_time: str | None       # ISO (UTC) de la culminación
    altitude_deg: float            # altura máxima sobre el horizonte
    separation_moon_deg: float     # mínima separación objeto-luna (noche entera)
    hour_altitudes: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class NightCurve:
    """Malla completa de la noche para dibujar y clasificar la captura.

    Un punto por cada ``SAMPLE_MIN`` minutos de la ventana nocturna:

    - ``times_iso``: instante (ISO, UTC) de cada punto.
    - ``hours_local``: hora local decimal (0-24) de cada punto, para el eje X.
    - ``altitudes``: altitud del objeto (grados).
    - ``moon_separations``: separación angular objeto-Luna (grados).
    - ``astro_night``: True si el sol está bajo -18° (noche astronómica).
    - ``moon_illumination``: fracción iluminada (0-1) en el centro de la noche.
    - ``transit_index``: índice del punto de culminación.
    """

    times_iso: list[str]
    hours_local: list[float]
    altitudes: list[float]
    moon_separations: list[float]
    astro_night: list[bool]
    moon_illumination: float
    transit_index: int

    @property
    def transit_time(self) -> str:
        """ISO (UTC) de la culminación."""
        return self.times_iso[self.transit_index]

    @property
    def transit_altitude(self) -> float:
        """Altura máxima sobre el horizonte (grados)."""
        return self.altitudes[self.transit_index]

    @property
    def min_separation_moon_deg(self) -> float:
        """Menor separación objeto-Luna mientras el objeto está visible."""
        visible = [sep for alt, sep in zip(self.altitudes, self.moon_separations)
                   if alt > 0.0]
        return min(visible) if visible else 0.0


def _night_times(date_iso: str, longitude_deg: float, sample_min: int = SAMPLE_MIN) -> Time:
    """Malla temporal de la noche de ``date_iso`` para ``longitude_deg``.

    Ventana de 16 h centrada en la noche local: de ~17:00 a ~09:00 hora
    local, muestreada cada ``sample_min`` minutos. Trabaja en UTC; el
    desfase local se compensa con la longitud (este = positivo).
    """
    lon_hours = longitude_deg / 15.0
    start = Time(date_iso) + (16.0 - lon_hours) * u.hour
    steps = int(NIGHT_HOURS * 60 / sample_min) + 1
    return start + np.arange(steps) * sample_min * u.min


def _location(latitude_deg: float, longitude_deg: float) -> EarthLocation:
    return EarthLocation(lat=latitude_deg * u.deg, lon=longitude_deg * u.deg)


def _night_times(
    date_iso: str,
    longitude_deg: float,
    sample_min: int = SAMPLE_MIN,
    utc_offset_hours: float | None = None,
) -> Time:
    """Malla temporal de la noche de ``date_iso`` para ``longitude_deg``.

    Ventana de 16 h centrada en la noche local: de ~16:00 a ~08:00 hora
    local, muestreada cada ``sample_min`` minutos. Trabaja en UTC; el
    desfase local lo pone :func:`local_utc_offset`.
    """
    start = Time(date_iso) + (
        16.0 - local_utc_offset(longitude_deg, utc_offset_hours)
    ) * u.hour
    steps = int(NIGHT_HOURS * 60 / sample_min) + 1
    return start + np.arange(steps) * sample_min * u.min


def _local_hours(
    times: Time, longitude_deg: float, utc_offset_hours: float | None = None
) -> list[float]:
    """Hora local decimal de cada ``Time`` (UTC fraccionario + desfase)."""
    offset = local_utc_offset(longitude_deg, utc_offset_hours)
    return [float((t.mjd % 1.0) * 24.0 + offset) % 24.0 for t in times]


def night_curve(
    ra_hours: float,
    dec_deg: float,
    latitude: float,
    longitude: float,
    date_iso: str,
    utc_offset_hours: float | None = None,
) -> NightCurve:
    """Curva completa de la noche: altitud, luna y noche astronómica.

    Es la fuente única de datos para la gráfica de tránsito y para las
    ventanas de captura (Ideal/Posible): cada instante trae altitud,
    separación lunar y si estamos dentro de la noche astronómica.

    ``utc_offset_hours`` (desfase de la ubicación, ver
    :func:`local_utc_offset`) solo afecta al eje horario; la física se
    calcula en UTC.
    """
    location = _location(latitude, longitude)
    times = _night_times(date_iso, longitude, utc_offset_hours=utc_offset_hours)
    frame = AltAz(obstime=times, location=location)

    target = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_deg * u.deg, frame="icrs")
    target_altaz = target.transform_to(frame)
    moon_altaz = get_body("moon", times, location).transform_to(frame)
    sun_alt = get_sun(times).transform_to(frame).alt

    alts = target_altaz.alt.to_value(u.deg)
    separations = angular_separation(
        target_altaz.az, target_altaz.alt, moon_altaz.az, moon_altaz.alt
    ).to_value(u.deg)

    # Fase lunar en el centro de la ventana (noche local aproximada)
    mid = times[len(times) // 2]
    moon = get_body("moon", mid, location)
    sun = get_sun(mid)
    elongation = angular_separation(moon.ra, moon.dec, sun.ra, sun.dec)
    illumination = float((1.0 - np.cos(elongation.to_value(u.rad))) / 2.0)

    return NightCurve(
        times_iso=[str(t.iso) for t in times],
        hours_local=_local_hours(times, longitude, utc_offset_hours),
        altitudes=[float(a) for a in alts],
        moon_separations=[float(s) for s in separations],
        astro_night=[bool(alt < ASTRO_TWILIGHT_DEG) for alt in sun_alt.to_value(u.deg)],
        moon_illumination=round(illumination, 3),
        transit_index=int(np.argmax(alts)),
    )


def _crossing_iso(
    times: Time,
    values: np.ndarray,
    threshold: float,
    descending: bool,
    sample_min: int,
) -> str | None:
    """Instante (ISO) en que ``values`` cruza ``threshold``, interpolando.

    ``descending=True`` busca el primer cruce hacia abajo (puesta de sol);
    ``descending=False`` el primero hacia arriba (salida de sol). Devuelve
    ``None`` si la curva no cruza (p. ej. sol de medianoche o día polar).
    """
    for index in range(len(values) - 1):
        start, end = float(values[index]), float(values[index + 1])
        hit = start >= threshold > end if descending else start < threshold <= end
        if hit:
            fraction = (threshold - start) / (end - start)
            return str(times[index] + fraction * sample_min * u.min)
    return None


def night_info(
    latitude: float,
    longitude: float,
    date_iso: str,
    sample_min: int = SAMPLE_MIN,
) -> NightInfo:
    """Horas de noche astronómica y fase lunar para ``date_iso``.

    - ``astronomical_dusk``/``dawn``: primer y último instante con el sol
      bajo -18° (None si esa noche no llega a la noche astronómica).
    - ``moon_phase``: fracción iluminada de la luna en el centro de la
      noche (0 = nueva, 1 = llena).

    ``sample_min`` sube la malla (p. ej. 30) para baratar el cálculo cuando
    solo hace falta una estimación, como al recorrer 30 noches en el plan
    de captura. Por defecto usa la malla fina de :data:`SAMPLE_MIN`.
    """
    location = _location(latitude, longitude)
    times = _night_times(date_iso, longitude, sample_min)
    frame = AltAz(obstime=times, location=location)

    sun_alt = get_sun(times).transform_to(frame).alt
    astronomical = sun_alt < ASTRO_TWILIGHT_DEG * u.deg

    dusk = dawn = None
    hours = 0.0
    if np.any(astronomical):
        indices = np.flatnonzero(astronomical)
        # Una sola ventana continua esperada; si hay huecos, cubrimos el rango.
        dusk = times[indices[0]].iso
        dawn = times[indices[-1]].iso
        hours = (indices[-1] - indices[0] + 1) * sample_min / 60.0

    # Fase lunar en el centro de la ventana (noche local aproximada)
    mid = times[len(times) // 2]
    moon = get_body("moon", mid, location)
    sun = get_sun(mid)
    elongation = angular_separation(moon.ra, moon.dec, sun.ra, sun.dec)
    illumination = float((1.0 - np.cos(elongation.to_value(u.rad))) / 2.0)

    sun_alt_values = sun_alt.to_value(u.deg)
    sunset = _crossing_iso(
        times, sun_alt_values, SUN_HORIZON_DEG, descending=True, sample_min=sample_min
    )
    sunrise = _crossing_iso(
        times, sun_alt_values, SUN_HORIZON_DEG, descending=False, sample_min=sample_min
    )

    # Edad de la luna respecto a una luna nueva de referencia (sin astropy:
    # basta el período sinódico para saber si crece o mengua).
    moon_age = (mid.jd - _NEW_MOON_JD) % SYNODIC_PERIOD_DAYS

    return NightInfo(
        astronomical_dusk=dusk,
        astronomical_dawn=dawn,
        astronomical_hours=round(float(hours), 2),
        moon_phase=round(illumination, 3),
        moon_illumination=round(illumination, 3),
        sunset=sunset,
        sunrise=sunrise,
        moon_age_days=round(float(moon_age), 2),
        waxing=bool(moon_age < SYNODIC_PERIOD_DAYS / 2.0),
    )


def transit_info(
    ra_hours: float,
    dec_deg: float,
    latitude: float,
    longitude: float,
    date_iso: str,
) -> TransitInfo:
    """Tránsito de un objeto y su mínima separación con la luna esa noche.

    - ``transit_time``/``altitude_deg``: culminación dentro de la ventana.
    - ``separation_moon_deg``: menor separación angular objeto-luna mientras
      el objeto está sobre el horizonte (peor caso de la noche).
    - ``hour_altitudes``: (ISO, altitud) cada SAMPLE_MIN min para graficar.

    Internamente delega en :func:`night_curve`, que es la misma malla que
    alimenta la gráfica y las ventanas de captura.
    """
    curve = night_curve(ra_hours, dec_deg, latitude, longitude, date_iso)
    return TransitInfo(
        transit_time=curve.transit_time,
        altitude_deg=round(curve.transit_altitude, 1),
        separation_moon_deg=round(curve.min_separation_moon_deg, 1),
        hour_altitudes=[
            (iso, alt) for iso, alt in zip(curve.times_iso, curve.altitudes, strict=True)
        ],
    )
