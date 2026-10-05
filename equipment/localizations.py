"""CRUD de localizaciones geográficas (tabla ``locations``)."""
import json

from db.connection import get_connection

from . import images
from .models import DIRECTIONS, LP_LEVELS, OBSTACLE_TYPES, Location
from .validaciones import validar_ubicacion


def _obstacles_desde(valor: str | None) -> dict[str, list[str]]:
    """Horizonte con las 8 direcciones; JSON roto o claves ausentes → vacío.

    Carga defensiva: una fila corrupta (o con tipos fuera de catálogo) nunca
    lanza excepción al pintar la lista — se queda en el defecto y la
    validación de guardado ya impedió escribirla así.
    """
    try:
        crudo = json.loads(valor) if valor else {}
    except (json.JSONDecodeError, TypeError):
        crudo = {}
    if not isinstance(crudo, dict):
        crudo = {}
    horizonte: dict[str, list[str]] = {}
    for direccion in DIRECTIONS:
        tipos = crudo.get(direccion, [])
        if not isinstance(tipos, list):
            tipos = []
        horizonte[direccion] = [t for t in tipos if t in OBSTACLE_TYPES]
    return horizonte


def _lp_desde(valor: str | None) -> dict[str, int]:
    """CL por dirección con las 8 claves y niveles 0-3; lo raro → 0."""
    try:
        crudo = json.loads(valor) if valor else {}
    except (json.JSONDecodeError, TypeError):
        crudo = {}
    if not isinstance(crudo, dict):
        crudo = {}
    niveles: dict[str, int] = {}
    for direccion in DIRECTIONS:
        try:
            nivel = int(crudo.get(direccion, 0))
        except (TypeError, ValueError):
            nivel = 0
        niveles[direccion] = nivel if nivel in LP_LEVELS else 0
    return niveles


def _sitio(location: Location) -> tuple[str, str]:
    """El bloque de sitio serializado a JSON (las 8 direcciones, ya validado)."""
    return json.dumps(location.obstacles), json.dumps(location.lp)


def _sync_lp_map(location_id: int, lp_map: str | None) -> None:
    """Imagen única de CL: ``[lp_map]`` si hay, ``[]`` si no (quita la vieja)."""
    images.sync("location", location_id, [lp_map] if lp_map else [])


def create(location: Location) -> int:
    """Guarda una localización y devuelve su id (la deja en ``location.id``).

    El sitio se serializa a JSON con las 8 direcciones (lo garantiza
    ``validar_ubicacion``) y la imagen única de CL (``location.lp_map``)
    se sincroniza después: mismo contrato D-5 que el resto — el valor en
    memoria es la verdad al guardar.
    """
    validar_ubicacion(location)
    obstacles, lp = _sitio(location)
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO locations (name, latitude, longitude, altitude,"
        " utc_offset_hours, obstacles, lp, bortle, sqm, consider_lp)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            location.name,
            location.latitude,
            location.longitude,
            location.altitude_m,
            location.utc_offset_hours,
            obstacles,
            lp,
            location.bortle,
            location.sqm,
            int(location.consider_lp),
        ),
    )
    conn.commit()
    location.id = cur.lastrowid
    _sync_lp_map(location.id, location.lp_map)
    return location.id


def update(location: Location) -> None:
    """Actualiza una localización existente (sitio + imagen única de CL).

    Contrato D-5: ``location.lp_map`` es la verdad al guardar — si cambió,
    se adjunta la nueva y se quita la anterior; ``None`` la borra. Parte
    siempre del valor que devuelva ``images.list_images("location", id)``
    (vacío si no hay imagen): cargar la ficha sin la imagen y guardar
    borraría el mapa.
    """
    if location.id is None:
        raise ValueError("Ubicación: falta el id (crea antes de actualizar).")
    validar_ubicacion(location)
    obstacles, lp = _sitio(location)
    conn = get_connection()
    conn.execute(
        "UPDATE locations SET name = ?, latitude = ?, longitude = ?, altitude = ?,"
        " utc_offset_hours = ?, obstacles = ?, lp = ?, bortle = ?, sqm = ?,"
        " consider_lp = ? WHERE id = ?",
        (
            location.name,
            location.latitude,
            location.longitude,
            location.altitude_m,
            location.utc_offset_hours,
            obstacles,
            lp,
            location.bortle,
            location.sqm,
            int(location.consider_lp),
            location.id,
        ),
    )
    conn.commit()
    _sync_lp_map(location.id, location.lp_map)


def list_locations() -> list[dict]:
    """Todas las localizaciones (dicts), con ``obstacles``/``lp`` parseados.

    La UI no ve JSON crudo: cada fila trae los dos dicts de las 8
    direcciones con carga defensiva (JSON roto, clave ausente o valor fuera
    de catálogo → defecto), nunca una excepción por una fila. Las demás
    columnas son crudas como en el resto del proyecto (``consider_lp``
    llega 0/1).
    """
    conn = get_connection()
    rows = conn.execute("SELECT * FROM locations ORDER BY name").fetchall()
    filas = []
    for row in rows:
        d = dict(row)
        d["obstacles"] = _obstacles_desde(d.get("obstacles"))
        d["lp"] = _lp_desde(d.get("lp"))
        filas.append(d)
    return filas


def delete(location_id: int) -> None:
    """Elimina una localización (los setups que la usan quedan sin ella).

    Los equipos la pierden con ``ON DELETE SET NULL`` — el aviso previo es
    ``manager.count_setups_using("location", id)``. Las filas de
    ``location_images`` caen en cascada y los ficheros ``images.purge``.
    """
    conn = get_connection()
    conn.execute("DELETE FROM locations WHERE id = ?", (location_id,))
    conn.commit()
    images.purge("location", location_id)
