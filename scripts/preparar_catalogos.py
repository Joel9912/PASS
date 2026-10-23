"""Prepara adjuntos de catálogos desde fuentes verificadas, sin abrir la BD personal.

Uso: python -m scripts.preparar_catalogos --version VERSION --output CARPETA_NUEVA.
No crea tags, releases ni sube archivos. Revisar atribuciones y permisos de
redistribución de las fuentes antes de publicar los artefactos.
"""
import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from db import connection
from planners import catalog_loader, catalog_packages, ldn_loader
from planners.catalog_records import validate_records


def export_data_manifest(output, edition, packages, resources):
    """Escribe un manifiesto global nuevo de artefactos ya revisados; no descarga, copia datos personales ni publica.

    Los adjuntos deben haberse preparado/verificado por separado. Esta
    validación comprueba el contrato técnico, no concede derechos ni
    acredita los cálculos o la cobertura de sus fuentes.
    """
    from planners.data_packages import parse_manifest

    manifest = {"format": 2, "edition": edition, "reader": {"min": 1, "max": 1},
                "packages": packages, "resources": resources}
    payload = json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode("utf-8")
    parse_manifest(payload)
    with Path(output).open("xb") as stream:
        stream.write(payload)


def export_identified(version, output, components, registry):
    """Exporta componentes explícitamente revisados con IDs de un registro existente, sin red ni datos personales.

    Cada componente contiene ``rows`` y ``records`` del contrato formato 2.
    La validez estructural no acredita cobertura ni autoriza redistribuir
    una fuente: el llamante debe revisar sus permisos y atribuciones.
    No cambia la ruta CLI legacy ni genera el paquete global definitivo.
    """
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("Versión no válida para un adjunto de release.")
    output = Path(output)
    if output.exists() or not isinstance(components, dict) or set(components) != set(catalog_packages.GROUPS):
        raise ValueError("Destino nuevo y manifiesto completo de componentes conocidos requeridos.")
    artifacts, packages = {}, {}
    identities, source_keys, targets = set(), set(), set()
    for group, content in components.items():
        if not isinstance(content, dict) or set(content) != {"rows", "records"}:
            raise ValueError("Componente con identidades incompatible.")
        rows, records = content["rows"], content["records"]
        catalog_packages.validate_rows(group, rows)
        validate_records(rows, records)
        for record in records:
            if record["pass_id"] in identities:
                raise ValueError("Identidad repetida entre componentes; no se fusionan filas automáticamente.")
            identities.add(record["pass_id"])
            targets.update(relation["target"] for relation in record["relations"])
            for source in record["sources"]:
                key = source["source"], source["key"]
                if key in source_keys:
                    raise ValueError("Registro de fuente repetido entre componentes.")
                source_keys.add(key)
                known = registry.execute("SELECT pass_id FROM source_records WHERE source=? AND source_key=?",
                                         (source["source"], source["key"])).fetchone()
                if known is None or known[0] != record["pass_id"]:
                    raise ValueError("La identidad de la fuente no coincide con el registro persistente del preparador.")
        name = f"catalog-{group}-{version}.json.gz"
        payload = json.dumps({"format": 2, **content}, ensure_ascii=False, allow_nan=False).encode()
        data = gzip.compress(payload, mtime=0)
        if max(len(data), len(payload)) > catalog_packages.MAX_PACKAGE:
            raise ValueError("Paquete demasiado grande para el instalador.")
        artifacts[name] = data
        packages[group] = {"version": version, "date": datetime.now(UTC).date().isoformat(),
                           "payload_format": 2, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                           "url": f"https://github.com/Joel9912/PASS/releases/download/{version}/{name}"}
    if not targets <= identities:
        raise ValueError("La exportación contiene relaciones con identidades ausentes.")
    output.mkdir(parents=True)
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
    (output / "catalogs-manifest.json").write_text(
        json.dumps({"format": 1, "packages": packages}, indent=2), encoding="utf-8")


