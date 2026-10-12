"""Descarga y carga de catálogos en SQLite (OpenNGC + estrellas HYG + LDN).

Fuentes:
- OpenNGC (NGC.csv + addendum.csv): objetos deep-sky NGC/IC/Messier y
  objetos del addendum (Barnard, Caldwell...). Licencia CC-BY-SA.
- HYG (hygdata_v40.csv.gz): estrellas con magnitud <= 8. Licencia CC-BY.
- LDN (VizieR VII/7A/ldn): nebulosas oscuras de Lynds, vía TAP
  (ver :mod:`planners.ldn_loader`). Licencia del catálogo original.

Uso manual (el arranque usa paquetes incluidos, sin descargar)::

    python -m planners.catalog_loader [--force]

Los ficheros se cachean en ``data/downloads/`` (no se re-descargan).
"""
import csv
import gzip
import io
import sys
import urllib.request
from pathlib import Path

from db.connection import get_connection
from planners import ldn_loader

#: Descargas cacheadas (no versionadas; ver .gitignore)
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "downloads"

URL_NGC = "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/NGC.csv"
URL_ADDENDUM = "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/addendum.csv"
URL_HYG = "https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v40.csv.gz"

#: Magnitud límite de las estrellas que guardamos (visibles a ojo/near-naked).
STAR_MAG_LIMIT = 8.0

#: Tipos de OpenNGC que no aportan (duplicados y objetos inexistentes).
_SKIP_TYPES = {"Dup", "NonEx"}

#: M102 está disputado históricamente; la convención moderna lo identifica
#: con NGC 5866 (Galaxia del Huso), que OpenNGC no marca como Messier.
_MANUAL_MESSIER = {"NGC5866": 102}

_USER_AGENT = "PASS/0.1 (planning-astronomical-stacking-suite)"


