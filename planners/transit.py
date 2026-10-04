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
from threading import Lock

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
#: 1 minuto: las fronteras de las ventanas caen a minuto exacto (21:22, no
#: 21:20) y las duraciones salen como son (3h 32min, no 3h 30min). Con
#: ``SAMPLE_MIN = 10`` la cuantización se veía en la UI, porque los rangos
#: de ``capture_window_summary`` son muestras de esta malla. Cuesta unos
#: 4× en cómputo (~0,5 s por curva), holgado para recalcular al cambiar
#: de objeto o de fecha.
SAMPLE_MIN = 1
NIGHT_HOURS = 16.0

#: Umbral de noche astronómica (sol bajo -18°).
ASTRO_TWILIGHT_DEG = -18.0

#: Paso (minutos) para la Luna y el sol: se mueven despacio, así que se
#: calculan cada N muestras y se interpolan a la malla de 1 min (ver
#: :func:`_moon_sun_series`). Medido con 961 muestras: 1 min → 622 ms,
#: 5 min + interp → 139 ms, con error máximo de 0,009° en la altitud
#: lunar y 0,006° en la separación, y los bordes de la noche
#: astronómica **idénticos**. Los umbrales se manejan en grados, así
#: que el error no llega a notarse.
MOON_SUN_SAMPLE_MIN = 5

