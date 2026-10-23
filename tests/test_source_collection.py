"""Fuentes físicamente independientes, consulta conjunta y cruces revisados; datos sintéticos, sin migraciones personales."""

import copy
import gzip
import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from db import catalog_editions as editions
from db import connection
from db.catalog_identity import identity_registry
from db.catalog_records import describe, lookup
from planners import celestial_search, data_packages, sky_loader
from planners.catalog_records import prepare_record
from scripts.preparar_catalogos import export_source_collection


@pytest.fixture
def collection(tmp_path, monkeypatch):
    """Tres fuentes ficticias; un cruce revisado conserva medidas distintas sin fabricar promedios."""
    personal = sqlite3.connect(tmp_path / "personal.sqlite")
    personal.row_factory = sqlite3.Row
    personal.executescript(connection.SCHEMA_PATH.read_text(encoding="utf-8"))
    monkeypatch.setattr(connection, "_connection", personal)
    monkeypatch.setattr(connection, "DB_PATH", tmp_path / "personal.sqlite")
    sources = {}
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        shared = None
        for priority, name, kind, magnitude, ra in ((0, "OpenNGC", "openngc", 3.5, 1.0),
                                                  (1, "HYG", "hyg", 1.5, 2.0),
                                                  (2, "SIMBAD-ident", "openngc", None, 1.1)):
            source = {"source": name, "key": "original-1", "revision": "synthetic-A", "license": "Prueba propia",
                      "data": {"original_ra": ra, "original_magnitude": magnitude}}
            aliases = [{"namespace": "messier", "designation": "M31"}] if kind != "hyg" else []
            if name == "SIMBAD-ident":
                aliases.append({"namespace": "ngc", "designation": "NGC 224"})
            record = prepare_record(registry, 0, source, aliases=aliases, same_as=shared if name == "SIMBAD-ident" else None)
            if name == "OpenNGC":
                shared = record["pass_id"]
            row = (["Estrella ficticia", magnitude, ra, 20, None, None] if kind == "hyg" else
                   ["M31", "messier", 31, 224, None, "Etiqueta de fuente", "G", magnitude, ra, 30, 10, None, "And"])
            metadata = {"source_id": name, "priority": priority, "version": "A", "date": "2026-10-22",
                        "license": "Prueba propia", "attribution": "Síntesis PASS", "source": "Síntesis local",
                        "revision": "synthetic-A", "requires": {}}
            sources[f"source{priority}"] = {"metadata": metadata, "groups": {kind: {"rows": [row], "records": [record]}}}
        crosses = [{"pass_id": shared, "members": [{"source": name, "key": "original-1"}
                                                   for name in ("OpenNGC", "SIMBAD-ident")],
                    "evidence": "Cruce sintético explícito; no semejanza de posición."}]
        export_source_collection("private-A", tmp_path / "artifacts", sources, registry, crosses=crosses)
    manifest = json.loads((tmp_path / "artifacts/data-manifest.json").read_bytes())
    calls = []

    def reader(url, limit):
        """Solo admite los adjuntos generados por esta prueba, nunca accede a Internet."""
        name = url.rsplit("/", 1)[1]
        calls.append(name)
        data = (tmp_path / "artifacts" / name).read_bytes()
        assert len(data) <= limit
        return data

    yield personal, tmp_path / "personal.sqlite", manifest, reader, calls, sources
    personal.close()


