"""Prepara OpenNGC/HYG locales con identidad y procedencia completas; no descarga, mezcla licencias ni abre datos personales."""

import csv
import gzip
import hashlib
import io
import math
import re
from collections import Counter

from planners.catalog_loader import _MANUAL_MESSIER, _primary_designation
from planners.catalog_packages import validate_rows
from planners.catalog_records import prepare_record, validate_records

MAX_SOURCE = 64 * 1024 * 1024
NGC_FIELDS = {"Name", "Type", "RA", "Dec", "Const", "MajAx", "MinAx", "PosAng", "B-Mag", "V-Mag",
              "M", "NGC", "IC", "Identifiers", "Common names", "Sources"}
HYG_FIELDS = {"id", "hip", "hd", "hr", "gl", "bf", "proper", "ra", "dec", "mag", "spect", "con", "pmra", "pmdec"}


def _text(value):
    """Requiere metadatos literales explícitos sin inventar revisiones ni corregir claves de la fuente."""
    if not isinstance(value, str) or not value.strip() or value != value.strip() or "\x00" in value:
        raise ValueError("Identificador o revisión de preparación inválidos.")
    return value


def _csv(data, required, delimiter):
    """Lee CSV acotado, con cabecera única y filas completas, preservando todos sus campos originales."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_SOURCE:
        raise ValueError("Fuente de catálogo vacía o demasiado grande.")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), delimiter=delimiter, strict=True)
    fields = reader.fieldnames
    if not fields or len(fields) != len(set(fields)) or not required <= set(fields) or any(not field for field in fields):
        raise ValueError("Cabecera de catálogo incompatible o repetida.")
    count = 0
    for row in reader:
        if None in row or any(value is None or "\x00" in value for value in row.values()):
            raise ValueError("Fila CSV incompleta o con datos ajenos a la cabecera.")
        count += 1
        if count > 200000:
            raise ValueError("Demasiadas filas en la fuente de catálogo.")
        yield row
    if not count:
        raise ValueError("Fuente sin filas de catálogo.")


def _number(text):
    """Interpreta solo medidas finitas o ausentes; un valor ilegible no se sustituye silenciosamente por otra banda."""
    if not text.strip():
        return None
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("Medida no finita en fuente de catálogo.")
    return value


def _integer(text):
    """Admite identificadores decimales positivos explícitos, no agregados, coordenadas o nombres parecidos."""
    if not text.strip():
        return None
    if not re.fullmatch(r"[0-9]+", text.strip()) or not 0 < int(text) < 2 ** 63:
        raise ValueError("Identificador numérico inválido en la fuente.")
    return int(text)


def _coordinate(text, *, ra):
    """Convierte sexagesimal válido sin aceptar minutos fuera de rango ni interpretar una ausencia como cero."""
    if not text.strip():
        return None
    match = re.fullmatch(r"([+-]?)([0-9]+):([0-9]+):([0-9]+(?:\.[0-9]+)?)", text.strip())
    if match is None or ra and match[1]:
        raise ValueError("Coordenada sexagesimal ilegible en la fuente.")
    degrees, minutes, seconds = int(match[2]), int(match[3]), float(match[4])
    value = degrees + minutes / 60 + seconds / 3600
    if minutes >= 60 or seconds >= 60 or value > (24 if ra else 90):
        raise ValueError("Coordenada sexagesimal fuera de rango.")
    return -value if match[1] == "-" else value


def _alias(name):
    """Aporta un alias convencional solo cuando el identificador declara su catálogo, conservando sufijos."""
    match = re.fullmatch(r"(NGC|IC|M|B|C|LDN)\s*([0-9]+)(.*)", name)
    if match is None:
        return {"namespace": "other", "designation": name}
    prefix, number, suffix = match.groups()
    space = {"NGC": "ngc", "IC": "ic", "M": "messier", "B": "barnard", "C": "caldwell", "LDN": "ldn"}[prefix]
    display = {"M": "M", "B": "Barnard ", "C": "Caldwell "}.get(prefix, prefix + " ")
    return {"namespace": space, "designation": f"{display}{int(number)}{suffix}"}


def _prepare(registry, group, items):
    """Confirma un lote identificado únicamente tras comprobar proyecciones y fuentes; no fusiona alias ambiguos."""
    rows = [row for row, _source, _aliases in items]
    validate_rows(group, rows)
    keys = [(source["source"], source["key"]) for _row, source, _aliases in items]
    if len(set(keys)) != len(keys):
        raise ValueError("Clave de fuente repetida en la preparación.")
    registry.execute("SAVEPOINT prepare_local_catalog")
    try:
        records = [prepare_record(registry, index, source, aliases=aliases)
                   for index, (_row, source, aliases) in enumerate(items)]
        validate_records(rows, records)
        registry.execute("RELEASE SAVEPOINT prepare_local_catalog")
        return {"rows": rows, "records": records}
    except Exception:
        registry.execute("ROLLBACK TO SAVEPOINT prepare_local_catalog")
        registry.execute("RELEASE SAVEPOINT prepare_local_catalog")
        raise


def prepare_openngc(registry, files: dict, *, revision: str, exclusions=None) -> dict:
    """Prepara CSV OpenNGC fijados, conservando campos, bandas y designaciones sin deducir fusiones físicas."""
    _text(revision)
    if not isinstance(files, dict) or not files or set(files) - {"NGC.csv", "addendum.csv"}:
        raise ValueError("Archivos de OpenNGC desconocidos.")
    if exclusions is not None and not isinstance(exclusions, list):
        raise TypeError("El destino de exclusiones debe ser una lista.")
    items, excluded, seen = [], [], set()
    for filename, data in sorted(files.items()):
        digest = hashlib.sha256(data).hexdigest()
        for raw in _csv(data, NGC_FIELDS, ";"):
            name = _text(raw["Name"])
            if name in seen:
                raise ValueError("Registro OpenNGC repetido entre archivos; no se fusiona por nombre.")
            seen.add(name)
            kind = _text(raw["Type"])
            if kind in {"*", "**", "Nova", "Dup", "NonEx"}:
                excluded.append({"key": name, "reason": "excluded_source_type", "row": raw,
                                 "filename": filename, "snapshot_sha256": digest})
                continue
            messier = _integer(raw["M"])
            convention = messier is None and name in _MANUAL_MESSIER
            if convention:
                messier = _MANUAL_MESSIER[name]
            ngc = _integer(raw["NGC"]) if re.fullmatch(r"[0-9]*", raw["NGC"]) else None
            ic = _integer(raw["IC"]) if re.fullmatch(r"[0-9]*", raw["IC"]) else None
            if ngc is None and name.startswith("NGC"):
                match = re.match(r"NGC([0-9]+)", name)
                if match is None:
                    raise ValueError("Designación NGC ilegible.")
                ngc = int(match[1])
            if ic is None and name.startswith("IC"):
                match = re.match(r"IC([0-9]+)", name)
                if match is None:
                    raise ValueError("Designación IC ilegible.")
                ic = int(match[1])
            object_id, namespace = _primary_designation(name, messier, ngc, ic)
            v_mag, b_mag = _number(raw["V-Mag"]), _number(raw["B-Mag"])
            try:
                ra, dec = _coordinate(raw["RA"], ra=True), _coordinate(raw["Dec"], ra=False)
            except ValueError:
                excluded.append({"key": name, "reason": "invalid_source_coordinates", "row": raw,
                                 "filename": filename, "snapshot_sha256": digest})
                continue
            row = [object_id, namespace, messier, ngc, ic, raw["Common names"].strip() or None, kind,
                   v_mag if v_mag is not None else b_mag, ra, dec, _number(raw["MajAx"]), _number(raw["MinAx"]),
                   raw["Const"].strip() or None]
            aliases = [{"namespace": namespace, "designation": object_id}, _alias(name)]
            for prefix, field in (("M", "M"), ("NGC", "NGC"), ("IC", "IC")):
                for value in raw[field].split(","):
                    if value.strip():
                        aliases.append(_alias(prefix + value.strip()))
            for value in raw["Identifiers"].split(","):
                if value.strip():
                    aliases.append(_alias(value.strip()))
            aliases = [dict(pair) for pair in dict.fromkeys(tuple(alias.items()) for alias in aliases)]
            source = {"source": "OpenNGC", "key": name, "revision": revision,
                      "url": "https://github.com/mattiaverga/OpenNGC", "license": "CC-BY-SA-4.0",
                      "attribution": "OpenNGC, Mattia Verga and contributors",
                      "data": {"row": raw, "filename": filename, "snapshot_sha256": digest,
                               "coordinates_reference": "J2000 (OpenNGC)", "size_unit": "arcmin",
                               "magnitude_band": "V" if v_mag is not None else "B" if b_mag is not None else None,
                               "position_angle_deg": _number(raw["PosAng"]),
                               "messier_convention": "M102 = NGC5866 (convención PASS existente)" if convention else None}}
            items.append((row, source, aliases))
    repeated = Counter((row[0], row[1]) for row, _source, _aliases in items)
    for row, source, _aliases in items:
        if repeated[row[0], row[1]] > 1:
            designation = _alias(source["key"])
            row[0], row[1] = designation["designation"], designation["namespace"]
            source["data"]["projection_resolution"] = "Alias compartido; se conserva la designación de fuente sin fusionar."
    result = _prepare(registry, "openngc", items)
    if exclusions is not None:
        exclusions.extend(excluded)
    return result


def prepare_hyg(registry, data: bytes, *, revision: str, exclusions=None) -> dict:
    """Prepara HYG comprimido con magnitud ≤8 e identidades fuente, conservando movimiento propio e IDs secundarios."""
    _text(revision)
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_SOURCE:
        raise ValueError("Archivo HYG vacío o demasiado grande.")
    if exclusions is not None and not isinstance(exclusions, list):
        raise TypeError("El destino de exclusiones debe ser una lista.")
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        decompressed = stream.read(MAX_SOURCE + 1)
    source_rows = _csv(decompressed, HYG_FIELDS, ",")
    items, excluded, seen = [], [], set()
    digest = hashlib.sha256(data).hexdigest()
    for raw in source_rows:
        key = _text(raw["id"])
        if not re.fullmatch(r"[0-9]+", key) or key in seen:
            raise ValueError("Identificador HYG inválido o repetido.")
        seen.add(key)
        mag, ra, dec = (_number(raw[field]) for field in ("mag", "ra", "dec"))
        reason = ("sun_not_star_catalog" if key == "0" or raw["proper"] == "Sol" else
                  "missing_measurement" if None in (mag, ra, dec) else "magnitude_limit" if mag > 8 else None)
        if reason is not None:
            if exclusions is not None:
                excluded.append({"key": key, "reason": reason, "magnitude": mag, "snapshot_sha256": digest})
            continue
        row = [raw["proper"].strip() or None, mag, ra, dec, raw["spect"].strip() or None, raw["con"].strip() or None]
        aliases = [{"namespace": "hyg", "designation": f"HYG {key}"}]
        for field in ("hip", "hd", "hr"):
            identifier = _integer(raw[field])
            if identifier is not None:
                aliases.append({"namespace": field, "designation": f"{field.upper()} {identifier}"})
        for field in ("gl", "bf", "proper"):
            if raw[field].strip():
                aliases.append({"namespace": {"gl": "gliese", "bf": "bayer-flamsteed", "proper": "name"}[field],
                                "designation": raw[field].strip()})
        source = {"source": "HYG", "key": key, "revision": revision,
                  "url": "https://github.com/astronexus/HYG-Database", "license": "CC-BY-SA-4.0",
                  "attribution": "HYG Database, David Nash / Astronexus and contributors",
                  "data": {"row": raw, "snapshot_sha256": digest, "coordinates_epoch_equinox": "2000.0 (HYG)",
                           "ra_unit": "hourangle", "dec_unit": "deg", "magnitude_band": "visual (HYG)",
                           "proper_motion_mas_year": {field: _number(raw[field]) for field in ("pmra", "pmdec")}}}
        items.append((row, source, aliases))
    result = _prepare(registry, "hyg", items)
    if exclusions is not None:
        exclusions.extend(excluded)
    return result
