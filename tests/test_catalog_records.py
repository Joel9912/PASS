"""Procedencia e identidades explícitas: transporte offline, continuidad, referencias personales y rechazo conservador."""

import copy
import gzip
import hashlib
import json
import sqlite3
from uuid import uuid4

import pytest

from db import catalog_editions as editions
from db import catalog_identity, catalog_records, connection
from planners import (
    catalog_packages,
    celestial_search,
    personal_catalog,
    planned_sessions,
)
from planners.catalog_records import prepare_record, validate_records


@pytest.fixture
def personal(tmp_path, monkeypatch):
    """Crea una base sintética aislada, sin utilizar datos personales o red."""
    path = tmp_path / "personal.sqlite"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(connection.SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO catalog(object_id,catalog,name,ra_hours,dec_deg) VALUES ('M31','messier','Legacy',1,2)")
    conn.execute("INSERT INTO personal_catalog(object_id,catalog,notes,ra_hours,dec_deg) VALUES ('M31','messier','Propias',3,4)")
    conn.execute("INSERT INTO planned_sessions(object_id,session_date,notes,ra_hours) VALUES ('M31','2026-10-20','Original',5)")
    conn.commit()
    monkeypatch.setattr(connection, "_connection", conn)
    monkeypatch.setattr(connection, "DB_PATH", path)
    yield conn, path
    conn.close()


def _row(designation="M31", name="Edición", ra=6):
    """Proyección compatible con el lector anterior, distinta de la identidad persistente."""
    return [designation, "messier", 31, 224, None, name, "G", 3.4, ra, 40, 190, 60, "And"]


def _record(pass_id=None, row=0, key="literal-001", aliases=None):
    """Conserva todos los campos originales de una fuente ficticia, incluidos sufijos y ausencias."""
    return {"row": row, "pass_id": pass_id or f"PASS-{uuid4()}",
            "sources": [{"source": "sintetica", "key": key, "revision": "rev1",
                         "data": {"Name": "Fuente 001 A", "Diameter": None, "Opacity": "6", "Other": "0001"},
                         "license": "Solo prueba sintética", "attribution": "Prueba"}],
            "aliases": aliases if aliases is not None else [{"namespace": "messier", "designation": "M31"}],
            "relations": []}


def _install(path, rows, records, *, legacy=False):
    """Transporte real gzip/SHA del contenido sintético, sin descargar ni publicar artefactos."""
    content = rows if legacy else {"format": 2, "rows": rows, "records": records}
    data = gzip.compress(json.dumps(content).encode())
    item = {"version": "sintetica", "date": "2026-10-20", "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "url": "sintetico", "payload_format": 1 if legacy else 2}
    catalog_packages.update_packages(path, {"openngc": item}, ["openngc"], reader=lambda *args: data)


def test_transporte_identidad_y_campos_originales_sin_alterar_sesiones(personal):
    """Activa y vincula en la misma transacción; campos observacionales originales no se sustituyen por la proyección."""
    conn, path = personal
    record = _record()
    _install(path, [_row()], [record])
    with editions.catalog_snapshot(conn) as catalog:
        details = catalog_records.describe(catalog, record["pass_id"])
    assert details["sources"] == record["sources"]
    assert details["aliases"] == record["aliases"]
    assert conn.execute("SELECT pass_object_id FROM personal_catalog").fetchone()[0] == record["pass_id"]
    assert tuple(conn.execute("SELECT pass_object_id,notes,ra_hours FROM planned_sessions").fetchone()) == (
        record["pass_id"], "Original", 5,
    )
    assert conn.execute("SELECT name FROM catalog").fetchone()[0] == "Legacy"


def test_nombre_cambia_sin_perder_vinculo_y_recuperacion_no_reasigna(personal):
    """Identidad estable no es número de fila ni nombre actual; recuperar no reescribe notas o vínculos posteriores."""
    conn, path = personal
    record = _record()
    _install(path, [_row()], [record])
    changed = copy.deepcopy(record)
    changed["sources"][0]["revision"] = "rev2"
    _install(path, [_row("NGC 224", "Actualizado", 9)], [changed])
    saved = personal_catalog.list_objects()[0]
    assert (saved["object_id"], saved["name"], saved["ra_hours"], saved["notes"]) == ("M31", "Actualizado", 9, "Propias")
    assert celestial_search.get_object("M31")["object_id"] == "NGC 224"
    conn.execute("UPDATE personal_catalog SET notes='Posterior'")
    conn.commit()
    editions.restore_previous(path)
    saved = personal_catalog.list_objects()[0]
    assert saved["name"] == "Edición" and saved["notes"] == "Posterior"
    assert saved["pass_object_id"] == record["pass_id"]


def test_altas_nuevas_vinculan_solo_catalogos_no_regiones(personal):
    """No exige otra actualización para vincular altas y deja coordenadas de sesiones como instantánea personal."""
    conn, path = personal
    record = _record(aliases=[{"namespace": "messier", "designation": "M32"}])
    _install(path, [_row("M32")], [record])
    personal_catalog.add("M32", "messier")
    session = planned_sessions.add("M32", "Mi nombre", "2026-10-21", ra_hours=11)
    personal_catalog.add_region("M32", 2, 3)
    region = planned_sessions.add("M32", "Región", "2026-10-21", target_kind="region")
    assert conn.execute("SELECT pass_object_id FROM personal_catalog WHERE object_id='M32' AND kind='catalog'").fetchone()[0] == record["pass_id"]
    assert conn.execute("SELECT pass_object_id FROM planned_sessions WHERE id=?", (session,)).fetchone()[0] == record["pass_id"]
    assert conn.execute("SELECT pass_object_id FROM planned_sessions WHERE id=?", (region,)).fetchone()[0] is None
    assert conn.execute("SELECT pass_object_id FROM personal_catalog WHERE kind='region'").fetchone()[0] is None


def test_alias_ambiguo_no_fusiona_ni_vincula_por_orden(personal):
    """Compartir designación no une identidades; tanto búsqueda como migración conservan la ambigüedad."""
    conn, path = personal
    records = [_record(row=0), _record(row=1, key="literal-002")]
    _install(path, [_row("NGC 224A"), _row("NGC 224B")], records)
    assert editions.reference_id(conn, "M31", "messier") is None
    assert celestial_search.get_object("M31") is None
    assert conn.execute("SELECT pass_object_id FROM personal_catalog").fetchone()[0] is None
    assert conn.execute("SELECT pass_object_id FROM planned_sessions").fetchone()[0] is None
    assert personal_catalog.list_objects()[0]["name"] is None
    with editions.catalog_snapshot(conn) as catalog:
        assert catalog.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 2


def test_identidad_ausente_no_caera_a_otro_objeto_con_el_mismo_nombre(personal):
    """Un vínculo estable ausente conserva referencia y coordenadas personales, no adopta otra identidad homónima."""
    _, path = personal
    original = _record()
    _install(path, [_row()], [original])
    other = _record(key="objeto-distinto")
    _install(path, [_row(name="No adoptar", ra=10)], [other])
    saved = personal_catalog.list_objects()[0]
    assert saved["pass_object_id"] == original["pass_id"]
    assert saved["name"] is None and saved["ra_hours"] == 3
    assert saved["notes"] == "Propias"


@pytest.mark.parametrize("change", ["reassign_source", "reuse_identity", "lose_records", "dangling_relation"])
def test_candidato_contradictorio_no_cambia_seleccion_versiones_o_vinculos(personal, change):
    """Los paquetes incompatibles se rechazan antes de activar, sin decidir cruces nuevos por el usuario."""
    conn, path = personal
    original = _record()
    _install(path, [_row()], [original])
    before = editions.active_id(conn)
    version = catalog_packages.installed(conn)
    altered = copy.deepcopy(original)
    if change == "reassign_source":
        altered["pass_id"] = f"PASS-{uuid4()}"
    elif change == "reuse_identity":
        altered["sources"][0]["key"] = "otra-fuente"
    elif change == "dangling_relation":
        altered["relations"] = [{"target": f"PASS-{uuid4()}", "kind": "component", "evidence": "Prueba explícita"}]
    with pytest.raises(ValueError):
        _install(path, [_row(name="No activar")], [altered], legacy=change == "lose_records")
    assert editions.active_id(conn) == before
    assert catalog_packages.installed(conn) == version
    assert conn.execute("SELECT pass_object_id FROM personal_catalog").fetchone()[0] == original["pass_id"]


def test_relaciones_no_fusionan_y_componentes_persisten_con_actualizacion_parcial(personal):
    """Una relación de componentes no convierte sus miembros en un único objeto; HYG no borra las relaciones."""
    conn, path = personal
    parent, child = _record(), _record(row=1, key="componente", aliases=[])
    parent["relations"] = [{"target": child["pass_id"], "kind": "component", "evidence": "Relación sintética revisada"}]
    _install(path, [_row(), _row("M32")], [parent, child])
    with editions.catalog_snapshot(conn) as catalog:
        before = catalog_records.describe(catalog, parent["pass_id"])
    data = gzip.compress(json.dumps([["Estrella", 1, 2, 3, None, None]]).encode())
    item = {"version": "1", "date": "2026-10-20", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "url": "sintetico"}
    catalog_packages.update_packages(path, {"hyg": item}, ["hyg"], reader=lambda *args: data)
    with editions.catalog_snapshot(conn) as catalog:
        assert catalog_records.describe(catalog, parent["pass_id"]) == before
        assert catalog.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 2


def test_fallo_vinculacion_revierte_activacion_y_todos_los_vinculos(personal):
    """Una activación incompleta no deja primeras filas vinculadas a una edición que no se llegó a seleccionar."""
    conn, path = personal
    conn.execute("CREATE TRIGGER fallo BEFORE UPDATE OF pass_object_id ON planned_sessions BEGIN SELECT RAISE(ABORT,'fallo sintetico'); END")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _install(path, [_row()], [_record()])
    assert editions.active_id(conn) is None
    assert conn.execute("SELECT pass_object_id FROM personal_catalog").fetchone()[0] is None
    assert conn.execute("SELECT count(*) FROM catalog_editions").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [
    ("row", True), ("pass_id", "M31"), ("sources", []), ("aliases", "M31"), ("relations", None),
])
def test_contrato_rechaza_metadatos_invalidos(field, value):
    """El contrato tipado no confunde booleanos, nombres o campos omitidos con procedencia válida."""
    record = _record()
    record[field] = value
    with pytest.raises((TypeError, ValueError)):
        validate_records([_row()], [record])


def test_preparador_conserva_id_literal_entre_exportaciones(tmp_path):
    """El preparador usa el registro persistente, no UUID nuevos por exportación o índices de fila."""
    source = _record()["sources"][0]
    registry_path = tmp_path / "identidades.sqlite"
    with catalog_identity.identity_registry(registry_path) as registry:
        first = prepare_record(registry, 0, source)
    with catalog_identity.identity_registry(registry_path) as registry:
        second = prepare_record(registry, 8, source)
    assert first["pass_id"] == second["pass_id"]
    assert first["row"] != second["row"]


def test_recuperacion_a_legacy_no_permite_reasignar_identidad_conocida(personal):
    """La vuelta a una edición anterior no borra la evidencia de las identidades ya usadas en el equipo."""
    conn, path = personal
    record = _record()
    _install(path, [_row()], [record])
    editions.restore_previous(path)
    before = editions.active_id(conn)
    changed = copy.deepcopy(record)
    changed["pass_id"] = f"PASS-{uuid4()}"
    with pytest.raises(ValueError, match="reasigna"):
        _install(path, [_row()], [changed])
    assert editions.active_id(conn) == before
    assert conn.execute("SELECT pass_object_id FROM personal_catalog").fetchone()[0] == record["pass_id"]


def test_historia_no_verificable_impide_reasignaciones_sin_tocar_edicion_activa(personal):
    """Un archivo antiguo perdido no autoriza a saltar la comparación de identidades y reutilizar sus IDs."""
    conn, path = personal
    record = _record()
    _install(path, [_row()], [record])
    previous = editions._record(conn, editions.active_id(conn))
    _install(path, [_row(name="Actual")], [record])
    current = editions.active_id(conn)
    (path.parent / previous["relative_path"]).unlink()
    with pytest.raises(editions.CatalogUnavailableError):
        _install(path, [_row(name="No activar")], [record])
    assert editions.active_id(conn) == current
    assert personal_catalog.list_objects()[0]["name"] == "Actual"


def test_relacion_entrante_con_destino_eliminado_rechaza_actualizacion_parcial(personal):
    """No borra ni inventa un componente para satisfacer una referencia conservada de otro paquete."""
    conn, path = personal
    target = _record()
    _install(path, [_row()], [target])
    source = _record(key="nube")
    source["relations"] = [{"target": target["pass_id"], "kind": "overlap", "evidence": "Solo relación sintética"}]
    cloud = ["LDN 1", "ldn", None, None, None, None, "DrkN", None, 2, 3, None, None, None]
    data = gzip.compress(json.dumps({"format": 2, "rows": [cloud], "records": [source]}).encode())
    item = {"version": "1", "date": "2026-10-20", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "url": "sintetico", "payload_format": 2}
    catalog_packages.update_packages(path, {"ldn": item}, ["ldn"], reader=lambda *args: data)
    current = editions.active_id(conn)
    with pytest.raises(ValueError, match="relación"):
        _install(path, [_row("M32")], [_record(key="otro")])
    assert editions.active_id(conn) == current


def test_proyeccion_legacy_homonima_hace_ambiguo_el_alias(personal):
    """Una coincidencia sin identidad no desaparece del chequeo por no pertenecer todavía al formato nuevo."""
    conn, path = personal
    conn.execute("INSERT INTO catalog(object_id,catalog,ra_hours,dec_deg) VALUES ('M31','ldn',1,2)")
    conn.commit()
    _install(path, [_row("NGC 224")], [_record()])
    assert editions.reference_id(conn, "M31") is None
    assert celestial_search.get_object("M31") is None
    assert conn.execute("SELECT pass_object_id FROM planned_sessions").fetchone()[0] is None
    assert conn.execute("SELECT pass_object_id FROM personal_catalog").fetchone()[0] is not None


def test_exportacion_e_instalacion_desde_registro_persistente_sin_red(personal, tmp_path):
    """Recorre registro→preparador→manifiesto→instalador con los tres componentes y ninguna descarga real."""
    from scripts.preparar_catalogos import export_identified

    conn, path = personal
    output = tmp_path / "adjuntos"
    with catalog_identity.identity_registry(tmp_path / "identidades.sqlite") as registry:
        obj = prepare_record(registry, 0, _record()["sources"][0], aliases=[{"namespace": "messier", "designation": "M31"}])
        star = prepare_record(registry, 0, {"source": "estrellas", "key": "0001A", "revision": "rev1", "data": {"ID": "0001A"}})
        cloud = prepare_record(registry, 0, {"source": "nubes", "key": "sin_numero-A", "revision": "rev1", "data": {"ID": None}})
        export_identified("sintetica", output, {
            "openngc": {"rows": [_row()], "records": [obj]},
            "hyg": {"rows": [[None, 1, 2, 3, None, None]], "records": [star]},
            "ldn": {"rows": [["Nube A", "ldn", None, None, None, None, "DrkN", None, 2, 3, None, None, None]], "records": [cloud]},
        }, registry)
    catalog_packages.install_bundled(path, output)
    # El componente legacy no vacío se conserva; instalación explícita consentida simulada para el resto.
    packages = catalog_packages.parse_manifest((output / "catalogs-manifest.json").read_bytes())
    catalog_packages.update_packages(path, packages, ["openngc"],
                                    reader=lambda url, limit: (output / url.rsplit("/", 1)[-1]).read_bytes())
    assert editions.reference_id(conn, "M31", "messier") == obj["pass_id"]
    with editions.catalog_snapshot(conn) as catalog:
        assert catalog_records.describe(catalog, star["pass_id"])["sources"][0]["key"] == "0001A"
        assert catalog_records.describe(catalog, cloud["pass_id"])["sources"][0]["data"]["ID"] is None


def test_preparacion_invalida_no_deja_identidad_ni_alias_a_medias(tmp_path):
    """El preparador revierte su savepoint sin confirmar ni perder la transacción de su llamante."""
    with catalog_identity.identity_registry(tmp_path / "registro.sqlite") as registry:
        source = {"source": "sintetica", "key": "nueva", "revision": "rev1", "data": {"value": float("nan")}}
        with pytest.raises(ValueError):
            prepare_record(registry, 0, source)
        assert registry.in_transaction
        assert registry.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 0


def test_exportador_no_acepta_identidades_no_registradas_ni_escribe_salida(personal, tmp_path):
    """No basta un UUID con forma válida: la fuente debe constar en el registro persistente elegido."""
    from scripts.preparar_catalogos import export_identified

    with catalog_identity.identity_registry(tmp_path / "registro.sqlite") as registry:
        output = tmp_path / "no_crear"
        content = {"rows": [_row()], "records": [_record()]}
        with pytest.raises(ValueError, match="registro persistente"):
            export_identified("sintetica", output, {group: content for group in catalog_packages.GROUPS}, registry)
        assert not output.exists()


@pytest.mark.parametrize("change", ["duplicate_row", "duplicate_id", "duplicate_source", "nonfinite_source", "invalid_relation"])
def test_metadatos_incompatibles_no_crean_edicion(personal, change):
    """La huella correcta no legitima un contrato inválido ni deja una activación parcial."""
    conn, path = personal
    first, second = _record(), _record(row=1, key="segunda")
    if change == "duplicate_row":
        second["row"] = 0
    elif change == "duplicate_id":
        second["pass_id"] = first["pass_id"]
    elif change == "duplicate_source":
        second["sources"] = first["sources"]
    elif change == "nonfinite_source":
        first["sources"][0]["data"]["valor"] = float("inf")
    else:
        first["relations"] = [{"target": "M31", "kind": "component", "evidence": "sintetica"}]
    with pytest.raises(ValueError):
        _install(path, [_row(), _row("M32")], [first, second])
    assert editions.active_id(conn) is None
    assert conn.execute("SELECT COUNT(*) FROM catalog_editions").fetchone()[0] == 0


def test_identidades_y_fuentes_no_dependen_del_orden_de_filas(personal):
    """Reordenar una exportación solo cambia la proyección; los vínculos siguen el registro de fuentes."""
    conn, path = personal
    first, second = _record(), _record(row=1, key="segunda", aliases=[])
    _install(path, [_row(), _row("M32", "Segundo")], [first, second])
    first["row"], second["row"] = 1, 0
    _install(path, [_row("M32", "Segundo"), _row(name="Primero actualizado")], [first, second])
    assert personal_catalog.list_objects()[0]["name"] == "Primero actualizado"
    assert conn.execute("SELECT pass_object_id FROM personal_catalog").fetchone()[0] == first["pass_id"]


def test_referencia_pendiente_no_muestra_datos_de_un_alias_ambiguo_directo(personal):
    """Ni siquiera una coincidencia principal tiene prioridad sobre una segunda identidad que reclama ese alias."""
    _, path = personal
    first, second = _record(), _record(row=1, key="segunda")
    _install(path, [_row(), _row("M32")], [first, second])
    saved = personal_catalog.list_objects()[0]
    assert saved["pass_object_id"] is None and saved["name"] is None
    assert saved["ra_hours"] == 3 and saved["notes"] == "Propias"
    assert celestial_search.get_object("M31") is None


def test_actualizacion_desde_edicion_esquema1_sin_metadatos(personal):
    """Una edición anterior genuina se lee sin inventar identidades y puede adoptar un paquete explícito nuevo."""
    conn, path = personal
    folder = path.parent / editions.EDITION_FOLDER
    folder.mkdir()
    old = folder / "anterior.sqlite"
    with sqlite3.connect(old) as catalog:
        catalog.executescript(editions.CATALOG_SCHEMA.read_text(encoding="utf-8").split("-- Metadatos de procedencia")[0])
        catalog.execute("INSERT INTO catalog(object_id,catalog,name,ra_hours,dec_deg) VALUES ('M31','messier','Edición vieja',2,3)")
    conn.execute("INSERT INTO catalog_editions(edition_id,schema_version,relative_path,sha256,size_bytes,versions) VALUES (?,?,?,?,?,?)",
                 ("anterior", 1, f"{editions.EDITION_FOLDER}/{old.name}", hashlib.sha256(old.read_bytes()).hexdigest(), old.stat().st_size, "{}"))
    conn.execute("INSERT INTO settings VALUES (?,?)", (editions.ACTIVE_KEY, "anterior"))
    conn.commit()
    assert personal_catalog.list_objects()[0]["name"] == "Edición vieja"
    record = _record()
    _install(path, [_row()], [record])
    assert personal_catalog.list_objects()[0]["pass_object_id"] == record["pass_id"]
    editions.restore_previous(path)
    assert editions.active_id(conn) == "anterior"
    assert conn.execute("SELECT pass_object_id FROM personal_catalog").fetchone()[0] == record["pass_id"]
    assert old.exists()


@pytest.mark.parametrize("payload_format", [True, 3, "2", None])
def test_manifiesto_no_acepta_formato_de_contenido_desconocido(payload_format):
    """Un marcador opcional explícito debe ser entero soportado, no un booleano que se convierta en uno."""
    item = {"version": "1", "date": "2026-10-20", "url": "sintetico", "sha256": "0" * 64,
            "size": 1, "payload_format": payload_format}
    with pytest.raises(ValueError, match="contenido"):
        catalog_packages.parse_manifest(json.dumps({"format": 1, "packages": {group: item for group in catalog_packages.GROUPS}}))
