"""Proveedores de clima/seeing: Clear Outside (clima) y Meteoblue (seeing).

Uso típico::

    from planners.weather import ClearOutside, Meteoblue

    clima = ClearOutside().forecast(lat, lon, "2026-10-02")
    if clima.available:
        nubes = clima.cloud_cover_pct[0]

Sin API key guardada (o con error de red) los proveedores devuelven
``available=False`` con un ``note`` legible: **nunca lanzan excepción**, para
que la UI pueda mostrar "Sin datos" sin bloquear el resto del planificador.
"""
from .base import WeatherForecast, WeatherProvider, load_api_key, transparency
from .clear_outside import ClearOutside
from .meteoblue import Meteoblue

__all__ = [
    "ClearOutside",
    "Meteoblue",
    "WeatherForecast",
    "WeatherProvider",
    "load_api_key",
    "transparency",
]
