"""Borradores locales independientes de sesiones guardadas y configuración."""

import json
import math
import sqlite3
from uuid import uuid4

from db.connection import get_connection

FORMAT_VERSION = 1
MAX_BYTES = 16 * 1024 * 1024
WORKFLOWS = ("planner", "stacker")


class DraftError(ValueError):
    """Impide reemplazar un borrador ilegible, incompatible o cambiado por otra instancia."""


def read(workflow: str) -> dict | None:
    """Lee la fila sin interpretarla para permitir conservar incluso formatos futuros."""
    _check_workflow(workflow)
    row = get_connection().execute(
        "SELECT * FROM work_drafts WHERE workflow = ?", (workflow,)
    ).fetchone()
    return dict(row) if row is not None else None


def decode(row: dict) -> dict:
    """Acepta únicamente el formato conocido, JSON finito y un objeto acotado."""
    if not isinstance(row, dict):
        raise DraftError("No hay una fila de borrador válida.")
    if row.get("format_version") != FORMAT_VERSION:
        raise DraftError("El borrador usa un formato no compatible; se conserva sin modificar.")
    raw = row.get("payload")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
        raise DraftError("El borrador no tiene un tamaño o contenido válido.")
    try:
        data = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise DraftError("El borrador no se pudo leer; se conserva sin modificar.") from exc
    if not isinstance(data, dict):
        raise DraftError("El borrador no contiene un estado válido.")
    values = [data]
    while values:
        value = values.pop()
        if isinstance(value, dict):
            values.extend(value.values())
        elif isinstance(value, list):
            values.extend(value)
        elif isinstance(value, float) and not math.isfinite(value):
            raise DraftError("El borrador contiene números no finitos.")
    return data


def save(workflow: str, payload: dict, revision: str | None) -> str:
    """Confirma un reemplazo completo y rechaza sobrescrituras entre instancias."""
    _check_workflow(workflow)
    if not isinstance(payload, dict):
        raise DraftError("El estado debe ser un objeto JSON.")
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if len(raw.encode("utf-8")) > MAX_BYTES:
        raise DraftError("El borrador supera el tamaño permitido; el anterior se conserva.")
    new_revision = uuid4().hex
    conn = get_connection()
    with conn:
        if revision is None:
            try:
                conn.execute(
                    "INSERT INTO work_drafts(workflow,format_version,revision,payload) VALUES(?,?,?,?)",
                    (workflow, FORMAT_VERSION, new_revision, raw),
                )
            except sqlite3.IntegrityError as exc:
                raise DraftError("Ya existe un borrador; no se sobrescribirá. Vuelve a abrir PASS.") from exc
        else:
            updated = conn.execute(
                "UPDATE work_drafts SET format_version=?,revision=?,payload=?,updated_at=datetime('now') "
                "WHERE workflow=? AND revision=?",
                (FORMAT_VERSION, new_revision, raw, workflow, revision),
            )
            if updated.rowcount != 1:
                raise DraftError("Otra instancia cambió el borrador; no se sobrescribirá. Vuelve a abrir PASS.")
    return new_revision


def delete(workflow: str, revision: str | None) -> None:
    """Retira solo el borrador esperado; nunca toca sesiones, originales ni resultados."""
    _check_workflow(workflow)
    conn = get_connection()
    with conn:
        if revision is None:
            current = conn.execute("SELECT revision FROM work_drafts WHERE workflow=?", (workflow,)).fetchone()
            if current is not None:
                raise DraftError("Hay otro borrador; no se eliminará.")
        else:
            deleted = conn.execute("DELETE FROM work_drafts WHERE workflow=? AND revision=?", (workflow, revision))
            if deleted.rowcount != 1:
                raise DraftError("Otra instancia cambió el borrador; no se eliminará.")


def _check_workflow(workflow: str) -> None:
    """Acota los borradores a los dos flujos aprobados."""
    if workflow not in WORKFLOWS:
        raise DraftError("Flujo de borrador desconocido.")


def _reject_constant(value: str):
    """Rechaza NaN e infinitos, que no son valores de estado recuperables."""
    raise ValueError(f"Número no válido: {value}")
