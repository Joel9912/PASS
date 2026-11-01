"""Contratos del reparto por visitas y eventos, separados de Qt y de las conexiones de datos."""

from dataclasses import dataclass
from datetime import datetime
from functools import cached_property

import numpy as np


@dataclass(frozen=True)
class SkyTrack:
    """Altura muestreada y tránsito superior por tesela para valorar candidatos reales."""

    objective: str
    tile: int
    night: str
    times: tuple[datetime, ...]
    altitudes: tuple[float, ...]
    transits: tuple[datetime, ...] = ()

    @cached_property
    def interpolation(self):
        """Prepara vectores readonly una vez, evitando convertir la malla en cada candidato o toma."""
        seconds = np.asarray([(moment-self.times[0]).total_seconds() for moment in self.times])
        altitudes = np.asarray(self.altitudes)
        seconds.setflags(write=False)
        altitudes.setflags(write=False)
        return seconds, altitudes


@dataclass(frozen=True)
class Operation:
    """Tiempo ocupado que nunca se suma a la integración fotográfica."""

    kind: str
    night: str
    start: datetime
    end: datetime
    objective: str
    tile: int
    filter_name: str


@dataclass(frozen=True)
class Visit:
    """Una presencia continua del objeto en una noche, incluyendo maniobras internas necesarias."""

    objective: str
    night: str
    start: datetime
    end: datetime
    integration_s: int
    reason: str


@dataclass(frozen=True)
class Alternative:
    """Propuesta seleccionable; excepciones no se adoptan automáticamente al calcular."""

    key: str
    label: str
    allocations: tuple
    balances: tuple
    operations: tuple[Operation, ...]
    visits: tuple[Visit, ...]
    notes: tuple[str, ...]
    requires_consent: bool = False
