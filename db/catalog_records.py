"""Persistencia y resolución de identidades de una edición; los alias ambiguos nunca eligen un objeto arbitrario."""

import json

TABLES = {
    "objects": "pass_id,package_group,row_kind,row_id",
    "source_records": "source,source_key,pass_id,payload",
    "designations": "namespace,designation,pass_id",
    "object_relations": "source_id,target_id,kind,evidence",
}


def has_records(catalog) -> bool:
    """Comprueba las tablas de metadatos de una edición ya fijada por el llamante."""
    tables = {row[0] for row in catalog.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return set(TABLES) <= tables


def insert_records(catalog, group: str, row_kind: str, row_ids: list[int], records: list[dict]) -> None:
    """Inserta identidades aportadas y preserva fuentes literales; SQLite comprueba cruces y destinos al confirmar."""
    for record in records:
        pass_id = record["pass_id"]
        catalog.execute("INSERT INTO objects VALUES (?,?,?,?)", (pass_id, group, row_kind, row_ids[record["row"]]))
        for source in record["sources"]:
            catalog.execute("INSERT INTO source_records VALUES (?,?,?,?)",
                            (source["source"], source["key"], pass_id, json.dumps(source, ensure_ascii=False, allow_nan=False)))
        for alias in record["aliases"]:
            catalog.execute("INSERT INTO designations VALUES (?,?,?)", (alias["namespace"], alias["designation"], pass_id))
        for relation in record["relations"]:
            catalog.execute("INSERT INTO object_relations VALUES (?,?,?,?)",
                            (pass_id, relation["target"], relation["kind"], relation["evidence"]))


def resolve(catalog, designation: str, namespace: str | None = None) -> str | None:
    """Resuelve la referencia literal solo si designaciones y proyección apuntan a una única identidad de objeto."""
    if not has_records(catalog):
        return None
    parameters = [designation, designation]
    direct = "c.object_id=? COLLATE NOCASE"
    alias = "d.designation=? COLLATE NOCASE"
    if namespace is not None:
        direct += " AND c.catalog=?"
        alias += " AND d.namespace=?"
        parameters = [designation, namespace, designation, namespace]
    rows = catalog.execute(
        "SELECT o.pass_id FROM catalog c LEFT JOIN objects o ON o.row_kind='catalog' AND o.row_id=c.id WHERE " + direct
        + " UNION SELECT o.pass_id FROM objects o JOIN designations d ON d.pass_id=o.pass_id "
        + "WHERE o.row_kind='catalog' AND " + alias + " LIMIT 2", parameters,
    ).fetchall()
    return rows[0][0] if len(rows) == 1 else None


def object_rows(catalog) -> list[dict]:
    """Aporta la identidad explícita junto a cada proyección, sin derivarla de la designación ni del ID SQLite."""
    if not has_records(catalog):
        return [dict(row) for row in catalog.execute("SELECT * FROM catalog")]
    return [dict(row) for row in catalog.execute(
        "SELECT c.*,o.pass_id FROM catalog c LEFT JOIN objects o ON o.row_kind='catalog' AND o.row_id=c.id"
    )]


def lookup(catalog, designation: str, namespace: str | None = None) -> dict | None:
    """Busca una proyección inequívoca por designación/alias, incluyendo las filas legacy de una edición mixta."""
    if not has_records(catalog):
        sql = "SELECT * FROM catalog WHERE object_id=? COLLATE NOCASE"
        parameters = [designation]
        if namespace is not None:
            sql += " AND catalog=?"
            parameters.append(namespace)
    else:
        direct = "c.object_id=? COLLATE NOCASE"
        alias = "d.designation=? COLLATE NOCASE"
        parameters = [designation, designation]
        if namespace is not None:
            direct += " AND c.catalog=?"
            alias += " AND d.namespace=?"
            parameters = [designation, namespace, designation, namespace]
        sql = ("SELECT c.*,o.pass_id FROM catalog c "
               "LEFT JOIN objects o ON o.row_kind='catalog' AND o.row_id=c.id WHERE (" + direct
               + ") OR o.pass_id IN (SELECT d.pass_id FROM designations d WHERE " + alias + ")")
    rows = catalog.execute(sql + " LIMIT 2", parameters).fetchall()
    return dict(rows[0]) if len(rows) == 1 else None


def validate_continuity(captured: dict, records: dict) -> None:
    """Impide reasignar una clave conocida o reciclar una identidad para una fuente completamente distinta."""
    previous = {}
    identities = {}
    for source, key, pass_id, _payload in captured.get("source_records", (None, []))[1]:
        previous[source, key] = pass_id
        identities.setdefault(pass_id, set()).add((source, key))
    for group_records in records.values():
        for record in group_records:
            pass_id = record["pass_id"]
            keys = {(source["source"], source["key"]) for source in record["sources"]}
            if any(key in previous and previous[key] != pass_id for key in keys):
                raise ValueError("El paquete reasigna una clave de fuente conocida a otra identidad PASS.")
            if pass_id in identities and not keys & identities[pass_id]:
                raise ValueError("El paquete reutiliza una identidad sin conservar ninguna de sus fuentes conocidas.")


def describe(catalog, pass_id: str) -> dict | None:
    """Devuelve procedencia original y relaciones sin atribuirles validez científica o permisos no comprobados."""
    if not has_records(catalog) or catalog.execute("SELECT 1 FROM objects WHERE pass_id=?", (pass_id,)).fetchone() is None:
        return None
    return {
        "pass_id": pass_id,
        "sources": [json.loads(row[0]) for row in catalog.execute("SELECT payload FROM source_records WHERE pass_id=? ORDER BY source,source_key", (pass_id,))],
        "aliases": [{"namespace": row[0], "designation": row[1]} for row in catalog.execute("SELECT namespace,designation FROM designations WHERE pass_id=? ORDER BY namespace,designation", (pass_id,))],
        "relations": [{"target": row[0], "kind": row[1], "evidence": row[2]} for row in catalog.execute("SELECT target_id,kind,evidence FROM object_relations WHERE source_id=? ORDER BY target_id,kind", (pass_id,))],
    }
