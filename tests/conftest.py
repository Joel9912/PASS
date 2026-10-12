"""Fixtures compartidos de los tests de PASS.

Aíslan la base del usuario, las descargas y el área de trabajo en un sandbox
temporal (ver ``pytest_configure``), y retienen una ``QApplication`` única
para toda la sesión.
"""
import os
import sqlite3
import tempfile
from contextlib import closing
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

    La base del usuario se abre solo en lectura y se clona a una carpeta
    temporal. Así los tests que construyen páginas sin ``memory_db`` tampoco
    migran ni escriben en ``data/pass.db``. Las descargas y el área de SirIL
    se redirigen incluso si la copia no tenía catálogos.
    """
    global _SANDBOX
    from planners import catalog_loader, ldn_loader
    from stacks import siril_runner

    _SANDBOX = tempfile.TemporaryDirectory(
        dir=Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp" / "opencode"
        if os.name == "nt" else None
    )
    base = Path(_SANDBOX.name)
    origen = db_connection.DB_PATH.resolve()
    if origen.is_file():
        with (
            closing(sqlite3.connect(origen.as_uri() + "?mode=ro", uri=True)) as fuente,
            closing(sqlite3.connect(base / "pass.db")) as destino,
        ):
            fuente.backup(destino)
    db_connection.DATA_DIR = base
    db_connection.DB_PATH = base / "pass.db"
    catalog_loader.CACHE_DIR = base / "downloads"
    ldn_loader.CACHE_DIR = base / "downloads"
    siril_runner.WORKING_FOLDER = base / "working"


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
