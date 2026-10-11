# planners/weather/

## Qué es
Integración de datos atmosféricos para el Planificador: **Clear Outside** (pronóstico astronómico: nubes, viento, humedad) y **Meteoblue** (seeing en arcseg).

## Estado actual
- `base.py` — interfaz `WeatherProvider` (con `forecast(..., api_key)`), dataclass `WeatherForecast` y lectura/escritura de API keys (`load_api_key` / `save_api_key`) en `settings` vía `db.settings`: **la key la lee quien llama, en su hilo**; los proveedores jamás tocan la BD.
- `clear_outside.py` y `meteoblue.py` — implementaciones **en modo mock** y **hilo puro** (sin `settings`): sin key devuelven `available=False` con aviso legible; **con key por parámetro también** devuelven `available=False` con nota «llamada real pendiente» (nunca lanzan: la UI no debe crashear al guardar una key). Las llamadas reales están pendientes.
- `__init__.py` — reexporta `ClearOutside`, `Meteoblue`, `WeatherForecast`, `WeatherProvider` y `load_api_key`, para que la UI haga un único `from planners.weather import ...`.

## Qué hacer aquí
- Todo proveedor implementa `WeatherProvider.forecast()` y su `settings_key`.
- **Sin SQL dentro del proveedor**: corre en el hilo del `QThreadPool` (A-32) y SQLite exige el hilo que creó la conexión — quien llama lee la key en el suyo (`load_api_key`) y se la pasa.
- Sin key → respuesta con `available=False` + `note`; **nunca** romper el resto del Planificador.
- Las keys se guardan en la tabla `settings` (nunca en código ni en el repositorio).

## Planes futuros
1. Llamada real a la API de Clear Outside (clima).
2. Llamada real a la API de Meteoblue (seeing).
3. Combinar ambos pronósticos en el ranking (`planners/ranking.py`).
