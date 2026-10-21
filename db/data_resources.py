"""Contrato y almacenamiento inmutable de recursos de una edición; las huellas no acreditan permisos científicos o legales."""

import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

GROUPS = {"openngc", "hyg", "ldn"}
READER_PROTOCOL = 1
RESOURCE_FOLDER = "edition-resources"
MAX_RESOURCE = 64 * 1024 * 1024


def _text(value):
    """Exige metadatos explícitos, sin rellenar revisiones o licencias desconocidas."""
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("Metadato de edición ausente o inválido.")


def validate_manifest(manifest: dict) -> None:
    """Valida compatibilidad, dependencias y contrato de archivos; no prueba cobertura, precisión ni derechos."""
    if (not isinstance(manifest, dict) or set(manifest) != {"format", "edition", "reader", "packages", "resources"}
            or type(manifest["format"]) is not int or manifest["format"] != 2):
        raise ValueError("Manifiesto global no compatible.")
    _text(manifest["edition"])
    bounds = manifest["reader"]
    if (not isinstance(bounds, dict) or set(bounds) != {"min", "max"}
            or any(type(bounds[key]) is not int for key in bounds)
            or not 1 <= bounds["min"] <= READER_PROTOCOL <= bounds["max"]):
        raise ValueError("Esta edición requiere otro protocolo lector de PASS.")
    packages, resources = manifest["packages"], manifest["resources"]
    if not isinstance(packages, dict) or set(packages) != GROUPS or not isinstance(resources, dict):
        raise ValueError("Componentes de edición incompletos.")
    if set(resources) & GROUPS or len(resources) > 4096:
        raise ValueError("Identificadores de recursos repetidos o demasiados componentes.")
    components = {**packages, **resources}
    for name, item in components.items():
        if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) is None or not isinstance(item, dict):
            raise ValueError("Componente de edición inválido.")
        for key in ("version", "license", "attribution", "source", "revision", "url"):
            _text(item.get(key))
        if (type(item.get("size")) is not int or not 0 < item["size"] <= MAX_RESOURCE
                or not isinstance(item.get("sha256"), str) or re.fullmatch(r"[a-f0-9]{64}", item["sha256"]) is None):
            raise ValueError("Tamaño o huella de componente inválidos.")
        if name in packages:
            if type(item.get("payload_format")) is not int or item["payload_format"] != 2:
                raise ValueError("La edición global requiere catálogos con procedencia explícita.")
        elif item.get("format") not in ("utf8-v1", "json-v1") or type(item.get("optional")) is not bool:
            raise ValueError("Formato de recurso no compatible; no se reinterpretan archivos desconocidos.")
        if not isinstance(item.get("requires"), dict):
            raise TypeError("Dependencias de componente inválidas.")
        for dependency, version in item["requires"].items():
            if (not isinstance(version, str) or not isinstance(components.get(dependency), dict)
                    or version != components[dependency].get("version")):
                raise ValueError("Dependencia de edición ausente o incompatible.")
            if (name in packages or not item["optional"]) and dependency in resources and resources[dependency].get("optional") is not False:
                raise ValueError("Un componente obligatorio no puede depender de un recurso opcional.")
    done, pending = set(), set()

    def visit(name):
        """Detecta ciclos antes de escribir o descargar cualquier componente."""
        if name in pending:
            raise ValueError("Dependencias cíclicas en la edición.")
        if name in done:
            return
        if len(pending) >= 64:
            raise ValueError("Grafo de dependencias demasiado profundo.")
        pending.add(name)
        for dependency in components[name]["requires"]:
            visit(dependency)
        pending.remove(name)
        done.add(name)

    for name in components:
        visit(name)


def selected_resources(manifest: dict, optional=()) -> list[str]:
    """Selecciona base obligatoria y opciones consentidas, sin descargar dependencias opcionales por sorpresa."""
    validate_manifest(manifest)
    resources = manifest["resources"]
    optional = set(optional)
    if optional - resources.keys():
        raise ValueError("Selección de recursos opcionales desconocida.")
    selected = optional | {name for name, item in resources.items() if not item["optional"]}
    available = selected | GROUPS
    if any(set(resources[name]["requires"]) - available for name in selected):
        raise ValueError("Faltan dependencias en la selección opcional; selecciona explícitamente el conjunto requerido.")
    return sorted(selected)


def resource_path(root: Path, sha256: str) -> Path:
    """Genera una ruta local por contenido; nunca usa nombres o rutas incluidos en el manifiesto remoto."""
    if not isinstance(sha256, str) or re.fullmatch(r"[a-f0-9]{64}", sha256) is None:
        raise ValueError("Huella de recurso inválida.")
    folder = root / RESOURCE_FOLDER
    path = folder / f"{sha256}.blob"
    if (folder.is_symlink() or folder.is_junction() or path.is_symlink() or path.is_junction()
            or path.resolve().parent != folder.resolve()):
        raise ValueError("Ruta local de recurso no permitida.")
    return path


def validate_content(data: bytes, item: dict) -> None:
    """Comprueba bytes, codificación y sintaxis del formato admitido, sin inferir semántica astronómica."""
    if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError("Integridad del recurso no coincide con su edición.")
    text = data.decode("utf-8")
    if item["format"] == "json-v1":
        content = json.loads(text)
        json.dumps(content, allow_nan=False)


def prepare_resource(root: Path, item: dict, reader) -> Path:
    """Reutiliza solo archivos verificados; publica un archivo nuevo sin sustituir activos ni limpiar históricos."""
    path = resource_path(root, item["sha256"])
    if path.exists():
        if path.stat().st_size != item["size"]:
            raise ValueError("El recurso local está alterado; se conserva sin sobrescribir.")
        validate_content(path.read_bytes(), item)
        return path
    data = reader(item["url"], item["size"])
    validate_content(data, item)
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_name(f"{uuid4().hex}.part")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            validate_content(path.read_bytes(), item)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def verify_binding(root: Path, binding: dict, versions: dict) -> dict[str, Path]:
    """Verifica la selección fijada a una SQLite; una ausencia opcional declarada no equivale a archivo perdido."""
    if not isinstance(binding, dict) or set(binding) != {"manifest", "selected"}:
        raise ValueError("Vinculación de recursos incompatible.")
    manifest = binding["manifest"]
    selected = binding["selected"]
    if not isinstance(selected, list) or any(not isinstance(name, str) for name in selected):
        raise ValueError("Selección local de recursos inválida.")
    if selected_resources(manifest, selected) != sorted(selected) or len(selected) != len(set(selected)):
        raise ValueError("La selección local no contiene los recursos obligatorios.")
    for group, item in manifest["packages"].items():
        if not isinstance(versions.get(group), dict) or any(versions[group].get(key) != item[key] for key in ("version", "sha256")):
            raise ValueError("Versiones de catálogo y recursos no pertenecen a la misma edición.")
    result = {}
    for name in selected:
        item = manifest["resources"][name]
        path = resource_path(root, item["sha256"])
        if not path.is_file() or path.stat().st_size != item["size"]:
            raise ValueError("Recurso de la edición ausente o alterado.")
        validate_content(path.read_bytes(), item)
        result[name] = path
    return result
