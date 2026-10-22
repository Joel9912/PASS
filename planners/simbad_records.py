"""Prepara fichas SIMBAD desde instantáneas TAP locales con procedencia e identidades; no descarga ni publica catálogos."""

import hashlib
import json
import math
import re

from db.catalog_identity import identify
from planners.catalog_packages import validate_rows
from planners.catalog_records import prepare_record, validate_records

FIELDS = ("id", "oid", "main_id", "otype", "ra", "dec", "coo_bibcode", "galdim_majaxis",
          "galdim_minaxis", "galdim_wavelength", "galdim_bibcode", "V")
SOURCE = "SIMBAD-ident"
TAXONOMY_QUERY = "SELECT otype,label,path,description,is_candidate FROM otypedef"
TAP_QUERY = (
    "SELECT i.id,b.oid,b.main_id,b.otype,b.ra,b.dec,b.coo_bibcode,"
    "b.galdim_majaxis,b.galdim_minaxis,b.galdim_wavelength,b.galdim_bibcode,f.V "
    "FROM ident i JOIN basic b ON b.oid=i.oidref LEFT JOIN allfluxes f ON f.oidref=b.oid "
    "WHERE i.id LIKE 'LDN %' OR i.id LIKE 'Barnard %'"
)


def _number(value):
    """Distingue ausencia de número finito; no convierte cadenas, booleanos o metadatos ilegibles en medidas."""
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ValueError("Medida SIMBAD no numérica o no finita.")
    return value


def _designation(value):
    """Añade una forma de consulta convencional sin alterar la clave literal conservada en la procedencia."""
    match = re.fullmatch(r"(LDN|Barnard)\s+(\d+)\s*([A-Za-z]*)", value)
    return f"{match[1]} {int(match[2])}{match[3]}"


def _taxonomy(data):
    """Lee jerarquía oficial fijada; solo los tipos básicos explícitos se conocen sin una instantánea adicional."""
    if data is None:
        return {code: {"path": path, "source": "https://simbad.cds.unistra.fr/guide/otypes.htx"}
                for code, path in (("DNe", "ISM > Cld > DNe"), ("*", "*"), ("**", "* > **"))}
    if not isinstance(data, bytes) or not 0 < len(data) <= 256 * 1024:
        raise ValueError("Taxonomía SIMBAD vacía o demasiado grande.")
    content = json.loads(data)
    json.dumps(content, allow_nan=False)
    if not isinstance(content, dict) or set(content) != {"metadata", "data"}:
        raise ValueError("Taxonomía TAP incompatible.")
    metadata = content["metadata"]
    if not isinstance(metadata, list) or any(not isinstance(field, dict) for field in metadata):
        raise ValueError("Metadatos de taxonomía inválidos.")
    names = [field.get("name") for field in metadata]
    if len(names) != 5 or set(names) != {"otype", "label", "path", "description", "is_candidate"}:
        raise ValueError("Columnas de taxonomía incompatibles.")
    rows = content["data"]
    if not isinstance(rows, list) or not rows or len(rows) > 1000:
        raise ValueError("Taxonomía sin tipos o fuera del límite de preparación.")
    result = {}
    digest = hashlib.sha256(data).hexdigest()
    for values in rows:
        if not isinstance(values, list) or len(values) != len(names):
            raise ValueError("Fila de taxonomía incompleta.")
        row = dict(zip(names, values, strict=True))
        if any(not isinstance(row[name], str) or not row[name].strip() or "\x00" in row[name]
               for name in ("otype", "label", "description")):
            raise ValueError("Tipo o jerarquía SIMBAD desconocidos.")
        if (row["path"] is not None and (not isinstance(row["path"], str) or "\x00" in row["path"])):
            raise ValueError("Jerarquía de tipos inválida.")
        if (row["otype"] in result or type(row["is_candidate"]) is not int or row["is_candidate"] not in (0, 1)
                or row["path"] and not row["is_candidate"] and row["path"].split(" > ")[-1] != row["otype"]):
            raise ValueError("Jerarquía de tipos contradictoria.")
        result[row["otype"]] = {"row": row, "path": row["path"], "snapshot_sha256": digest,
                                 "query": TAXONOMY_QUERY}
    if any(item["row"]["is_candidate"] and item["path"] and item["path"].split(" > ")[-1] not in result
           for item in result.values()):
        raise ValueError("Tipo candidato sin referencia de clasificación.")
    return result


