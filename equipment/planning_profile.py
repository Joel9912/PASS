"""Tiempos declarados por equipo: datos operativos, no órdenes de control del hardware."""

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PlanningProfile:
    """Instantánea de maniobras y enfoque; None conserva un tiempo no informado."""

    version: int = 1
    meridian_flip: bool = False
    meridian_s: float = 300
    pause_s: float | None = None
    filter_s: float | None = None
    slew_s: float | None = None
    focus_s: float | None = None
    focus_start: bool = False
    focus_filter: bool = False
    focus_flip: bool = False
    focus_interval_s: float | None = None
    focus_frames: int | None = None

    def validate(self):
        """No confunde cero explícito, ausencia y valores imposibles de representar."""
        if type(self.version) is not int or self.version != 1:
            raise ValueError("Perfil operativo de versión incompatible.")
        for name in ("meridian_flip", "focus_start", "focus_filter", "focus_flip"):
            if type(getattr(self, name)) is not bool:
                raise ValueError("Activación operativa inválida.")
        for name in ("meridian_s", "pause_s", "filter_s", "slew_s", "focus_s", "focus_interval_s"):
            value = getattr(self, name)
            if value is not None and (type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 86400):
                raise ValueError("Los tiempos operativos deben ser finitos entre 0 y 86400 segundos.")
        if self.meridian_s is None or self.meridian_flip and self.meridian_s <= 0:
            raise ValueError("El cambio de meridiano necesita una duración positiva.")
        if self.focus_interval_s is not None and self.focus_interval_s <= 0:
            raise ValueError("El intervalo de enfoque debe ser positivo.")
        if self.focus_frames is not None and (type(self.focus_frames) is not int or not 1 <= self.focus_frames <= 1_000_000):
            raise ValueError("El contador de enfoque debe ser un entero positivo.")
        if (self.focus_start or self.focus_filter or self.focus_flip or self.focus_interval_s or self.focus_frames) and not self.focus_s:
            raise ValueError("Configura una duración positiva para las rutinas de autoenfoque activas.")
        return self

    def data(self):
        """Entrega datos serializables sin perder ausencias ni mutar la instantánea."""
        self.validate()
        return asdict(self)


def profile_from_data(data):
    """Lee un perfil conocido; no convierte un perfil corrupto en tiempos cero."""
    if data is None:
        return PlanningProfile()
    if not isinstance(data, dict) or set(data) != set(PlanningProfile.__dataclass_fields__):
        raise ValueError("Perfil operativo incompatible.")
    return PlanningProfile(**data).validate()
