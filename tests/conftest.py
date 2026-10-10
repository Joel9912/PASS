"""Fixtures compartidos de los tests de PASS."""
import os
import sqlite3
from pathlib import Path

import pytest

from db import connection as db_connection

ROOT = Path(__file__).resolve().parent.parent

#: Los tests de UI nunca piden pantalla real: offscreen para todo el proceso.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

#: QApplication retenida a nivel de módulo: si la última referencia Python se
#: descarta, PyQt6 la destruye al hacer GC y el siguiente widget crashea la
#: proceso. El módulo ``conftest`` sobrevive a todos los tests, así que aquí
#: la referencia vive el tiempo que hace falta (regla del propio test_dialogos).
_QT_APP = None


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
