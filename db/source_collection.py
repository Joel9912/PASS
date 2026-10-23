"""Colecciones por fuente: archivos independientes y consulta federada en memoria, sin distribuir una base mezclada."""

import gzip
import hashlib
import io
import json
import os
import sqlite3
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
from threading import RLock
from uuid import uuid4

from . import catalog_editions as editions
from .catalog_records import insert_records, validate_continuity
from .data_resources import prepare_resource, selected_resources

SOURCE_FOLDER = "catalog-sources"
_SOURCE_PROOFS = OrderedDict()
_COLLECTION_PROOFS = OrderedDict()
_PROOF_LOCK = RLock()


def _known_proof(cache, key):
    """Reutiliza únicamente una comprobación semántica previa; el llamante ya debe haber verificado los bytes actuales."""
    with _PROOF_LOCK:
        if key not in cache:
            return False
        cache.move_to_end(key)
        return True


def _remember_proof(cache, key, limit):
    """Acota pruebas de contenido en memoria sin almacenar datos, rutas abiertas o conexiones SQLite."""
    with _PROOF_LOCK:
        cache[key] = True
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)


def validate_payload(content, item):
    """Comprueba una sola fuente literal, filas tipadas y procedencia sin cruzar ni completar sus medidas."""
    from planners.catalog_packages import GROUPS, validate_rows
    from planners.catalog_records import validate_records

    if (not isinstance(content, dict) or set(content) != {"format", "source_id", "groups"}
            or type(content["format"]) is not int or content["format"] != 3
            or content["source_id"] != item["source_id"] or not isinstance(content["groups"], dict)
            or not content["groups"] or set(content["groups"]) - set(GROUPS)):
        raise ValueError("Paquete por fuente incompatible.")
    identities, keys = set(), set()
    for group, component in content["groups"].items():
        if not isinstance(component, dict) or set(component) != {"rows", "records"}:
            raise ValueError("Proyección de fuente incompatible.")
        validate_rows(group, component["rows"])
        validate_records(component["rows"], component["records"])
        for record in component["records"]:
            if record["pass_id"] in identities:
                raise ValueError("La fuente repite una identidad en sus proyecciones.")
            identities.add(record["pass_id"])
            for source in record["sources"]:
                if (source["source"] != item["source_id"] or source["revision"] != item["revision"]
                        or source.get("license", item["license"]) != item["license"]):
                    raise ValueError("El paquete mezcla fuentes, revisiones o condiciones distintas; regenera sus aportaciones separadas.")
                key = source["source"], source["key"]
                if key in keys:
                    raise ValueError("Clave de fuente repetida.")
                keys.add(key)


def _source_path(root, relative):
    """Restringe un componente a un archivo SQLite propio y directo, sin enlaces o escapes de directorio."""
    if not isinstance(relative, str):
        raise TypeError("Ruta de fuente inválida.")
    folder = root / SOURCE_FOLDER
    path = root / relative
    if (folder.is_symlink() or folder.is_junction() or path.is_symlink() or path.is_junction()
            or path.parent != folder or path.resolve().parent != folder.resolve() or path.suffix != ".sqlite"):
        raise ValueError("Ruta de fuente no permitida.")
    return path


def _prepare_source(root, content, item):
    """Publica una fuente por SHA sin sobrescribir archivos; reintentos idénticos no duplican su volumen."""
    validate_payload(content, item)
    relative = f"{SOURCE_FOLDER}/{uuid4().hex}.sqlite"
    path = _source_path(root, relative)
    path.parent.mkdir(exist_ok=True)
    schema = editions.CATALOG_SCHEMA.read_text(encoding="utf-8")
    # Los destinos de relaciones pueden vivir en otra fuente: se verifican
    # sobre el conjunto, no se copian objetos ajenos para satisfacer una FK.
    schema = schema.replace("target_id TEXT NOT NULL REFERENCES objects(pass_id) DEFERRABLE INITIALLY DEFERRED,",
                            "target_id TEXT NOT NULL,")
    with path.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(path)) as target:
            target.executescript(schema)
            target.execute("PRAGMA foreign_keys=ON")
            with target:
                for group, component in content["groups"].items():
                    table, columns = ("stars", editions.STAR_COLUMNS) if group == "hyg" else ("catalog", editions.CAT_COLUMNS)
                    sql = f"INSERT INTO {table}({columns}) VALUES ({','.join('?' for _ in columns.split(','))})"
                    row_ids = [target.execute(sql, row).lastrowid for row in component["rows"]]
                    insert_records(target, group, table, row_ids, component["records"])
        digest, size = editions._digest(path), path.stat().st_size
        final_relative = f"{SOURCE_FOLDER}/{digest}.sqlite"
        final = _source_path(root, final_relative)
        try:
            os.link(path, final)
        except FileExistsError:
            if final.stat().st_size != size or editions._digest(final) != digest:
                raise ValueError("La fuente local está alterada; no se sobrescribe.") from None
        path.unlink()
        return {"relative_path": final_relative, "sha256": digest, "size_bytes": size}
    except Exception:
        path.unlink(missing_ok=True)
        raise


