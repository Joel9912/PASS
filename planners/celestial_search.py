"""Búsqueda de objetos astronómicos con filtros (SQL sobre la tabla ``catalog``).

Alimenta la tabla de resultados de la subpestaña "Búsqueda" del Planificador.

Además del filtrado SQL, si el usuario ha indicado su latitud se anota a cada
fila el tránsito analítico (rápido, sin astropy): ``max_altitude``,
``transit_local`` y ``hours_above_30``. Son los valores de las columnas
Tránsito y Horas >30° de la tabla; la curva detallada del objeto elegido
sí la calcula :mod:`planners.transit` con astropy.
"""
import re
from dataclasses import dataclass, field

from db.connection import get_connection
from planners.analytical_transit import (
    format_transit_hours,
    hours_above_altitude,
    max_altitude,
    transit_local_hours,
)
from planners.planning_dates import planning_date

#: Catálogos disponibles en el programa (cargados por catalog_loader).
CATALOGS: tuple[str, ...] = (
    "messier", "ngc", "ic", "barnard", "caldwell", "ldn", "other",
)

#: Grupos de tipo de objeto (lo que ve el usuario) → códigos OpenNGC.
#: Un objeto puede pertenecer a varios grupos (p. ej. Cl+N = cúmulo y nebulosa).
TYPE_GROUPS: dict[str, tuple[str, ...]] = {
    "galaxia": ("G", "GPair", "GTrpl", "GGroup"),
    "nebulosa": ("Neb", "PN", "HII", "EmN", "RfN", "SNR", "DrkN"),
    "nebulosa oscura": ("DrkN",),
    "cúmulo": ("OCl", "GCl", "*Ass", "Cl+N"),
    "cúmulo abierto": ("OCl", "*Ass"),
    "cúmulo globular": ("GCl",),
    "cúmulo y nebulosa": ("Cl+N",),
    "estrella": ("*", "**", "Nova"),
}

#: Opciones de orden de la tabla (lo que ve el usuario → clave interna).
SORT_OPTIONS: dict[str, str] = {
    "Magnitud": "magnitude",
    "Tamaño": "size",
    "Nombre": "name",
    "Tránsito": "transit",
}

#: Códigos de constelación (IAU) → nombre en español.
#: Incluye Se1/Se2 (OpenNGC parte Serpens en Cabeza y Coda).
CONSTELLATIONS: dict[str, str] = {
    "And": "Andrómeda", "Ant": "Antlia", "Aps": "Ave del Paraíso",
    "Aql": "Águila", "Aqr": "Acuario", "Ara": "Altar", "Ari": "Aries",
    "Aur": "Cochero", "Boo": "Boyero", "Cae": "Cincel", "Cam": "Jirafa",
    "Cap": "Capricornio", "Car": "Quilla", "Cas": "Casiopea",
    "Cen": "Centauro", "Cep": "Cefeo", "Cet": "Ballena",
    "Cha": "Camaleón", "Cir": "Compás", "Cnc": "Cáncer", "Col": "Paloma",
    "Com": "Cabellera de Berenice", "CrA": "Corona Austral",
    "CrB": "Corona Boreal", "Crt": "Copa", "Cru": "Cruz del Sur",
    "Crv": "Cuervo", "Cyg": "Cisne", "Del": "Delfín", "Dor": "Dorado",
    "Dra": "Dragón", "Equ": "Potro", "Eri": "Eridano", "For": "Horno",
    "Gem": "Géminis", "Gru": "Grulla", "Her": "Hércules", "Hor": "Reloj",
    "Hya": "Hidra", "Hyi": "Hidra Austral", "Ind": "Indio",
    "LMi": "León Menor", "Lac": "Lagarto", "Leo": "Leo", "Lep": "Liebre",
    "Lib": "Libra", "Lup": "Lobo", "Lyn": "Lince", "Lyr": "Lira",
    "Men": "Mesa", "Mic": "Microscopio", "Mon": "Unicornio", "Mus": "Mosca",
    "Nor": "Escuadra", "Oct": "Octante", "Oph": "Ofiuco", "Ori": "Orión",
    "Pav": "Pavo", "Peg": "Pegaso", "Per": "Perseo", "Phe": "Fénix",
    "Pic": "Pintor", "PsA": "Pez Austral", "Psc": "Piscis", "Pup": "Popa",
    "Pyx": "Brújula", "Ret": "Retícula", "Scl": "Escultor",
    "Sco": "Escorpio", "Sct": "Escudo", "Se1": "Serpiente (Cabeza)",
    "Se2": "Serpiente (Coda)", "Sex": "Sextante", "Sge": "Flecha",
    "Sgr": "Sagitario", "Tau": "Tauro", "Tel": "Telescopio",
    "TrA": "Triángulo Austral", "Tri": "Triángulo", "Tuc": "Tucán",
    "UMa": "Osa Mayor", "UMi": "Osa Menor", "Vel": "Vela", "Vir": "Virgo",
    "Vol": "Pez Volador", "Vul": "Zorro",
}

#: Muestra de resultados por defecto (la tabla puede paginar sobre esto).
DEFAULT_LIMIT = 500


