"""Interfaz común de los proveedores de clima/seeing."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from db.settings import get_setting, set_setting


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
    return get_setting(settings_key)


def save_api_key(settings_key: str, value: str) -> None:
    """Guarda la API key en la tabla ``settings`` (nunca en código ni en el repo)."""
    set_setting(settings_key, value)


def transparency(cloud_pct: float | None) -> str:
    """Transparencia cualitativa del cielo a partir de la nubosidad (%).

    Regla de negocio que antes vivía en la UI (`widgets.py`, A-31): sin
    nubosidad no se inventa cualitativa — «--».
    """
    if cloud_pct is None:
        return "--"
    if cloud_pct <= 10:
        return "Excelente"
    if cloud_pct <= 30:
        return "Buena"
    if cloud_pct <= 60:
        return "Regular"
    return "Mala"
