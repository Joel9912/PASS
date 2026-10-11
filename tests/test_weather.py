"""Proveedores de clima: nunca lanzan, con o sin API key, y en cualquier hilo.

Con key pero sin llamada real implementada (mock), ``forecast`` debe
devolver ``available=False`` con nota legible: la UI de Búsqueda no
debe crashear al guardar una key en Configuración.

La key la lee la UI en su hilo y se la pasa por parámetro (A-32): los
proveedores son código de hilo puro y jamás tocan ``settings``.
"""
import inspect
import threading

from planners.weather import clear_outside, meteoblue
from planners.weather.base import load_api_key, save_api_key
from planners.weather.clear_outside import ClearOutside
from planners.weather.meteoblue import Meteoblue

DATE = "2026-10-02"
LAT, LON = 10.0, -84.0


def test_forecast_without_key_is_not_available(memory_settings):
    """Sin key: available=False y nota que dice qué falta (sin excepción)."""
    clear = ClearOutside().forecast(LAT, LON, DATE)
    meteo = Meteoblue().forecast(LAT, LON, DATE)

    for forecast in (clear, meteo):
        assert forecast.available is False
        assert "API key" in forecast.note


def test_forecast_with_key_does_not_raise(memory_settings):
    """Con key: la llamada real está pendiente → nota, NO NotImplementedError.

    Simula el camino de la UI: guardar en ``settings`` (hilo principal),
    leerla con ``load_api_key`` y pasarla a ``forecast`` por parámetro.
    """
    save_api_key("clear_outside_api_key", "co-demo")
    save_api_key("meteoblue_api_key", "mb-demo")

    clear = ClearOutside().forecast(
        LAT, LON, DATE, api_key=load_api_key("clear_outside_api_key")
    )
    meteo = Meteoblue().forecast(
        LAT, LON, DATE, api_key=load_api_key("meteoblue_api_key")
    )

    for forecast in (clear, meteo):
        assert forecast.available is False
        assert "pendiente" in forecast.note
        assert not forecast.note.startswith("Falta")


def test_forecast_en_hilo_secundario_no_toca_bd(memory_settings):
    """Regresión A-32: el pronóstico corre en un hilo que no creó la conexión.

    Antes ``forecast`` leía ``settings`` desde el worker del clima y
    SQLite lanzaba ``ProgrammingError`` («SQLite objects created in a
    thread can only be used in that same thread»): la app se caía y las
    tarjetas nunca se rellenaban. La key viaja ahora por parámetro, así
    que el proveedor no necesita la BD en ningún hilo.
    """
    save_api_key("clear_outside_api_key", "co-demo")
    save_api_key("meteoblue_api_key", "mb-demo")
    claves = (
        load_api_key("clear_outside_api_key"),
        load_api_key("meteoblue_api_key"),
    )

    resultados: list = []
    errores: list = []

    def traer():
        """El camino exacto del worker: proveedores sin tocar la BD."""
        try:
            resultados.append(
                ClearOutside().forecast(LAT, LON, DATE, api_key=claves[0])
            )
            resultados.append(Meteoblue().forecast(LAT, LON, DATE, api_key=claves[1]))
        except Exception as exc:  # el hilo no traga errores: los sube al test
            errores.append(exc)

    hilo = threading.Thread(target=traer)
    hilo.start()
    hilo.join(timeout=10)

    assert not errores, f"el proveedor falló en el hilo secundario: {errores}"
    assert len(resultados) == 2
    for forecast in resultados:
        assert "guardada" in forecast.note


def test_proveedores_no_importan_bd():
    """Pin del invariante: los proveedores son código de hilo puro (A-03/A-32).

    Si algún día vuelven a importar ``load_api_key``, el crashe en el
    QThreadPool vuelve con ellos: settings la lee quien llama.
    """
    for modulo in (clear_outside, meteoblue):
        assert "load_api_key" not in inspect.getsource(modulo)
        assert "db." not in inspect.getsource(modulo)
