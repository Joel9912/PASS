"""Ediciones externas, lectores coherentes y recuperación sin restaurar trabajo personal antiguo."""

import gzip
import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager

import pytest

from db import catalog_editions as editions
from db import connection
from planners import catalog_packages, celestial_search, personal_catalog, sky_loader


@pytest.fixture
def file_db(tmp_path, monkeypatch):
    """Base sintética de fichero: no copia ni consulta una base personal existente."""
    path = tmp_path / "personal.sqlite"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(connection.SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO catalog(object_id,catalog,messier_num,ngc_num,name,type,ra_hours,dec_deg) "
                 "VALUES ('M31','messier',31,224,'Anterior','G',1,20)")
    conn.execute("INSERT INTO catalog(object_id,catalog,type,ra_hours,dec_deg) VALUES ('LDN 1','ldn','DrkN',2,30)")
    conn.execute("INSERT INTO stars(name,magnitude,ra_hours,dec_deg) VALUES ('Anterior',1,2,3)")
    conn.execute("INSERT INTO personal_catalog(object_id,catalog,notes,ra_hours,dec_deg) "
                 "VALUES ('M31','messier','nota privada sintetica',3,40)")
    conn.execute("INSERT INTO planned_sessions(object_id,session_date,notes) VALUES ('M31','2026-10-20','original')")
    conn.execute("INSERT INTO settings VALUES ('clave_privada','no_exportar_al_catalogo')")
    conn.commit()
    monkeypatch.setattr(connection, "_connection", conn)
    monkeypatch.setattr(connection, "DB_PATH", path)
    yield conn, path
    conn.close()


