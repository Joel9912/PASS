"""settings: claves-valor y API keys del clima (db/settings + weather.base).

Los tests de ``stacks/siril_finder`` (que también usan settings para la ruta
guardada) viven en su fichero propio, ``test_siril_finder.py``.
"""
from db import settings as settings_mod
from planners.weather import base as weather_base


def test_pytest_no_usa_base_de_usuario():
    """La conexión por defecto de las pruebas nunca apunta a data/pass.db."""
    from db import connection

    assert connection.DB_PATH.resolve() != (connection.ROOT / "data" / "pass.db").resolve()


def test_conexion_fallida_no_se_reutiliza(tmp_path, monkeypatch):
    """Una migración fallida no publica una conexión SQLite a medio iniciar."""
    import sqlite3

    import pytest

    from db import connection

    previa = connection._connection
    monkeypatch.setattr(connection, "_connection", None)
    monkeypatch.setattr(connection, "DATA_DIR", tmp_path)
    monkeypatch.setattr(connection, "DB_PATH", tmp_path / "prueba.db")
    aplicar = connection._apply_schema

    def fallar(_conn):
        """Simula un error de esquema antes de confirmar la conexión."""
        raise sqlite3.DatabaseError("migración simulada")

    monkeypatch.setattr(connection, "_apply_schema", fallar)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="simulada"):
            connection.get_connection()
        assert connection._connection is None
        monkeypatch.setattr(connection, "_apply_schema", aplicar)
        nueva = connection.get_connection()
        assert nueva.execute("SELECT count(*) FROM settings").fetchone()[0] == 0
        nueva.close()
    finally:
        connection._connection = previa

# El fixture ``memory_settings`` vive en conftest.py (compartido con
# test_weather.py).


def test_set_get_roundtrip(memory_settings):
    """set/get con upsert y valores por defecto cuando la clave no existe."""
    assert settings_mod.get_setting("clave") is None
    assert settings_mod.get_setting("clave", "por-defecto") == "por-defecto"

    settings_mod.set_setting("clave", "valor")
    assert settings_mod.get_setting("clave") == "valor"

    settings_mod.set_setting("clave", "valor-2")  # actualiza, no duplica
    assert settings_mod.get_setting("clave") == "valor-2"


def test_get_float_lee_y_defiende_lo_corrupto(memory_settings):
    """get_float: texto numérico → float; clave ausente o rara → default.

    La tabla guarda TEXT: los umbrales de muestreo (Configuración) leen con
    éste y jamás deben reventar por una clave sucia.
    """
    assert settings_mod.get_float("umbral", 1.0) == 1.0  # ausente → default

    settings_mod.set_setting("umbral", "0.75")
    assert settings_mod.get_float("umbral", 1.0) == 0.75

    settings_mod.set_setting("umbral", "no-numérico")
    assert settings_mod.get_float("umbral", 1.0) == 1.0  # corrupto → default


def test_api_key_roundtrip(memory_settings):
    """save_api_key escribe en settings y load_api_key lo lee (o None)."""
    assert weather_base.load_api_key("clear_outside_api_key") is None

    weather_base.save_api_key("clear_outside_api_key", "abc123")
    assert weather_base.load_api_key("clear_outside_api_key") == "abc123"

    # Cada proveedor usa su propia clave: no se pisan.
    assert weather_base.load_api_key("meteoblue_api_key") is None
