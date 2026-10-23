"""Ediciones SQLite de catálogo separadas, inmutables tras prepararlas y activadas sin restaurar datos personales."""

import hashlib
import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4

from .catalog_identity import link_personal_references
from .catalog_records import (
    TABLES,
    has_records,
    insert_records,
    resolve,
    validate_continuity,
)
from .data_resources import verify_binding

ACTIVE_KEY = "catalog_active_edition"
EDITION_FOLDER = "catalog-editions"
CATALOG_SCHEMA = Path(__file__).with_name("catalog_schema.sql")
CAT_COLUMNS = ("object_id,catalog,messier_num,ngc_num,ic_num,name,type,magnitude,"
               "ra_hours,dec_deg,size_major_arcmin,size_minor_arcmin,constellation")
STAR_COLUMNS = "name,magnitude,ra_hours,dec_deg,color,constellation"


class CatalogUnavailableError(ValueError):
    """La edición indicada no está disponible; no se oculta el fallo mezclando un catálogo legacy distinto."""


def _root(conn: sqlite3.Connection) -> Path:
    """Obtiene la raíz de la conexión llamante, nunca de un global que pueda pertenecer a otra base."""
    filename = next((row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"), "")
    if not filename:
        raise CatalogUnavailableError("La base personal no tiene una ruta de catálogo persistente.")
    return Path(filename).absolute().parent


def active_id(conn: sqlite3.Connection) -> str | None:
    """Lee una sola elección de edición; ausencia significa legacy, no vigencia acreditada."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'").fetchone() is None:
        return None
    row = conn.execute("SELECT value FROM settings WHERE key=?", (ACTIVE_KEY,)).fetchone()
    return row[0] if row else None


def require_legacy_catalog(conn: sqlite3.Connection) -> None:
    """Evita que el cargador manual escriba una tabla oculta después de adoptar ediciones separadas."""
    if active_id(conn) is not None:
        raise ValueError("Hay una edición de catálogo activa; actualiza sus paquetes desde Configuración, no las tablas legacy.")


def _record(conn: sqlite3.Connection, edition_id: str) -> dict:
    """Recupera metadatos del registro local; un puntero huérfano se conserva y se comunica como no disponible."""
    try:
        cursor = conn.execute("SELECT edition_id,schema_version,resource_manifest,relative_path,sha256,size_bytes,versions,previous_id "
                              "FROM catalog_editions WHERE edition_id=?", (edition_id,))
        row = cursor.fetchone()
    except sqlite3.Error as exc:
        raise CatalogUnavailableError("El registro de ediciones no está disponible.") from exc
    if row is None:
        raise CatalogUnavailableError("La edición activa no figura en el registro local.")
    return dict(zip((column[0] for column in cursor.description), row, strict=True))


def _digest(path: Path) -> str:
    """Comprueba contenido por bloques sin cargar toda la base en memoria."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _path(root: Path, record: dict) -> Path:
    """Restringe una edición a un archivo directo, sin enlaces ni rutas suministradas por el paquete remoto."""
    folder = root / EDITION_FOLDER
    relative = record["relative_path"]
    if not isinstance(relative, str):
        raise CatalogUnavailableError("Ruta de edición inválida.")
    path = root / relative
    if (folder.is_symlink() or folder.is_junction() or path.is_symlink() or path.is_junction()
            or path.parent != folder or path.resolve().parent != folder.resolve() or path.suffix != ".sqlite"):
        raise CatalogUnavailableError("La ruta de edición no es un archivo permitido.")
    return path


def _open(root: Path, record: dict) -> sqlite3.Connection:
    """Verifica tamaño/huella y abre readonly; una edición corrupta nunca se sustituye silenciosamente."""
    conn = None
    try:
        if record["schema_version"] not in (1, 2, 3):
            raise CatalogUnavailableError("Formato de edición no compatible; se conserva sin convertir.")
        if record.get("resource_manifest") is not None:
            verify_binding(root, json.loads(record["resource_manifest"]), json.loads(record["versions"]))
        path = _path(root, record)
        if not path.is_file() or path.stat().st_size != record["size_bytes"] or _digest(path) != record["sha256"]:
            raise CatalogUnavailableError("La edición falta o su integridad no coincide con el registro.")
        if record["schema_version"] == 3:
            from .source_collection import open_collection

            binding = json.loads(record["resource_manifest"])
            if binding["manifest"]["format"] != 3:
                raise ValueError("El índice por fuentes requiere un manifiesto de colección.")
            return open_collection(root, path, binding["manifest"])
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise CatalogUnavailableError("La edición no supera la comprobación SQLite.")
        for table, columns in (("catalog", CAT_COLUMNS), ("stars", STAR_COLUMNS)):
            conn.execute(f"SELECT id,{columns} FROM {table} LIMIT 0")
        if record["schema_version"] == 2:
            for table, columns in TABLES.items():
                conn.execute(f"SELECT {columns} FROM {table} LIMIT 0")
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise CatalogUnavailableError("Relaciones de catálogo incompletas.")
        return conn
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        if conn is not None:
            conn.close()
        raise CatalogUnavailableError(f"Catálogo no disponible: {exc}") from exc


@contextmanager
def catalog_snapshot(personal: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Fija la edición de una lectura completa; no cierra ni cambia una conexión personal prestada."""
    edition = active_id(personal)
    if edition is None:
        yield personal
    else:
        with closing(_open(_root(personal), _record(personal, edition))) as catalog:
            yield catalog


@contextmanager
def data_snapshot(personal: sqlite3.Connection):
    """Fija catálogo y rutas de recursos de una sola edición, sin consultar otra selección durante la lectura."""
    edition = active_id(personal)
    if edition is None:
        yield personal, {}, None
        return
    record = _record(personal, edition)
    with closing(_open(_root(personal), record)) as catalog:
        binding = json.loads(record["resource_manifest"]) if record["resource_manifest"] else None
        resources = verify_binding(_root(personal), binding, json.loads(record["versions"])) if binding else {}
        yield catalog, resources, binding


def read_rows(personal: sqlite3.Connection, sql: str, parameters=()) -> list:
    """Lee la edición vigente; ante pérdida devuelve ausencia explícita en vez de datos de otra edición."""
    try:
        with catalog_snapshot(personal) as catalog:
            return catalog.execute(sql, parameters).fetchall()
    except CatalogUnavailableError as exc:
        logging.getLogger(__name__).error("%s", exc)
        return []


def reference_id(personal: sqlite3.Connection, designation: str, namespace: str | None = None) -> str | None:
    """Vincula nuevas referencias solo a una identidad explícita de la edición activa; legacy sigue sin atribución."""
    if active_id(personal) is None:
        return None
    try:
        with catalog_snapshot(personal) as catalog:
            return resolve(catalog, designation, namespace)
    except CatalogUnavailableError:
        return None


def status(personal: sqlite3.Connection) -> dict:
    """Estado local comprobable para Configuración, independiente de que una release declare la misma huella."""
    edition = active_id(personal)
    prepared = _unactivated_count(personal)
    if edition is None:
        return {"edition": None, "available": True, "previous": False, "error": "", "prepared": prepared}
    record = None
    try:
        record = _record(personal, edition)
        with closing(_open(_root(personal), record)):
            pass
        return {"edition": edition, "available": True, "previous": bool(record["previous_id"]), "error": "", "prepared": prepared}
    except CatalogUnavailableError as exc:
        return {"edition": edition, "available": False,
                "previous": bool(record and record["previous_id"]), "error": str(exc), "prepared": prepared}


def _unactivated_count(personal: sqlite3.Connection) -> int:
    """Detecta archivos preparados/interrumpidos sin promoverlos ni borrarlos automáticamente."""
    try:
        root = _root(personal)
        folder = root / EDITION_FOLDER
        if not folder.is_dir() or folder.is_symlink() or folder.is_junction():
            return 0
        known = {row[0] for row in personal.execute("SELECT relative_path FROM catalog_editions")}
        return sum(path.suffix == ".sqlite" and f"{EDITION_FOLDER}/{path.name}" not in known
                   for path in folder.iterdir() if not path.is_symlink() and not path.is_junction())
    except (OSError, sqlite3.Error, CatalogUnavailableError):
        return 0


def _capture(source: sqlite3.Connection, *, include_records: bool = False) -> dict:
    """Captura solo tablas astronómicas; nunca clona equipo, ubicaciones, sesiones, notas o claves."""
    result = {}
    for table, fields in (("catalog", CAT_COLUMNS), ("stars", STAR_COLUMNS)):
        columns = "id," + fields
        cursor = source.execute(f"SELECT {columns} FROM {table} ORDER BY id")
        result[table] = (columns, [tuple(row) for row in cursor])
    if include_records and has_records(source):
        for table, columns in TABLES.items():
            result[table] = (columns, [tuple(row) for row in source.execute(f"SELECT {columns} FROM {table}")])
    return result


def _candidate(root: Path, captured: dict, replacements: dict, versions: dict, previous: str | None, *, records=None) -> dict:
    """Construye un archivo nuevo; un fallo elimina solo este candidato, nunca un recurso activo o anterior."""
    folder = root / EDITION_FOLDER
    if folder.is_symlink() or folder.is_junction():
        raise CatalogUnavailableError("La carpeta de ediciones no puede ser un enlace.")
    folder.mkdir(exist_ok=True)
    edition_id = uuid4().hex
    path = folder / f"{edition_id}.sqlite"
    with path.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(path)) as target, target:
            target.execute("PRAGMA foreign_keys=ON")
            statement = ""
            for line in CATALOG_SCHEMA.read_text(encoding="utf-8").splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    target.execute(statement)
                    statement = ""
            target.execute("BEGIN")
            target.execute("PRAGMA defer_foreign_keys=ON")
            for table, (columns, rows) in captured.items():
                placeholders = ",".join("?" for _ in columns.split(","))
                target.executemany(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", rows)
            for group, (columns, rows) in replacements.items():
                table = "stars" if group == "hyg" else "catalog"
                old_ids = target.execute("SELECT 1 FROM objects WHERE package_group=? LIMIT 1", (group,)).fetchone()
                if old_ids and group not in (records or {}):
                    raise ValueError("El componente ya tiene identidades: no se admite una actualización que las pierda.")
                target.execute("DELETE FROM objects WHERE package_group=?", (group,))
                clause = "" if group == "hyg" else (" WHERE catalog='ldn'" if group == "ldn" else " WHERE catalog!='ldn'")
                target.execute(f"DELETE FROM {table}{clause}")
                placeholders = ",".join("?" for _ in columns.split(","))
                sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
                if group in (records or {}):
                    row_ids = [target.execute(sql, row).lastrowid for row in rows]
                    insert_records(target, group, table, row_ids, records[group])
                else:
                    target.executemany(sql, rows)
            if target.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("Una relación del paquete apunta a una identidad ausente; no se activa una edición incompleta.")
        record = {"edition_id": edition_id, "schema_version": 2, "relative_path": f"{EDITION_FOLDER}/{path.name}",
                  "sha256": _digest(path), "size_bytes": path.stat().st_size,
                  "versions": json.dumps(versions, ensure_ascii=False), "previous_id": previous}
        with closing(_open(root, record)):
            pass
        return record
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _legacy_versions(conn: sqlite3.Connection, groups) -> dict:
    """Mantiene desconocidas las versiones legacy que nunca se identificaron."""
    result = {}
    for group in groups:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (f"catalog_package_{group}",)).fetchone()
        result[group] = json.loads(row[0]) if row else None
    return result


def _validate_history(personal: sqlite3.Connection, records: dict) -> None:
    """Contrasta identidades con todas las ediciones conservadas, también las posteriores a una recuperación.

    Sin un recurso histórico verificable no se puede descartar un reciclado
    de identidad: se conserva la selección y se exige reparar ese recurso.
    """
    if not records:
        return
    root = _root(personal)
    for (edition_id,) in personal.execute("SELECT edition_id FROM catalog_editions WHERE schema_version!=1"):
        with closing(_open(root, _record(personal, edition_id))) as catalog:
            previous = [tuple(row) for row in catalog.execute("SELECT source,source_key,pass_id,payload FROM source_records")]
            validate_continuity({"source_records": (None, previous)}, records)


def install_edition(db_path: Path, replacements: dict, versions: dict, groups, *, only_missing: bool = False, records=None,
                    resource_manifest=None, expected_active=None, require_expected=False, require_empty=False) -> None:
    """Prepara fuera de pass.db y activa con comparación optimista, sin borrar tablas legacy ni edición anterior."""
    if not replacements and resource_manifest is None:
        return
    uri = Path(db_path).absolute().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as personal:
        root = _root(personal)
        personal.execute("BEGIN")
        before = active_id(personal)
        if before and _record(personal, before)["schema_version"] == 3:
            raise ValueError("Hay una colección por fuentes activa; actualiza el conjunto, no construyas una base mezclada.")
        if require_expected and before != expected_active:
            raise ValueError("La edición cambió mientras se preparaban los recursos; no se activa sobre otra selección.")
        if before and _record(personal, before)["resource_manifest"] and resource_manifest is None:
            raise ValueError("Hay una edición global activa; actualiza el conjunto, no un catálogo separado.")
        with catalog_snapshot(personal) as source:
            captured = _capture(source, include_records=source is not personal)
        if require_empty and (before is not None or captured["catalog"][1] or captured["stars"][1]):
            return
        old_versions = _legacy_versions(personal, groups)
        personal.rollback()
        if only_missing:
            catalog_index = captured["catalog"][0].split(",").index("catalog")
            missing = {"hyg": not captured["stars"][1],
                       "ldn": not any(row[catalog_index] == "ldn" for row in captured["catalog"][1]),
                       "openngc": not any(row[catalog_index] != "ldn" for row in captured["catalog"][1])}
            replacements = {group: rows for group, rows in replacements.items() if missing[group]}
            versions = {group: value for group, value in versions.items() if group in replacements}
            records = {group: value for group, value in (records or {}).items() if group in replacements}
            if not replacements:
                return
        _validate_history(personal, records or {})
        baseline = None if before else _candidate(root, captured, {}, old_versions, None)
        previous = before or baseline["edition_id"]
        updated = {**old_versions, **versions}
        validate_continuity(captured, records or {})
        candidate = _candidate(root, captured, replacements, updated, previous, records=records)
        candidate["resource_manifest"] = json.dumps(resource_manifest, ensure_ascii=False) if resource_manifest is not None else None
        with closing(_open(root, candidate)):
            pass
        with personal:
            personal.execute("BEGIN IMMEDIATE")
            if active_id(personal) != before or _legacy_versions(personal, groups) != old_versions:
                raise ValueError("Otra operación cambió los catálogos; comprueba las ediciones antes de reintentar.")
            _validate_history(personal, records or {})
            if before is None and _capture(personal) != captured:
                raise ValueError("El catálogo legacy cambió durante la preparación; se conserva sin sustituir.")
            for record in ([baseline, candidate] if baseline else [candidate]):
                record.setdefault("resource_manifest", None)
                personal.execute("INSERT INTO catalog_editions(edition_id,schema_version,resource_manifest,relative_path,sha256,size_bytes,versions,previous_id) "
                                 "VALUES (:edition_id,:schema_version,:resource_manifest,:relative_path,:sha256,:size_bytes,:versions,:previous_id)", record)
            _activate(personal, candidate, updated)


def _activate(personal: sqlite3.Connection, record: dict, versions: dict) -> None:
    """Confirma selección/versiones y vínculos aditivos; nunca restaura una copia vieja de la base personal."""
    if record["schema_version"] in (2, 3):
        with closing(_open(_root(personal), record)) as catalog:
            link_personal_references(personal, catalog)
    personal.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (ACTIVE_KEY, record["edition_id"]))
    for group, version in versions.items():
        key = f"catalog_package_{group}"
        if version is None:
            personal.execute("DELETE FROM settings WHERE key=?", (key,))
        else:
            personal.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(version)))


def restore_previous(db_path: Path) -> None:
    """Recupera la edición anterior por elección explícita, conservando todo trabajo personal posterior."""
    uri = Path(db_path).absolute().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as personal, personal:
        personal.execute("BEGIN IMMEDIATE")
        current = active_id(personal)
        record = _record(personal, current) if current else None
        if not record or not record["previous_id"]:
            raise ValueError("No hay una edición anterior registrada para recuperar.")
        previous = _record(personal, record["previous_id"])
        with closing(_open(_root(personal), previous)):
            pass
        _activate(personal, previous, json.loads(previous["versions"]))