# ---------------------------------------------------------------- descargas
def _download(url: str) -> bytes:
    """Descarga ``url`` con caché local: si el fichero ya existe, lo reutiliza."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / url.rsplit("/", 1)[-1]
    cached = ldn_loader.leer_cache_verificada(target)
    if cached is not None:
        return cached
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = ldn_loader.leer_respuesta(response)
    ldn_loader.guardar_cache_verificada(target, data)
    return data


# ------------------------------------------------------------------ parsers
def _float_or_none(value: str) -> float | None:
    """Cadena del CSV → ``float``; vacía o no numérica → ``None`` (sin excepción)."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _int_or_none(value: str) -> int | None:
    """Cadena del CSV → ``int``; vacía o no numérica → ``None`` (sin excepción)."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _ra_to_hours(value: str) -> float | None:
    """'00:08:27.05' -> horas decimales."""
    parts = (value or "").strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = (float(p) for p in parts)
    except ValueError:
        return None
    return h + m / 60.0 + s / 3600.0


def _dec_to_degrees(value: str) -> float | None:
    """'+27:43:03.6' -> grados decimales (con signo)."""
    value = (value or "").strip()
    if not value:
        return None
    sign = -1.0 if value.startswith("-") else 1.0
    parts = value.lstrip("+-").split(":")
    if len(parts) != 3:
        return None
    try:
        d, m, s = (float(p) for p in parts)
    except ValueError:
        return None
    return sign * (d + m / 60.0 + s / 3600.0)


def _leading_number(name: str, prefix_len: int) -> tuple[int | None, str]:
    """Extrae el número inicial tras un prefijo y el resto del nombre.

    'IC0186A' -> (186, 'A'); 'IC0080 NED01' -> (80, ' NED01');
    'IC0001' -> (1, ''); 'ICxyz' -> (None, '').
    """
    start = prefix_len
    end = start
    while end < len(name) and name[end].isdigit():
        end += 1
    if end == start:
        return None, ""
    return int(name[start:end]), name[end:]


def _primary_designation(name: str, messier_num: int | None, ngc_num: int | None,
                         ic_num: int | None) -> tuple[str, str]:
    """Mejor designación del objeto: Messier > NGC > IC > la del fichero.

    Devuelve ``(object_id, catalog)``. Ej: NGC0224 con M=31 → ('M31', 'messier').
    Los nombres de componentes conservan su sufijo ('IC0186A' → 'IC 186A').
    """
    if messier_num is not None:
        return f"M{messier_num}", "messier"
    if name.startswith("NGC"):
        number, suffix = _leading_number(name, 3)
        if number is not None:
            return f"NGC {number}{suffix}", "ngc"
    if name.startswith("IC"):
        number, suffix = _leading_number(name, 2)
        if number is not None:
            return f"IC {number}{suffix}", "ic"
    if len(name) >= 2 and name[0] == "B" and name[1:].isdigit():
        return f"Barnard {int(name[1:])}", "barnard"
    if len(name) >= 2 and name[0] == "C" and name[1:].isdigit():
        return f"Caldwell {int(name[1:])}", "caldwell"
    return name, "other"


def _magnitude(v_mag: str, b_mag: str) -> float | None:
    """Magnitud aparente: prefiere V, usa B como alternativa."""
    return _float_or_none(v_mag) if _float_or_none(v_mag) is not None else _float_or_none(b_mag)


def parse_ngc_rows(text: str) -> list[tuple]:
    """Parsea un CSV de OpenNGC (NGC.csv o addendum.csv) a filas de ``catalog``.

    Excluye tipos Dup/NonEx. Devuelve tuplas con las columnas de la tabla.
    """
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = next(reader, None)
    if not header or header[0] != "Name":
        raise ValueError("Cabecera inesperada en el CSV de OpenNGC")

    rows: list[tuple] = []
    for fields in reader:
        if len(fields) < 29:
            continue
        name, obj_type = fields[0].strip(), fields[1].strip()
        if not name or obj_type in _SKIP_TYPES:
            continue

        messier_num = _int_or_none(fields[23])
        if messier_num is None:
            messier_num = _MANUAL_MESSIER.get(name)
        # Número propio del objeto si su nombre lleva el prefijo del catálogo
        # (los componentes 'IC0186A' cuentan como IC 186)
        ngc_num = _int_or_none(fields[24])
        if ngc_num is None and name.startswith("NGC"):
            ngc_num = _leading_number(name, 3)[0]
        ic_num = _int_or_none(fields[25])
        if ic_num is None and name.startswith("IC"):
            ic_num = _leading_number(name, 2)[0]

        object_id, catalog = _primary_designation(name, messier_num, ngc_num, ic_num)
        rows.append((
            object_id, catalog, messier_num, ngc_num, ic_num,
            fields[28].strip() or None,          # Common names
            obj_type or None,                    # Type
            _magnitude(fields[9], fields[8]),    # V-Mag, B-Mag
            _ra_to_hours(fields[2]),             # RA
            _dec_to_degrees(fields[3]),          # Dec
            _float_or_none(fields[5]),           # MajAx
            _float_or_none(fields[6]),           # MinAx
            fields[4].strip() or None,           # Const
        ))
    return rows


def parse_hyg_rows(data: bytes, mag_limit: float = STAR_MAG_LIMIT) -> list[tuple]:
    """Parsea ``hygdata_v*.csv.gz`` a filas de ``stars`` (magnitud <= límite)."""
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8", newline="")
        reader = csv.DictReader(text)
        rows: list[tuple] = []
        for star in reader:
            mag = _float_or_none(star.get("mag", ""))
            ra = _float_or_none(star.get("ra", ""))
            dec = _float_or_none(star.get("dec", ""))
            if mag is None or ra is None or dec is None:
                continue
            if mag > mag_limit:
                continue
            proper = (star.get("proper") or "").strip() or None
            if proper == "Sol":
                continue
            rows.append((
                proper,                     # name
                mag,                        # magnitude
                ra,                         # ra_hours (decimal)
                dec,                        # dec_deg (decimal)
                (star.get("spect") or "").strip() or None,   # color / tipo espectral
                (star.get("con") or "").strip() or None,     # constelación
            ))
    return rows


# ------------------------------------------------------------ carga en SQLite
def load_catalog() -> int:
    """Descarga y carga los objetos OpenNGC (refresco completo).

    Primero se descarga y parsea todo; solo entonces se borra la tabla y se
    inserta, para no dejar la base a medias si falla la red.
    Devuelve el nº de filas insertadas.
    """
    conn = get_connection()
    all_rows: list[tuple] = []
    for url in (URL_NGC, URL_ADDENDUM):
        text = _download(url).decode("utf-8")
        ldn_loader.validar_csv(text, (("Name",), ("Type",), ("RA",), ("Dec",)), delimiter=";")
        rows = parse_ngc_rows(text)
        if not rows:
            raise ValueError("La descarga OpenNGC no contiene objetos utilizables.")
        all_rows.extend(rows)
    with conn:
        conn.execute("DELETE FROM catalog WHERE catalog != 'ldn'")
        conn.executemany(
            "INSERT OR REPLACE INTO catalog (object_id, catalog, messier_num, ngc_num,"
            " ic_num, name, type, magnitude, ra_hours, dec_deg,"
            " size_major_arcmin, size_minor_arcmin, constellation)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            all_rows,
        )
    return len(all_rows)


def load_stars(mag_limit: float = STAR_MAG_LIMIT) -> int:
    """Descarga y carga las estrellas HYG con ``mag <= mag_limit`` (refresco).

    El DELETE previo es imprescindible: las estrellas sin nombre (name NULL)
    no las deduplica el UNIQUE de SQLite al volver a cargar.
    """
    conn = get_connection()
    data = _download(URL_HYG)
    text = gzip.decompress(data).decode("utf-8")
    ldn_loader.validar_csv(text, (("mag",), ("ra",), ("dec",)))
    rows = parse_hyg_rows(data, mag_limit)
    if not rows:
        raise ValueError("La descarga HYG no contiene estrellas utilizables.")
    with conn:
        conn.execute("DELETE FROM stars")
        conn.executemany(
            "INSERT OR REPLACE INTO stars (name, magnitude, ra_hours, dec_deg, color, constellation)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def catalog_counts() -> dict[str, int]:
    """Filas actuales de ``catalog``, ``stars`` y objetos LDN."""
    conn = get_connection()
    n_catalog = conn.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
    n_stars = conn.execute("SELECT COUNT(*) FROM stars").fetchone()[0]
    n_ldn = conn.execute("SELECT COUNT(*) FROM catalog WHERE catalog = 'ldn'").fetchone()[0]
    return {"catalog": n_catalog, "stars": n_stars, "ldn": n_ldn}


def ensure_catalog(force: bool = False) -> dict[str, int]:
    """Carga los catálogos solo si las tablas están vacías (o con ``force``).

    Nunca lanza excepciones por red: si la descarga falla, el programa sigue
    funcionando y se reintentará en el próximo arranque.
    """
    counts = catalog_counts()
    try:
        if force or counts["catalog"] == 0:
            print("Descargando catálogo OpenNGC (~4 MB, primera vez)...")
            counts["catalog"] = load_catalog()
        if force or counts["stars"] == 0:
            print("Descargando estrellas HYG (~14 MB, primera vez)...")
            counts["stars"] = load_stars()
        if force or counts["ldn"] == 0:
            print("Descargando nebulosas oscuras LDN (VizieR VII/7A)...")
            counts["ldn"] = ldn_loader.load_ldn()
    except Exception as error:  # sin red u otro error: seguimos adelante
        # El DELETE previo (y cualquier INSERT a medias) queda en una
        # transacción abierta: sin rollback, el próximo commit de otro
        # módulo la consignaría y el catálogo se quedaría vacío (M-10).
        try:
            get_connection().rollback()
        except Exception:  # la conexión pudo ser la que falló
            pass
        print(f"[aviso] No se pudieron cargar los catálogos: {error}")
    return counts


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m planners.catalog_loader [--force]``."""
    args = sys.argv[1:] if argv is None else argv
    force = "--force" in args
    counts = ensure_catalog(force=force)
    print(
        f"catalog: {counts['catalog']} objetos | stars: {counts['stars']} estrellas"
        f" | ldn: {counts['ldn']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
