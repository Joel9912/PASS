"""Paquetes offline: huellas, transacciones y arranque sin descargas."""
import gzip
import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from db.catalog_editions import catalog_snapshot
from planners import catalog_packages as packages


def _catalog_rows(path, sql):
    """Consulta la edición seleccionada en vez de confundir las tablas legacy conservadas con los datos activos."""
    with closing(sqlite3.connect(path)) as personal, catalog_snapshot(personal) as catalog:
        return [tuple(row) for row in catalog.execute(sql)]


def _package(rows):
    """Construye un paquete mínimo y sus metadatos verificables."""
    data = gzip.compress(json.dumps(rows).encode())
    return data, {"version": "prueba", "date": "2026-10-12", "size": len(data),
                  "sha256": hashlib.sha256(data).hexdigest(),
                  "url": "https://github.com/Joel9912/PASS/releases/download/test/hyg.gz"}


def _seed_database(path):
    """Datos anteriores y personales sintéticos para detectar cualquier sustitución parcial."""
    from db.connection import SCHEMA_PATH

    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO stars(name,magnitude,ra_hours,dec_deg) VALUES ('Anterior',1,2,3)")
        conn.execute("INSERT INTO catalog(object_id,catalog,magnitude) VALUES ('M31','messier',3.44)")
        conn.execute("INSERT INTO personal_catalog(object_id,catalog,kind,ra_hours,dec_deg,notes) "
                     "VALUES ('Mi región','region','region',1,20,'Notas propias')")
        conn.execute("INSERT INTO equipment_setups(id,name) VALUES (7,'Mi equipo')")
        conn.execute("INSERT INTO planned_sessions(object_id,setup_id,session_date,notes) "
                     "VALUES ('M31',7,'2026-10-22','Sesión propia')")
        conn.execute("INSERT INTO settings VALUES ('personal','intacto')")
        return list(conn.iterdump())


@pytest.mark.parametrize("column,value", [(0, 123), (1, "brillante"), (1, None), (2, None),
                                         (3, None), (4, 123), (5, 123), (1, True),
                                         (1, float("nan")), (1, float("inf")),
                                         (1, 2 ** 70), (1, 2 ** 1000)])
def test_estrellas_con_tipos_invalidos_no_sustituyen_catalogo(tmp_path, monkeypatch, column, value):
    """Una huella válida no legitima magnitudes de texto ni campos que SQLite convertiría silenciosamente."""
    path = tmp_path / "catalog.sqlite"
    before = _seed_database(path)
    row = ["Nueva", 2, 3, 4, "A0", "Ori"]
    row[column] = value
    data, item = _package([row])
    monkeypatch.setattr(packages, "_read", lambda *args: data)
    with pytest.raises(ValueError):
        packages.update_packages(path, {"hyg": item}, ["hyg"])
    with sqlite3.connect(path) as conn:
        assert list(conn.iterdump()) == before


@pytest.mark.parametrize("column,value", [(0, 123), (1, "region"), (1, "desconocido"), (2, "31"),
                                         (3, 0), (4, 1.5), (5, 123), (6, 123), (7, "brillante"),
                                         (10, "190"), (10, -2), (12, 123), (2, 2 ** 70)])
def test_objetos_invalidos_no_se_mezclan_con_regiones_personales(tmp_path, monkeypatch, column, value):
    """El instalador rechaza tipos/familias incompatibles antes de tocar catálogos, versiones o vínculos."""
    path = tmp_path / "catalog.sqlite"
    before = _seed_database(path)
    row = ["M31", "messier", 31, 224, None, "Andrómeda", "G", 3.44, .712, 41.27, 190, 60, "And"]
    row[column] = value
    data, item = _package([row])
    monkeypatch.setattr(packages, "_read", lambda *args: data)
    with pytest.raises(ValueError):
        packages.update_packages(path, {"openngc": item}, ["openngc"])
    with sqlite3.connect(path) as conn:
        assert list(conn.iterdump()) == before


def test_segundo_paquete_invalido_impide_sustituir_el_primero(tmp_path):
    """Se valida toda la tanda antes de abrir la transacción que reemplaza filas y versiones."""
    path = tmp_path / "catalog.sqlite"
    before = _seed_database(path)
    star_data, star = _package([[None, -1.46, 6.75, -16.7, None, None]])
    cat_data, cat = _package([["M31", "region", None, None, None, None, None, None, 1, 20, None, None, None]])
    star["url"], cat["url"] = "estrellas", "objetos"
    with pytest.raises(ValueError):
        packages.update_packages(path, {"hyg": star, "openngc": cat}, ["hyg", "openngc"],
                                 reader=lambda url, limit: {"estrellas": star_data, "objetos": cat_data}[url])
    with sqlite3.connect(path) as conn:
        assert list(conn.iterdump()) == before


