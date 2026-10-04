"""Tests del cálculo de campo de visión (FOV) desde el equipo."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planners.framing import (
    calculate_fov,
    calculate_mosaic_extent,
    fov_to_arcmin,
)

#: Equipo completo de referencia: 500 mm, sensor 6048×4032 de 3.76 µm.
FULL_SETUP = {
    "telescope_focal_mm": 500.0,
    "camera_width_px": 6048,
    "camera_height_px": 4032,
    "camera_pixel_size_um": 3.76,
}


def test_calculate_fov_known_values():
    """Sensor 22.74×15.16 mm con focal 500 mm → 2.61°×1.74°."""
    fov_major, fov_minor = calculate_fov(FULL_SETUP)
    assert fov_major == pytest.approx(2.605, abs=0.01)
    assert fov_minor == pytest.approx(1.737, abs=0.01)
    assert fov_major > fov_minor


def test_calculate_fov_longer_focal_narrower_field():
    """Más focal ⇒ campo más estrecho (relación inversa)."""
    wide = calculate_fov({**FULL_SETUP, "telescope_focal_mm": 200.0})
    narrow = calculate_fov({**FULL_SETUP, "telescope_focal_mm": 1000.0})
    assert wide[0] > narrow[0]


@pytest.mark.parametrize("missing", [
    "telescope_focal_mm", "camera_width_px", "camera_height_px",
    "camera_pixel_size_um",
])
def test_calculate_fov_missing_data_returns_none(missing):
    """Sin cualquier dato el encuadre se desactiva (None, nunca inventa FOV)."""
    setup = {key: value for key, value in FULL_SETUP.items() if key != missing}
    assert calculate_fov(setup) is None


@pytest.mark.parametrize("bad_value", [0, -500, None, "abc"])
def test_calculate_fov_invalid_values_return_none(bad_value):
    """Focal o píxel inválidos ⇒ None en vez de un FOV falso."""
    assert calculate_fov({**FULL_SETUP, "telescope_focal_mm": bad_value}) is None
    assert calculate_fov({**FULL_SETUP, "camera_pixel_size_um": bad_value}) is None


def test_fov_to_arcmin():
    """Grados → minutos de arco (×60)."""
    assert fov_to_arcmin(1.0) == 60.0
    assert fov_to_arcmin(2.5) == 150.0


def test_calculate_mosaic_extent_multiplies_by_tiles():
    """Un mosaico 2×2 dobla el encuadre nominal en cada eje."""
    assert calculate_mosaic_extent(2.5, 1.7, 2, 2) == (5.0, 3.4)


def test_calculate_mosaic_extent_minimum_one_tile():
    """Teselas 0 o negativas se tratan como 1 (sin mosaico)."""
    assert calculate_mosaic_extent(2.5, 1.7, 0, -3) == (2.5, 1.7)
