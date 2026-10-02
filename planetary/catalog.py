"""Carga y consulta de los catálogos de objetos: Messier, NGC, IC, LDN."""
from dataclasses import dataclass

#: Catálogos soportados.
CATALOGS: tuple[str, ...] = ("messier", "ngc", "ic", "ldn")


@dataclass
class CelestialObject:
    """Objeto del catálogo."""

    object_id: str        # p. ej. 'M31', 'NGC 7000'
    catalog: str          # 'messier' | 'ngc' | 'ic' | 'ldn'
    ra_hours: float       # ascensión recta (horas)
    dec_deg: float        # declinación (grados)
    magnitude: float | None
    type: str             # 'galaxia' | 'nebulosa' | 'cúmulo' | ...
    size_arcmin: float | None


def load(catalog: str) -> list[CelestialObject]:
    """Carga un catálogo completo desde sus ficheros de datos."""
    raise NotImplementedError


def by_id(object_id: str, catalog: str) -> CelestialObject | None:
    """Busca un objeto concreto por su identificador."""
    raise NotImplementedError
