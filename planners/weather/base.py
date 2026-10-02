"""Interfaz común de los proveedores de clima/seeing."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class WeatherForecast:
    """Pronóstico para una fecha y ubicación."""

    provider: str
    date_iso: str
    cloud_cover_pct: list[float] = field(default_factory=list)  # por franja horaria
    wind_kmh: list[float] = field(default_factory=list)
    humidity_pct: list[float] = field(default_factory=list)
    seeing_arcsec: list[float] = field(default_factory=list)     # Meteoblue
    available: bool = True      # False cuando falta API key o hay error
    note: str = ""              # aviso legible, p. ej. 'falta API key'


class WeatherProvider(ABC):
    """Interfaz de un proveedor de datos atmosféricos."""

    #: Clave en la tabla ``settings`` donde se guarda la API key (si aplica).
    settings_key: str

    @abstractmethod
    def forecast(self, latitude: float, longitude: float, date_iso: str) -> WeatherForecast:
        """Devuelve el pronóstico. Sin API key debe devolver ``available=False``
        con un ``note`` legible, sin lanzar excepciones (decisión: integraciones
        funcionan como mock hasta que el usuario añada sus keys)."""


def load_api_key(settings_key: str) -> str | None:
    """Lee la API key desde la tabla ``settings``; ``None`` si no está definida."""
    from db.connection import get_connection

    row = get_connection().execute(
        "SELECT value FROM settings WHERE key = ?", (settings_key,)
    ).fetchone()
    return row["value"] if row else None
