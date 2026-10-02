"""Tests del cargador de nebulosas oscuras LDN (VizieR VII/7A)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planners import ldn_loader  # noqa: E402

#: Cabecera tal y como la serializa el TAP en CSV (coordenadas con '_').
TAP_HEADER = "LDN,_RA_icrs,_DE_icrs,Area,Opacity"
#: Variante con punto, el nombre real en TAP_SCHEMA.
TAP_HEADER_DOTTED = 'LDN,"_RA.icrs","_DE.icrs",Area,Opacity'


def test_parse_ldn_rows_builds_catalog_rows():
    """Cada LDN pasa a fila de catalog con RA en horas (J2000 grados/15)."""
    csv_text = (
        TAP_HEADER + "\n"
        "621,281.875,3.2225,16.3,4\n"
        "34,7.0,60.0,0.25,2\n"
    )
    rows = ldn_loader.parse_ldn_rows(csv_text)

    assert len(rows) == 2
    object_id, catalog, m, n, i, name, obj_type, mag, ra, dec, major, minor, const = rows[0]
    assert object_id == "LDN 621" and catalog == "ldn"
    assert (m, n, i, name) == (None, None, None, None)   # sin cross-refs ni nombre
    assert obj_type == "DrkN" and mag is None            # nebulosa oscura sin magnitud
    assert ra == pytest.approx(281.875 / 15.0)           # grados → horas
    assert dec == pytest.approx(3.2225)
    assert const is None                                  # el catálogo no da constelación


def test_parse_ldn_rows_accepts_dotted_column_names():
    """El CSV puede traer '_RA.icrs' (nombre real en TAP_SCHEMA)."""
    csv_text = TAP_HEADER_DOTTED + "\n621,281.875,3.2225,16.3,4\n"
    rows = ldn_loader.parse_ldn_rows(csv_text)
    assert rows and rows[0][8] == pytest.approx(281.875 / 15.0)


def test_parse_ldn_rows_skips_objects_without_number():
    """Los 4 objetos sin número LDN (colas de la tabla) se descartan."""
    csv_text = (
        TAP_HEADER + "\n"
        "621,281.875,3.2225,16.3,4\n"
        ",23.9,58.5,0.0,\n"
        ",2.87,60.5,0.0,\n"
    )
    rows = ldn_loader.parse_ldn_rows(csv_text)
    assert len(rows) == 1
    assert rows[0][0] == "LDN 621"


def test_parse_ldn_rows_skips_rows_without_coordinates():
    """Sin coordenadas J2000 no hay objeto utilizable."""
    csv_text = TAP_HEADER + "\n621,,3.2225,16.3,4\n622,281.875,,16.3,4\n"
    assert ldn_loader.parse_ldn_rows(csv_text) == []


def test_size_major_from_area_is_equivalent_diameter():
    """El área en deg² se traduce a diámetro circular equivalente en arcmin."""
    from planners.ldn_loader import _size_major_from_area

    # Área de un círculo de 1° de diámetro (π·0.5² ≈ 0.7854 deg²)
    size = _size_major_from_area(0.7853981634)
    assert size == pytest.approx(60.0, abs=0.1)
    assert _size_major_from_area(0.0) is None
    assert _size_major_from_area(None) is None
    assert _size_major_from_area(-1.0) is None


def test_ldn_loaded_in_database():
    """Si los catálogos están cargados, hay LDN reales consultables."""
    from planners import catalog_loader

    counts = catalog_loader.ensure_catalog()
    if counts.get("ldn", 0) == 0:
        pytest.skip("Sin LDN cargados y sin red para descargarlos")

    from planners.celestial_search import SearchFilters, search

    assert counts["ldn"] >= 1700
    results = search(SearchFilters(catalogs=["ldn"], text="LDN 621"))
    assert results and results[0]["type"] == "DrkN"
    assert results[0]["ra_hours"] is not None
