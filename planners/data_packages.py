"""Instalación explícita de edición global: recursos completos primero y un solo cambio de selección después."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from db import catalog_editions
from db.data_resources import prepare_resource, selected_resources, validate_manifest
from planners import catalog_packages


def parse_manifest(data) -> dict:
    """Valida la edición global y sus paquetes sin descargar ni adoptar contenido no compatible."""
    if len(data) > 65536:
        raise ValueError("Manifiesto global demasiado grande.")
    manifest = json.loads(data)
    validate_manifest(manifest)
    catalog_packages.parse_manifest(json.dumps({"format": 1, "packages": manifest["packages"]}))
    return manifest


def install(db_path, manifest: dict, *, reader=None, optional=None, expected_empty=False) -> None:
    """Prepara solo componentes diferentes; conserva selección y datos personales ante cualquier fallo.

    Sin selección opcional explícita conserva las opciones instaladas, nunca
    activa por primera vez un fondo opcional. El lector por defecto solo
    admite adjuntos PASS autorizados; la UI debe pedir consentimiento.
    """
    parse_manifest(json.dumps(manifest))
    uri = Path(db_path).absolute().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True)) as personal:
        before = catalog_editions.active_id(personal)
        versions = catalog_packages.installed(personal)
        with catalog_editions.data_snapshot(personal) as (catalog, _resources, binding):
            if expected_empty and (before is not None or any(catalog.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                                                           for table in ("catalog", "stars"))):
                return
        root = catalog_editions._root(personal)
    if optional is None:
        optional = [name for name in (binding["selected"] if binding else []) if name in manifest["resources"]]
    selected = selected_resources(manifest, optional)
    reader = reader or catalog_packages._read
    for name in selected:
        prepare_resource(root, manifest["resources"][name], reader)
    groups = [group for group in catalog_packages.GROUPS
              if not versions[group] or any(versions[group].get(key) != manifest["packages"][group][key]
                                            for key in ("version", "sha256"))]
    new_binding = {"manifest": manifest, "selected": selected}
    if not groups and binding == new_binding:
        return
    catalog_packages.update_packages(
        db_path, manifest["packages"], groups, reader=reader,
        resource_manifest=new_binding, expected_active=before, require_expected=True,
        require_empty=expected_empty,
    )


def describe(personal) -> dict | None:
    """Metadatos de la selección para Configuración; no presenta archivos opcionales ausentes como instalados."""
    current = catalog_editions.active_id(personal)
    if not current:
        return None
    raw = catalog_editions._record(personal, current)["resource_manifest"]
    if raw is None:
        return None
    binding = json.loads(raw)
    manifest = binding["manifest"]
    validate_manifest(manifest)
    return {"edition": manifest["edition"], "manifest": manifest, "selected": binding["selected"],
            "absent_optional": sorted(set(manifest["resources"]) - set(binding["selected"]))}
