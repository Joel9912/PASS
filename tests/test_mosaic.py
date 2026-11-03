"""Geometría del mosaico con referencias vectoriales independientes de Qt, red y fotografías."""

import math
from dataclasses import replace

import numpy as np
import pytest
from test_multinight import request

from planners.mosaic import mosaic_extent, mosaic_tiles
from planners.multinight import tile_centers, validate


def vectors(points):
    """Direcciones unitarias de RA/Dec para comprobar ángulos y giros sin depender de la carta."""
    values = np.asarray(points)
    ra, dec = np.radians(values[:, 0]*15), np.radians(values[:, 1])
    return np.stack((np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)), axis=1)


def tangent(points, ra=0., dec=0.):
    """Proyección de contraste sobre una base celeste explícita, distinta del constructor del mosaico."""
    coordinates = vectors(points)
    origin = vectors([(ra, dec)])[0]
    east = np.array((-math.sin(math.radians(ra*15)), math.cos(math.radians(ra*15)), 0.))
    north = np.cross(origin, east)
    return np.stack((coordinates@east/(coordinates@origin), coordinates@north/(coordinates@origin)), axis=1)


@pytest.mark.parametrize(("nx", "ny"), [(2, 3), (3, 3), (2, 2), (1, 3), (3, 1)])
def test_mosaico_centrado_pares_e_impares(nx, ny):
    """El centro queda entre las cámaras centrales pares y en T5 para la rejilla 3×3."""
    tiles = mosaic_tiles(0, 30, 2, 1, nx, ny, overlap_x=.2, overlap_y=.3)
    points = tangent([(tile.ra_hours, tile.dec_deg) for tile in tiles], dec=30)
    assert points.mean(axis=0) == pytest.approx([0, 0], abs=1e-15)
    assert points == pytest.approx(-points[::-1], abs=1e-15)
    if (nx, ny) == (2, 3):
        assert points[2:4, 1] == pytest.approx([0, 0], abs=1e-15)
        assert points[2, 0] == pytest.approx(-points[3, 0])
    if (nx, ny) == (3, 3):
        assert (tiles[4].ra_hours, tiles[4].dec_deg) == (0, 30)
    assert [t.number for t in tiles] == list(range(1, nx*ny+1))


def test_solape_reduce_paso_no_fov_de_camara():
    """El 25% horizontal reduce el paso al 75%; no parte el sensor en fragmentos."""
    tiles = mosaic_tiles(0, 0, 4, 2, 2, 3, overlap_x=.25, overlap_y=.4)
    centers = tangent([(t.ra_hours, t.dec_deg) for t in tiles])
    assert centers[0, 0]-centers[1, 0] == pytest.approx(2*math.tan(math.radians(2))*.75)
    assert centers[0, 1]-centers[2, 1] == pytest.approx(2*math.tan(math.radians(1))*.6)
    for tile in tiles:
        corners = vectors(tile.corners)
        horizontal = corners[[0, 3]].sum(axis=0), corners[[1, 2]].sum(axis=0)
        vertical = corners[[0, 1]].sum(axis=0), corners[[2, 3]].sum(axis=0)
        for (a, b), angle in ((horizontal, 4), (vertical, 2)):
            assert math.degrees(math.acos(np.dot(a, b)/np.linalg.norm(a)/np.linalg.norm(b))) == pytest.approx(angle, abs=1e-10)


@pytest.mark.parametrize("angle", [0, 37, 90, 180, 360])
def test_giro_rigido_de_centros_y_camaras(angle):
    """Un mismo giro maestro preserva distancias entre todas las cámaras y sus esquinas."""
    original = mosaic_tiles(23.98, 72, 3, 2, 2, 3, overlap_x=.2, overlap_y=.2)
    rotated = mosaic_tiles(23.98, 72, 3, 2, 2, 3, overlap_x=.2, overlap_y=.2, rotation_deg=angle)
    points = [(t.ra_hours, t.dec_deg) for t in original]+[p for t in original for p in t.corners]
    changed = [(t.ra_hours, t.dec_deg) for t in rotated]+[p for t in rotated for p in t.corners]
    a, b = vectors(points), vectors(changed)
    assert a@a.T == pytest.approx(b@b.T, abs=3e-15)
    before = tangent(points, 23.98, 72)
    after = tangent(changed, 23.98, 72)
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    expected = before@np.array(((c, -s), (s, c)))
    assert after == pytest.approx(expected, abs=3e-15)
    if angle == 90:
        assert not np.allclose(before[:6], after[:6])


