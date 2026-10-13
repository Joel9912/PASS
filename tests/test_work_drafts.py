"""Borradores transaccionales, incompatibilidad y recuperación sin datos personales."""

import json
import sqlite3

import pytest

from db import connection, work_drafts
from planners import planned_sessions


def test_borradores_separados_y_revision(memory_db):
    """Cada pestaña tiene un único estado y no sobrescribe la revisión de otra ventana."""
    first = work_drafts.save("planner", {"name": "Primero"}, None)
    work_drafts.save("stacker", {"step": 1}, None)
    second = work_drafts.save("planner", {"name": "Segundo"}, first)
    assert second != first
    with pytest.raises(work_drafts.DraftError):
        work_drafts.save("planner", {"name": "Perdido"}, first)
    with pytest.raises(work_drafts.DraftError):
        work_drafts.delete("planner", first)
    assert work_drafts.decode(work_drafts.read("planner")) == {"name": "Segundo"}
    assert work_drafts.decode(work_drafts.read("stacker")) == {"step": 1}
    work_drafts.delete("planner", second)
    assert work_drafts.read("planner") is None


@pytest.mark.parametrize("payload,version", [('no json', 1), ('[]', 1), ('{"a": NaN}', 1), ('{"a": 1e999}', 1), ('{}', 99)])
def test_borrador_ilegible_se_conserva(memory_db, payload, version):
    """Leer un formato inválido o futuro no lo normaliza, elimina ni reemplaza."""
    memory_db.execute("INSERT INTO work_drafts VALUES('planner',?,?,?,datetime('now'))", (version, "r", payload))
    memory_db.commit()
    row = work_drafts.read("planner")
    with pytest.raises(work_drafts.DraftError):
        work_drafts.decode(row)
    assert work_drafts.read("planner") == row


def test_guardado_fallido_conserva_anterior(memory_db):
    """Un fallo SQLite o JSON deja intacto el borrador previamente confirmado."""
    revision = work_drafts.save("planner", {"name": "Anterior"}, None)
    previous = work_drafts.read("planner")
    with pytest.raises(ValueError):
        work_drafts.save("planner", {"invalid": float("nan")}, revision)
    memory_db.execute("CREATE TRIGGER rechazar_borrador BEFORE UPDATE ON work_drafts BEGIN SELECT RAISE(ABORT,'fallo'); END")
    memory_db.commit()
    with pytest.raises(sqlite3.Error):
        work_drafts.save("planner", {"name": "Nuevo"}, revision)
    assert work_drafts.read("planner") == previous


def test_sesion_y_retiro_borrador_son_atomicos(memory_db):
    """Un fallo al crear sesión revierte también el retiro del borrador."""
    revision = work_drafts.save("planner", {"name": "Pendiente"}, None)
    memory_db.execute("CREATE TRIGGER rechazar_sesion BEFORE INSERT ON planned_sessions BEGIN SELECT RAISE(ABORT,'fallo'); END")
    memory_db.commit()
    with pytest.raises(sqlite3.Error):
        planned_sessions.add("Región", "Noche", "2026-10-15", draft_revision=revision)
    assert work_drafts.read("planner")["revision"] == revision
    memory_db.execute("DROP TRIGGER rechazar_sesion")
    memory_db.commit()
    planned_sessions.add("Región", "Noche", "2026-10-15", draft_revision=revision)
    assert work_drafts.read("planner") is None
    assert len(planned_sessions.list_sessions()) == 1
    with pytest.raises(work_drafts.DraftError):
        planned_sessions.add("Región", "Duplicada", "2026-10-15", draft_revision=revision)
    assert len(planned_sessions.list_sessions()) == 1


def test_tabla_nueva_se_aplica_idempotentemente(memory_db):
    """Una base anterior recibe la tabla sin perder sesiones ni duplicar borradores."""
    planned_sessions.add("M31", "Noche", "2026-10-15")
    memory_db.execute("DROP TABLE work_drafts")
    memory_db.commit()
    connection.init_db(memory_db)
    revision = work_drafts.save("planner", {"name": "Persistente"}, None)
    connection.init_db(memory_db)
    assert work_drafts.read("planner")["revision"] == revision
    assert planned_sessions.list_sessions()[0]["target_name"] == "Noche"


def test_tamano_limitado_no_pisa_borrador(memory_db, monkeypatch):
    """El límite del JSON conserva el anterior y no altera la otra pestaña."""
    revision = work_drafts.save("planner", {"a": 1}, None)
    monkeypatch.setattr(work_drafts, "MAX_BYTES", 30)
    with pytest.raises(work_drafts.DraftError):
        work_drafts.save("planner", {"texto": "a" * 100}, revision)
    assert json.loads(work_drafts.read("planner")["payload"]) == {"a": 1}
