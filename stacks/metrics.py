"""Métricas y auditoría de los lights registrados.

SirIL entrega métricas al registrar: FWHM, redondez (roundness), transparencia
y otras. Con ellas se:
- grafica el comportamiento a lo largo de todas las sesiones,
- detecta valores extremos,
- hace un ranking de frames y se descartan los peores antes del apilado final.
"""
from dataclasses import dataclass


@dataclass
class FrameMetrics:
    """Métricas de un light registrado por SirIL."""

    path: str
    session: str
    fwhm: float            # píxeles
    roundness: float       # 0..1 (1 = perfectamente redondo)
    transparency: float    # 0..1
    background: float      # nivel de fondo
    weighted: float        # peso asignado para el apilado


def extract_metrics(session_name: str) -> list[FrameMetrics]:
    """Extrae las métricas que SirIL genera durante el registro."""
    raise NotImplementedError


def outliers(metrics: list[FrameMetrics], sigma: float = 3.0) -> list[FrameMetrics]:
    """Marca frames con valores extremos (fuera de `sigma` desviaciones)."""
    raise NotImplementedError


def reject_list(metrics: list[FrameMetrics], sigma: float = 3.0) -> list[str]:
    """Devuelve la lista de frames a descartar del apilado final."""
    raise NotImplementedError
