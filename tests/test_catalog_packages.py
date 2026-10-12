"""Paquetes offline: huellas, transacciones y arranque sin descargas."""
import gzip
import hashlib
import json
import sqlite3

import pytest

from planners import catalog_packages as packages


def _package(rows):
    """Construye un paquete mínimo y sus metadatos verificables."""
    data = gzip.compress(json.dumps(rows).encode())
    return data, {"version": "prueba", "date": "2026-10-12", "size": len(data),
                  "sha256": hashlib.sha256(data).hexdigest(),
                  "url": "https://github.com/Joel9912/PASS/releases/download/test/hyg.gz"}


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
        assert conn.execute("SELECT name FROM stars").fetchone()[0] == ("Anterior" if corrupt else "Nueva")
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
        assert conn.execute("SELECT name FROM stars").fetchone()[0] == "Nueva"
        assert packages.installed(conn)["openngc"] is None


def test_install_sql_failure_rolls_back(tmp_path, monkeypatch):
    """Un fallo después del DELETE conserva filas y versión anterior."""
    from db.connection import SCHEMA_PATH

    path = tmp_path / "db.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO stars(name,magnitude,ra_hours,dec_deg) VALUES ('Anterior',1,2,3)")
        conn.execute("CREATE TRIGGER fallo BEFORE INSERT ON stars BEGIN SELECT RAISE(ABORT,'fallo'); END")
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
    assert "Actualizado" not in page._labels["hyg"].text()
    assert not page._update.isEnabled()
    page.deleteLater()


def test_catalog_config_no_network_on_open(qt_app, monkeypatch):
    """Abrir la sección no descarga nada y no inventa versiones."""
    from ui.config_tab.catalogs_page import CatalogsPage

    monkeypatch.setattr(packages, "check_manifest", lambda: pytest.fail("No debe consultar la red"))
    page = CatalogsPage()
    assert not page._update.isEnabled()
    assert "sin identificar" in page._labels["hyg"].text()
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
    monkeypatch.setattr(main, "QApplication", Application)
    monkeypatch.setattr(main, "MainWindow", Window)
    monkeypatch.setattr(main, "apply_style", lambda app: None)
    with pytest.raises(SystemExit):
        main.main()
    assert calls == ["app", "show"]
