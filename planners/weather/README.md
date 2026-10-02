# planners/weather/

## Qué es
Integración de datos atmosféricos para el Planificador: **Clear Outside** (pronóstico astronómico: nubes, viento, humedad) y **Meteoblue** (seeing en arcseg).

## Estado actual
- `base.py` — interfaz `WeatherProvider`, dataclass `WeatherForecast` y lectura de API keys desde `settings`.
- `clear_outside.py` y `meteoblue.py` — implementaciones **en modo mock**: sin API key devuelven `available=False` con aviso legible (no lanzan excepciones). Las llamadas reales están pendientes.
- `__init__.py` — reexporta `ClearOutside`, `Meteoblue`, `WeatherForecast`, `WeatherProvider` y `load_api_key`, para que la UI haga un único `from planners.weather import ...`.

## Qué hacer aquí
- Todo proveedor implementa `WeatherProvider.forecast()` y su `settings_key`.
- Sin key → respuesta con `available=False` + `note`; **nunca** romper el resto del Planificador.
- Las keys se guardan en la tabla `settings` (nunca en código ni en el repositorio).

## Planes futuros
1. Llamada real a la API de Clear Outside (clima).
2. Llamada real a la API de Meteoblue (seeing).
3. Combinar ambos pronósticos en el ranking (`planners/ranking.py`).