def export_source_collection(version, output, sources, registry, *, crosses=(), resources=None):
    """Exporta fuentes independientes con condiciones explícitas; no mezcla sus fichas ni concede derechos jurídicos.

    Cada entrada tiene ``metadata`` del componente y ``groups`` de proyecciones
    identificadas. Las prioridades y cruces se aportan expresamente; los datos
    originales se mantienen dentro del archivo de su única fuente.
    """
    from db.source_collection import validate_crosses, validate_payload
    from planners.data_packages import parse_manifest

    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("Versión no válida.")
    output = Path(output)
    if output.exists() or not isinstance(sources, dict) or not sources:
        raise ValueError("Se requieren fuentes explícitas y un destino nuevo.")
    packages, artifacts, by_id, counts, targets = {}, {}, {}, {}, set()
    for name, source in sources.items():
        if not isinstance(source, dict) or set(source) != {"metadata", "groups"}:
            raise ValueError("Preparación por fuente incompatible.")
        item = dict(source["metadata"])
        content = {"format": 3, "source_id": item.get("source_id"), "groups": source["groups"]}
        validate_payload(content, item)
        for component in source["groups"].values():
            for record in component["records"]:
                pass_id = record["pass_id"]
                counts[pass_id] = counts.get(pass_id, 0) + 1
                targets.update(relation["target"] for relation in record["relations"])
                for original in record["sources"]:
                    key = original["source"], original["key"]
                    known = registry.execute("SELECT pass_id FROM source_records WHERE source=? AND source_key=?", key).fetchone()
                    if known is None or known[0] != pass_id:
                        raise ValueError("Identidad de fuente ajena al registro del preparador.")
                    by_id.setdefault(pass_id, set()).add(key)
        payload = json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        data = gzip.compress(payload, mtime=0)
        if max(len(data), len(payload)) > catalog_packages.MAX_PACKAGE:
            raise ValueError("Fuente demasiado grande para el instalador.")
        filename = f"source-{name}-{version}.json.gz"
        item.update(payload_format=3, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                    url=f"https://github.com/Joel9912/PASS/releases/download/{version}/{filename}")
        packages[name], artifacts[filename] = item, data
    validate_crosses(by_id, {key for key, count in counts.items() if count > 1}, list(crosses))
    if not targets <= by_id.keys():
        raise ValueError("Relaciones con identidades ausentes.")
    manifest = {"format": 3, "edition": version, "reader": {"min": 1, "max": 1},
                "packages": packages, "resources": resources or {}, "cross_identifications": list(crosses)}
    encoded = json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode("utf-8")
    parse_manifest(encoded)
    output.mkdir(parents=True)
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
    (output / "data-manifest.json").write_bytes(encoded)


def prepare(version, output):
    """Descarga en un sandbox y genera paquetes sin reutilizar datos del usuario."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("Versión no válida para un adjunto de release.")
    if output.exists():
        raise ValueError("La carpeta de salida debe ser nueva para no sobrescribir archivos.")
    with tempfile.TemporaryDirectory(prefix="pass-catalog-release-") as temporary:
        base = Path(temporary)
        previous = connection.DB_PATH, catalog_loader.CACHE_DIR, ldn_loader.CACHE_DIR
        previous_conn = connection._connection
        conn = sqlite3.connect(base / "catalogs.sqlite")
        try:
            conn.executescript(connection.SCHEMA_PATH.read_text(encoding="utf-8"))
            connection.DB_PATH = base / "catalogs.sqlite"
            # Este comando se ejecuta en un proceso propio; no usa get_connection de la UI.
            connection._connection = conn
            catalog_loader.CACHE_DIR = ldn_loader.CACHE_DIR = base / "downloads"
            catalog_loader.load_catalog()
            catalog_loader.load_stars()
            ldn_loader.load_ldn()
            artifacts, packages = {}, {}
            for group in catalog_packages.GROUPS:
                table = "stars" if group == "hyg" else "catalog"
                columns = catalog_packages.STAR_COLUMNS if group == "hyg" else catalog_packages.CAT_COLUMNS
                clause = "" if group == "hyg" else (" WHERE catalog='ldn'" if group == "ldn"
                                                    else " WHERE catalog!='ldn'")
                rows = [list(row) for row in conn.execute(f"SELECT {columns} FROM {table}{clause} ORDER BY id")]
                catalog_packages.validate_rows(group, rows)
                name = f"catalog-{group}-{version}.json.gz"
                data = gzip.compress(json.dumps(rows, allow_nan=False).encode(), mtime=0)
                if len(data) > catalog_packages.MAX_PACKAGE:
                    raise ValueError("Paquete demasiado grande para el instalador.")
                artifacts[name] = data
                packages[group] = {"version": version, "date": datetime.now(UTC).date().isoformat(),
                                   "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                   "url": f"https://github.com/Joel9912/PASS/releases/download/{version}/{name}"}
            output.mkdir(parents=True)
            for name, data in artifacts.items():
                (output / name).write_bytes(data)
            (output / "catalogs-manifest.json").write_text(
                json.dumps({"format": 1, "packages": packages}, indent=2), encoding="utf-8")
        finally:
            connection.DB_PATH, catalog_loader.CACHE_DIR, ldn_loader.CACHE_DIR = previous
            connection._connection = previous_conn
            conn.close()


def main():
    """Exige versión y destino explícitos; generar archivos no autoriza su publicación."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.version, args.output)


if __name__ == "__main__":
    main()
