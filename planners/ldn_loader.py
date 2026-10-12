"""Catálogo de Nebulosas Oscuras de Lynds (LDN) desde VizieR.

Fuente: **VII/7A/ldn** (Lynds 1962, *Catalogue of Dark Nebulae*, versión
actualizada con 1791 objetos). El usuario quiere planificar nebulosas
oscuras, así que se cargan junto al resto de catálogos.

Descarga por **TAP** (``tapvizier.cds.unistra.fr``) con ADQL, que devuelve
las coordenadas J2000 en grados decimales (``_RA_icrs``/``_DE_icrs``).
El resultado se cachea en ``data/downloads/ldn.csv``.

Parseo de columnas útiles:
- ``LDN``: número de catálogo (los objetos sin número se descartan).
- ``_RA_icrs``/``_DE_icrs``: J2000 en grados (→ RA en horas = grados/15).
- ``Area``: superficie en deg² (→ diámetro equivalente para la columna Tamaño).
- ``Opacity``: clase 1 (más clara) a 6 (más oscura); no se almacena aún.

Nunca lanza excepciones por red: si la descarga falla, el programa sigue.
"""
from __future__ import annotations

import csv
import io
import math
from pathlib import Path

from db.connection import get_connection

#: Descargas cacheadas (compartidas con catalog_loader).
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "downloads"

#: Endpoint TAP de VizieR y consulta ADQL de la tabla LDN.
#: Ojo: en TAP_SCHEMA las columnas de coordenadas se llaman ``_RA.icrs``
#: (con punto); el CSV de respuesta las serializa con guion bajo, así que
#: :func:`parse_ldn_rows` acepta ambos nombres.
URL_LDN_TAP = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
QUERY_LDN = 'SELECT "LDN", "_RA.icrs", "_DE.icrs", "Area", "Opacity" FROM "VII/7A/ldn"'

_USER_AGENT = "PASS/0.1 (planning-astronomical-stacking-suite)"

#: Tipo OpenNGC de nebulosa oscura (los LDN se cargan con ese código).
LDN_TYPE = "DrkN"


def _download_tap(query: str, cache_name: str) -> bytes:
    """Ejecuta una consulta ADQL por TAP con caché local en ``cache_name``."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / cache_name
    if target.exists() and target.stat().st_size > 0:
        return target.read_bytes()

    import urllib.parse

    payload = urllib.parse.urlencode(
        {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}
    ).encode()
    request = urllib.request.Request(
        URL_LDN_TAP, data=payload, headers={"User-Agent": _USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data = leer_respuesta(response)
    target.write_bytes(data)
    return data


def leer_respuesta(response) -> bytes:
    """Lee el cuerpo HTTP y comprueba la longitud anunciada antes de cachearlo."""
    data = response.read()
    longitud = response.headers.get("Content-Length")
    if not data or (longitud is not None and len(data) != int(longitud)):
        raise ValueError("Descarga vacía o incompleta del catálogo.")
    return data


def _float_or_none(value: str | None) -> float | None:
    """Cadena (o ``None``) → ``float``; vacía o no numérica → ``None`` (sin excepción)."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def validar_csv(text: str, columnas: tuple[tuple[str, ...], ...], *, delimiter=",") -> None:
    """Rechaza CSV vacíos, cabeceras ajenas y filas truncadas antes de borrar datos.

    Cada grupo de columnas contiene alias válidos para una columna requerida.
    No prueba integridad semántica ni detecta truncaciones entre filas completas.
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, strict=True)
    try:
        header = next(reader, [])
        if not header or any(not set(alias).intersection(header) for alias in columnas):
            raise ValueError("Cabecera inesperada en la descarga del catálogo.")
        n = 0
        for fields in reader:
            if not fields:
                continue
            if len(fields) != len(header):
                raise ValueError("Fila incompleta en la descarga del catálogo.")
            n += 1
        if not n:
            raise ValueError("La descarga del catálogo no contiene filas.")
    except csv.Error as exc:
        raise ValueError("CSV inválido en la descarga del catálogo.") from exc


def _pick(record: dict, *names: str) -> str | None:
    """Primer nombre de columna presente en la fila ('_RA.icrs' o '_RA_icrs')."""
    for name in names:
        if name in record and record[name] is not None:
            return record[name]
    return None


def _size_major_from_area(area_deg2: float | None) -> float | None:
    """Área (deg²) → diámetro circular equivalente en minutos de arco.

    El catálogo solo da superficie; estimamos el eje como el diámetro de un
    círculo de esa área (``d = 2·√(Area/π)``), útil como referencia de tamaño.
    """
    if area_deg2 is None or area_deg2 <= 0:
        return None
    diameter_deg = 2.0 * math.sqrt(area_deg2 / math.pi)
    return round(diameter_deg * 60.0, 3)


def parse_ldn_rows(text: str) -> list[tuple]:
    """Parsea el CSV de TAP de VII/7A a filas de la tabla ``catalog``.

    Descarta los objetos sin número LDN (4 casos al final de la tabla) y los
    que no tienen coordenadas J2000. Devuelve tuplas con las 13 columnas de
    ``catalog`` (mismo orden que :func:`planners.catalog_loader.parse_ngc_rows`).
    """
    reader = csv.DictReader(io.StringIO(text))
    rows: list[tuple] = []
    for record in reader:
        ldn = (record.get("LDN") or "").strip()
        if not ldn:
            continue  # objeto sin número de catálogo
        try:
            ldn_num = int(float(ldn))
        except ValueError:
            continue

        ra_deg = _float_or_none(_pick(record, "_RA_icrs", "_RA.icrs"))
        dec_deg = _float_or_none(_pick(record, "_DE_icrs", "_DE.icrs"))
        if ra_deg is None or dec_deg is None:
            continue

        area = _float_or_none(record.get("Area"))
        rows.append((
            f"LDN {ldn_num}",   # object_id
            "ldn",              # catalog
            None, None, None,   # messier_num, ngc_num, ic_num
            None,               # name (sin nombre común)
            LDN_TYPE,           # type: nebulosa oscura
            None,               # magnitude (los LDN no tienen)
            ra_deg / 15.0,      # ra_hours (J2000, grados → horas)
            dec_deg,            # dec_deg (J2000)
            _size_major_from_area(area),  # size_major_arcmin (equivalente)
            None,               # size_minor_arcmin (desconocido)
            None,               # constellation (el catálogo no la da)
        ))
    return rows


def load_ldn() -> int:
    """Descarga y carga los LDN (refresco solo de ``catalog='ldn'``).

    Borra únicamente los LDN previos: el resto de catálogos no se toca.
    Primero descarga y parsea todo para no dejar la base a medias si falla.
    Devuelve el nº de filas insertadas.
    """
    conn = get_connection()
    text = _download_tap(QUERY_LDN, "ldn.csv").decode("utf-8")
    validar_csv(text, (("LDN",), ("_RA_icrs", "_RA.icrs"), ("_DE_icrs", "_DE.icrs")))
    rows = parse_ldn_rows(text)
    if not rows:
        raise ValueError("La descarga LDN no contiene objetos utilizables.")
    with conn:
        conn.execute("DELETE FROM catalog WHERE catalog = 'ldn'")
        conn.executemany(
            "INSERT OR REPLACE INTO catalog (object_id, catalog, messier_num, ngc_num,"
            " ic_num, name, type, magnitude, ra_hours, dec_deg,"
            " size_major_arcmin, size_minor_arcmin, constellation)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)