@pytest.mark.parametrize(("ra", "dec"), [(0, 0), (24, 45), (23.999, 89.9), (1, -89.9), (3, 90), (3, -90)])
def test_ra_circular_y_polos_no_deforman_fov(ra, dec):
    """El cálculo usa direcciones vectoriales, sin dividir por cos(Dec) ni saltar en RA cero."""
    tiles = mosaic_tiles(ra, dec, 2, 1, 2, 3, rotation_deg=47, overlap_x=.1, overlap_y=.2)
    assert all(0 <= t.ra_hours < 24 and -90 <= t.dec_deg <= 90 and 0 <= t.position_angle < 360 for t in tiles)
    assert all(math.isfinite(value) for tile in tiles for pair in tile.corners for value in pair)


def test_unica_camara_gira_alrededor_de_su_centro():
    """Con 1×1 el PA cambia la huella pero no desplaza el apuntado."""
    base = mosaic_tiles(2, 30, 4, 2)[0]
    rotated = mosaic_tiles(2, 30, 4, 2, rotation_deg=90)[0]
    assert (base.ra_hours, base.dec_deg) == (rotated.ra_hours, rotated.dec_deg) == (2, 30)
    assert rotated.position_angle == pytest.approx(90)
    assert rotated.corners != base.corners


def test_fov_total_con_solape_es_invertible():
    """La región total explícita y el FOV por cámara comparten la misma definición de paso."""
    total = mosaic_extent(2, 1, 2, 3, overlap_x=.2, overlap_y=.3)
    assert total[0] < mosaic_extent(2, 1, 2, 3)[0]
    assert mosaic_extent(*total, 2, 3, overlap_x=.2, overlap_y=.3, inverse=True) == pytest.approx((2, 1))


@pytest.mark.parametrize("data", [dict(rotation_deg=float("nan")), dict(rotation_deg=True), dict(rotation_deg=-1),
                                  dict(rotation_deg=361), dict(overlap_x=1), dict(overlap_y=-.1), dict(overlap_x=True)])
def test_geometria_invalida_no_se_normaliza(data):
    """Una entrada corrupta no se convierte en un plan norte-arriba o sin solape."""
    obj = replace(request().objectives[0], fov_width=2, fov_height=1, **data)
    with pytest.raises(ValueError):
        validate(replace(request(), objectives=(obj,)))


def test_centros_anteriores_sin_geometria_nueva_se_conservan():
    """Contrasta el caso antiguo con su fórmula gnomónica para no reinterpretar maestros previos."""
    obj = replace(request().objectives[0], ra_hours=23.99, dec_deg=60, tiles_x=2, tiles_y=3, fov_width=2, fov_height=1)
    expected = []
    ra0, dec0 = math.radians(obj.ra_hours*15), math.radians(obj.dec_deg)
    for row in range(3):
        for column in range(2):
            xi = (.5-column)*2*math.tan(math.radians(1))
            eta = (1-row)*2*math.tan(math.radians(.5))
            rho = math.hypot(xi, eta)
            c = math.atan(rho)
            dec = math.asin(math.cos(c)*math.sin(dec0)+eta*math.sin(c)*math.cos(dec0)/rho)
            ra = ra0+math.atan2(xi*math.sin(c), rho*math.cos(dec0)*math.cos(c)-eta*math.sin(dec0)*math.sin(c))
            expected.append((math.degrees(ra)%360/15, math.degrees(dec)))
    assert np.asarray(tile_centers(obj)) == pytest.approx(np.asarray(expected), abs=1e-12)