def _snapshot(data: bytes):
    """Valida respuesta y metadatos antes de tocar el registro; columnas futuras no se interpretan silenciosamente."""
    if not isinstance(data, bytes) or not 0 < len(data) <= 32 * 1024 * 1024:
        raise ValueError("Instantánea SIMBAD vacía o demasiado grande.")
    content = json.loads(data)
    json.dumps(content, allow_nan=False)
    if not isinstance(content, dict) or set(content) != {"metadata", "data"}:
        raise ValueError("Respuesta TAP incompatible o incompleta.")
    metadata = content["metadata"]
    if not isinstance(metadata, list) or any(not isinstance(field, dict) for field in metadata):
        raise ValueError("Metadatos TAP inválidos.")
    names = [field.get("name") for field in metadata]
    if len(names) != len(FIELDS) or set(names) != set(FIELDS):
        raise ValueError("Columnas SIMBAD incompatibles; falta identidad, tipo o procedencia.")
    fields = {field["name"]: field for field in metadata}
    for name, unit in (("ra", "deg"), ("dec", "deg"), ("galdim_majaxis", "arcmin"), ("galdim_minaxis", "arcmin")):
        if fields[name].get("unit") != unit:
            raise ValueError("Unidades SIMBAD no compatibles.")
    if any("CS.spaceSys=ICRS CT.epoch=J2000" not in fields[name].get("utype", "") for name in ("ra", "dec")):
        raise ValueError("Referencia de coordenadas SIMBAD desconocida.")
    if fields["V"].get("ucd") != "phot.mag;em.opt.V":
        raise ValueError("Banda de magnitud SIMBAD desconocida.")
    rows = content["data"]
    if not isinstance(rows, list) or not rows or len(rows) > 10000:
        raise ValueError("Instantánea SIMBAD sin fichas o fuera del límite de preparación.")
    result = []
    for values in rows:
        if not isinstance(values, list) or len(values) != len(names):
            raise ValueError("Fila SIMBAD incompleta.")
        row = dict(zip(names, values, strict=True))
        if (not isinstance(row["id"], str) or row["id"] != row["id"].strip()
                or not re.fullmatch(r"(?:LDN|Barnard)\s+\d+\s*[A-Za-z]*", row["id"])
                or type(row["oid"]) is not int or not 0 < row["oid"] < 2 ** 63):
            raise ValueError("Identificador SIMBAD inválido o fuera del alcance aprobado.")
        for name in ("main_id", "otype"):
            if not isinstance(row[name], str) or not row[name].strip() or "\x00" in row[name]:
                raise ValueError("Nombre principal o clasificación SIMBAD ausente.")
        for name in ("coo_bibcode", "galdim_wavelength", "galdim_bibcode"):
            if row[name] is not None and (not isinstance(row[name], str) or "\x00" in row[name]):
                raise ValueError("Referencia SIMBAD inválida.")
        for name in ("ra", "dec", "galdim_majaxis", "galdim_minaxis", "V"):
            _number(row[name])
        if (row["ra"] is not None and not 0 <= row["ra"] <= 360
                or row["dec"] is not None and not -90 <= row["dec"] <= 90
                or any(row[name] is not None and row[name] < 0 for name in ("galdim_majaxis", "galdim_minaxis"))):
            raise ValueError("Coordenada o tamaño SIMBAD fuera de rango.")
        result.append(row)
    return metadata, result