def test_instalacion_separa_archivos_y_busqueda_no_duplica_ni_mezcla_medidas(collection):
    """La base persistida de cada fuente mantiene su medida; el índice solo contiene rutas y huellas."""
    personal, path, manifest, reader, _calls, _sources = collection
    data_packages.install(path, manifest, reader=reader)
    record = editions._record(personal, editions.active_id(personal))
    assert record["schema_version"] == 3
    with closing(sqlite3.connect(path.parent / record["relative_path"])) as index:
        assert index.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("source_components",)]
        files = index.execute("SELECT relative_path FROM source_components").fetchall()
    assert len(files) == 3
    found = {}
    for (filename,) in files:
        with closing(sqlite3.connect(path.parent / filename)) as source:
            names = source.execute("SELECT DISTINCT source FROM source_records").fetchall()
            assert len(names) == 1
            if names[0][0] != "HYG":
                found[names[0][0]] = source.execute("SELECT ra_hours,magnitude FROM catalog").fetchone()
    assert found == {"OpenNGC": (1, 3.5), "SIMBAD-ident": (1.1, None)}
    rows = celestial_search.search(celestial_search.SearchFilters(text="NGC 224"))
    assert len(rows) == 1 and rows[0]["ra_hours"] == 1 and rows[0]["magnitude"] == 3.5
    with editions.catalog_snapshot(personal) as snapshot:
        obj = lookup(snapshot, "NGC 224", "ngc")
        assert obj["object_id"] == "M31"
        assert len(describe(snapshot, obj["pass_id"])["sources"]) == 2
        with pytest.raises(sqlite3.OperationalError):
            snapshot.execute("DELETE FROM catalog")
    stars, objects = sky_loader.load_sky()
    assert list(objects["ids"]) == ["M31"] and len(stars["ra"]) == 1


def test_actualizacion_solo_recursos_reutiliza_fuentes_y_recupera(collection):
    """Una edición nueva no descarga fuentes idénticas ni permite que una lectura abierta cambie de selección."""
    personal, path, manifest, reader, calls, _sources = collection
    data_packages.install(path, manifest, reader=reader)
    before = editions.active_id(personal)
    manifest = copy.deepcopy(manifest)
    manifest["edition"] = "private-B"
    calls.clear()
    with editions.catalog_snapshot(personal) as earlier:
        data_packages.install(path, manifest, reader=reader)
        assert earlier.execute("SELECT ra_hours FROM catalog").fetchone()[0] == 1
    assert editions.active_id(personal) != before and not calls
    editions.restore_previous(path)
    assert editions.active_id(personal) == before and editions.status(personal)["available"]


@pytest.mark.parametrize("damage", ["missing", "corrupt", "escape_path"])
def test_fuente_invalida_impide_lectura_sin_fallback(collection, damage):
    """La pérdida de un componente no convierte resultados de otra edición en una respuesta válida."""
    personal, path, manifest, reader, _calls, _sources = collection
    data_packages.install(path, manifest, reader=reader)
    current = editions.active_id(personal)
    index_path = path.parent / editions._record(personal, current)["relative_path"]
    with closing(sqlite3.connect(index_path)) as index:
        filename = index.execute("SELECT relative_path FROM source_components LIMIT 1").fetchone()[0]
    file = path.parent / filename
    if damage == "missing":
        file.unlink()
    elif damage == "corrupt":
        with file.open("ab") as stream:
            stream.write(b"alterado")
    else:
        with closing(sqlite3.connect(index_path)) as index, index:
            index.execute("UPDATE source_components SET relative_path='../ajena.sqlite' WHERE relative_path=?", (filename,))
        personal.execute("UPDATE catalog_editions SET sha256=?,size_bytes=? WHERE edition_id=?",
                         (hashlib.sha256(index_path.read_bytes()).hexdigest(), index_path.stat().st_size, current))
        personal.commit()
    assert not editions.status(personal)["available"]
    assert celestial_search.search(celestial_search.SearchFilters()) == []
    assert editions.active_id(personal) == current


