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