def prepare_simbad(registry, data: bytes, *, revision: str, same_as=None, taxonomy=None, exclusions=None) -> dict:
    """Convierte una instantánea local a componentes identificados; solo el mismo OID explícito une designaciones.

    ``same_as`` permite cruces revisados por clave literal SIMBAD hacia IDs
    PASS existentes. No infiere equivalencias con OpenNGC ni reasigna vínculos.
    La salida contiene únicamente aportaciones SIMBAD; no es una edición
    global completa ni decide la licencia de una base combinada.
    ``taxonomy`` fija la jerarquía de tipos para excluir estrellas sin
    confundir cúmulos con ellas; ``exclusions`` recibe evidencia solo si el
    lote termina correctamente. Un tipo desconocido exige revisión.
    """
    if not isinstance(revision, str) or not revision.strip() or revision != revision.strip() or "\x00" in revision:
        raise ValueError("Revisión de instantánea SIMBAD requerida.")
    metadata, rows = _snapshot(data)
    types = _taxonomy(taxonomy)
    if exclusions is not None and not isinstance(exclusions, list):
        raise TypeError("El destino de exclusiones debe ser una lista.")
    if any(row["otype"] not in types or not types[row["otype"]]["path"] for row in rows):
        raise ValueError("Tipo SIMBAD desconocido: aporta una taxonomía verificada, no se infiere por la designación.")
    same_as = {} if same_as is None else same_as
    if not isinstance(same_as, dict) or set(same_as) - {row["id"] for row in rows}:
        raise ValueError("Cruces SIMBAD ajenos a la instantánea.")
    grouped, sources = {}, {}
    for row in rows:
        if row["id"] in sources:
            raise ValueError("Identificador SIMBAD repetido; conservar respuesta para revisión.")
        sources[row["id"]] = row["oid"]
        group = grouped.setdefault(row["oid"], [])
        if group and {key: value for key, value in group[0].items() if key != "id"} != {
                key: value for key, value in row.items() if key != "id"}:
            raise ValueError("Fichas del mismo OID SIMBAD contienen medidas contradictorias.")
        group.append(row)
    components = {name: {"rows": [], "records": []} for name in ("openngc", "ldn")}
    digest = hashlib.sha256(data).hexdigest()
    excluded = []
    registry.execute("SAVEPOINT prepare_simbad_snapshot")
    try:
        for oid in sorted(grouped):
            entries = sorted(grouped[oid], key=lambda row: (not row["id"].startswith("LDN"), row["id"]))
            primary = entries[0]
            type_evidence = types[primary["otype"]]
            if type_evidence["path"].split(" > ")[0] == "*":
                excluded.append({"reason": "stellar_type", "rows": entries, "type_evidence": type_evidence,
                                 "snapshot_sha256": digest, "revision": revision})
                continue
            namespace = "ldn" if primary["id"].startswith("LDN") else "barnard"
            component = components["ldn" if namespace == "ldn" else "openngc"]
            projected = [_designation(primary["id"]), namespace, None, None, None, primary["main_id"],
                         "DrkN" if primary["otype"] == "DNe" else primary["otype"], primary["V"],
                         None if primary["ra"] is None else primary["ra"] / 15, primary["dec"],
                         primary["galdim_majaxis"] or None, primary["galdim_minaxis"] or None, None]
            aliases = []
            for row in entries:
                space = "ldn" if row["id"].startswith("LDN") else "barnard"
                names = [row["id"], _designation(row["id"])]
                if space == "barnard":
                    names.append("B " + _designation(row["id"]).split(" ", 1)[1])
                for name in names:
                    alias = {"namespace": space, "designation": name}
                    if alias not in aliases:
                        aliases.append(alias)
            explicit = {same_as[row["id"]] for row in entries if row["id"] in same_as}
            for row in entries:
                known = registry.execute("SELECT pass_id FROM source_records WHERE source=? AND source_key=?",
                                         (SOURCE, row["id"])).fetchone()
                if known is not None:
                    explicit.add(known[0])
            if len(explicit) > 1:
                raise ValueError("Cruces revisados contradictorios para el mismo OID SIMBAD.")
            record = None
            for row in entries:
                source = {"source": SOURCE, "key": row["id"], "revision": revision,
                          "url": "https://simbad.cds.unistra.fr/simbad/", "license": "ODbL-1.0",
                          "attribution": "SIMBAD astronomical database, CDS, Strasbourg, France",
                          "data": {"row": row, "metadata": metadata, "snapshot_sha256": digest,
                                   "query": TAP_QUERY, "magnitude_band": "V", "type_evidence": type_evidence}}
                if record is None:
                    record = prepare_record(registry, len(component["rows"]), source, aliases=aliases,
                                            same_as=next(iter(explicit), None))
                else:
                    identify(registry, SOURCE, row["id"], same_as=record["pass_id"])
                    record["sources"].append(source)
            component["rows"].append(projected)
            component["records"].append(record)
        for group, component in components.items():
            if component["rows"]:
                validate_rows(group, component["rows"])
                validate_records(component["rows"], component["records"])
        registry.execute("RELEASE SAVEPOINT prepare_simbad_snapshot")
        if exclusions is not None:
            exclusions.extend(excluded)
        return components
    except Exception:
        registry.execute("ROLLBACK TO SAVEPOINT prepare_simbad_snapshot")
        registry.execute("RELEASE SAVEPOINT prepare_simbad_snapshot")
        raise
