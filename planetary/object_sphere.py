"""Esfera de objetos: puntos de los catálogos sobre la segunda esfera.

Capa transparente con los puntos de Messier/NGC/IC/LDN; el usuario la mira
desde el centro de las dos esferas concéntricas.
"""
from .catalog import CelestialObject


class ObjectSphere:
    """Esfera con los puntos de los objetos de los catálogos."""

    def __init__(self, objects: list[CelestialObject] | None = None) -> None:
        self.objects = objects or []

    def visible_points(self, ra_hours: float, dec_deg: float, fov_deg: float) -> list[CelestialObject]:
        """Objetos dentro del campo de visión actual."""
        raise NotImplementedError

    def pick(self, x: float, y: float) -> CelestialObject | None:
        """Objeto más cercano a una posición de pantalla (selección con clic)."""
        raise NotImplementedError