#: (lat, lon, fecha, desfase) → (az de la Luna, alt de la Luna, alt del
#: sol, iluminación). Solo en memoria: la Luna y el sol **no dependen del
#: objeto**, así que al cambiar de objetivo se reutilizan. Acotada a las
#: últimas entradas; el candado protege si algún día se calcula en
#: segundo plano desde la UI.
_MOON_SUN_CACHE: dict[tuple, tuple] = {}
_MOON_SUN_CACHE_MAX = 8
_CACHE_LOCK = Lock()

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
    - ``moon_altitudes``: altitud de la Luna (grados; para dibujar su
      curva y ver salida/ocaso y altura máxima).
    - ``moon_separations``: separación angular objeto-Luna (grados).
    - ``astro_night``: True si el sol está bajo -18° (noche astronómica).
    - ``moon_illumination``: fracción iluminada (0-1) en el centro de la noche.
    - ``transit_index``: índice del punto de culminación.
    """

    times_iso: list[str]
    hours_local: list[float]
    altitudes: list[float]
    moon_altitudes: list[float]
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


def _location(latitude_deg: float, longitude_deg: float) -> EarthLocation:
    """Grados → ``EarthLocation`` de astropy, el punto de partida de todo AltAz."""
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
    """Hora local decimal de cada ``Time`` (UTC fraccionario + desfase).

    Vectorizado: leer ``t.mjd`` uno a uno dispara el mecanismo de
    atributos de ``Time`` ~1000 veces (medido: 0,12 s de los 0,5 s del
    perfil), mientras que ``times.mjd`` devuelve el array entero de una
    vez. El resultado es bit a bit el mismo.
    """
    offset = local_utc_offset(longitude_deg, utc_offset_hours)
    mjd = np.asarray(times.mjd)
    return [float(value) for value in ((mjd % 1.0) * 24.0 + offset) % 24.0]


def _target_arrays(times: Time, location: EarthLocation, target: SkyCoord):
    """(az, alt) del objeto en grados para ``times``."""
    frame = AltAz(obstime=times, location=location)
    altaz = target.transform_to(frame)
    return altaz.az.to_value(u.deg), altaz.alt.to_value(u.deg)


def _moon_sun_arrays(times: Time, location: EarthLocation):
    """(az de la Luna, alt de la Luna, alt del sol) en grados para ``times``."""
    frame = AltAz(obstime=times, location=location)
    moon = get_body("moon", times, location).transform_to(frame)
    sun = get_sun(times).transform_to(frame).alt
    return moon.az.to_value(u.deg), moon.alt.to_value(u.deg), sun.to_value(u.deg)


def _lunar_illumination(times: Time, location: EarthLocation) -> float:
    """Fracción iluminada de la Luna en el centro de la ventana nocturna."""
    mid = times[len(times) // 2]
    moon = get_body("moon", mid, location)
    sun = get_sun(mid)
    elongation = angular_separation(moon.ra, moon.dec, sun.ra, sun.dec)
    return float((1.0 - np.cos(elongation.to_value(u.rad))) / 2.0)


def _moon_sun_series(times: Time, location: EarthLocation):
    """(az de la Luna, alt de la Luna, alt del sol) en **toda** la malla.

    Se calculan cada :data:`MOON_SUN_SAMPLE_MIN` minutos — la Luna avanza
    ~0,1° y el sol ~0,04° en ese tramo — y se interpolan linealmente hasta
    la malla de 1 min. La interpolación va en **coordenadas rectangulares**
    (x, y, z) y no en azimut+altitud, porque el azimut da vueltas de 180°
    al pasar por el cenit y un tramo lineal ahí sería monstruoso.

    Con paso de 5 min el error medido es de 0,009° de altitud lunar y
    0,006° de separación, y los bordes de la noche astronómica no se
    mueven: ahorra ~4,5× en la parte más cara del cálculo (622 → 139 ms).
    """
    every = max(1, round(MOON_SUN_SAMPLE_MIN / SAMPLE_MIN))
    if every == 1:
        return _moon_sun_arrays(times, location)
    idx = np.arange(0, len(times), every)
    caz, calt, csun = _moon_sun_arrays(times[idx], location)
    lat, az = np.radians(calt), np.radians(caz)
    x = np.cos(lat) * np.cos(az)
    y = np.cos(lat) * np.sin(az)
    z = np.sin(lat)
    grid = np.arange(len(times))
    return (
        np.degrees(np.arctan2(np.interp(grid, idx, y), np.interp(grid, idx, x))),
        np.degrees(np.arcsin(np.interp(grid, idx, z))),
        np.interp(grid, idx, csun),
    )


def _remember_moon_sun(key: tuple, value: tuple) -> None:
    """Guarda la entrada, descartando la más vieja si la caché está llena."""
    with _CACHE_LOCK:
        if key in _MOON_SUN_CACHE:
            _MOON_SUN_CACHE[key] = _MOON_SUN_CACHE.pop(key)
        elif len(_MOON_SUN_CACHE) >= _MOON_SUN_CACHE_MAX:
            _MOON_SUN_CACHE.pop(next(iter(_MOON_SUN_CACHE)))
        _MOON_SUN_CACHE[key] = value


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

    Tres optimizaciones, sin tocar la física (el resultado es el mismo
    salvo el error de muestreo de :func:`_moon_sun_series`, de 0,009°):

    - la Luna y el sol se guardan en :data:`_MOON_SUN_CACHE` por
      (fecha, ubicación), que es todo lo que les afecta: al cambiar de
      objeto solo se transforma el objeto;
    - la Luna y el sol se calculan a paso grueso y se interpolan;
    - el objeto se calcula en su malla de 1 min, que es lo barato.
    """
    location = _location(latitude, longitude)
    times = _night_times(date_iso, longitude, utc_offset_hours=utc_offset_hours)

    # Luna y sol: solo dependen de la fecha y la ubicación, no del objeto.
    key = (latitude, longitude, date_iso, utc_offset_hours)
    with _CACHE_LOCK:
        cached = _MOON_SUN_CACHE.get(key)
    if cached is None:
        moon_az, moon_alt, sun_alt = _moon_sun_series(times, location)
        illumination = _lunar_illumination(times, location)
        _remember_moon_sun(key, (moon_az, moon_alt, sun_alt, illumination))
    else:
        moon_az, moon_alt, sun_alt, illumination = cached

    # El objeto sí es nuevo en cada llamada: es lo barato.
    target = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_deg * u.deg, frame="icrs")
    target_az, target_alt = _target_arrays(times, location, target)

    alts = target_alt
    separations = angular_separation(
        target_az * u.deg, alts * u.deg, moon_az * u.deg, moon_alt * u.deg
    ).to_value(u.deg)

    return NightCurve(
        # times.iso vectorizado = [str(t.iso) for t in times] (verificado
        # bit a bit), y sin ~1000 visitas al mecanismo de atributos de Time.
        times_iso=[str(value) for value in times.iso],
        hours_local=_local_hours(times, longitude, utc_offset_hours),
        altitudes=[float(a) for a in alts],
        moon_altitudes=[float(a) for a in moon_alt],
        moon_separations=[float(s) for s in separations],
        astro_night=[bool(alt < ASTRO_TWILIGHT_DEG) for alt in sun_alt],
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
    utc_offset_hours: float | None = None,
) -> NightInfo:
    """Horas de noche astronómica y fase lunar para ``date_iso``.

    - ``astronomical_dusk``/``dawn``: primer y último instante del **tramo
      continuo más largo** con el sol bajo -18° (None si esa noche no
      llega a la noche astronómica).
    - ``moon_phase``: fracción iluminada de la luna en el centro de la
      noche (0 = nueva, 1 = llena).

    ``utc_offset_hours`` (desfase guardado, ver :func:`local_utc_offset`)
    centra la ventana nocturna **igual que** :func:`night_curve`: sin él la
    ventana se abría con el huso inferido de la longitud y, en ubicaciones
    con huso político distinto, las efemérides y la curva miraban noches
    distintas (la del plan salía vacía con >3 h de desfase).

    ``sample_min`` sube la malla (p. ej. 30) para baratar el cálculo cuando
    solo hace falta una estimación, como al recorrer 30 noches en el plan
    de captura. Por defecto usa la malla fina de :data:`SAMPLE_MIN`.
    """
    location = _location(latitude, longitude)
    times = _night_times(date_iso, longitude, sample_min, utc_offset_hours=utc_offset_hours)
    frame = AltAz(obstime=times, location=location)

    sun_alt = get_sun(times).transform_to(frame).alt
    astronomical = sun_alt < ASTRO_TWILIGHT_DEG * u.deg

    dusk = dawn = None
    hours = 0.0
    if np.any(astronomical):
        # La noche es el tramo CONTINUO más largo de la ventana: con el
        # huso guardado la ventana puede contener el final de una noche y
        # el principio de la siguiente (con el día entre medias) y, si se
        # cubre el rango de la primera a la última muestra, el día cuenta
        # como noche (medido: 16 h de «noche» vs 0,78 h reales).
        indices = np.flatnonzero(astronomical)
        tramos = np.split(indices, np.flatnonzero(np.diff(indices) != 1) + 1)
        run = max(tramos, key=len)
        dusk = times[run[0]].iso
        dawn = times[run[-1]].iso
        hours = len(run) * sample_min / 60.0

    # Fase lunar en el centro de la ventana (noche local aproximada).
    # Si night_curve ya guardó esta noche la iluminación, se reutiliza:
    # el centro de la malla cae en el mismo instante (start + 8 h) sea
    # cual sea sample_min, y la clave de caché incluye el huso (M-09).
    mid = times[len(times) // 2]
    key = (latitude, longitude, date_iso, utc_offset_hours)
    with _CACHE_LOCK:
        cached = _MOON_SUN_CACHE.get(key)
    if cached is not None:
        illumination = float(cached[3])
    else:
        illumination = _lunar_illumination(times, location)

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
    utc_offset_hours: float | None = None,
) -> TransitInfo:
    """Tránsito de un objeto y su mínima separación con la luna esa noche.

    - ``transit_time``/``altitude_deg``: culminación dentro de la ventana.
    - ``separation_moon_deg``: menor separación angular objeto-luna mientras
      el objeto está sobre el horizonte (peor caso de la noche).
    - ``hour_altitudes``: (ISO, altitud) cada SAMPLE_MIN min para graficar.

    Internamente delega en :func:`night_curve`, que es la misma malla que
    alimenta la gráfica y las ventanas de captura; ``utc_offset_hours``
    centra la ventana con el huso guardado (igual que ``night_info``).
    """
    curve = night_curve(
        ra_hours, dec_deg, latitude, longitude, date_iso,
        utc_offset_hours=utc_offset_hours,
    )
    return TransitInfo(
        transit_time=curve.transit_time,
        altitude_deg=round(curve.transit_altitude, 1),
        separation_moon_deg=round(curve.min_separation_moon_deg, 1),
        hour_altitudes=[
            (iso, alt) for iso, alt in zip(curve.times_iso, curve.altitudes, strict=True)
        ],
    )
