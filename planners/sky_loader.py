"""Datos del planetario: estrellas HYG y objetos del catálogo.

La UI del planetario pinta lo que aquí devuelva: la consulta y la
conversión (RA en horas → grados) viven en la capa de datos, no en
``ui/`` (regla del proyecto: sin SQL en la interfaz).
"""
from __future__ import annotations

import numpy as np

from db.catalog_editions import CatalogUnavailableError, catalog_snapshot, read_rows
from db.connection import get_connection

_STAR_SQL = "SELECT ra_hours, dec_deg, magnitude, color FROM stars ORDER BY magnitude"
_OBJECT_SQL = ("SELECT object_id, catalog, ra_hours, dec_deg, magnitude FROM catalog"
               " WHERE ra_hours IS NOT NULL AND dec_deg IS NOT NULL")


def load_stars() -> dict[str, np.ndarray]:
    """Estrellas HYG (mag ≤ 8) como arrays: ra(deg), dec(deg), mag, clase espectral."""
    return _stars(read_rows(get_connection(), _STAR_SQL))


def _stars(rows) -> dict:
    """Convierte filas estelares en arrays, conservando el estado vacío cuando falta una edición."""
    if not rows:
        empty = np.empty(0)
        return {"ra": empty, "dec": empty, "mag": empty, "spect": []}
    return {
        "ra": np.array([r[0] * 15.0 for r in rows]),
        "dec": np.array([r[1] for r in rows]),
        "mag": np.array([r[2] if r[2] is not None else 99.0 for r in rows]),
        "spect": [r[3] for r in rows],
    }


def load_objects() -> dict:
    """Objetos deep-sky del catálogo global (las regiones NO se pintan aquí)."""
    return _objects(read_rows(get_connection(), _OBJECT_SQL))


def _objects(rows) -> dict:
    """Convierte filas de espacio profundo sin añadir regiones personales ni coordenadas inventadas."""
    if not rows:
        empty = np.empty(0)
        return {"ra": empty, "dec": empty, "ids": [], "catalogs": [], "mag": empty}
    return {
        "ra": np.array([r[2] * 15.0 for r in rows]),
        "dec": np.array([r[3] for r in rows]),
        "ids": [r[0] for r in rows],
        "catalogs": [r[1] for r in rows],
        "mag": np.array([r[4] if r[4] is not None else 99.0 for r in rows]),
    }


def load_sky() -> tuple[dict, dict]:
    """Fija una sola edición para estrellas y objetos de una carta; una activación concurrente no los mezcla."""
    try:
        with catalog_snapshot(get_connection()) as catalog:
            stars = catalog.execute(_STAR_SQL).fetchall()
            objects = catalog.execute(_OBJECT_SQL).fetchall()
    except CatalogUnavailableError:
        stars, objects = [], []
    return _stars(stars), _objects(objects)
