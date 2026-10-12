"""Fixtures compartidos de los tests de PASS.

Aíslan la base del usuario, las descargas y el área de trabajo en un sandbox
temporal (ver ``pytest_configure``), y retienen una ``QApplication`` única
para toda la sesión.
"""
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from db import connection as db_connection

ROOT = Path(__file__).resolve().parent.parent

#: Los tests de UI nunca piden pantalla real: offscreen para todo el proceso.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

#: QApplication retenida a nivel de módulo: si la última referencia Python se
#: descarta, PyQt6 la destruye al hacer GC y el siguiente widget crashea la
#: proceso. El módulo ``conftest`` sobrevive a todos los tests, así que aquí
#: la referencia vive el tiempo que hace falta (regla del propio test_dialogos).
_QT_APP = None

_SANDBOX: tempfile.TemporaryDirectory | None = None


def pytest_configure() -> None:
    """Aísla BD, descargas y working antes de importar los módulos de test.

    Crea esquema y datos sintéticos en una carpeta temporal sin abrir la base
    del usuario. Descargas y working quedan aislados también.
    """
    global _SANDBOX
    from planners import catalog_loader, ldn_loader
    from stacks import siril_runner

    _SANDBOX = tempfile.TemporaryDirectory(
        dir=Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp" / "opencode"
        if os.name == "nt" else None
    )
    base = Path(_SANDBOX.name)
    db_connection.DATA_DIR = base
    db_connection.DB_PATH = base / "pass.db"
    catalog_loader.CACHE_DIR = base / "downloads"
    ldn_loader.CACHE_DIR = base / "downloads"
    siril_runner.WORKING_FOLDER = base / "working"
    from astropy.utils import iers

    iers.conf.auto_download = False
    iers.conf.auto_max_age = None
    conn = db_connection.get_connection()
    conn.executemany(
        "INSERT INTO catalog(object_id,catalog,messier_num,ngc_num,name,type,magnitude,ra_hours,dec_deg)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("M31", "messier", 31, 224, "Andromeda Galaxy", "G", 3.44, 0.712, 41.27),
            ("M42", "messier", 42, 1976, "Orion Nebula", "Neb", 4.0, 5.59, -5.39),
            ("M45", "messier", 45, None, "Pleiades", "OCl", 1.6, 3.79, 24.12),
            ("M13", "messier", 13, 6205, "Hercules", "GCl", 5.8, 16.69, 36.46),
            ("M102", "messier", 102, 5866, "Spindle", "G", 9.9, 15.11, 55.76),
            ("NGC 7000", "ngc", None, 7000, "North America", "Neb", None, 20.98, 44.52),
            ("IC 1", "ic", None, None, None, "**", None, 0.14, 27.72),
            ("LDN 621", "ldn", None, None, None, "DrkN", None, 18.79, 3.22),
        ],
    )
    conn.execute("UPDATE catalog SET ic_num=1 WHERE object_id='IC 1'")
    conn.executemany(
        "UPDATE catalog SET constellation=? WHERE object_id=?",
        [("And", "M31"), ("Ori", "M42"), ("Tau", "M45"),
         ("Her", "M13"), ("Dra", "M102"), ("Cyg", "NGC 7000"), ("Peg", "IC 1")],
    )
    conn.executemany(
        "INSERT INTO stars(name,magnitude,ra_hours,dec_deg,color,constellation) VALUES (?,?,?,?,?,?)",
        [("Estrella A", 1.0, 5.5, -5.0, "A0", "Ori"),
         ("Estrella B", 2.0, 0.7, 41.0, "K0", "And")],
    )
    conn.commit()


@pytest.fixture(autouse=True)
def sin_red_real(monkeypatch):
    """Impide descargas accidentales; los tests de HTTP instalan sus propios dobles."""
    import urllib.request

    def rechazar(*args, **kwargs):
        """Falla explícitamente si un test intenta acceder a Internet."""
        raise AssertionError("La suite debe funcionar sin red; falta un doble HTTP.")

    monkeypatch.setattr(urllib.request, "urlopen", rechazar)


def pytest_unconfigure() -> None:
    """Cierra SQLite para poder retirar la copia temporal también en Windows."""
    if db_connection._connection is not None:
        db_connection._connection.close()
        db_connection._connection = None
    if _SANDBOX is not None:
        _SANDBOX.cleanup()


@pytest.fixture()
def qt_app():
    """QApplication única de los tests de UI (offscreen, referencia retenida).

    Los tests de UI la piden como parámetro en vez de construirla: la
    plataforma offscreen ya está activa (línea superior) y la referencia
    retenida en ``_QT_APP`` evita el crashe de GC entre tests.
    """
    global _QT_APP
    from PyQt6.QtWidgets import QApplication

    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


@pytest.fixture()
def memory_db(monkeypatch):
    """Base en memoria con esquema completo y FK activas.

    Parchea la conexión global (``db.connection._connection``), así que todos
    los módulos que llaman a ``get_connection()`` (settings, manager,
    localizations, images) ven esta base sin tocar cada uno por su lado.
    Con ``PRAGMA foreign_keys`` activo los ``ON DELETE`` del esquema se
    comportan como en producción (SET NULL de sesiones, CASCADE de imágenes),
    cosa que una conexión en memoria «pelada» no hace: SQLite los trae
    desactivados.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    monkeypatch.setattr(db_connection, "_connection", conn)
    yield conn
    conn.close()


@pytest.fixture()
def memory_settings(memory_db):
    """Tabla ``settings`` en memoria: alias de ``memory_db`` (mismo esquema)."""
    return memory_db
