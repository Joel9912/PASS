"""settings: claves-valor, API keys del clima y ruta de SirIL."""
from db import settings as settings_mod
from planners.weather import base as weather_base
from stacks import siril_finder

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


def test_find_siril_ignores_empty_saved_path(memory_settings, monkeypatch):
    """Una ruta vacía guardada cuenta como «no guardado»."""
    monkeypatch.setattr(siril_finder, "which", lambda _name: None)
    siril_finder.save_user_path("")
    assert siril_finder.find_siril() is None


def test_siril_version_reads_first_line(memory_settings, monkeypatch):
    """siril_version devuelve la primera línea de `--version` si todo va bien."""
    import subprocess as sp

    def fake_run(_cmd, **_kwargs):
        """Sustituto de `subprocess.run`: SirIL responde con la 1.2.1 en stdout."""
        return sp.CompletedProcess(
            _cmd, 0, stdout="Siril 1.2.1\notra línea\n", stderr=""
        )

    monkeypatch.setattr(siril_finder.subprocess, "run", fake_run)
    assert siril_finder.siril_version("C:/siril/siril-cli.exe") == "Siril 1.2.1"


def test_siril_version_none_on_failure(memory_settings, monkeypatch):
    """Fallo de ejecución (código ≠ 0 o error del sistema) → None, sin excepciones."""
    import subprocess as sp

    def fake_run(_cmd, **_kwargs):
        """Sustituto de `subprocess.run`: SirIL devuelve código de salida 1 (fallo)."""
        return sp.CompletedProcess(_cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(siril_finder.subprocess, "run", fake_run)
    assert siril_finder.siril_version("malo.exe") is None

    def raise_oserror(_cmd, **_kwargs):
        """Sustituto de `subprocess.run` que revienta como si SirIL no existiera."""
        raise OSError("no existe")

    monkeypatch.setattr(siril_finder.subprocess, "run", raise_oserror)
    assert siril_finder.siril_version("otro.exe") is None