def test_valores_ausentes_y_magnitud_negativa_no_se_convierten_en_ceros(tmp_path, monkeypatch):
    """Desconocidos opcionales siguen siendo NULL y las magnitudes negativas son válidas."""
    path = tmp_path / "catalog.sqlite"
    _seed_database(path)
    data, item = _package([[None, -1.46, 6.75, -16.7, None, None]])
    monkeypatch.setattr(packages, "_read", lambda *args: data)
    packages.update_packages(path, {"hyg": item}, ["hyg"])
    assert _catalog_rows(path, "SELECT name,magnitude,color,constellation FROM stars") == [(None, -1.46, None, None)]


@pytest.mark.parametrize("group", ["hyg", "openngc"])
def test_identidad_repetida_incompatible_con_sql_se_rechaza_antes_de_instalar(tmp_path, monkeypatch, group):
    """Un paquete no resuelve colisiones sobrescribiendo entradas ni llega al DELETE para descubrirlas."""
    path = tmp_path / "catalog.sqlite"
    before = _seed_database(path)
    row = (["Nueva", 2, 3, 4, None, None] if group == "hyg" else
           ["M31", "messier", 31, 224, None, None, "G", None, 1, 20, None, None, None])
    data, item = _package([row, row])
    monkeypatch.setattr(packages, "_read", lambda *args: data)
    with pytest.raises(ValueError, match="repetida"):
        packages.update_packages(path, {group: item}, [group])
    with sqlite3.connect(path) as conn:
        assert list(conn.iterdump()) == before


def test_no_fusiona_estrellas_anonimas_solo_por_coincidir_coordenadas(tmp_path, monkeypatch):
    """El formato legacy sin identidad estelar no acredita que dos fuentes anónimas sean el mismo objeto."""
    path = tmp_path / "catalog.sqlite"
    _seed_database(path)
    row = [None, 2, 3, 4, None, None]
    data, item = _package([row, row])
    monkeypatch.setattr(packages, "_read", lambda *args: data)
    packages.update_packages(path, {"hyg": item}, ["hyg"])
    assert _catalog_rows(path, "SELECT count(*) FROM stars WHERE name IS NULL")[0][0] == 2


def test_version_booleana_no_se_interpreta_como_formato_uno():
    """JSON true no es el número de versión 1 aunque Python los compare como iguales."""
    _, item = _package([["Nueva", 2, 3, 4, None, None]])
    with pytest.raises(ValueError, match="formato|Formato"):
        packages.parse_manifest(json.dumps({"format": True, "packages": {group: item for group in packages.GROUPS}}))


@pytest.mark.parametrize("invalid", [False, True])
def test_preparador_valida_contrato_antes_de_escribir_sin_red(memory_db, tmp_path, monkeypatch, invalid):
    """Preparador e instalador comparten validación; datos sintéticos inválidos no dejan artefactos de salida."""
    from db import connection
    from scripts import preparar_catalogos as prepare

    original_db = connection.DB_PATH
    monkeypatch.setattr(prepare.tempfile, "tempdir", str(tmp_path))

    def catalog():
        """Simula fuente verificada sin descargar ni leer ningún catálogo personal."""
        conn = connection.get_connection()
        conn.execute("INSERT INTO catalog(object_id,catalog,magnitude,ra_hours,dec_deg) VALUES ('M31','messier',3.44,1,20)")
        conn.commit()

    def stars():
        """SQLite admite texto en REAL: el contrato debe detectarlo al exportar."""
        conn = connection.get_connection()
        conn.execute("INSERT INTO stars(name,magnitude,ra_hours,dec_deg) VALUES ('Estrella',?,2,3)",
                     ("brillante" if invalid else -1.46,))
        conn.commit()

    def ldn():
        """Añade únicamente una fila ficticia del grupo esperado."""
        conn = connection.get_connection()
        conn.execute("INSERT INTO catalog(object_id,catalog,ra_hours,dec_deg) VALUES ('LDN 1','ldn',1,20)")
        conn.commit()

    monkeypatch.setattr(prepare.catalog_loader, "load_catalog", catalog)
    monkeypatch.setattr(prepare.catalog_loader, "load_stars", stars)
    monkeypatch.setattr(prepare.ldn_loader, "load_ldn", ldn)
    output = tmp_path / "artefactos-sinteticos"
    if invalid:
        with pytest.raises(ValueError):
            prepare.prepare("synthetic", output)
        assert not output.exists()
    else:
        prepare.prepare("synthetic", output)
        manifest = packages.parse_manifest((output / "catalogs-manifest.json").read_bytes())
        for group, item in manifest.items():
            name = item["url"].rsplit("/", 1)[-1]
            raw = (output / name).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == item["sha256"]
            packages.validate_rows(group, json.loads(gzip.decompress(raw)))
    assert connection._connection is memory_db and connection.DB_PATH == original_db
    assert memory_db.execute("SELECT count(*) FROM stars").fetchone()[0] == 0