@pytest.mark.parametrize("damage", ["missing_cross", "incomplete_cross", "duplicate_source", "duplicate_priority"])
def test_cruces_y_fuentes_ambiguas_no_activan(collection, damage):
    """Ni una identidad coincidente ni un orden arbitrario autorizan fundir aportaciones de dos fuentes."""
    personal, path, manifest, reader, _calls, _sources = collection
    if damage == "missing_cross":
        manifest["cross_identifications"] = []
    elif damage == "incomplete_cross":
        manifest["cross_identifications"][0]["members"].pop()
    elif damage == "duplicate_source":
        manifest["packages"]["source2"]["source_id"] = "OpenNGC"
    else:
        manifest["packages"]["source2"]["priority"] = 0
    with pytest.raises(ValueError):
        data_packages.install(path, manifest, reader=reader)
    assert editions.active_id(personal) is None


def test_exportador_no_admite_mezclar_procedencias_en_una_ficha(collection, tmp_path):
    """El paquete experimental combinado antiguo no se transforma atribuyendo todos sus campos a una sola fuente."""
    _personal, _path, _manifest, _reader, _calls, sources = collection
    record = sources["source0"]["groups"]["openngc"]["records"][0]
    record["sources"].append({"source": "SIMBAD-ident", "key": "otra", "revision": "A", "data": {}})
    with identity_registry(tmp_path / "registry.sqlite") as registry, pytest.raises(ValueError, match="mezcla"):
        export_source_collection("invalid", tmp_path / "invalid-output", sources, registry)
    assert not (tmp_path / "invalid-output").exists()


def test_configuracion_muestra_fuentes_de_edicion_y_avisa_licencias(qt_app, collection):
    """La UI reconoce formato 3 y muestra los componentes instalados sin presentar grupos antiguos como fuentes."""
    from ui.config_tab.catalogs_page import CatalogsPage

    _personal, path, manifest, reader, _calls, _sources = collection
    data_packages.install(path, manifest, reader=reader)
    page = CatalogsPage()
    try:
        assert page._table.rowCount() == 3
        assert [page._table.item(index, 0).text() for index in range(3)] == ["SOURCE0", "SOURCE1", "SOURCE2"]
        page._finished(manifest, "")
        assert page._global_manifest == manifest
        assert "Prueba propia" in data_packages.notices(connection.get_connection())
    finally:
        page.deleteLater()


@pytest.mark.parametrize("day", ["1950-01-01", "2026-10-22", "2100-12-31"])
def test_cambio_fuentes_no_cambia_curva_ni_fechas(collection, day):
    """El catálogo suministra coordenadas reales de su ficha; reorganizar archivos no inventa un modelo temporal nuevo."""
    from planners.transit import night_curve

    _personal, path, manifest, reader, _calls, _sources = collection
    baseline = night_curve(1, 30, 40, -3, day)
    data_packages.install(path, manifest, reader=reader)
    obj = celestial_search.get_object("M31")
    actual = night_curve(obj["ra_hours"], obj["dec_deg"], 40, -3, day)
    assert actual.times_iso == baseline.times_iso
    assert actual.altitudes == pytest.approx(baseline.altitudes)
    assert actual.sun_altitudes == pytest.approx(baseline.sun_altitudes)
    assert actual.moon_separations == pytest.approx(baseline.moon_separations)


@pytest.mark.parametrize("coordinate,value", [(8, 25), (9, 91)])
def test_fuente_con_coordenadas_invalidas_no_se_instala(collection, coordinate, value):
    """Incluso con tamaño/huella nuevos correctos se rechazan medidas inválidas, sin inventar una posición alternativa."""
    personal, path, manifest, reader, _calls, _sources = collection
    name = manifest["packages"]["source0"]["url"].rsplit("/", 1)[1]
    artifact = path.parent / "artifacts" / name
    content = json.loads(gzip.decompress(artifact.read_bytes()))
    content["groups"]["openngc"]["rows"][0][coordinate] = value
    data = gzip.compress(json.dumps(content).encode())
    artifact.write_bytes(data)
    manifest["packages"]["source0"].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    with pytest.raises(ValueError, match="Coordenada"):
        data_packages.install(path, manifest, reader=reader)
    assert editions.active_id(personal) is None


