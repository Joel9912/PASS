"""Clear Outside — pronóstico astronómico (nubes, viento, humedad).

Requiere API key (se guarda en ``settings`` con la clave ``clear_outside_api_key``).
Sin key devuelve un pronóstico con ``available=False`` en lugar de fallar.
"""
from .base import WeatherForecast, WeatherProvider


class ClearOutside(WeatherProvider):
    """Proveedor de clima astronómico (hilo puro: no toca la BD, A-32)."""

    settings_key = "clear_outside_api_key"

    def forecast(
        self,
        latitude: float,
        longitude: float,
        date_iso: str,
        api_key: str | None = None,
    ) -> WeatherForecast:
        """Pronóstico astronómico (nubes/viento/humedad) de Clear Outside.

        Sin key —o mientras la llamada real siga pendiente— devuelve
        ``available=False`` con nota: el clima nunca debe romper la UI.
        """
        if not api_key:
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
