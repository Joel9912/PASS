"""Datos del planetario: estrellas HYG y objetos del catálogo.

La UI del planetario pinta lo que aquí devuelva: la consulta y la
conversión (RA en horas → grados) viven en la capa de datos, no en
``ui/`` (regla del proyecto: sin SQL en la interfaz).
"""
from __future__ import annotations

import numpy as np

from db.catalog_editions import CatalogUnavailableError, catalog_snapshot, read_rows
from db.catalog_records import has_records
from db.connection import get_connection
from planners.celestial_search import designation_key

_STAR_SQL = "SELECT ra_hours, dec_deg, magnitude, color FROM stars ORDER BY magnitude"
_OBJECT_SQL = ("SELECT object_id, catalog, ra_hours, dec_deg, magnitude, rowid FROM catalog"
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
    personal = get_connection()
    try:
        with catalog_snapshot(personal) as catalog:
            claims, identities = _target_claims(catalog, identified=catalog is not personal)
            return _objects(catalog.execute(_OBJECT_SQL).fetchall(), claims, identities)
    except CatalogUnavailableError:
        return _objects([])


def _objects(rows, claims=(), identities=()) -> dict:
    """Convierte filas de espacio profundo sin añadir regiones personales ni coordenadas inventadas."""
    positions = {row[5]: index for index, row in enumerate(rows)}
    candidates = {}
    for designation, namespace, row_id in claims:
        key = designation_key(designation)
        for target in ((key, None), (key, namespace)):
            candidates.setdefault(target, set()).add(row_id)
    targets = {key: positions.get(next(iter(ids))) if len(ids) == 1 else None
               for key, ids in candidates.items()}
    identity_targets = {pass_id: positions.get(row_id) for pass_id, row_id in identities}
    if not rows:
        empty = np.empty(0)
        return {"ra": empty, "dec": empty, "ids": [], "catalogs": [], "mag": empty,
                "targets": targets, "identities": identity_targets}
    return {
        "ra": np.array([r[2] * 15.0 for r in rows]),
        "dec": np.array([r[3] for r in rows]),
        "ids": [r[0] for r in rows],
        "catalogs": [r[1] for r in rows],
        "mag": np.array([r[4] if r[4] is not None else 99.0 for r in rows]),
        "targets": targets,
        "identities": identity_targets,
    }


def _target_claims(catalog, *, identified: bool) -> tuple[list, list]:
    """Conserva candidaturas incluso sin posición, para que no parezcan inequívocas solo por no poder pintarlas."""
    claims = list(catalog.execute("SELECT object_id,catalog,rowid FROM catalog"))
    identities = []
    if identified and has_records(catalog):
        identities = list(catalog.execute("SELECT pass_id,row_id FROM objects WHERE row_kind='catalog'"))
        claims.extend(catalog.execute(
            "SELECT d.designation,d.namespace,c.rowid FROM designations d JOIN objects o ON o.pass_id=d.pass_id "
            "JOIN catalog c ON o.row_kind='catalog' AND o.row_id=c.rowid"
        ))
    return claims, identities


def target_index(objects: dict, designation: str, namespace: str | None = None, *, pass_id: str | None = None) -> int | None:
    """Resuelve solo en los datos ya cargados, sin consultar otra edición ni escoger entre alias ambiguos."""
    if pass_id is not None:
        return objects.get("identities", {}).get(pass_id)
    key = designation_key(designation)
    if "targets" in objects:
        return objects["targets"].get((key, namespace))
    matches = [index for index, name in enumerate(objects["ids"])
               if designation_key(name) == key and (namespace is None or objects["catalogs"][index] == namespace)]
    return matches[0] if len(matches) == 1 else None


def load_sky() -> tuple[dict, dict]:
    """Fija una sola edición para estrellas y objetos de una carta; una activación concurrente no los mezcla."""
    personal = get_connection()
    try:
        with catalog_snapshot(personal) as catalog:
            stars = catalog.execute(_STAR_SQL).fetchall()
            objects = catalog.execute(_OBJECT_SQL).fetchall()
            claims, identities = _target_claims(catalog, identified=catalog is not personal)
    except CatalogUnavailableError:
        stars, objects, claims, identities = [], [], [], []
    return _stars(stars), _objects(objects, claims, identities)
