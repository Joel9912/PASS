"""Preparación offline OpenNGC/HYG desde CSV sintéticos, con claves persistentes y sin catálogos o bases personales."""

import csv
import gzip
import io
import sqlite3

import pytest

from db.catalog_identity import identity_registry
from planners import catalog_preparation as preparation


def csv_bytes(rows, fields, *, delimiter):
    """Serializa filas sintéticas con cabeceras explícitas y sin depender de archivos remotos."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, delimiter=delimiter)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def ngc(name="NGC0224", **changes):
    """Objeto ficticio con referencias y banda B disponibles, sin fabricar una banda V ausente."""
    row = dict.fromkeys(preparation.NGC_FIELDS, "")
    row.update(Name=name, Type="G", RA="00:42:00.0", Dec="+41:00:00.0", Const="And", MajAx="20", MinAx="10")
    row.update({"B-Mag": "-1.0", "Common names": "Nombre de prueba", "Sources": "Type:99|RA:99", "PosAng": "45"})
    row.update(changes)
    return row


def ngc_file(*rows):
    """Mantiene el orden de campos independiente del orden de columnas legacy."""
    return csv_bytes(rows, sorted(preparation.NGC_FIELDS), delimiter=";")


def hyg(identifier="1", **changes):
    """Estrella ficticia con identificadores y movimiento propio explícitos."""
    row = dict.fromkeys(preparation.HYG_FIELDS, "")
    row.update(id=identifier, hip="12", hd="34", hr="56", bf="Alp And", proper="Estrella de prueba",
               ra="2", dec="40", mag="-1.2", spect="A0", con="And", pmra="0", pmdec="-4.5")
    row.update(changes)
    return row


def hyg_file(*rows):
    """Genera un archivo HYG comprimido propio con contenido finito y reproducible."""
    return gzip.compress(csv_bytes(rows, sorted(preparation.HYG_FIELDS), delimiter=","), mtime=0)


def test_openngc_conserva_campos_banda_y_alias_sin_fundir(tmp_path):
    """Una fila mantiene fuente literal, nombres secundarios, orientación y la banda de la magnitud proyectada."""
    data = ngc_file(ngc(M="31", NGC="0224", Identifiers="C023,PGC 2557"))
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        result = preparation.prepare_openngc(registry, {"NGC.csv": data}, revision="synthetic-A")
    row = result["rows"][0]
    assert row[:5] == ["M31", "messier", 31, 224, None]
    assert row[7:12] == [-1, 0.7, 41, 20, 10]
    record = result["records"][0]
    assert {"namespace": "caldwell", "designation": "Caldwell 23"} in record["aliases"]
    source = record["sources"][0]
    assert source["key"] == "NGC0224" and source["data"]["row"]["B-Mag"] == "-1.0"
    assert source["data"]["magnitude_band"] == "B" and source["data"]["position_angle_deg"] == 45


def test_openngc_alias_compartido_no_sobrescribe_componentes(tmp_path):
    """Dos filas de fuente con el mismo alias Messier siguen separadas y consultables como candidatas."""
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        result = preparation.prepare_openngc(registry, {"NGC.csv": ngc_file(ngc("NGC0001", M="1"), ngc("NGC0002", M="1"))},
                                             revision="A")
    assert [row[0] for row in result["rows"]] == ["NGC 1", "NGC 2"]
    assert len({record["pass_id"] for record in result["records"]}) == 2
    assert all({"namespace": "messier", "designation": "M1"} in record["aliases"] for record in result["records"])


def test_openngc_estrellas_y_duplicados_excluidos_sin_excluir_cumulos(tmp_path):
    """Aplica las categorías explícitas de la guía, no una búsqueda del carácter asterisco."""
    rows = [ngc(f"NGC{index:04}", Type=kind) for index, kind in enumerate(("*", "**", "Nova", "Dup", "NonEx"), 1)]
    rows.append(ngc("NGC0006", Type="*Ass"))
    excluded = []
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        result = preparation.prepare_openngc(registry, {"NGC.csv": ngc_file(*rows)}, revision="A", exclusions=excluded)
    assert [row[0] for row in result["rows"]] == ["NGC 6"]
    assert len(excluded) == 5 and excluded[0]["row"]["Type"] == "*"


@pytest.mark.parametrize("field,value", [("V-Mag", "nan"), ("V-Mag", "brillante"), ("MajAx", "-1"), ("Name", "NGCfoo")])
def test_openngc_invalido_no_escribe_identidades(tmp_path, field, value):
    """La segunda fila errónea conserva el registro entero, sin sustituciones parciales o normalización silenciosa."""
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        with pytest.raises(ValueError):
            preparation.prepare_openngc(registry, {"NGC.csv": ngc_file(ngc(), ngc("NGC0002", **{field: value}))}, revision="A")
        assert registry.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [("RA", "10:60:00"), ("Dec", "+90:00:01"), ("RA", "-01:00:00")])
def test_coordenada_fuente_invalida_se_aparta_sin_normalizarla(tmp_path, field, value):
    """Una ficha inválida no retiene todo el catálogo ni se corrige imaginando lo que quiso medir su autor."""
    excluded = []
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        result = preparation.prepare_openngc(registry, {"NGC.csv": ngc_file(ngc(), ngc("NGC0002", **{field: value}))},
                                             revision="A", exclusions=excluded)
        assert [row[0] for row in result["rows"]] == ["NGC 224"]
        assert excluded[0]["reason"] == "invalid_source_coordinates" and excluded[0]["row"][field] == value
        assert registry.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 1


def test_openngc_identidad_estable_y_convencion_m102_declarada(tmp_path):
    """Cambiar nombre común/orden no cambia la identidad; la convención preexistente no se atribuye al campo fuente."""
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        before = preparation.prepare_openngc(registry, {"NGC.csv": ngc_file(ngc("NGC5866"))}, revision="A")
        after = preparation.prepare_openngc(registry, {"NGC.csv": ngc_file(ngc("NGC5866", **{"Common names": "Otro nombre"}))},
                                            revision="B")
    assert before["records"][0]["pass_id"] == after["records"][0]["pass_id"]
    assert after["rows"][0][0] == "M102"
    assert after["records"][0]["sources"][0]["data"]["row"]["M"] == ""
    assert "convención" in after["records"][0]["sources"][0]["data"]["messier_convention"]


def test_fallo_de_registro_revierte_lote_y_no_entrega_exclusiones(tmp_path):
    """Un error SQLite a mitad no deja IDs huérfanos ni informe de éxito parcial."""
    excluded = []
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        registry.execute("CREATE TRIGGER fallo BEFORE INSERT ON source_records WHEN NEW.source_key='NGC0002' "
                         "BEGIN SELECT RAISE(ABORT,'Fallo sintético'); END")
        with pytest.raises(sqlite3.IntegrityError):
            preparation.prepare_openngc(registry, {"NGC.csv": ngc_file(ngc("NGC0000", Type="*"), ngc("NGC0001"), ngc("NGC0002"))},
                                        revision="A", exclusions=excluded)
        assert registry.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 0 and not excluded


def test_openngc_duplicado_entre_archivos_rechazado(tmp_path):
    """No se interpreta repetir una clave literal como permiso para mezclar versiones o sobrescribir campos."""
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        with pytest.raises(ValueError, match="repetido entre archivos"):
            preparation.prepare_openngc(registry, {"NGC.csv": ngc_file(ngc()), "addendum.csv": ngc_file(ngc())}, revision="A")
        assert registry.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 0


def test_hyg_preserva_identificadores_movimiento_y_limite_inclusivo(tmp_path):
    """Magnitudes negativas y el límite aprobado son válidos; Sol y estrellas más débiles quedan fuera con evidencia."""
    excluded = []
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        result = preparation.prepare_hyg(registry, hyg_file(hyg(), hyg("2", mag="8", proper=""),
                                                           hyg("3", mag="8.01"), hyg("0", proper="Sol")),
                                         revision="synthetic-v4.0", exclusions=excluded)
    assert [row[1] for row in result["rows"]] == [-1.2, 8]
    assert result["rows"][1][0] is None
    source = result["records"][0]["sources"][0]
    assert source["data"]["proper_motion_mas_year"] == {"pmra": 0, "pmdec": -4.5}
    assert {"namespace": "hip", "designation": "HIP 12"} in result["records"][0]["aliases"]
    assert {item["reason"] for item in excluded} == {"magnitude_limit", "sun_not_star_catalog"}


def test_hyg_fuente_anonima_no_se_identifica_por_fila_o_coordenadas(tmp_path):
    """Dos estrellas sin nombre a las mismas coordenadas conservan las claves fuente y sobreviven a un reordenado."""
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        before = preparation.prepare_hyg(registry, hyg_file(hyg("1", proper=""), hyg("2", proper="")), revision="A")
        after = preparation.prepare_hyg(registry, hyg_file(hyg("2", proper=""), hyg("1", proper="")), revision="B")
    mapping = lambda result: {record["sources"][0]["key"]: record["pass_id"] for record in result["records"]}
    assert len(set(mapping(before).values())) == 2 and mapping(before) == mapping(after)


@pytest.mark.parametrize("field,value", [("id", "abc"), ("hip", "12.5"), ("ra", "25"), ("mag", "inf"), ("pmra", "nan")])
def test_hyg_invalido_conserva_registro(tmp_path, field, value):
    """Los identificadores y medidas inválidos no se convierten en valores razonables inventados."""
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        with pytest.raises(ValueError):
            preparation.prepare_hyg(registry, hyg_file(hyg("1"), hyg("2", **{field: value})), revision="A")
        assert registry.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 0


def test_hyg_gzip_acotado_no_expande_archivos_arbitrarios(tmp_path, monkeypatch):
    """El límite se comprueba también después de descomprimir antes de crear identidades."""
    data = hyg_file(*[hyg(str(index)) for index in range(20)])
    monkeypatch.setattr(preparation, "MAX_SOURCE", 1024)
    assert len(data) < preparation.MAX_SOURCE
    with identity_registry(tmp_path / "registry.sqlite") as registry, pytest.raises(ValueError, match="demasiado grande"):
        preparation.prepare_hyg(registry, data, revision="A")


def test_preparadores_a_exportacion_instalacion_y_alias_personal(tmp_path):
    """Los tres preparadores alimentan el instalador existente sin volver a la base personal ni a parsers legacy."""
    import json

    from db import catalog_editions, connection
    from db.catalog_records import describe, lookup
    from planners.catalog_packages import GROUPS, update_packages
    from planners.simbad_records import prepare_simbad
    from scripts.preparar_catalogos import export_identified
    from tests.test_simbad_records import encode, entry, snapshot

    output = tmp_path / "artifacts"
    path = tmp_path / "personal.sqlite"
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        components = prepare_simbad(registry, encode(snapshot([entry()])), revision="synthetic-A")
        components["openngc"] = preparation.prepare_openngc(registry, {"NGC.csv": ngc_file(ngc(M="31"))}, revision="synthetic-A")
        components["hyg"] = preparation.prepare_hyg(registry, hyg_file(hyg()), revision="synthetic-v4.0")
        export_identified("synthetic-A", output, components, registry)
    personal = sqlite3.connect(path)
    try:
        personal.executescript(connection.SCHEMA_PATH.read_text(encoding="utf-8"))
        personal.execute("INSERT INTO personal_catalog(object_id,catalog,notes) VALUES ('NGC 224','ngc','Mi nombre y nota')")
        personal.commit()
        manifest = json.loads((output / "catalogs-manifest.json").read_text(encoding="utf-8"))
        update_packages(path, manifest["packages"], GROUPS,
                        reader=lambda url, limit: (output / url.rsplit("/", 1)[1]).read_bytes())
        with catalog_editions.catalog_snapshot(personal) as catalog:
            obj = lookup(catalog, "NGC 224", "ngc")
            assert obj["object_id"] == "M31"
            source = describe(catalog, obj["pass_id"])["sources"][0]
            assert source["data"]["magnitude_band"] == "B"
            assert catalog.execute("SELECT COUNT(*) FROM stars").fetchone()[0] == 1
        name, note, pass_id = personal.execute("SELECT object_id,notes,pass_object_id FROM personal_catalog").fetchone()
        assert (name, note, pass_id) == ("NGC 224", "Mi nombre y nota", obj["pass_id"])
    finally:
        personal.close()