def validate_crosses(by_id, duplicates, crosses):
    """Exige cruces explícitos y completos, tanto al exportar como antes de activar una colección."""
    declared = set()
    for cross in crosses:
        if (not isinstance(cross, dict) or set(cross) != {"pass_id", "members", "evidence"}
                or not isinstance(cross["evidence"], str) or not cross["evidence"].strip()
                or not isinstance(cross["members"], list)):
            raise ValueError("Cruce de fuentes sin evidencia explícita.")
        members = set()
        for member in cross["members"]:
            if (not isinstance(member, dict) or set(member) != {"source", "key"}
                    or any(not isinstance(value, str) or not value.strip() for value in member.values())):
                raise ValueError("Miembro del cruce inválido.")
            members.add((member["source"], member["key"]))
        pass_id = cross["pass_id"]
        if (not isinstance(pass_id, str) or pass_id in declared or pass_id not in duplicates
                or len(members) != len(cross["members"]) or members != by_id.get(pass_id)):
            raise ValueError("Cruce incompleto, contradictorio o no utilizado.")
        declared.add(pass_id)
    if declared != duplicates:
        raise ValueError("Identidad compartida sin cruce revisado; no se fusiona automáticamente.")


def _check_crosses(conn, crosses):
    """Contrasta cruces y destinos contra los archivos realmente adjuntados, no solo el manifiesto."""
    by_id = {}
    for source, key, pass_id in conn.execute("SELECT source,source_key,pass_id FROM source_records"):
        by_id.setdefault(pass_id, set()).add((source, key))
    duplicates = {row[0] for row in conn.execute("SELECT pass_id FROM _candidates GROUP BY pass_id HAVING COUNT(*)>1")}
    if conn.execute("SELECT 1 FROM _candidates GROUP BY pass_id HAVING COUNT(DISTINCT row_kind)>1 LIMIT 1").fetchone():
        raise ValueError("Una identidad no puede ser a la vez estrella y objeto de espacio profundo.")
    validate_crosses(by_id, duplicates, crosses)
    if conn.execute("SELECT 1 FROM object_relations r LEFT JOIN objects o ON o.pass_id=r.target_id "
                    "WHERE o.pass_id IS NULL LIMIT 1").fetchone():
        raise ValueError("Relación con destino ausente en la colección.")


