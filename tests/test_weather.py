"""Proveedores de clima: nunca lanzan, con o sin API key.

Con key pero sin llamada real implementada (mock), ``forecast`` debe
devolver ``available=False`` con nota legible: la UI de Búsqueda no
debe crashear al guardar una key en Configuración.
"""
from planners.weather.base import save_api_key
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
    """Con key: la llamada real está pendiente → nota, NO NotImplementedError."""
    save_api_key("clear_outside_api_key", "co-demo")
    save_api_key("meteoblue_api_key", "mb-demo")

    clear = ClearOutside().forecast(LAT, LON, DATE)
    meteo = Meteoblue().forecast(LAT, LON, DATE)

    for forecast in (clear, meteo):
        assert forecast.available is False
        assert "pendiente" in forecast.note
        assert not forecast.note.startswith("Falta")