@pytest.mark.parametrize("corrupt", [False, True])
def test_install_integrity_and_preserve_user(tmp_path, monkeypatch, corrupt):
    """Un paquete válido cambia solo estrellas; uno alterado no cambia ni su versión."""
    from db.connection import SCHEMA_PATH

    path = tmp_path / "db.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO stars(name,magnitude,ra_hours,dec_deg) VALUES ('Anterior',1,2,3)")
        conn.execute("INSERT INTO settings VALUES ('personal','intacto')")
    data, item = _package([["Nueva", 2, 3, 4, "A0", "Ori"]])
    monkeypatch.setattr(packages, "_read", lambda *args: data + b"x" if corrupt else data)
    if corrupt:
        with pytest.raises(ValueError, match="integridad"):
            packages.update_packages(path, {"hyg": item}, ["hyg"])
    else:
        packages.update_packages(path, {"hyg": item}, ["hyg"])
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM stars").fetchone()[0] == "Anterior"
        assert _catalog_rows(path, "SELECT name FROM stars")[0][0] == ("Anterior" if corrupt else "Nueva")
        assert conn.execute("SELECT value FROM settings WHERE key='personal'").fetchone()[0] == "intacto"
        assert bool(packages.installed(conn)["hyg"]) is not corrupt


def test_invalid_manifest_rejected(monkeypatch):
    """No se presenta como vigente un manifiesto incompleto."""
    monkeypatch.setattr(packages, "_read", lambda *args: b'{"format":1,"packages":{}}')
    with pytest.raises(ValueError, match="incompleto"):
        packages.parse_manifest(b'{"format":1,"packages":{}}')


def test_discovery_includes_prerelease(monkeypatch):
    """La primera alpha puede ofrecer paquetes aunque GitHub no la marque latest estable."""
    _, item = _package([["Nueva", 2, 3, 4, "A0", "Ori"]])
    url = "https://github.com/Joel9912/PASS/releases/download/v0.2-alpha/catalogs-manifest.json"
    responses = {
        packages.RELEASES_URL: json.dumps([{"draft": False, "prerelease": True,
            "assets": [{"name": "catalogs-manifest.json", "browser_download_url": url}]}]).encode(),
        url: json.dumps({"format": 1, "packages": {group: item for group in packages.GROUPS}}).encode(),
    }
    monkeypatch.setattr(packages, "_read", lambda url, limit: responses[url])
    assert packages.check_manifest()["hyg"]["version"] == "prueba"


def test_bundled_install_offline_preserves_legacy(tmp_path, monkeypatch):
    """La distribución rellena tablas vacías sin red y no reemplaza objetos existentes."""
    from db.connection import SCHEMA_PATH

    path = tmp_path / "db.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO catalog(object_id,catalog) VALUES ('Personalizado','ngc')")
        conn.execute("INSERT INTO catalog(object_id,catalog) VALUES ('LDN antiguo','ldn')")
    folder = tmp_path / "included"
    folder.mkdir()
    data, item = _package([["Nueva", 2, 3, 4, "A0", "Ori"]])
    (folder / "hyg.gz").write_bytes(data)
    item["url"] = "https://github.com/Joel9912/PASS/releases/download/test/hyg.gz"
    (folder / "catalogs-manifest.json").write_text(json.dumps(
        {"format": 1, "packages": {group: item for group in packages.GROUPS}}), encoding="utf-8")
    monkeypatch.setattr(packages, "_read", lambda *args: pytest.fail("No debe usar red"))
    packages.install_bundled(path, folder)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM stars").fetchone()[0] == 0
        assert _catalog_rows(path, "SELECT name FROM stars")[0][0] == "Nueva"
        assert packages.installed(conn)["openngc"] is None


