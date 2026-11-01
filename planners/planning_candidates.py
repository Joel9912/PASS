"""Series de altura y pasos superiores por meridiano; candidatos sin puntuaciones científicas inventadas."""

import math
from datetime import UTC

import numpy as np
from astropy import units as u
from astropy.coordinates import TETE, SkyCoord
from astropy.time import Time

from .planning_models import SkyTrack


def sky_track(key, tile, night, times, altitudes, location, ra, dec):
    """Busca cruces de ángulo horario cero a ambos lados de la disponibilidad, no el máximo recortado de la curva."""
    grid = Time(np.arange(times[0].jd-1, times[-1].jd+1+1/288, 1/288), format="jd")
    target = SkyCoord(ra=ra*u.hourangle, dec=dec*u.deg, frame="icrs").transform_to(TETE(obstime=grid, location=location))
    ha = np.unwrap((grid.sidereal_time("apparent", longitude=location.lon)-target.ra).to_value(u.rad))
    transits = []
    for index in range(len(ha)-1):
        low, high = float(ha[index]), float(ha[index+1])
        crossing = math.ceil(low/(2*math.pi))*2*math.pi
        if high > low and low <= crossing < high:
            fraction = (crossing-low)/(high-low)
            moment = grid[index]+(grid[index+1]-grid[index])*fraction
            transits.append(moment.to_datetime(timezone=UTC))
    return SkyTrack(key, tile, night, tuple(times.to_datetime(timezone=UTC)), tuple(map(float, altitudes)), tuple(transits))


def altitude_at(track, moment):
    """Interpola altura de la malla para comparar bloques, sin extrapolar calidad fuera de su franja."""
    if track is None or not track.times:
        return 0.
    origin = track.times[0]
    seconds, altitudes = track.interpolation
    return float(np.interp((moment-origin).total_seconds(), seconds, altitudes))
