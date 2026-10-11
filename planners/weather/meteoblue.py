"""Meteoblue — seeing astronómico (arcseg).

Requiere API key (se guarda en ``settings`` con la clave ``meteoblue_api_key``).
Sin key devuelve un pronóstico con ``available=False`` en lugar de fallar.
"""
from .base import WeatherForecast, WeatherProvider


class Meteoblue(WeatherProvider):
    """Proveedor de seeing (hilo puro: no toca la BD, A-32)."""

    settings_key = "meteoblue_api_key"

    def forecast(
        self,
        latitude: float,
        longitude: float,
        date_iso: str,
        api_key: str | None = None,
    ) -> WeatherForecast:
        """Seeing (arcseg) de Meteoblue para ``date_iso``; mismo contrato que Clear Outside.

        Sin key —o con la llamada pendiente— devuelve ``available=False`` con
        nota explicativa en vez de fallar.
        """
        if not api_key:
            return WeatherForecast(
                provider="meteoblue",
                date_iso=date_iso,
                available=False,
                note="Falta la API key de Meteoblue (Ajustes > Clima)",
            )
        # TODO: llamada real a la API de Meteoblue. Mientras tanto,
        # no se lanza: la UI debe seguir funcionando con la key guardada.
        return WeatherForecast(
            provider="meteoblue",
            date_iso=date_iso,
            available=False,
            note="API key de Meteoblue guardada; la llamada real está pendiente",
        )
