"""Clear Outside — pronóstico astronómico (nubes, viento, humedad).

Requiere API key (se guarda en ``settings`` con la clave ``clear_outside_api_key``).
Sin key devuelve un pronóstico con ``available=False`` en lugar de fallar.
"""
from .base import WeatherForecast, WeatherProvider, load_api_key


class ClearOutside(WeatherProvider):
    """Proveedor de clima astronómico."""

    settings_key = "clear_outside_api_key"

    def forecast(self, latitude: float, longitude: float, date_iso: str) -> WeatherForecast:
        key = load_api_key(self.settings_key)
        if not key:
            return WeatherForecast(
                provider="clear_outside",
                date_iso=date_iso,
                available=False,
                note="Falta la API key de Clear Outside (Ajustes > Clima)",
            )
        # TODO: llamada real a la API de Clear Outside. Mientras tanto,
        # no se lanza: la UI debe seguir funcionando con la key guardada.
        return WeatherForecast(
            provider="clear_outside",
            date_iso=date_iso,
            available=False,
            note="API key de Clear Outside guardada; la llamada real está pendiente",
        )
