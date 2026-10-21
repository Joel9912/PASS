"""Comprueba e instala paquetes de catálogos PASS sin acceder a datos personales remotos."""
import gzip
import hashlib
import io
import json
import math
import re
import sqlite3
import urllib.request
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

from db.catalog_editions import (
    CAT_COLUMNS,
    STAR_COLUMNS,
    catalog_snapshot,
    install_edition,
)
from planners.catalog_records import validate_records

RELEASES_URL = "https://api.github.com/repos/Joel9912/PASS/releases?per_page=5"
GROUPS = ("openngc", "hyg", "ldn")
MAX_PACKAGE = 64 * 1024 * 1024
_OBJECT_CATALOGS = {"messier", "ngc", "ic", "barnard", "caldwell", "other"}


def _read(url, limit):
    """Limita respuestas HTTPS para no aceptar paquetes arbitrariamente grandes."""
    parsed = urlparse(url)
    allowed = ((parsed.hostname == "github.com" and parsed.path.startswith("/Joel9912/PASS/releases/"))
               or (parsed.hostname == "api.github.com" and parsed.path == "/repos/Joel9912/PASS/releases"))
    if parsed.scheme != "https" or not allowed:
        raise ValueError("Origen de paquetes no permitido.")
    request = urllib.request.Request(url, headers={"User-Agent": "PASS/catalogs"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError("Respuesta vacía o demasiado grande.")
    return data


def check_manifest():
    """Consulta únicamente el manifiesto; cualquier fallo deja la vigencia desconocida."""
    from planners.data_packages import parse_manifest as parse_data_manifest

    releases = json.loads(_read(RELEASES_URL, 131072))
    if not isinstance(releases, list):
        raise TypeError("No se pudo consultar la lista de releases.")
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        for asset in release.get("assets", []):
            if asset.get("name") == "data-manifest.json":
                return parse_data_manifest(_read(asset["browser_download_url"], 65536))
        for asset in release.get("assets", []):
            if asset.get("name") == "catalogs-manifest.json":
                return parse_manifest(_read(asset["browser_download_url"], 65536))
    raise ValueError("Todavía no hay paquetes de catálogos en las releases consultadas.")


def parse_manifest(data):
    """Aplica las mismas reglas a los manifiestos publicados e incluidos en la app."""
    manifest = json.loads(data)
    if not isinstance(manifest, dict) or type(manifest.get("format")) is not int or manifest["format"] != 1:
        raise ValueError("Formato de manifiesto no compatible.")
    packages = manifest.get("packages")
    if not isinstance(packages, dict) or set(packages) != set(GROUPS):
        raise ValueError("Manifiesto incompleto.")
    for item in packages.values():
        if not isinstance(item, dict):
            raise TypeError("Entrada de paquete inválida.")
        if type(item.get("payload_format", 1)) is not int or item.get("payload_format", 1) not in (1, 2):
            raise ValueError("Formato del contenido de paquete no compatible.")
        if (not isinstance(item.get("version"), str) or not item["version"]
                or not isinstance(item.get("date"), str)
                or not isinstance(item.get("url"), str)
                or not isinstance(item.get("sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}", item["sha256"]) is None
                or type(item.get("size")) is not int
                or not 0 < item["size"] <= MAX_PACKAGE):
            raise ValueError("Metadatos de paquete inválidos.")
    return packages


def installed(conn):
    """Lee versiones confirmadas, sin atribuir una versión a catálogos antiguos."""
    result = {}
    for group in GROUPS:
        row = conn.execute("SELECT value FROM settings WHERE key=?",
                           (f"catalog_package_{group}",)).fetchone()
        result[group] = json.loads(row[0]) if row else None
    return result


def _number(value, *, optional=True):
    """Acepta números finitos almacenables sin convertir texto, booleanos ni ausencias en mediciones."""
    if value is None:
        return optional
    if type(value) is int:
        return -(2 ** 63) <= value < 2 ** 63
    return type(value) is float and math.isfinite(value)


def validate_rows(group, rows):
    """Valida el contrato tipado común al preparador y al instalador, sin modificar datos ni demostrar cobertura."""
    if group not in GROUPS:
        raise ValueError("Catálogo desconocido.")
    columns = (STAR_COLUMNS if group == "hyg" else CAT_COLUMNS).split(",")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Paquete sin filas.")
    seen = set()
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError("Fila de catálogo inválida.")
        if group == "hyg":
            texts, numbers, integers = (0, 4, 5), (1, 2, 3), ()
            required = (1, 2, 3)
        else:
            texts, numbers, integers = (0, 1, 5, 6, 12), (7, 8, 9, 10, 11), (2, 3, 4)
            required = ()
            if not all(isinstance(row[index], str) and row[index].strip() for index in (0, 1)):
                raise ValueError("Identidad de objeto inválida en el paquete.")
            allowed = {"ldn"} if group == "ldn" else _OBJECT_CATALOGS
            if row[1] not in allowed:
                raise ValueError("El paquete contiene objetos de otro catálogo.")
            for index in (10, 11):
                if row[index] is not None and (not _number(row[index]) or row[index] < 0):
                    raise ValueError(f"Tamaño inválido en el paquete: {columns[index]}.")
        for index in texts:
            if row[index] is not None and not isinstance(row[index], str):
                raise ValueError(f"Texto inválido en el paquete: {columns[index]}.")
        for index in numbers:
            if not _number(row[index], optional=index not in required):
                raise ValueError(f"Número inválido en el paquete: {columns[index]}.")
        for index in integers:
            value = row[index]
            if value is not None and (type(value) is not int or not 0 < value < 2 ** 63):
                raise ValueError(f"Identificador numérico inválido en el paquete: {columns[index]}.")
        ra, dec = (row[2], row[3]) if group == "hyg" else (row[8], row[9])
        for value, low, high in ((ra, 0, 24), (dec, -90, 90)):
            if value is not None and not low <= value <= high:
                raise ValueError("Coordenada inválida en el paquete.")
        key = (row[0], row[2], row[3]) if group == "hyg" else (row[0], row[1])
        if key[0] is not None:
            if key in seen:
                raise ValueError("Identidad repetida en el paquete; no se fusionan entradas.")
            seen.add(key)


def update_packages(db_path, packages, groups, *, reader=None, only_missing=False, resource_manifest=None,
                    expected_active=None, require_expected=False, require_empty=False):
    """Valida todas las descargas y prepara una edición externa antes de activar sus versiones.

    Abre una conexión propia en el hilo llamante; jamás reutiliza la conexión Qt.
    Conserva tablas legacy y ediciones anteriores; solo selección/versiones
    se confirman en pass.db. Los archivos se validan antes de activarlos.
    """
    prepared = {}
    records = {}
    reader = reader or _read
    for group in groups:
        if group not in GROUPS:
            raise ValueError("Catálogo desconocido.")
        item = packages[group]
        data = reader(item["url"], min(item["size"], MAX_PACKAGE))
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("La integridad del paquete no coincide con el manifiesto.")
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            payload = stream.read(MAX_PACKAGE + 1)
        if len(payload) > MAX_PACKAGE:
            raise ValueError("El paquete descomprimido es demasiado grande.")
        content = json.loads(payload)
        payload_format = item.get("payload_format", 1)
        if type(payload_format) is not int or payload_format not in (1, 2):
            raise ValueError("Formato del contenido de paquete no compatible.")
        if payload_format == 2:
            if (not isinstance(content, dict) or set(content) != {"format", "rows", "records"}
                    or type(content["format"]) is not int or content["format"] != 2):
                raise ValueError("Contenido con identidades incompatible.")
            rows = content["rows"]
            validate_rows(group, rows)
            validate_records(rows, content["records"])
            records[group] = content["records"]
        else:
            rows = content
        validate_rows(group, rows)
        prepared[group] = rows
    replacements = {group: (STAR_COLUMNS if group == "hyg" else CAT_COLUMNS, rows)
                    for group, rows in prepared.items()}
    versions = {group: {"version": packages[group]["version"], "date": packages[group]["date"],
                        "sha256": packages[group]["sha256"]} for group in prepared}
    install_edition(Path(db_path), replacements, versions, GROUPS, only_missing=only_missing, records=records,
                    resource_manifest=resource_manifest, expected_active=expected_active, require_expected=require_expected,
                    require_empty=require_empty)


def install_bundled(db_path, folder):
    """Carga solo catálogos ausentes desde la distribución, sin Internet ni sobrescribir legacy."""
    folder = Path(folder)
    data_manifest = folder / "data-manifest.json"
    if data_manifest.is_file():
        from planners import data_packages

        if data_manifest.is_symlink() or data_manifest.stat().st_size > 65536:
            raise ValueError("Manifiesto global incluido no permitido.")
        manifest = data_packages.parse_manifest(data_manifest.read_bytes())

        def read_data_local(url, limit):
            """Lee adjuntos directos sin red ni extracción de rutas aportadas por el manifiesto."""
            path = folder / urlparse(url).path.rsplit("/", 1)[-1]
            if path.is_symlink() or path.is_junction() or path.resolve().parent != folder.resolve():
                raise ValueError("Ruta de recurso incluido no permitida.")
            with path.open("rb") as stream:
                return stream.read(limit + 1)

        data_packages.install(db_path, manifest, reader=read_data_local, expected_empty=True)
        return
    manifest_path = folder / "catalogs-manifest.json"
    if not manifest_path.is_file():
        return
    if manifest_path.stat().st_size > 65536:
        raise ValueError("Manifiesto incluido demasiado grande.")
    packages = parse_manifest(manifest_path.read_bytes())
    missing = []
    with closing(sqlite3.connect(db_path)) as personal, catalog_snapshot(personal) as conn:
        for group in GROUPS:
            query = ("SELECT COUNT(*) FROM stars" if group == "hyg" else
                     "SELECT COUNT(*) FROM catalog WHERE catalog " +
                     ("='ldn'" if group == "ldn" else "!='ldn'"))
            if conn.execute(query).fetchone()[0] == 0:
                missing.append(group)

    def read_local(url, limit):
        """Lee únicamente un adjunto directo de la carpeta incluida y comprueba su tamaño."""
        name = urlparse(url).path.rsplit("/", 1)[-1]
        path = folder / name
        if path.is_symlink() or path.resolve().parent != folder.resolve():
            raise ValueError("Ruta de paquete incluido no permitida.")
        with path.open("rb") as stream:
            return stream.read(limit + 1)

    update_packages(db_path, packages, missing, reader=read_local, only_missing=True)