def test_mismo_alias_con_identidades_distintas_no_se_funde_por_parecido(collection):
    """Un alias ambiguo devuelve candidatos distintos; lookup/carta no escogen uno por orden de fuente."""
    from uuid import uuid4

    personal, path, manifest, reader, _calls, _sources = collection
    name = manifest["packages"]["source2"]["url"].rsplit("/", 1)[1]
    artifact = path.parent / "artifacts" / name
    content = json.loads(gzip.decompress(artifact.read_bytes()))
    content["groups"]["openngc"]["records"][0]["pass_id"] = f"PASS-{uuid4()}"
    data = gzip.compress(json.dumps(content).encode())
    artifact.write_bytes(data)
    manifest["packages"]["source2"].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    manifest["cross_identifications"] = []
    data_packages.install(path, manifest, reader=reader)
    rows = celestial_search.search(celestial_search.SearchFilters(text="M31"))
    assert len(rows) == 2 and {row["ra_hours"] for row in rows} == {1, 1.1}
    with editions.catalog_snapshot(personal) as snapshot:
        assert lookup(snapshot, "M31", "messier") is None
    sky = sky_loader.load_objects()
    assert sky_loader.target_index(sky, "M31", "messier") is None


def test_fallo_al_activar_conserva_seleccion_y_no_escribe_equipo(collection):
    """Permitir reinicios alpha no autoriza que un fallo transaccional borre datos o active un índice incompleto."""
    personal, path, manifest, reader, _calls, _sources = collection
    personal.execute("CREATE TRIGGER impedir BEFORE INSERT ON settings WHEN NEW.key='catalog_active_edition' "
                     "BEGIN SELECT RAISE(ABORT,'Fallo sintético'); END")
    personal.commit()
    with pytest.raises(sqlite3.IntegrityError):
        data_packages.install(path, manifest, reader=reader)
    assert editions.active_id(personal) is None
    assert personal.execute("SELECT COUNT(*) FROM catalog_editions").fetchone()[0] == 0


def test_actualizacion_no_reasigna_clave_conocida_a_otro_objeto(collection):
    """Renunciar a migraciones alpha no permite que una actualización ordinaria cambie la identidad de una fuente."""
    from uuid import uuid4

    personal, path, manifest, reader, _calls, _sources = collection
    data_packages.install(path, manifest, reader=reader)
    previous = editions.active_id(personal)
    name = manifest["packages"]["source2"]["url"].rsplit("/", 1)[1]
    artifact = path.parent / "artifacts" / name
    content = json.loads(gzip.decompress(artifact.read_bytes()))
    content["groups"]["openngc"]["records"][0]["pass_id"] = f"PASS-{uuid4()}"
    data = gzip.compress(json.dumps(content).encode())
    artifact.write_bytes(data)
    manifest["packages"]["source2"].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    manifest["cross_identifications"] = []
    manifest["edition"] = "private-B"
    with pytest.raises(ValueError, match="reasigna"):
        data_packages.install(path, manifest, reader=reader)
    assert editions.active_id(personal) == previous


def test_recursos_y_modelo_permanecen_ligados_a_la_coleccion(collection):
    """El formato por fuentes no desvincula el kernel ni lo sustituye por builtin al cambiar solo la edición."""
    from planners.ephemeris import selected_model
    from tests.spk_factory import synthetic_spk

    personal, path, manifest, reader, calls, _sources = collection
    data = synthetic_spk()
    (path.parent / "artifacts/kernel.bsp").write_bytes(data)
    manifest["resources"]["ephemeris"] = {"version": "synthetic-A", "format": "spk-planets-v1", "optional": False,
                                          "license": "Síntesis propia", "attribution": "Prueba PASS", "source": "Síntesis",
                                          "revision": "synthetic-A", "requires": {}, "size": len(data),
                                          "sha256": hashlib.sha256(data).hexdigest(),
                                          "url": "https://github.com/Joel9912/PASS/releases/download/private/kernel.bsp"}
    data_packages.install(path, manifest, reader=reader)
    original = selected_model()
    assert original.path.is_file() and original.label == "synthetic-A"
    before = editions.active_id(personal)
    manifest["edition"] = "private-B"
    calls.clear()
    data_packages.install(path, manifest, reader=reader)
    assert not calls and selected_model().path == original.path
    editions.restore_previous(path)
    assert editions.active_id(personal) == before and selected_model() == original