@dataclass
class SearchFilters:
    """Filtros de búsqueda que aplica el usuario en la interfaz.

    Todos son opcionales: sin filtros, el programa devuelve el catálogo
    completo ordenado por magnitud.

    La altitud mínima y las columnas de tránsito requieren la posición del
    usuario (``latitude``); si no se da, no se filtra por altitud ni se
    calcula el tránsito. ``longitude``/``date_iso`` solo hacen falta para
    la hora local del tránsito.
    """

    catalogs: list[str] = field(default_factory=lambda: list(CATALOGS))
    max_magnitude: float | None = None       # magnitud aparente máxima
    object_types: list[str] = field(default_factory=list)  # grupos de TYPE_GROUPS
    min_ra_hours: float | None = None        # ascensión recta (horas, 0-24)
    max_ra_hours: float | None = None
    min_dec_deg: float | None = None         # declinación (grados)
    max_dec_deg: float | None = None
    text: str | None = None                  # búsqueda libre: 'M31', 'orion'...
    constellation: str | None = None         # código IAU ('And'), ver CONSTELLATIONS
    min_altitude: float | None = None        # altitud mínima de culminación (grados)
    sort_by: str = "magnitude"               # 'magnitude' | 'size' | 'name' | 'transit'
    latitude: float | None = None            # latitud del usuario (para altitud/tránsito)
    longitude: float | None = None           # longitud (este = positivo) para hora local
    date_iso: str | None = None              # fecha para la hora local del tránsito
    utc_offset_hours: float | None = None    # desfase horario de la ubicación (hora de reloj)


def _catalog_clause(catalogs: list[str]) -> tuple[str, list]:
    """Condición SQL: un objeto pertenece a un catálogo si su cross-ref lo dice."""
    conditions: list[str] = []
    params: list = []
    for cat in catalogs:
        if cat in ("messier", "ngc", "ic"):
            conditions.append(f"{cat}_num IS NOT NULL")
        else:
            conditions.append("catalog = ?")
            params.append(cat)
    if not conditions:
        return "", []
    return f"({' OR '.join(conditions)})", params


def _order_clause(sort_by: str) -> str:
    """Orden SQL (el orden por tránsito se aplica después, en Python)."""
    if sort_by == "size":
        return "size_major_arcmin IS NULL, size_major_arcmin DESC"
    if sort_by == "name":
        return "object_id ASC"
    if sort_by == "transit":
        # se reordena en Python al anotar el tránsito
        return "magnitude IS NULL, magnitude ASC"
    return "magnitude IS NULL, magnitude ASC"


def _annotate_transit(rows: list[dict], filters: SearchFilters) -> None:
    """Anota en cada fila ``max_altitude``, ``transit_local`` y ``hours_above_30``.

    Sin ``latitude`` las tres columnas quedan en None (la UI las muestra
    vacías). Con latitud pero sin ``date_iso``, la hora local del tránsito
    también queda en None: antes se inventaba una fecha («2026-01-01»,
    M-24). Una fila sin ``ra_hours`` o ``dec_deg`` no es calculable y
    tampoco revienta la búsqueda entera.
    """
    if filters.latitude is None:
        for row in rows:
            row["max_altitude"] = None
            row["transit_local"] = None
            row["hours_above_30"] = None
        return

    latitude = filters.latitude
    date_iso = filters.date_iso
    longitude = filters.longitude or 0.0
    for row in rows:
        dec = row["dec_deg"]
        ra = row["ra_hours"]
        if dec is None or ra is None:
            row["max_altitude"] = None
            row["transit_local"] = None
            row["hours_above_30"] = None
            continue
        row["max_altitude"] = round(max_altitude(latitude, dec), 1)
        row["transit_local"] = (
            format_transit_hours(
                transit_local_hours(ra, date_iso, longitude, filters.utc_offset_hours)
            )
            if date_iso
            else None
        )
        row["hours_above_30"] = hours_above_altitude(latitude, dec, 30.0)