def open_collection(root, index_path, manifest):
    """Adjunta fuentes readonly y crea vistas temporales; selecciona filas enteras por prioridad declarada, sin promedios."""
    with closing(sqlite3.connect(index_path.as_uri() + "?mode=ro", uri=True)) as index:
        index.row_factory = sqlite3.Row
        components = {row["name"]: dict(row) for row in index.execute("SELECT * FROM source_components")}
    if set(components) != set(manifest["packages"]):
        raise ValueError("Índice y fuentes de la edición no coinciden.")
    conn = sqlite3.connect(":memory:", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA temp_store=MEMORY")
        attached = []
        source_proofs = []
        for number, (name, item) in enumerate(sorted(manifest["packages"].items(), key=lambda pair: pair[1]["priority"])):
            component = components[name]
            if component["package_sha256"] != item["sha256"]:
                raise ValueError("Fuente no pertenece a la edición seleccionada.")
            path = _source_path(root, component["relative_path"])
            if (not path.is_file() or path.stat().st_size != component["size_bytes"]
                    or editions._digest(path) != component["sha256"]):
                raise ValueError("Fuente ausente o alterada.")
            alias = f"source_{number}"
            conn.execute(f"ATTACH DATABASE ? AS {alias}", (path.as_uri() + "?mode=ro",))
            proof = (component["sha256"], item["source_id"], item["revision"], item["license"])
            if not _known_proof(_SOURCE_PROOFS, proof):
                if conn.execute(f"PRAGMA {alias}.quick_check").fetchone()[0] != "ok":
                    raise ValueError("Fuente SQLite inválida.")
                foreign = conn.execute(
                    f"SELECT 1 FROM {alias}.source_records WHERE source!=? OR json_extract(payload,'$.revision')!=? "
                    "OR COALESCE(json_extract(payload,'$.license'),?)!=? LIMIT 1",
                    (item["source_id"], item["revision"], item["license"], item["license"]),
                ).fetchone()
                if foreign or conn.execute(f"PRAGMA {alias}.foreign_key_check").fetchone():
                    raise ValueError("Fuente mezclada o relaciones locales inválidas.")
                _remember_proof(_SOURCE_PROOFS, proof, 32)
            source_proofs.append((name, item["priority"], proof))
            attached.append(alias)
        candidates = [f"SELECT *,{number} AS origin,row_id+{number * 1000000000} AS global_id FROM {alias}.objects"
                      for number, alias in enumerate(attached)]
        conn.execute("CREATE TEMP VIEW _candidates AS " + " UNION ALL ".join(candidates))
        choices = []
        for number, alias in enumerate(attached):
            query = f"SELECT o.*,{number} AS origin,o.row_id+{number * 1000000000} AS global_id FROM {alias}.objects o"
            if number:
                query += " WHERE " + " AND ".join(
                    f"NOT EXISTS(SELECT 1 FROM {previous}.objects p WHERE p.pass_id=o.pass_id)" for previous in attached[:number]
                )
            choices.append(query)
        conn.execute("CREATE TEMP TABLE _chosen AS " + " UNION ALL ".join(choices))
        conn.execute("CREATE UNIQUE INDEX chosen_identity ON _chosen(pass_id)")
        conn.execute("CREATE INDEX chosen_projection ON _chosen(origin,row_kind,row_id)")
        conn.execute("CREATE INDEX chosen_global_id ON _chosen(global_id,row_kind)")
        conn.execute("CREATE TEMP VIEW objects AS SELECT pass_id,package_group,row_kind,global_id AS row_id FROM _chosen")
        for table, columns in (("catalog", editions.CAT_COLUMNS), ("stars", editions.STAR_COLUMNS)):
            parts = [f"SELECT c.global_id AS id,{','.join('t.' + name for name in columns.split(','))} "
                     f"FROM {alias}.{table} t JOIN _chosen c ON c.origin={number} AND c.row_kind='{table}' AND c.row_id=t.id"
                     for number, alias in enumerate(attached)]
            conn.execute(f"CREATE TEMP VIEW {table} AS " + " UNION ALL ".join(parts))
        for table in ("source_records", "designations", "object_relations"):
            separator = " UNION ALL " if table == "source_records" else " UNION "
            conn.execute(f"CREATE TEMP VIEW {table} AS " + separator.join(f"SELECT * FROM {alias}.{table}" for alias in attached))
        proof = (tuple(source_proofs), json.dumps(manifest["cross_identifications"], sort_keys=True, ensure_ascii=False))
        if not _known_proof(_COLLECTION_PROOFS, proof):
            _check_crosses(conn, manifest["cross_identifications"])
            _remember_proof(_COLLECTION_PROOFS, proof, 8)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        return conn
    except Exception:
        conn.close()
        raise


def install(db_path, manifest, *, reader, optional=None, expected_empty=False):
    """Prepara fuentes/recursos y activa un índice único; no migra ni reinicia datos experimentales por rutina."""
    uri = Path(db_path).absolute().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True)) as personal:
        before = editions.active_id(personal)
        old = editions._record(personal, before) if before else None
        root = editions._root(personal)
        with editions.data_snapshot(personal) as (catalog, _resources, binding):
            if expected_empty and (before or any(catalog.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                                                for table in ("catalog", "stars"))):
                return
        if optional is None:
            optional = [name for name in (binding["selected"] if binding else []) if name in manifest["resources"]]
        selected = selected_resources(manifest, optional)
        new_binding = {"manifest": manifest, "selected": selected}
        if old and old["schema_version"] == 3 and binding == new_binding:
            return
        for name in selected:
            prepare_resource(root, manifest["resources"][name], reader)
        previous = {}
        if old and old["schema_version"] == 3:
            with closing(sqlite3.connect(editions._path(root, old))) as index:
                index.row_factory = sqlite3.Row
                previous = {row["name"]: dict(row) for row in index.execute("SELECT * FROM source_components")}
        components = {}
        for name, item in manifest["packages"].items():
            if name in previous and previous[name]["package_sha256"] == item["sha256"]:
                components[name] = previous[name]
                continue
            data = reader(item["url"], item["size"])
            if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("Integridad del paquete de fuente incorrecta.")
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                payload = stream.read(64 * 1024 * 1024 + 1)
            if len(payload) > 64 * 1024 * 1024:
                raise ValueError("Fuente descomprimida demasiado grande.")
            components[name] = {**_prepare_source(root, json.loads(payload), item), "package_sha256": item["sha256"]}
        folder = root / editions.EDITION_FOLDER
        if folder.is_symlink() or folder.is_junction():
            raise ValueError("Carpeta de índices no permitida.")
        folder.mkdir(exist_ok=True)
        identifier = uuid4().hex
        index_path = folder / f"{identifier}.sqlite"
        with index_path.open("xb"):
            pass
        with closing(sqlite3.connect(index_path)) as index, index:
            index.execute("CREATE TABLE source_components(name TEXT PRIMARY KEY,relative_path TEXT NOT NULL,"
                          "sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,package_sha256 TEXT NOT NULL)")
            index.executemany("INSERT INTO source_components VALUES (:name,:relative_path,:sha256,:size_bytes,:package_sha256)",
                              [{**component, "name": name} for name, component in components.items()])
        versions = {name: {key: item[key] for key in ("version", "date", "sha256")} for name, item in manifest["packages"].items()}
        record = {"edition_id": identifier, "schema_version": 3, "relative_path": f"{editions.EDITION_FOLDER}/{index_path.name}",
                  "sha256": editions._digest(index_path), "size_bytes": index_path.stat().st_size,
                  "versions": json.dumps(versions), "previous_id": before, "resource_manifest": json.dumps(new_binding)}
        with closing(editions._open(root, record)) as candidate:
            incoming = {}
            for source, key, pass_id in candidate.execute("SELECT source,source_key,pass_id FROM source_records"):
                incoming.setdefault(pass_id, []).append({"source": source, "key": key})
        with personal:
            personal.execute("BEGIN IMMEDIATE")
            if editions.active_id(personal) != before:
                raise ValueError("La edición cambió durante la preparación; no se activa sobre otra selección.")
            # Es validación de identidad de las nuevas colecciones, no una
            # migración para rescatar estados experimentales anteriores.
            for (previous_id,) in personal.execute("SELECT edition_id FROM catalog_editions WHERE schema_version=3"):
                with closing(editions._open(root, editions._record(personal, previous_id))) as previous_catalog:
                    previous_records = [tuple(row) for row in previous_catalog.execute(
                        "SELECT source,source_key,pass_id,payload FROM source_records")]
                validate_continuity({"source_records": (None, previous_records)},
                                    {"collection": [{"pass_id": key, "sources": values} for key, values in incoming.items()]})
            if expected_empty and (before or any(personal.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                                                 for table in ("catalog", "stars"))):
                raise ValueError("El catálogo se rellenó mientras se preparaban sus fuentes.")
            personal.execute("INSERT INTO catalog_editions(edition_id,schema_version,relative_path,sha256,size_bytes,versions,"
                             "previous_id,resource_manifest) VALUES (:edition_id,:schema_version,:relative_path,:sha256,"
                             ":size_bytes,:versions,:previous_id,:resource_manifest)", record)
            editions._activate(personal, record, versions)
