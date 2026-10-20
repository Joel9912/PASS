"""Registro persistente de identidades de catálogo, separado de la base personal y de las ediciones."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

_SCHEMA = """
CREATE TABLE IF NOT EXISTS identity_schema(version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS objects(pass_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS source_records(
    source TEXT NOT NULL,
    source_key TEXT NOT NULL,
    pass_id TEXT NOT NULL REFERENCES objects(pass_id),
    PRIMARY KEY(source, source_key)
);
CREATE TABLE IF NOT EXISTS designations(
    namespace TEXT NOT NULL,
    designation TEXT NOT NULL,
    pass_id TEXT NOT NULL REFERENCES objects(pass_id),
    PRIMARY KEY(namespace, designation, pass_id)
);
CREATE INDEX IF NOT EXISTS source_object ON source_records(pass_id);
CREATE INDEX IF NOT EXISTS designation_object ON designations(pass_id);
"""


def _text(value: str) -> str:
    """Rechaza claves ausentes o con espacios exteriores sin normalizar la identidad original."""
    if not isinstance(value, str) or not value.strip() or value != value.strip() or "\x00" in value:
        raise ValueError("Identidad de fuente o designación inválida.")
    return value


@contextmanager
def identity_registry(path: Path) -> Iterator[sqlite3.Connection]:
    """Abre un registro del preparador con transacción y FK, nunca la base personal de PASS.

    Una ruta debe pertenecer al área de preparación, aportada explícitamente;
    no se crea bajo data/pass.db ni se acepta una base ajena como registro.
    Las versiones futuras se rechazan sin intentar convertirlas.
    """
    path = Path(path)
    if path.name.casefold() == "pass.db" or path.is_symlink() or path.is_junction():
        raise ValueError("El registro de identidades debe ser independiente de la base personal.")
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and tables != {"identity_schema", "objects", "source_records", "designations"}:
            raise ValueError("La base elegida no es un registro de identidades PASS.")
        if tables:
            versions = conn.execute("SELECT version FROM identity_schema").fetchall()
            if versions != [(1,)]:
                raise ValueError("Versión del registro de identidades no compatible.")
        with conn:
            statement = ""
            for line in _SCHEMA.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    conn.execute(statement)
                    statement = ""
            if not tables:
                conn.execute("INSERT INTO identity_schema VALUES (1)")
            yield conn
    finally:
        conn.close()


def identify(conn: sqlite3.Connection, source: str, source_key: str, *, same_as: str | None = None) -> str:
    """Conserva identidad entre ediciones; solo un cruce explícito permite unir dos registros de fuente.

    source_key procede de la fuente, no de coordenadas redondeadas ni del
    número de fila de una exportación. No asume que un alias LDN/Barnard o
    una región compartida equivalgan al mismo objeto físico.
    """
    source, source_key = _text(source), _text(source_key)
    if same_as is not None:
        same_as = _text(same_as)
        if conn.execute("SELECT 1 FROM objects WHERE pass_id=?", (same_as,)).fetchone() is None:
            raise ValueError("El cruce apunta a una identidad PASS inexistente.")
    row = conn.execute("SELECT pass_id FROM source_records WHERE source=? AND source_key=?",
                       (source, source_key)).fetchone()
    if row:
        if same_as is not None and row[0] != same_as:
            raise ValueError("El cruce contradice una identidad persistida; no se fusionan objetos automáticamente.")
        return row[0]
    pass_id = same_as or f"PASS-{uuid4()}"
    if same_as is None:
        conn.execute("INSERT INTO objects(pass_id) VALUES (?)", (pass_id,))
    conn.execute("INSERT INTO source_records VALUES (?,?,?)", (source, source_key, pass_id))
    return pass_id


def add_designation(conn: sqlite3.Connection, pass_id: str, namespace: str, designation: str) -> None:
    """Añade una designación literal sin convertirla en clave única ni resolver cruces ambiguos."""
    namespace, designation = _text(namespace), _text(designation)
    if conn.execute("SELECT 1 FROM objects WHERE pass_id=?", (pass_id,)).fetchone() is None:
        raise ValueError("La designación apunta a una identidad PASS inexistente.")
    conn.execute("INSERT OR IGNORE INTO designations VALUES (?,?,?)", (namespace, designation, pass_id))


def resolve_designation(conn: sqlite3.Connection, namespace: str, designation: str) -> str | None:
    """Resuelve solo una coincidencia inequívoca; ambigüedad/ausencia no autorizan migrar referencias personales."""
    rows = conn.execute("SELECT pass_id FROM designations WHERE namespace=? AND designation=? LIMIT 2",
                        (_text(namespace), _text(designation))).fetchall()
    return rows[0][0] if len(rows) == 1 else None


def link_personal_references(personal: sqlite3.Connection, registry: sqlite3.Connection) -> dict[str, int]:
    """Añade vínculos inequívocos sin reescribir designación, notas, encuadre, equipo o estado de sesiones.

    Las sesiones legacy no guardaban namespace: se exige una única identidad
    entre todos los alias literales coincidentes. Las regiones son personales.
    Una referencia ya vinculada nunca se reasigna. Un savepoint conserva el
    control de cualquier transacción previa del llamante, incluida activación.
    """
    counts = {"linked": 0, "unresolved": 0, "preserved": 0, "regions": 0}
    personal.execute("SAVEPOINT pass_catalog_links")
    try:
        for table, kind_column in (("personal_catalog", "kind"), ("planned_sessions", "target_kind")):
            rows = personal.execute(f"SELECT id,object_id,{kind_column},pass_object_id FROM {table}").fetchall()
            for row_id, designation, kind, previous in rows:
                if kind == "region":
                    counts["regions"] += 1
                    continue
                if previous is not None:
                    counts["preserved"] += 1
                    continue
                if table == "personal_catalog":
                    namespace = personal.execute("SELECT catalog FROM personal_catalog WHERE id=?", (row_id,)).fetchone()[0]
                    pass_id = resolve_designation(registry, namespace, designation)
                else:
                    matches = registry.execute("SELECT DISTINCT pass_id FROM designations WHERE designation=? LIMIT 2",
                                               (designation,)).fetchall()
                    pass_id = matches[0][0] if len(matches) == 1 else None
                if pass_id is None:
                    counts["unresolved"] += 1
                else:
                    personal.execute(f"UPDATE {table} SET pass_object_id=? WHERE id=?", (pass_id, row_id))
                    counts["linked"] += 1
        personal.execute("RELEASE SAVEPOINT pass_catalog_links")
    except Exception:
        personal.execute("ROLLBACK TO SAVEPOINT pass_catalog_links")
        personal.execute("RELEASE SAVEPOINT pass_catalog_links")
        raise
    return counts
