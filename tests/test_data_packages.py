"""Edición global sintética: catálogo/archivos coherentes, opciones, diferencias y recuperación conservadora."""

import copy
import gzip
import hashlib
import json
import sqlite3
from uuid import uuid4

import pytest

from db import catalog_editions as editions
from db import connection, data_resources
from planners import catalog_packages, data_packages
from tests.spk_factory import synthetic_spk


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """Proporciona exclusivamente adjuntos ficticios y una base temporal; el lector nunca accede a la red."""
    path = tmp_path / "personal.sqlite"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(connection.SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO personal_catalog(object_id,catalog,notes) VALUES ('M31','messier','Nota original')")
    conn.execute("INSERT INTO planned_sessions(object_id,session_date,notes) VALUES ('M31','2026-10-20','Sesión original')")
    conn.commit()
    monkeypatch.setattr(connection, "_connection", conn)
    monkeypatch.setattr(connection, "DB_PATH", path)
    blobs = {}
    packages = {}
    rows = {"openngc": [["M31", "messier", 31, 224, None, "Objeto sintético", "G", 3, 4, 40, 12, 8, "And"]],
            "hyg": [["Estrella sintética", 2, 3, 4, None, None]],
            "ldn": [["LDN 1", "ldn", None, None, None, None, "DrkN", None, 2, 3, None, None, None]]}
    for group, projected in rows.items():
        record = {"row": 0, "pass_id": f"PASS-{uuid4()}",
                  "sources": [{"source": group, "key": "literal-A", "revision": "sintetica", "data": {"ID": "A"}}],
                  "aliases": [], "relations": []}
        data = gzip.compress(json.dumps({"format": 2, "rows": projected, "records": [record]}).encode())
        packages[group] = _item(blobs, f"{group}.gz", data, payload_format=2, date="2026-10-20")
    resources = {"credits": _item(blobs, "credits.txt", b"Creditos ficticios para prueba", format="utf8-v1", optional=False),
                 "sample": _item(blobs, "sample.json", b'{"synthetic":true}', format="json-v1", optional=True)}
    manifest = {"format": 2, "edition": "PASS.synthetic.A", "reader": {"min": 1, "max": 1},
                "packages": packages, "resources": resources}
    calls = []

    def reader(url, limit):
        """Adjuntos exactos, con registro para probar que no se descargan componentes idénticos/opcionales."""
        calls.append(url)
        return blobs[url]

    yield conn, path, manifest, blobs, calls, reader
    conn.close()


def _item(blobs, filename, data, **extra):
    """Metadatos ficticios expresos; no afirman licencias de ninguna fuente real."""
    url = f"https://github.com/Joel9912/PASS/releases/download/sintetica/{filename}"
    blobs[url] = data
    return {"version": "A", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "url": url,
            "source": "Fuente ficticia", "revision": "sintetica", "license": "Solo muestra inventada",
            "attribution": "Prueba sintética", "requires": {}, **extra}


def _install(bundle, **kwargs):
    """Instala mediante el contrato real, sin sustituir el instalador ni el lector de SQLite."""
    _conn, path, manifest, _blobs, _calls, reader = bundle
    data_packages.install(path, manifest, reader=reader, **kwargs)


def test_edicion_global_vincula_catalogos_archivos_y_datos_personales(bundle):
    """Un único puntero selecciona todos los recursos y el catálogo, sin clonar equipo o sesiones antiguos."""
    conn, _path, manifest, _blobs, calls, _reader = bundle
    _install(bundle)
    with editions.data_snapshot(conn) as (catalog, resources, binding):
        assert catalog.execute("SELECT name FROM catalog WHERE object_id='M31'").fetchone()[0] == "Objeto sintético"
        assert resources["credits"].read_bytes() == b"Creditos ficticios para prueba"
        assert binding["manifest"] == manifest
        assert binding["selected"] == ["credits"]
    assert manifest["resources"]["sample"]["url"] not in calls
    assert len(calls) == 4
    assert conn.execute("SELECT notes FROM personal_catalog").fetchone()[0] == "Nota original"
    assert conn.execute("SELECT pass_object_id FROM personal_catalog").fetchone()[0] is not None
    assert data_packages.describe(conn)["absent_optional"] == ["sample"]


def test_actualizacion_solo_recurso_reutiliza_catalogos_y_recupera_conjunto(bundle):
    """Una edición de recursos no vuelve a descargar catálogos; recuperar cambia ambos sin perder notas posteriores."""
    conn, path, manifest, blobs, calls, reader = bundle
    _install(bundle)
    previous = editions.active_id(conn)
    manifest["edition"] = "PASS.synthetic.B"
    manifest["resources"]["credits"] = _item(blobs, "credits-B.txt", b"Creditos B", format="utf8-v1", optional=False)
    calls.clear()
    data_packages.install(path, manifest, reader=reader)
    assert calls == [manifest["resources"]["credits"]["url"]]
    assert editions.active_id(conn) != previous
    conn.execute("UPDATE personal_catalog SET notes='Posterior'")
    conn.execute("INSERT INTO planned_sessions(object_id,session_date) VALUES ('M32','2026-10-21')")
    conn.commit()
    editions.restore_previous(path)
    with editions.data_snapshot(conn) as (_catalog, resources, binding):
        assert binding["manifest"]["edition"] == "PASS.synthetic.A"
        assert resources["credits"].read_bytes() == b"Creditos ficticios para prueba"
    assert conn.execute("SELECT notes FROM personal_catalog").fetchone()[0] == "Posterior"
    assert conn.execute("SELECT COUNT(*) FROM planned_sessions").fetchone()[0] == 2


def test_reinstalar_no_descarga_ni_crea_otra_edicion(bundle):
    """Coincidencias verificadas no equivalen a trabajo pendiente ni llenan el historial con duplicados."""
    conn, _path, _manifest, _blobs, calls, _reader = bundle
    _install(bundle)
    previous = editions.active_id(conn)
    calls.clear()
    _install(bundle)
    assert not calls and editions.active_id(conn) == previous


def test_kernel_global_actualiza_y_recupera_sin_retroceder_notas(bundle):
    """El SPK sigue la selección global y su recuperación; notas posteriores permanecen en la base personal."""
    conn, path, manifest, blobs, calls, reader = bundle
    original = synthetic_spk()
    manifest["resources"]["ephemeris"] = _item(blobs, "kernel-A.bsp", original, format="spk-planets-v1", optional=False)
    _install(bundle)
    previous = editions.active_id(conn)
    manifest["edition"] = "PASS.synthetic.kernel-B"
    manifest["resources"]["ephemeris"] = _item(
        blobs, "kernel-B.bsp", synthetic_spk(value=2000), format="spk-planets-v1", optional=False,
    )
    calls.clear()
    data_packages.install(path, manifest, reader=reader)
    assert calls == [manifest["resources"]["ephemeris"]["url"]]
    assert editions.active_id(conn) != previous
    conn.execute("UPDATE personal_catalog SET notes='Trabajo posterior al kernel'")
    conn.commit()
    editions.restore_previous(path)
    with editions.data_snapshot(conn) as (_catalog, resources, _binding):
        assert resources["ephemeris"].read_bytes() == original
    assert conn.execute("SELECT notes FROM personal_catalog").fetchone()[0] == "Trabajo posterior al kernel"


def test_kernel_con_huella_correcta_pero_sin_luna_no_activa(bundle):
    """Un binario bien transferido pero científicamente incompleto conserva la selección anterior."""
    conn, path, manifest, blobs, _calls, reader = bundle
    _install(bundle)
    before = editions.active_id(conn)
    manifest["edition"] = "PASS.synthetic.incomplete-kernel"
    manifest["resources"]["ephemeris"] = _item(
        blobs, "kernel-invalid.bsp", synthetic_spk(missing=[(3, 301)]), format="spk-planets-v1", optional=False,
    )
    with pytest.raises(ValueError, match="cadenas completas"):
        data_packages.install(path, manifest, reader=reader)
    assert editions.active_id(conn) == before


def test_kernel_activo_alterado_no_declara_disponible_la_edicion(bundle):
    """La revalidación al leer también incluye el recurso científico y no cae al catálogo legacy."""
    conn, path, manifest, blobs, _calls, _reader = bundle
    data = synthetic_spk()
    manifest["resources"]["ephemeris"] = _item(blobs, "kernel.bsp", data, format="spk-planets-v1", optional=False)
    _install(bundle)
    selected = editions.active_id(conn)
    resource = data_resources.resource_path(path.parent, manifest["resources"]["ephemeris"]["sha256"])
    resource.write_bytes(data[:-1] + b"X")
    assert not editions.status(conn)["available"]
    assert editions.active_id(conn) == selected
    assert editions.read_rows(conn, "SELECT * FROM catalog") == []


def test_opcional_se_instala_solo_con_seleccion_y_se_conserva_al_actualizar(bundle):
    """Un opcional ausente es un estado legítimo; una opción instalada no se pierde al cambiar de edición."""
    conn, path, manifest, _blobs, calls, reader = bundle
    _install(bundle, optional=["sample"])
    assert data_packages.describe(conn)["absent_optional"] == []
    assert manifest["resources"]["sample"]["url"] in calls
    manifest["edition"] = "PASS.synthetic.B"
    calls.clear()
    data_packages.install(path, manifest, reader=reader)
    assert not calls
    with editions.data_snapshot(conn) as (_catalog, resources, _binding):
        assert set(resources) == {"credits", "sample"}


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_recurso_seleccionado_roto_no_mezcla_legacy_y_recupera_edicion_anterior(bundle, damage):
    """La SQLite válida no basta para declarar disponible el conjunto si pierde un recurso seleccionado."""
    conn, path, manifest, _blobs, _calls, _reader = bundle
    _install(bundle)
    selected = editions.active_id(conn)
    resource = data_resources.resource_path(path.parent, manifest["resources"]["credits"]["sha256"])
    if damage == "missing":
        resource.unlink()
    else:
        resource.write_bytes(b"archivo alterado")
    assert not editions.status(conn)["available"]
    assert editions.read_rows(conn, "SELECT * FROM catalog") == []
    assert editions.active_id(conn) == selected
    editions.restore_previous(path)
    assert editions.status(conn)["available"]
    assert conn.execute("SELECT notes FROM personal_catalog").fetchone()[0] == "Nota original"


def test_fallo_recurso_deja_edicion_y_versiones_anteriores(bundle):
    """Una tanda parcialmente preparada no confirma versiones ni adopta recursos aunque algunos bytes sean válidos."""
    conn, path, manifest, blobs, _calls, reader = bundle
    _install(bundle)
    before = editions.active_id(conn)
    old_versions = catalog_packages.installed(conn)
    manifest["edition"] = "PASS.synthetic.B"
    manifest["resources"]["credits"] = _item(blobs, "broken.txt", b"Esperado", format="utf8-v1", optional=False)
    blobs[manifest["resources"]["credits"]["url"]] = b"No coincide"
    with pytest.raises(ValueError):
        data_packages.install(path, manifest, reader=reader)
    assert editions.active_id(conn) == before and catalog_packages.installed(conn) == old_versions


def test_fallo_sqlite_no_activa_recursos_preparados_al_reabrir(bundle):
    """Archivos preparados no son autoridad: sin confirmación SQLite no existe edición activada."""
    conn, path, _manifest, _blobs, _calls, _reader = bundle
    conn.execute("CREATE TRIGGER fallo BEFORE INSERT ON settings WHEN NEW.key='catalog_active_edition' "
                 "BEGIN SELECT RAISE(ABORT,'fallo sintetico'); END")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _install(bundle)
    assert editions.active_id(conn) is None
    assert list((path.parent / data_resources.RESOURCE_FOLDER).glob("*.blob"))
    with sqlite3.connect(path) as reopened:
        assert editions.active_id(reopened) is None


@pytest.mark.parametrize("case", ["reader", "version", "cycle", "missing", "required_optional", "format", "license", "path"])
def test_manifiesto_incompatible_rechazado_antes_de_red_o_escrituras(bundle, case):
    """Compatibilidad y dependencias fallan antes de preparar ni descargar un solo componente."""
    conn, path, manifest, _blobs, calls, reader = bundle
    bad = copy.deepcopy(manifest)
    if case == "reader":
        bad["reader"]["min"] = 2
    elif case == "version":
        bad["resources"]["credits"]["requires"] = {"openngc": "inexistente"}
    elif case == "cycle":
        bad["packages"]["openngc"]["requires"] = {"openngc": "A"}
    elif case == "missing":
        bad["resources"]["credits"]["requires"] = {"no_existe": "A"}
    elif case == "required_optional":
        bad["resources"]["credits"]["requires"] = {"sample": "A"}
    elif case == "format":
        bad["resources"]["credits"]["format"] = "kernel-desconocido"
    elif case == "path":
        bad["resources"]["../escape"] = bad["resources"].pop("credits")
    else:
        bad["resources"]["credits"]["license"] = ""
    with pytest.raises(ValueError):
        data_packages.install(path, bad, reader=reader)
    assert not calls and editions.active_id(conn) is None
    assert not (path.parent / data_resources.RESOURCE_FOLDER).exists()


def test_lectura_global_conserva_catalogo_y_archivos_anteriores_durante_activacion(bundle):
    """Una lectura iniciada mantiene su conjunto aunque se seleccione otra edición en otra conexión."""
    conn, path, manifest, blobs, _calls, reader = bundle
    _install(bundle)
    with editions.data_snapshot(conn) as (catalog, resources, binding):
        manifest["edition"] = "PASS.synthetic.B"
        manifest["resources"]["credits"] = _item(blobs, "B.txt", b"B", format="utf8-v1", optional=False)
        data_packages.install(path, manifest, reader=reader)
        assert resources["credits"].read_bytes() == b"Creditos ficticios para prueba"
        assert binding["manifest"]["edition"] == "PASS.synthetic.A"
        assert catalog.execute("SELECT COUNT(*) FROM stars").fetchone()[0] == 1


def test_edicion_global_no_se_degrada_con_actualizacion_legacy(bundle):
    """La API antigua no puede dejar una SQLite nueva con archivos de otra edición o desvincularlos silenciosamente."""
    conn, path, manifest, _blobs, _calls, reader = bundle
    _install(bundle)
    before = editions.active_id(conn)
    with pytest.raises(ValueError, match="global activa"):
        catalog_packages.update_packages(path, manifest["packages"], ["openngc"], reader=reader)
    assert editions.active_id(conn) == before


def test_inicializacion_incluida_no_sustituye_datos_legacy_ni_hace_red(bundle, tmp_path):
    """La distribución global no sustituye una base existente al arrancar sin una elección de actualización."""
    conn, path, manifest, _blobs, calls, _reader = bundle
    conn.execute("INSERT INTO stars(name,magnitude,ra_hours,dec_deg) VALUES ('Legacy',1,2,3)")
    conn.commit()
    folder = tmp_path / "incluidos"
    folder.mkdir()
    (folder / "data-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    catalog_packages.install_bundled(path, folder)
    assert editions.active_id(conn) is None and not calls
    assert conn.execute("SELECT name FROM stars").fetchone()[0] == "Legacy"


def test_ui_global_exige_consentimiento_y_actualiza_recursos_aunque_catalogos_coincidan(qt_app, bundle, monkeypatch):
    """Los recursos distintos habilitan Actualizar sin fingir que un SHA de catálogo prueba toda la edición."""
    from ui.config_tab.catalogs_page import CatalogsPage, QMessageBox

    conn, _path, manifest, _blobs, _calls, _reader = bundle
    _install(bundle)
    page = CatalogsPage()
    try:
        new = copy.deepcopy(manifest)
        new["edition"] = "PASS.synthetic.B"
        page._finished(new, "")
        assert page._global_manifest == new and page._update.isEnabled()
        assert "PASS.synthetic.A" in page._edition_label.text()
        assert "sample" in page._edition_label.text()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
        monkeypatch.setattr(page, "_submit", lambda *args: pytest.fail("No debe actualizar sin consentimiento"))
        page.start_update()
        assert data_packages.describe(conn)["edition"] == "PASS.synthetic.A"
        operations = []
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(page, "_submit", lambda *args: operations.append(args))
        page.start_update()
        assert len(operations) == 1 and operations[0][0] is data_packages.install
    finally:
        page.deleteLater()


def test_exportacion_instalacion_offline_y_reinicio_sin_descargas(bundle, tmp_path, monkeypatch):
    """Recorre preparador→distribución incluida→activación→reinicio con adjuntos locales sintéticos."""
    from scripts.preparar_catalogos import export_data_manifest

    conn, path, manifest, blobs, calls, _reader = bundle
    folder = tmp_path / "incluidos"
    folder.mkdir()
    for url, content in blobs.items():
        (folder / url.rsplit("/", 1)[-1]).write_bytes(content)
    export_data_manifest(folder / "data-manifest.json", manifest["edition"], manifest["packages"], manifest["resources"])
    monkeypatch.setattr(catalog_packages, "_read", lambda *args: pytest.fail("La instalación incluida no debe hacer red"))
    catalog_packages.install_bundled(path, folder)
    selected = editions.active_id(conn)
    assert selected is not None and not calls
    with sqlite3.connect(path) as reopened, editions.data_snapshot(reopened) as (_catalog, resources, binding):
        assert binding["manifest"]["edition"] == manifest["edition"]
        assert set(resources) == {"credits"}
    catalog_packages.install_bundled(path, folder)
    assert editions.active_id(conn) == selected
    with pytest.raises(FileExistsError):
        export_data_manifest(folder / "data-manifest.json", manifest["edition"], manifest["packages"], manifest["resources"])


def test_cambio_de_edicion_durante_preparacion_no_activa_sobre_la_nueva(bundle):
    """Una segunda operación gana antes de la preparación final; la primera no pisa su selección al terminar."""
    conn, path, manifest, blobs, _calls, _reader = bundle
    newer = []

    def interleave(url, limit):
        """Intercala una instalación de catálogo en otra conexión durante la lectura del primer recurso."""
        if not newer:
            catalog_packages.update_packages(path, manifest["packages"], ["hyg"], reader=lambda name, size: blobs[name])
            newer.append(editions.active_id(conn))
        return blobs[url]

    with pytest.raises(ValueError, match="edición cambió"):
        data_packages.install(path, manifest, reader=interleave)
    assert editions.active_id(conn) == newer[0]
    assert data_packages.describe(conn) is None


def test_inicializacion_recomprueba_vacio_tras_preparar_archivos(bundle):
    """Una carga legacy intercalada no cambia el puntero, por eso la guarda de base vacía se repite al activar."""
    conn, path, manifest, blobs, _calls, _reader = bundle
    changed = []

    def interleave(url, limit):
        """Simula otra carga legacy con datos creados después de la comprobación inicial de tablas vacías."""
        if not changed:
            conn.execute("INSERT INTO stars(name,magnitude,ra_hours,dec_deg) VALUES ('Concurrente',1,2,3)")
            conn.commit()
            changed.append(True)
        return blobs[url]

    data_packages.install(path, manifest, reader=interleave, expected_empty=True)
    assert editions.active_id(conn) is None
    assert conn.execute("SELECT name FROM stars").fetchone()[0] == "Concurrente"


def test_opcional_con_dependencia_no_se_descarga_sin_seleccion_completa(bundle):
    """La preferencia de instalar un opcional no autoriza a escoger otras opciones en nombre del usuario."""
    _conn, path, manifest, blobs, calls, reader = bundle
    manifest["resources"]["another"] = _item(blobs, "another.txt", b"Otro", format="utf8-v1", optional=True)
    manifest["resources"]["sample"]["requires"] = {"another": "A"}
    with pytest.raises(ValueError, match="selecciona explícitamente"):
        data_packages.install(path, manifest, reader=reader, optional=["sample"])
    assert not calls


def test_json_no_finito_con_huella_valida_no_se_activa(bundle):
    """SHA correcto no legitima NaN ni JSON roto en un formato que promete sintaxis JSON finita."""
    conn, path, manifest, blobs, calls, reader = bundle
    manifest["resources"]["credits"] = _item(blobs, "invalid.json", b'{"value":NaN}', format="json-v1", optional=False)
    with pytest.raises(ValueError):
        data_packages.install(path, manifest, reader=reader)
    assert len(calls) == 1 and editions.active_id(conn) is None


def test_recurso_local_corrupto_no_se_sobrescribe_ni_se_finge_actualizado(bundle):
    """La caché se reutiliza solo por contenido real, no por nombre o coincidencia de huella en metadatos."""
    conn, path, manifest, _blobs, calls, _reader = bundle
    cache = data_resources.resource_path(path.parent, manifest["resources"]["credits"]["sha256"])
    cache.parent.mkdir()
    cache.write_bytes(b"alterado")
    with pytest.raises(ValueError):
        _install(bundle)
    assert cache.read_bytes() == b"alterado" and not calls
    assert editions.active_id(conn) is None


def test_migracion_de_metadatos_anteriores_agrega_solo_vinculo_nullable(bundle):
    """El esquema personal anterior se amplía sin inventar una edición global para sus catálogos existentes."""
    conn, _path, _manifest, _blobs, _calls, _reader = bundle
    conn.execute("INSERT INTO catalog_editions(edition_id,relative_path,sha256,size_bytes,versions) VALUES ('legacy','catalog-editions/legacy.sqlite',?,1,'{}')", ("0" * 64,))
    conn.execute("ALTER TABLE catalog_editions DROP COLUMN resource_manifest")
    conn.commit()
    connection._apply_schema(conn)
    connection._apply_schema(conn)
    assert conn.execute("SELECT resource_manifest FROM catalog_editions WHERE edition_id='legacy'").fetchone()[0] is None
    assert conn.execute("SELECT notes FROM personal_catalog").fetchone()[0] == "Nota original"
    assert editions.active_id(conn) is None