def _install(path, name="Nueva", *, group="hyg", rows=None):
    """Adjunto sintético con tamaño/huella reales y lector sin red."""
    rows = rows if rows is not None else [[name, 2, 3, 4, "A0", "Ori"]]
    data = gzip.compress(json.dumps(rows).encode())
    item = {"version": name, "date": "2026-10-20", "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data), "url": "sintetico"}
    catalog_packages.update_packages(path, {group: item}, [group], reader=lambda *args: data)


def _star_name(conn):
    """Consulta una lectura explícitamente fijada a la edición actual."""
    return editions.read_rows(conn, "SELECT name FROM stars")[0][0]


def test_actualizar_no_escribe_tablas_legacy_ni_exporta_datos_personales(file_db):
    """La SQLite externa contiene solo datos astronómicos; pass.db mantiene originales y metadatos personales."""
    conn, path = file_db
    _install(path)
    assert _star_name(conn) == "Nueva"
    assert conn.execute("SELECT name FROM stars").fetchone()[0] == "Anterior"
    assert conn.execute("SELECT notes FROM personal_catalog").fetchone()[0] == "nota privada sintetica"
    assert conn.execute("SELECT count(*) FROM catalog_editions").fetchone()[0] == 2
    with editions.catalog_snapshot(conn) as snapshot:
        assert {row[0] for row in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {
            "catalog", "stars", "sqlite_sequence",
        }
        assert "nota privada" not in "\n".join(snapshot.iterdump())
        assert "no_exportar_al_catalogo" not in "\n".join(snapshot.iterdump())
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            snapshot.execute("DELETE FROM stars")


def test_una_lectura_conserva_su_edicion_al_activar_otra(file_db):
    """Activar no cierra recursos de lectores previos ni mezcla componentes en una misma carta."""
    conn, path = file_db
    _install(path, "Primera")
    with editions.catalog_snapshot(conn) as snapshot:
        before = snapshot.execute("SELECT name FROM stars").fetchone()[0]
        _install(path, "Segunda")
        assert snapshot.execute("SELECT name FROM stars").fetchone()[0] == before == "Primera"
    assert _star_name(conn) == "Segunda"


def test_recuperar_edicion_conserva_notas_y_sesiones_posteriores(file_db):
    """No restaura una copia de pass.db y no pierde trabajo creado después de instalar."""
    conn, path = file_db
    _install(path, "Primera")
    _install(path, "Segunda")
    conn.execute("UPDATE personal_catalog SET notes='posterior',pass_object_id='identidad a conservar'")
    conn.execute("INSERT INTO planned_sessions(object_id,session_date,notes) VALUES ('M42','2026-10-21','posterior')")
    conn.commit()
    editions.restore_previous(path)
    assert _star_name(conn) == "Primera"
    assert tuple(conn.execute("SELECT notes,pass_object_id FROM personal_catalog").fetchone()) == ("posterior", "identidad a conservar")
    assert conn.execute("SELECT count(*) FROM planned_sessions").fetchone()[0] == 2
    assert catalog_packages.installed(conn)["hyg"]["version"] == "Primera"
    editions.restore_previous(path)
    assert _star_name(conn) == "Anterior"
    assert catalog_packages.installed(conn)["hyg"] is None


@pytest.mark.parametrize("damage", ["absent", "corrupt"])
def test_edicion_inaccesible_no_usa_legacy_ni_se_declara_disponible(file_db, damage):
    """Un recurso roto se comunica y requiere recuperación explícita; no se mezclan datos de otra edición."""
    conn, path = file_db
    _install(path)
    edition = editions.active_id(conn)
    record = editions._record(conn, edition)
    resource = path.parent / record["relative_path"]
    if damage == "absent":
        resource.unlink()
    else:
        with resource.open("ab") as stream:
            stream.write(b"alterado")
    assert not editions.status(conn)["available"]
    assert editions.active_id(conn) == edition
    assert editions.read_rows(conn, "SELECT name FROM stars") == []
    assert len(sky_loader.load_stars()["ra"]) == 0
    assert celestial_search.get_object("M31") is None
    saved = personal_catalog.list_objects()
    assert saved[0]["notes"] == "nota privada sintetica"
    assert saved[0]["ra_hours"] == 3
    editions.restore_previous(path)
    assert _star_name(conn) == "Anterior"


def test_recuperacion_con_previa_corrupta_no_cambia_la_seleccion(file_db):
    """Nunca activa un recurso anterior que no supera la huella."""
    conn, path = file_db
    _install(path)
    selected = editions.active_id(conn)
    record = editions._record(conn, editions._record(conn, selected)["previous_id"])
    (path.parent / record["relative_path"]).unlink()
    with pytest.raises(editions.CatalogUnavailableError):
        editions.restore_previous(path)
    assert editions.active_id(conn) == selected and _star_name(conn) == "Nueva"


def test_fallo_activacion_no_promueve_candidato_al_reabrir(file_db):
    """DDL/datos de la edición y selección/versiones se confirman juntos; archivos sueltos no son autoridad."""
    conn, path = file_db
    conn.execute("CREATE TRIGGER fallo BEFORE INSERT ON settings WHEN NEW.key='catalog_active_edition' "
                 "BEGIN SELECT RAISE(ABORT,'fallo sintetico'); END")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _install(path)
    assert editions.active_id(conn) is None and _star_name(conn) == "Anterior"
    assert conn.execute("SELECT count(*) FROM catalog_editions").fetchone()[0] == 0
    assert catalog_packages.installed(conn)["hyg"] is None
    assert editions.status(conn)["prepared"] == 2
    with closing(sqlite3.connect(path)) as reopened:
        assert editions.active_id(reopened) is None
        assert _star_name(reopened) == "Anterior"


def test_lectores_busqueda_carta_y_personal_usan_la_edicion_activa(file_db):
    """La separación está conectada a los consumidores, no solo a una utilidad de preparación."""
    conn, path = file_db
    rows = [["M31", "messier", 31, 224, None, "Nombre de edición", "G", 3.44, 4, 50, 190, 60, "And"]]
    _install(path, group="openngc", rows=rows)
    assert celestial_search.get_object("NGC 224")["name"] == "Nombre de edición"
    assert celestial_search.search(celestial_search.SearchFilters(text="M31"))[0]["ra_hours"] == 4
    saved = personal_catalog.list_objects()[0]
    assert saved["name"] == "Nombre de edición" and saved["notes"] == "nota privada sintetica"
    assert saved["region_ra_hours"] == 3 and saved["ra_hours"] == 4
    stars, objects = sky_loader.load_sky()
    assert len(stars["ra"]) == 1 and "M31" in objects["ids"] and "LDN 1" in objects["ids"]
    assert conn.execute("SELECT name FROM catalog WHERE object_id='M31'").fetchone()[0] == "Anterior"


def test_solo_descarga_componentes_solicitados_y_conserva_los_demas(file_db):
    """Actualizar HYG no vuelve a descargar ni sustituye los objetos o la edición completa anterior."""
    conn, path = file_db
    _install(path, "Primera")
    before = [tuple(row) for row in editions.read_rows(conn, "SELECT * FROM catalog ORDER BY id")]
    _install(path, "Segunda")
    assert [tuple(row) for row in editions.read_rows(conn, "SELECT * FROM catalog ORDER BY id")] == before
    assert conn.execute("SELECT count(*) FROM catalog_editions").fetchone()[0] == 3


def test_no_acepta_ruta_de_edicion_que_escape_de_su_carpeta(file_db):
    """Metadatos locales alterados no autorizan leer otra base arbitraria."""
    conn, path = file_db
    _install(path)
    current = editions.active_id(conn)
    conn.execute("UPDATE catalog_editions SET relative_path='../ajena.sqlite' WHERE edition_id=?", (current,))
    conn.commit()
    assert not editions.status(conn)["available"]
    assert editions.read_rows(conn, "SELECT name FROM stars") == []


def test_configuracion_no_afirma_actualizado_si_falta_archivo_y_pide_consentimiento(qt_app, file_db, monkeypatch):
    """Un SHA de manifiesto coincidente no acredita disponibilidad; recuperar también requiere autorización."""
    from ui.config_tab.catalogs_page import CatalogsPage, QMessageBox

    conn, path = file_db
    _install(path)
    record = editions._record(conn, editions.active_id(conn))
    (path.parent / record["relative_path"]).unlink()
    page = CatalogsPage()
    try:
        version = catalog_packages.installed(conn)["hyg"]
        page._packages = {group: {"sha256": version["sha256"]} for group in catalog_packages.GROUPS}
        page.refresh()
        assert "Edición no disponible" in page._table.item(1, 2).text()
        assert page._restore.isEnabled()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
        monkeypatch.setattr(page, "_submit", lambda *args: pytest.fail("No debe recuperar sin permiso"))
        page.start_restore()
        assert not page._restoring
    finally:
        page.deleteLater()


def test_columnas_personales_agregadas_a_legacy_no_se_copian_a_ediciones(file_db):
    """La lista blanca no exporta columnas desconocidas ni ejecuta el esquema particular de una base de usuario."""
    conn, path = file_db
    conn.execute("ALTER TABLE catalog ADD COLUMN nota_privada TEXT")
    conn.execute("UPDATE catalog SET nota_privada='no_exportar_columna_personal'")
    conn.commit()
    _install(path)
    with editions.catalog_snapshot(conn) as snapshot:
        assert "nota_privada" not in {row[1] for row in snapshot.execute("PRAGMA table_info(catalog)")}
        assert "no_exportar_columna_personal" not in "\n".join(snapshot.iterdump())
    assert conn.execute("SELECT nota_privada FROM catalog LIMIT 1").fetchone()[0] == "no_exportar_columna_personal"


@pytest.mark.parametrize("operation", ["objects", "stars", "ldn"])
def test_cargadores_legacy_no_descargan_ni_escriben_tablas_ocultas(file_db, monkeypatch, operation):
    """Una vez seleccionada una edición no permite actualizar inadvertidamente las tablas que ya no leen las cartas."""
    from planners import catalog_loader, ldn_loader

    conn, path = file_db
    _install(path)
    monkeypatch.setattr(catalog_loader, "_download", lambda *args: pytest.fail("No debe descargar"))
    method = {"objects": catalog_loader.load_catalog, "stars": catalog_loader.load_stars, "ldn": ldn_loader.load_ldn}[operation]
    with pytest.raises(ValueError, match="edición.*activa"):
        method()
    assert _star_name(conn) == "Nueva"
    assert conn.execute("SELECT name FROM stars").fetchone()[0] == "Anterior"


def test_activacion_con_version_cambiada_no_pisa_el_otro_estado(file_db, monkeypatch):
    """La preparación libera el bloqueo de pass.db y vuelve a comparar su estado antes de activar."""
    conn, path = file_db
    _install(path, "Primera")
    current = editions.active_id(conn)
    build = editions._candidate

    def concurrent_change(*args, **kwargs):
        """Simula una segunda operación de catálogo mientras se prepara el archivo nuevo."""
        record = build(*args, **kwargs)
        conn.execute("UPDATE settings SET value=? WHERE key='catalog_package_hyg'",
                     (json.dumps({"version": "Cambio externo"}),))
        conn.commit()
        return record

    monkeypatch.setattr(editions, "_candidate", concurrent_change)
    with pytest.raises(ValueError, match="Otra operación"):
        _install(path, "No debe activarse")
    assert editions.active_id(conn) == current and _star_name(conn) == "Primera"
    assert catalog_packages.installed(conn)["hyg"]["version"] == "Cambio externo"
    assert editions.status(conn)["prepared"] == 1


def test_recuperacion_ui_real_con_consentimiento_emite_refresco(qt_app, file_db, monkeypatch):
    """El botón ejecuta la recuperación en su worker y renueva consumidores solo después de confirmar."""
    import time

    from ui.config_tab.catalogs_page import CatalogsPage, QMessageBox

    conn, path = file_db
    _install(path)
    conn.execute("UPDATE personal_catalog SET notes='posterior'")
    conn.commit()
    page = CatalogsPage()
    notifications = []
    page.catalogs_changed.connect(lambda: notifications.append(True))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    try:
        page.start_restore()
        deadline = time.monotonic() + 5
        while page._busy and time.monotonic() < deadline:
            qt_app.processEvents()
            time.sleep(.005)
        assert not page._busy and notifications == [True]
        assert "recuperada" in page._status.text()
        assert _star_name(conn) == "Anterior"
        assert conn.execute("SELECT notes FROM personal_catalog").fetchone()[0] == "posterior"
    finally:
        page.deleteLater()


@pytest.mark.parametrize("concurrent", ["legacy", "edition"])
def test_primera_carga_no_pisa_catalogo_rellenado_despues_del_chequeo(file_db, tmp_path, monkeypatch, concurrent):
    """La comprobación inicial de tablas vacías no autoriza sobrescribir una edición instalada mientras tanto."""
    conn, path = file_db
    conn.execute("DELETE FROM stars")
    conn.commit()
    folder = tmp_path / "included"
    folder.mkdir()
    data = gzip.compress(json.dumps([["Incluida", 2, 3, 4, None, None]]).encode())
    item = {"version": "Incluida", "date": "2026-10-20", "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data), "url": "https://github.com/Joel9912/PASS/releases/download/test/hyg.gz"}
    (folder / "hyg.gz").write_bytes(data)
    (folder / "catalogs-manifest.json").write_text(json.dumps({
        "format": 1, "packages": {group: item for group in catalog_packages.GROUPS},
    }), encoding="utf-8")
    update = catalog_packages.update_packages

    def concurrent_fill(*args, **kwargs):
        """Intercala otra instalación justo después de que bundled observara estrellas vacías."""
        if concurrent == "legacy":
            conn.execute("INSERT INTO stars(name,magnitude,ra_hours,dec_deg) VALUES ('Concurrente',2,3,4)")
            conn.commit()
        else:
            editions.install_edition(path, {"hyg": (editions.STAR_COLUMNS, [["Concurrente", 2, 3, 4, None, None]])},
                                     {"hyg": {"version": "Concurrente"}}, catalog_packages.GROUPS)
        return update(*args, **kwargs)

    monkeypatch.setattr(catalog_packages, "update_packages", concurrent_fill)
    catalog_packages.install_bundled(path, folder)
    assert _star_name(conn) == "Concurrente"


def test_la_carta_no_mezcla_objetos_nuevos_con_estrellas_de_otra_edicion(file_db, monkeypatch):
    """Intercalar una activación entre ambas consultas mantiene una vista coherente de los dos componentes."""
    _, path = file_db
    _install(path, "Primera")
    snapshot_context = sky_loader.catalog_snapshot

    class Interleaved:
        """Intercala la actualización sobre otra conexión tras abrir la primera consulta."""

        def __init__(self, snapshot):
            """Conserva el lector fijado y evita repetir la intercalación."""
            self.snapshot, self.first = snapshot, True

        def execute(self, sql):
            """El cursor permanece en su SQLite anterior aunque cambie el puntero de pass.db."""
            cursor = self.snapshot.execute(sql)
            if self.first:
                self.first = False
                _install(path, group="openngc", rows=[
                    ["M31", "messier", 31, 224, None, "Nueva", "G", 3, 4, 50, None, None, "And"],
                ])
            return cursor

    @contextmanager
    def interleaved(personal):
        """Simula una actualización concurrente sin temporizadores ni acceso a red."""
        with snapshot_context(personal) as snapshot:
            yield Interleaved(snapshot)

    monkeypatch.setattr(sky_loader, "catalog_snapshot", interleaved)
    _, objects = sky_loader.load_sky()
    assert objects["ra"][objects["ids"].index("M31")] == 15
    current = sky_loader.load_objects()
    assert current["ra"][current["ids"].index("M31")] == 60


def test_candidato_no_verificable_no_se_activa_ni_borra_ediciones_validas(file_db, monkeypatch):
    """Un fallo entre escritura del archivo y activación no toca el catálogo activo ni sus archivos anteriores."""
    conn, path = file_db
    _install(path, "Primera")
    current = editions.active_id(conn)
    files = set((path.parent / editions.EDITION_FOLDER).iterdir())
    open_snapshot = editions._open

    def reject_new(root, record):
        """Permite leer la edición de origen pero simula fallo de verificación del candidato recién creado."""
        if record["edition_id"] != current:
            raise editions.CatalogUnavailableError("Fallo sintético de verificación")
        return open_snapshot(root, record)

    monkeypatch.setattr(editions, "_open", reject_new)
    with pytest.raises(editions.CatalogUnavailableError):
        _install(path, "No debe activarse")
    assert editions.active_id(conn) == current and _star_name(conn) == "Primera"
    assert set((path.parent / editions.EDITION_FOLDER).iterdir()) == files


def test_ruta_personal_ausente_no_crea_una_base_vacia_por_error(tmp_path):
    """Instalar/recuperar requiere una base ya inicializada, no fabrica pass.db en una ruta equivocada."""
    path = tmp_path / "ausente.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        editions.restore_previous(path)
    with pytest.raises(sqlite3.OperationalError):
        _install(path)
    assert not path.exists()


def test_edicion_de_formato_futuro_se_conserva_sin_interpretar(file_db):
    """La presencia del archivo no autoriza a una versión antigua de PASS a reinterpretar una edición futura."""
    conn, path = file_db
    _install(path)
    current = editions.active_id(conn)
    conn.execute("UPDATE catalog_editions SET schema_version=999 WHERE edition_id=?", (current,))
    conn.commit()
    record = editions._record(conn, current)
    before = (path.parent / record["relative_path"]).read_bytes()
    assert not editions.status(conn)["available"]
    assert editions.read_rows(conn, "SELECT name FROM stars") == []
    assert editions.active_id(conn) == current
    assert (path.parent / record["relative_path"]).read_bytes() == before


def test_region_personal_no_adopta_coordenadas_o_nombre_del_catalogo(file_db):
    """Un nombre compartido no convierte una región/encuadre manual en un objeto distribuido."""
    conn, path = file_db
    conn.execute("INSERT INTO personal_catalog(object_id,catalog,kind,ra_hours,dec_deg,fov_major_arcmin,notes) "
                 "VALUES ('M31','region','region',5,30,90,'Region propia')")
    conn.commit()
    _install(path)
    saved = next(row for row in personal_catalog.list_objects() if row["kind"] == "region")
    assert (saved["ra_hours"], saved["dec_deg"], saved["fov_major_arcmin"]) == (5, 30, 90)
    assert saved["name"] is None and saved["notes"] == "Region propia"
    editions.restore_previous(path)
    assert conn.execute("SELECT ra_hours FROM personal_catalog WHERE kind='region'").fetchone()[0] == 5
