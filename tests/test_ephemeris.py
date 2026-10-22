"""Modelo fijado por cálculo, cachés independientes y estado Astropy aislado; SPK propio sin precisión física pretendida."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Event

import numpy as np
import pytest
from astropy.coordinates import solar_system_ephemeris
from astropy.utils import iers

from planners import capture_plan, ephemeris, transit
from tests.spk_factory import synthetic_spk


@pytest.fixture
def models(tmp_path):
    """Dos kernels originales deliberadamente diferentes para observar contaminación de modelo o caché."""
    result = []
    for index in range(2):
        data = synthetic_spk(value=1000 * (index + 1))
        path = tmp_path / f"synthetic-{index}.bsp"
        path.write_bytes(data)
        result.append(ephemeris.EphemerisModel(path, f"edition-{index}", sha256(data).hexdigest(), f"Sintético {index}"))
    return result


def test_sol_y_luna_usan_kernel_y_cache_separa_ediciones(models, monkeypatch):
    """El modo externo no llama get_sun y cambiar modelo no reutiliza la serie de la edición anterior."""
    def forbidden(*args, **kwargs):
        """Detecta mezcla accidental del Sol ERFA con una Luna externa."""
        pytest.fail("No se debe usar get_sun en el modo SPK")

    monkeypatch.setattr(transit, "get_sun", forbidden)
    monkeypatch.setattr(transit, "_MOON_SUN_CACHE", {})
    curves = []
    for model in models:
        with ephemeris.model_scope(model):
            curve = transit.night_curve(4, 40, 40, -3, "2020-01-01")
            info = transit.night_info(40, -3, "2020-01-01")
            assert curve.accuracy.sun_model == model.label == info.accuracy.model_label
            assert np.isfinite(curve.sun_altitudes).all()
            curves.append(curve)
    assert len(transit._MOON_SUN_CACHE) == 2
    assert not np.array_equal(curves[0].moon_separations, curves[1].moon_separations)
    assert solar_system_ephemeris.get() == "builtin"
    assert ephemeris.current_model() is None


def test_scope_restaura_estado_y_cierra_kernel_si_hay_error(models):
    """Un error de cálculo no deja el siguiente recorrido con un modelo ajeno o un fichero bloqueado en Windows."""
    with pytest.raises(RuntimeError, match="Fallo deliberado"), ephemeris.model_scope(models[0]):
        assert solar_system_ephemeris.get() == str(models[0].path.absolute())
        raise RuntimeError("Fallo deliberado")
    assert ephemeris.current_model() is None and solar_system_ephemeris.get() == "builtin"
    models[0].path.unlink()


def test_scope_no_admite_cambio_anidado(models):
    """Una operación compuesta no cambia de modelo a mitad aunque otra selección sea válida por separado."""
    with ephemeris.model_scope(models[0]):
        with pytest.raises(ValueError, match="mezclar"), ephemeris.model_scope(models[1]):
            pytest.fail("No debe entrar")
        assert ephemeris.current_model() == models[0]


def test_kernel_perdido_no_llama_builtin_ni_descarga(models, monkeypatch):
    """Desaparecer el recurso entre validación y apertura es error explícito, no otra efeméride."""
    models[0].path.unlink()
    monkeypatch.setattr(ephemeris, "selected_model", lambda: models[0])
    with pytest.raises(ValueError, match="no está disponible"):
        transit.night_info(40, -3, "2020-01-01")
    assert solar_system_ephemeris.get() == "builtin" and ephemeris.current_model() is None


def test_workers_serializan_astropy_y_no_comparten_contexto(models):
    """Dos cálculos concurrentes mantienen su propia selección y no dejan estado externo al terminar."""
    entered, release, attempted = Event(), Event(), Event()

    def first():
        """Mantiene ocupado el contexto para comprobar la segunda entrada sin temporizadores arbitrarios."""
        with ephemeris.model_scope(models[0]):
            entered.set()
            assert release.wait(10)
            assert ephemeris.current_model() == models[0]
            assert solar_system_ephemeris.get() == str(models[0].path.absolute())

    def second():
        """Pide otro modelo desde su propio hilo y lo comprueba al conseguir el candado."""
        attempted.set()
        with ephemeris.model_scope(models[1]):
            assert ephemeris.current_model() == models[1]
            assert solar_system_ephemeris.get() == str(models[1].path.absolute())

    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(first)
        try:
            assert entered.wait(10)
            b = executor.submit(second)
            assert attempted.wait(10)
            assert not b.done()
            assert ephemeris.current_model() is None
        finally:
            release.set()
        a.result(timeout=10)
        b.result(timeout=10)
    assert solar_system_ephemeris.get() == "builtin"


def test_best_dates_fija_seleccion_una_vez_para_todo_el_recorrido(models, monkeypatch):
    """Ranking, efemérides y curvas anidadas comparten modelo incluso si cambia la selección al consultar de nuevo."""
    calls = []

    def select():
        """Una segunda consulta devolvería otra edición, que no debe entrar en este recorrido."""
        calls.append(len(calls))
        return models[min(len(calls) - 1, 1)]

    monkeypatch.setattr(ephemeris, "selected_model", select)
    monkeypatch.setattr(transit, "_MOON_SUN_CACHE", {})
    capture_plan.best_dates(4, 40, 40, -3, "2020-01-01", date_range_days=2, top_n=1)
    assert calls == [0]
    assert all(key[-1] == models[0].cache_key for key in transit._MOON_SUN_CACHE)


def test_modelo_previo_remoto_no_se_activa_ni_restaura_por_red(monkeypatch):
    """Rechaza estados externos que podrían activar la descarga automática propia de Astropy."""
    monkeypatch.setattr(solar_system_ephemeris, "_value", "de999")
    with pytest.raises(ValueError, match="no es local"), ephemeris.model_scope(ephemeris.EphemerisModel()):
        pytest.fail("No debe entrar")


def test_calculo_offline_no_caduca_por_predicciones_locales_y_restaura_configuracion():
    """El rango futuro funciona fuera de la fixture global, con aviso IERS y sin reactivar descargas."""
    import warnings

    with (iers.conf.set_temp("auto_max_age", 30), iers.conf.set_temp("auto_download", True),
          warnings.catch_warnings(record=True)):
        info = transit.night_info(40, -3, "2100-12-31")
        assert info.accuracy.orientation == "outside"
        assert np.isfinite(info.moon_illumination)
        assert iers.conf.auto_max_age == 30 and iers.conf.auto_download