@pytest.mark.parametrize("field", ["revision", "license"])
def test_metadatos_no_reetiquetan_bytes_de_fuente_ya_instalada(collection, field):
    """Reutilizar un SHA no permite atribuir al archivo otra revisión o licencia que su procedencia no declara."""
    personal, path, manifest, reader, _calls, _sources = collection
    data_packages.install(path, manifest, reader=reader)
    before = editions.active_id(personal)
    manifest["edition"] = "private-B"
    manifest["packages"]["source0"][field] = "Otra etiqueta no acreditada"
    with pytest.raises(ValueError, match="Fuente mezclada"):
        data_packages.install(path, manifest, reader=reader)
    assert editions.active_id(personal) == before


def test_paquete_incluido_instala_fuentes_sin_red_y_no_reinicia_por_rutina(collection):
    """El arranque incluido admite la colección y un segundo intento no borra ni vuelve a importar datos existentes."""
    from planners.catalog_packages import install_bundled

    personal, path, _manifest, _reader, _calls, _sources = collection
    install_bundled(path, path.parent / "artifacts")
    before = editions.active_id(personal)
    assert before is not None and editions._record(personal, before)["schema_version"] == 3
    personal.execute("INSERT INTO personal_catalog(object_id,catalog,notes) VALUES ('M31','messier','Dato experimental')")
    personal.commit()
    install_bundled(path, path.parent / "artifacts")
    assert editions.active_id(personal) == before
    assert personal.execute("SELECT notes FROM personal_catalog").fetchone()[0] == "Dato experimental"


def test_reintento_tras_fallo_no_duplica_archivos_de_fuentes_identicas(collection):
    """Los candidatos de índice se conservan, pero reintentar no multiplica las mismas fuentes completas en disco."""
    personal, path, manifest, reader, _calls, _sources = collection
    personal.execute("CREATE TRIGGER impedir BEFORE INSERT ON settings WHEN NEW.key='catalog_active_edition' "
                     "BEGIN SELECT RAISE(ABORT,'Fallo sintético'); END")
    personal.commit()
    for attempt in range(2):
        with pytest.raises(sqlite3.IntegrityError):
            data_packages.install(path, manifest, reader=reader)
        files = list((path.parent / "catalog-sources").glob("*.sqlite"))
        assert len(files) == len(manifest["packages"]), attempt
    assert editions.active_id(personal) is None


def test_coleccion_no_se_degrada_a_base_mezclada_ni_descarga_antes_de_rechazar(collection):
    """Un manifiesto antiguo no permite reconstruir una base conjunta ni iniciar transferencias inútiles."""
    from planners.catalog_packages import update_packages

    personal, path, manifest, reader, calls, _sources = collection
    data_packages.install(path, manifest, reader=reader)
    before = editions.active_id(personal)
    old = {"format": 2, "edition": "old", "reader": {"min": 1, "max": 1}, "resources": {},
           "packages": {group: {**manifest["packages"]["source0"], "payload_format": 2}
                        for group in ("openngc", "hyg", "ldn")}}
    calls.clear()
    with pytest.raises(ValueError, match="colección"):
        data_packages.install(path, old, reader=reader)
    data_packages.install(path, old, reader=reader, expected_empty=True)
    with pytest.raises(ValueError, match="colección"):
        update_packages(path, old["packages"], ["openngc"], reader=reader)
    update_packages(path, old["packages"], ["openngc"], reader=reader, only_missing=True)
    assert not calls and editions.active_id(personal) == before
