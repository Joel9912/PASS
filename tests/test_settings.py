"""settings: claves-valor, API keys del clima y ruta de SirIL."""
import sqlite3
from pathlib import Path

import pytest

from db import settings as settings_mod
from planners.weather import base as weather_base
from stacks import siril_finder

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


def test_set_get_roundtrip(memory_settings):
    """set/get con upsert y valores por defecto cuando la clave no existe."""
    assert settings_mod.get_setting("clave") is None
    assert settings_mod.get_setting("clave", "por-defecto") == "por-defecto"

    settings_mod.set_setting("clave", "valor")
    assert settings_mod.get_setting("clave") == "valor"

    settings_mod.set_setting("clave", "valor-2")  # actualiza, no duplica
    assert settings_mod.get_setting("clave") == "valor-2"


def test_api_key_roundtrip(memory_settings):
    """save_api_key escribe en settings y load_api_key lo lee (o None)."""
    assert weather_base.load_api_key("clear_outside_api_key") is None

    weather_base.save_api_key("clear_outside_api_key", "abc123")
    assert weather_base.load_api_key("clear_outside_api_key") == "abc123"

    # Cada proveedor usa su propia clave: no se pisan.
    assert weather_base.load_api_key("meteoblue_api_key") is None


def test_find_siril_falls_back_to_saved_path(memory_settings, monkeypatch):
    """Sin SirIL en el PATH usa la ruta guardada por el usuario."""
    monkeypatch.setattr(siril_finder, "which", lambda _name: None)
    assert siril_finder.find_siril() is None

    siril_finder.save_user_path(r"C:\Program Files\Siril\bin\siril-cli.exe")
    assert (
        siril_finder.find_siril()
        == r"C:\Program Files\Siril\bin\siril-cli.exe"
    )


def test_find_siril_prefers_path_over_saved(memory_settings, monkeypatch):
    """El PATH del sistema tiene prioridad sobre la ruta guardada."""
    monkeypatch.setattr(siril_finder, "which", lambda _name: "C:/bin/siril.exe")
    siril_finder.save_user_path("ruta-antigua")
    assert siril_finder.find_siril() == "C:/bin/siril.exe"
