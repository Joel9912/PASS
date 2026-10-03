"""Fixtures compartidos de los tests de PAS.S."""
import sqlite3
from pathlib import Path

import pytest

from db import settings as settings_mod

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def memory_settings(monkeypatch):
    """Tabla ``settings`` en memoria: sustituye la conexión global."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    monkeypatch.setattr(settings_mod, "get_connection", lambda: conn)
    yield conn
    conn.close()
