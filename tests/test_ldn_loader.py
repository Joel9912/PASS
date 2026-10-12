"""Tests del cargador de nebulosas oscuras LDN (VizieR VII/7A)."""
import gzip
import sqlite3
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planners import catalog_loader, ldn_loader

#: Cabecera tal y como la serializa el TAP en CSV (coordenadas con '_').
TAP_HEADER = "LDN,_RA_icrs,_DE_icrs,Area,Opacity"
#: Variante con punto, el nombre real en TAP_SCHEMA.
TAP_HEADER_DOTTED = 'LDN,"_RA.icrs","_DE.icrs",Area,Opacity'


@pytest.mark.parametrize("contenido", ["", TAP_HEADER + "\n", TAP_HEADER + "\n621,281.875"])
def test_ldn_invalido_conserva_catalogo(memory_db, monkeypatch, contenido):
    """Una respuesta vacía o truncada no borra datos ya confirmados."""
    memory_db.execute("INSERT INTO catalog (object_id, catalog) VALUES ('LDN 1', 'ldn')")
    memory_db.commit()
    monkeypatch.setattr(ldn_loader, "_download_tap", lambda *args: contenido.encode())
    with pytest.raises(ValueError):
        ldn_loader.load_ldn()
    memory_db.commit()
    assert memory_db.execute("SELECT object_id FROM catalog").fetchone()[0] == "LDN 1"


def test_ngc_solo_cabecera_conserva_catalogo(memory_db, monkeypatch):
    """La cabecera sin objetos no se considera un refresco válido."""
    memory_db.execute("INSERT INTO catalog (object_id, catalog) VALUES ('M31', 'messier')")
    memory_db.commit()
    monkeypatch.setattr(catalog_loader, "_download", lambda url: b"Name;Type\n")
    with pytest.raises(ValueError):
        catalog_loader.load_catalog()
    assert memory_db.execute("SELECT object_id FROM catalog").fetchone()[0] == "M31"


def test_ldn_fallo_insert_rollback_directo(memory_db, monkeypatch):
    """Un fallo tras DELETE no queda pendiente para el próximo commit."""
    memory_db.execute("INSERT INTO catalog (object_id, catalog) VALUES ('LDN 1', 'ldn')")
    memory_db.execute("CREATE TRIGGER impedir_insert BEFORE INSERT ON catalog BEGIN SELECT RAISE(ABORT, 'fallo'); END")
    memory_db.commit()
    monkeypatch.setattr(ldn_loader, "_download_tap", lambda *args: (TAP_HEADER + "\n621,281.875,3.2,1,4\n").encode())
    with pytest.raises(sqlite3.IntegrityError):
        ldn_loader.load_ldn()
    memory_db.commit()
    assert memory_db.execute("SELECT object_id FROM catalog").fetchone()[0] == "LDN 1"


@pytest.mark.parametrize("text", ["mag,ra,dec\n", "mag,ra,dec\n1,2\n"])
def test_hyg_invalido_conserva_estrellas(memory_db, monkeypatch, text):
    """Ni CSV vacío ni fila parcial sustituyen las estrellas guardadas."""
    memory_db.execute("INSERT INTO stars (name, magnitude, ra_hours, dec_deg) VALUES ('anterior', 1, 2, 3)")
    memory_db.commit()
    monkeypatch.setattr(catalog_loader, "_download", lambda url: gzip.compress(text.encode()))
    with pytest.raises(ValueError):
        catalog_loader.load_stars()
    assert memory_db.execute("SELECT name FROM stars").fetchone()[0] == "anterior"


def test_refresco_ngc_conserva_ldn(memory_db, monkeypatch):
    """OpenNGC no borra el catálogo LDN gestionado por otro cargador."""
    memory_db.execute("INSERT INTO catalog (object_id, catalog) VALUES ('LDN 1', 'ldn')")
    memory_db.commit()
    header = ["Name", "Type", "RA", "Dec"] + [f"c{i}" for i in range(4, 29)]
    fila = ["NGC0001", "G", "00:01:00", "+01:00:00"] + [""] * 25
    data = (";".join(header) + "\n" + ";".join(fila) + "\n").encode()
    monkeypatch.setattr(catalog_loader, "_download", lambda url: data)
    catalog_loader.load_catalog()
    assert memory_db.execute("SELECT COUNT(*) FROM catalog WHERE catalog='ldn'").fetchone()[0] == 1


@pytest.mark.parametrize("tap", [False, True])
def test_descarga_truncada_no_se_cachea(tmp_path, monkeypatch, tap):
    """Content-Length permite detectar cortes incluso entre filas completas."""
    class Respuesta:
        """Respuesta HTTP simulada que anuncia más bytes de los que entrega."""
        def __init__(self):
            """Crea las cabeceras de esta respuesta simulada."""
            self.headers = {"Content-Length": "100"}

        def __enter__(self):
            """Abre el contexto del doble."""
            return self

        def __exit__(self, *args):
            """Cierra el contexto sin suprimir errores."""
            return False

        def read(self):
            """Entrega un cuerpo incompleto."""
            return b"LDN,RA\n1,2\n"

    modulo = ldn_loader if tap else catalog_loader
    monkeypatch.setattr(modulo, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: Respuesta())
    with pytest.raises(ValueError):
        if tap:
            ldn_loader._download_tap("consulta", "ldn.csv")
        else:
            catalog_loader._download("https://ejemplo/catalog.csv")
    assert not list(tmp_path.iterdir())


def test_parse_ldn_rows_builds_catalog_rows():
    """Cada LDN pasa a fila de catalog con RA en horas (J2000 grados/15)."""
    csv_text = (
        TAP_HEADER + "\n"
        "621,281.875,3.2225,16.3,4\n"
        "34,7.0,60.0,0.25,2\n"
    )
    rows = ldn_loader.parse_ldn_rows(csv_text)

    assert len(rows) == 2
    object_id, catalog, m, n, i, name, obj_type, mag, ra, dec, _, _, const = rows[0]
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