def search(filters: SearchFilters, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Devuelve los objetos que cumplen los filtros, con el orden elegido.

    Las magnitudes desconocidas van al final; con ``max_magnitude`` definido
    se conservan los objetos sin magnitud (no se esconden por desconocidos).

    El filtro de altitud mínima se traduce a una ventana de declinación en
    SQL (``90 − |lat − dec| >= mín``), de modo que respeta ``limit``. El
    orden por tránsito y las columnas analíticas se calculan en Python: en
    ese orden el ``limit`` también se aplica allí, porque el tránsito no
    vive en la tabla y una ventana SQL por magnitud desplazaría el resultado.
    """
    if filters.latitude is not None and filters.date_iso is not None:
        planning_date(filters.date_iso)
    where: list[str] = ["1=1"]
    params: list = []

    clause, clause_params = _catalog_clause(filters.catalogs)
    if clause:
        where.append(clause)
        params.extend(clause_params)

    if filters.max_magnitude is not None:
        where.append("(magnitude IS NULL OR magnitude <= ?)")
        params.append(filters.max_magnitude)

    if filters.object_types:
        codes: list[str] = []
        for group in filters.object_types:
            codes.extend(TYPE_GROUPS.get(group, (group,)))  # también acepta código directo
        unique = sorted(set(codes))
        where.append(f"type IN ({','.join('?' * len(unique))})")
        params.extend(unique)

    if filters.min_ra_hours is not None:
        where.append("ra_hours >= ?")
        params.append(filters.min_ra_hours)
    if filters.max_ra_hours is not None:
        where.append("ra_hours <= ?")
        params.append(filters.max_ra_hours)
    if filters.min_dec_deg is not None:
        where.append("dec_deg >= ?")
        params.append(filters.min_dec_deg)
    if filters.max_dec_deg is not None:
        where.append("dec_deg <= ?")
        params.append(filters.max_dec_deg)

    if filters.constellation:
        where.append("constellation = ?")
        params.append(filters.constellation)

    # Altitud mínima → ventana de declinación (90 - |lat - dec| >= mín)
    if filters.min_altitude is not None and filters.latitude is not None:
        max_delta = 90.0 - filters.min_altitude
        where.append("dec_deg >= ? AND dec_deg <= ?")
        params.extend([filters.latitude - max_delta, filters.latitude + max_delta])

    if filters.text:
        where.append("(object_id LIKE ? OR name LIKE ? OR 'NGC ' || ngc_num LIKE ?)")
        term = f"%{filters.text.strip()}%"
        params.extend([term, term, term])

    sql = (
        "SELECT object_id, catalog, messier_num, ngc_num, ic_num, name, type,"
        " magnitude, ra_hours, dec_deg, size_major_arcmin, size_minor_arcmin,"
        " constellation"
        " FROM catalog WHERE " + " AND ".join(where) +
        f" ORDER BY {_order_clause(filters.sort_by)}"
    )
    if filters.sort_by != "transit":
        # El tránsito no está en la tabla: limitar antes desplazaría el
        # resultado, así que ese orden corta al final, en Python.
        sql += " LIMIT ?"
        params.append(limit)
    conn = get_connection()
    rows = [dict(row) for row in conn.execute(sql, params)]

    _annotate_transit(rows, filters)

    if filters.sort_by == "transit":
        if filters.latitude is not None:
            # Orden "de más tarde a más temprano" no sirve: se ordena por
            # cercanía al mediodía local para ver primero lo que está
            # disponible al anochecer.
            rows.sort(key=lambda row: (row["transit_local"] or "99:99"))
        else:
            rows.sort(key=lambda row: (
                row["max_altitude"] is None, -(row["max_altitude"] or 0)
            ))
        rows = rows[: max(1, limit)]

    return rows


#: Designación canónica: prefijo de catálogo + número (+ sufijo de componente).
#: Admite 'm31', 'M 31', 'ngc224', 'IC  001'… el usuario no teclea siempre igual.
_DESIGNACION = re.compile(r"^(M|NGC|IC|BARNARD|CALDWELL|LDN)\s*0*(\d+)\s*([A-Z]*)$")

#: Prefijo de la designación → forma canónica del ID ('NGC' + '224').
_PREFIJOS = {
    "M": ("M", "messier_num"),
    "NGC": ("NGC", "ngc_num"),
    "IC": ("IC", "ic_num"),
    "BARNARD": ("Barnard", None),
    "CALDWELL": ("Caldwell", None),
    "LDN": ("LDN", None),
}


def _canonical_designation(text: str) -> tuple[str, str | None, int, str] | None:
    """Normaliza una designación a ``(forma_canónica, columna, número, sufijo)``.

    Plega a mayúsculas, colapsa espacios y quita los ceros a la izquierda,
    de modo que 'm31', 'M 31' y 'ngc0224' apunten al mismo objeto. Sin
    número reconocible no se inventa nada: devuelve ``None``.
    """
    match = _DESIGNACION.match(" ".join(text.upper().split()))
    if match is None:
        return None
    prefix, number, suffix = match.groups()
    forma, column = _PREFIJOS[prefix]
    canonical = (
        f"{forma}{number}{suffix}" if prefix == "M"
        else f"{forma} {number}{suffix}"
    )
    return canonical, column, int(number), suffix


def get_object(object_id: str) -> dict | None:
    """Carga un objeto por su designación ('M31', 'NGC 224'...).

    Acepta los alias habituales del usuario (mayúsculas, espacios de más o
    de menos, ceros a la izquierda). Un alias numérico que no es la
    designación principal ('NGC 224' de M31) resuelve por su columna de
    cruce, con la misma fila que devolvería el catálogo OpenNGC.
    """
    designation = _canonical_designation(object_id)
    if designation is None:
        return None
    canonical, column, number, suffix = designation
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM catalog WHERE object_id = ? COLLATE NOCASE", (canonical,)
    ).fetchone()
    if row is not None:
        return dict(row)
    if column is None or suffix:
        return None  # sin columna de cruce, o componente: solo el ID exacto
    row = conn.execute(
        f"SELECT * FROM catalog WHERE {column} = ? ORDER BY object_id",
        (number,),
    ).fetchone()
    return dict(row) if row else None