def test_install_sql_failure_rolls_back(tmp_path, monkeypatch):
    """Un fallo de activación conserva catálogo, selección y versiones anteriores."""
    from db.connection import SCHEMA_PATH

    path = tmp_path / "db.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO stars(name,magnitude,ra_hours,dec_deg) VALUES ('Anterior',1,2,3)")
        conn.execute("CREATE TRIGGER fallo BEFORE INSERT ON settings WHEN NEW.key='catalog_active_edition' "
                     "BEGIN SELECT RAISE(ABORT,'fallo'); END")
    data, item = _package([["Nueva", 2, 3, 4, "A0", "Ori"]])
    monkeypatch.setattr(packages, "_read", lambda *args: data)
    with pytest.raises(sqlite3.IntegrityError):
        packages.update_packages(path, {"hyg": item}, ["hyg"])
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM stars").fetchone()[0] == "Anterior"
        assert packages.installed(conn)["hyg"] is None


def test_update_requires_consent(qt_app, monkeypatch):
    """Rechazar la confirmación no encola descargas ni instalaciones."""
    from ui.config_tab.catalogs_page import CatalogsPage, QMessageBox

    page = CatalogsPage()
    _, item = _package([["Nueva", 2, 3, 4, "A0", "Ori"]])
    page._packages = {group: item for group in packages.GROUPS}
    page.refresh()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    monkeypatch.setattr(page, "_submit", lambda *args: pytest.fail("Sin consentimiento"))
    page.start_update()
    page._finished(None, "Sin red")
    assert page._table.item(list(packages.GROUPS).index("hyg"), 0).toolTip() != "Actualizado"
    assert not page._update.isEnabled()
    page.deleteLater()


def test_catalog_config_no_network_on_open(qt_app, monkeypatch):
    """Abrir la sección no descarga nada y no inventa versiones."""
    from ui.config_tab.catalogs_page import CatalogsPage

    monkeypatch.setattr(packages, "check_manifest", lambda: pytest.fail("No debe consultar la red"))
    page = CatalogsPage()
    assert not page._update.isEnabled()
    assert page._table.item(list(packages.GROUPS).index("hyg"), 1).text() == "Sin identificar"
    page.deleteLater()


def test_catalogos_tabla_botones_y_progreso(qt_app):
    """El diseño aprobado muestra columnas, botones en una fila y progreso honesto."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QHBoxLayout

    from ui.config_tab.catalogs_page import CatalogsPage

    page = CatalogsPage()
    assert [page._table.horizontalHeaderItem(i).text() for i in range(3)] == [
        "Catálogo", "Versión", "Actualizado",
    ]
    assert page._table.rowCount() == len(packages.GROUPS)
    assert all(page._table.item(row, column).textAlignment() == Qt.AlignmentFlag.AlignCenter
               for row in range(page._table.rowCount()) for column in range(3))
    panel = page._panel.layout()
    rows = [panel.itemAt(i).layout() for i in range(panel.count())]
    assert page._panel.objectName() == "GroupFrame"
    assert page._table.alternatingRowColors()
    buttons = next(row for row in rows if isinstance(row, QHBoxLayout))
    assert buttons.itemAt(0).widget() is page._check
    assert buttons.itemAt(1).widget() is page._update
    page._busy = True
    page._progress.setRange(0, 0)
    page._finished({}, "Sin red")
    assert page._progress.maximum() == 1 and page._progress.value() == 0
    assert all(page._table.item(row, 0).textAlignment() == Qt.AlignmentFlag.AlignCenter
               for row in range(page._table.rowCount()))
    page.deleteLater()


def test_main_no_download_before_window(monkeypatch):
    """B-0005: el arranque no llama al cargador bloqueante, ni antes ni después de pintar."""
    import main
    from planners import catalog_loader

    calls = []

    class Application:
        """Bucle Qt controlado sin una segunda QApplication."""
        def __init__(self, *args):
            """Registra construcción sin interfaz real."""
            calls.append("app")

        def exec(self):
            """Termina inmediatamente el bucle simulado."""
            return 0

    class Window:
        """Ventana mínima que registra el momento visible."""
        def resize(self, *args):
            """No necesita geometría real."""

        def show(self):
            """Registra que la ventana llegó a mostrarse."""
            calls.append("show")

    def download(*args):
        """Detecta la llamada bloqueante antigua."""
        calls.append("download")

    monkeypatch.setattr(catalog_loader, "ensure_catalog", download)
    monkeypatch.setattr(main, "ensure_catalog", download, raising=False)
    monkeypatch.setattr(main, "ActionLogger", lambda app: None)
    monkeypatch.setattr(main, "install_exception_hooks", lambda: None)
    monkeypatch.setattr(main, "QApplication", Application)
    monkeypatch.setattr(main, "MainWindow", Window)
    monkeypatch.setattr(main, "apply_style", lambda app: None)
    with pytest.raises(SystemExit):
        main.main()
    assert calls == ["app", "show"]
