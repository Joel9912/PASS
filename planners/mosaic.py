"""Mosaicos esféricos centrados: FOV completo por tesela y giro rígido de centros y huellas."""

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np


@dataclass(frozen=True)
class MosaicTile:
    """Tesela numerada por fila/columna; esquinas y PA local expresados sobre el cielo, no en píxeles."""

    number: int
    ra_hours: float
    dec_deg: float
    position_angle: float
    corners: tuple[tuple[float, float], ...]


def _finite(value, low, high):
    """Rechaza booleanos y no finitos para no normalizar una geometría corrupta en silencio."""
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Geometría de mosaico fuera del intervalo admitido.")


def validate_geometry(rotation_deg, overlap_x, overlap_y):
    """El PA maestro va de norte hacia este; los solapes son fracciones lineales nominales, no áreas."""
    _finite(rotation_deg, 0, 360)
    _finite(overlap_x, 0, .9)
    _finite(overlap_y, 0, .9)


def mosaic_extent(width, height, tiles_x, tiles_y, *, overlap_x=0., overlap_y=0., inverse=False):
    """Campo nominal alineado al mosaico ↔ FOV por tesela, con paso reducido por el solape de cada eje."""
    validate_geometry(0, overlap_x, overlap_y)
    for angle in (width, height):
        _finite(angle, .000001, 180-1e-6)
    for count in (tiles_x, tiles_y):
        if type(count) is not int or not 1 <= count <= 20:
            raise ValueError("Teselas fuera de rango.")
    factors = 1+(tiles_x-1)*(1-overlap_x), 1+(tiles_y-1)*(1-overlap_y)
    return tuple(math.degrees(2*math.atan(math.tan(math.radians(angle)/2)*(1/factor if inverse else factor)))
                 for angle, factor in zip((width, height), factors))


def _basis(ra_hours, dec_deg):
    """Base ortonormal centro/este/norte, también en polos y al cruzar RA cero."""
    ra, dec = math.radians(ra_hours*15), math.radians(dec_deg)
    center = np.array((math.cos(dec)*math.cos(ra), math.cos(dec)*math.sin(ra), math.sin(dec)))
    east = np.array((-math.sin(ra), math.cos(ra), 0.))
    north = np.cross(center, east)
    return center, east, north


def _coordinates(vector):
    """Convierte una dirección normalizada a RA circular y declinación sin discontinuidad geométrica."""
    x, y, z = vector/np.linalg.norm(vector)
    ra = (math.degrees(math.atan2(y, x)) % 360/15) % 24
    return ra, math.degrees(math.atan2(z, math.hypot(x, y)))


def _transport(vector, axis, dot):
    """Transporta la cámara por el arco mínimo sin cambiar sus dimensiones angulares."""
    return vector+np.cross(axis, vector)+np.cross(axis, np.cross(axis, vector))/(1+dot)


@lru_cache(maxsize=128, typed=True)
def mosaic_tiles(ra_hours, dec_deg, width, height, tiles_x=1, tiles_y=1, *, rotation_deg=0., overlap_x=0., overlap_y=0.):
    """Genera cámaras de igual FOV con transporte paralelo y rotación rígida alrededor del centro maestro.

    El paso de centros es 2*tan(FOV/2)*(1-solape) en el plano maestro.
    El porcentaje describe ese diseño nominal, no un área de intersección
    esférica garantizada. Cada cámara conserva su FOV angular completo.
    La numeración empieza en la esquina superior izquierda a PA cero.
    """
    _finite(ra_hours, 0, 24)
    _finite(dec_deg, -90, 90)
    for angle in (width, height):
        _finite(angle, .000001, 90)
    mosaic_extent(width, height, tiles_x, tiles_y, overlap_x=overlap_x, overlap_y=overlap_y)
    validate_geometry(rotation_deg, overlap_x, overlap_y)
    center, east, north = _basis(ra_hours, dec_deg)
    half_w, half_h = math.tan(math.radians(width)/2), math.tan(math.radians(height)/2)
    angle = math.radians(rotation_deg % 360)
    cosine, sine = math.cos(angle), math.sin(angle)

    def rotate(vector):
        """Gira todo el campo: PA positivo lleva el norte hacia el este, no rota cámaras aisladas."""
        return vector*cosine-np.cross(center, vector)*sine+center*np.dot(center, vector)*(1-cosine)

    result = []
    for row in range(tiles_y):
        for column in range(tiles_x):
            xi = ((tiles_x-1)/2-column)*2*half_w*(1-overlap_x)
            eta = ((tiles_y-1)/2-row)*2*half_h*(1-overlap_y)
            target = center+xi*east+eta*north
            target /= np.linalg.norm(target)
            axis = np.cross(center, target)
            dot = float(np.dot(center, target))

            tile_east, tile_north = rotate(_transport(east, axis, dot)), rotate(_transport(north, axis, dot))
            target = rotate(target)
            ra, dec = _coordinates(target)
            if xi == eta == 0:
                ra, dec = ra_hours % 24, dec_deg
            _c, local_east, local_north = _basis(ra, dec)
            pa = math.degrees(math.atan2(float(np.dot(tile_north, local_east)), float(np.dot(tile_north, local_north)))) % 360
            if math.isclose(pa, 360, rel_tol=0, abs_tol=1e-10):
                pa = 0.
            corners = tuple(_coordinates(target+x*half_w*tile_east+y*half_h*tile_north)
                            for x, y in ((1, 1), (-1, 1), (-1, -1), (1, -1)))
            result.append(MosaicTile(len(result)+1, ra, dec, pa, corners))
    return tuple(result)
