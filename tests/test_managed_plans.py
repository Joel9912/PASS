"""Maestros locales y exportación: nombres seguros, archivos ajenos y borradores preservados."""

import json
from pathlib import Path

import pytest
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from test_multinight import document_fixture, editor, editor_objective, window

from db import connection, work_drafts
from planners.multinight import distribute
from planners.plan_document import (
    index_document,
    make_document,
    plan_filename,
    read_document,
    reference_scope,
    save_local_document,
    write_document,
)


@pytest.mark.parametrize(("name", "expected"), [
    ("Andrómeda y Triángulo", "Andrómeda y Triángulo"),
    ('M31: L/R\\G?*<>|"', "M31_ L_R_G______"),
    ("  Plan... ", "Plan"), ("...", "Plan"), ("CON", "_CON"),
    ("nul.txt", "_nul.txt"), ("LPT1", "_LPT1"), ("COM¹", "_COM¹"),
    ("Una.pass-plan.json", "Una"), ("..\\..\\M31", ".._.._M31"),
])
def test_nombre_portable_sin_dispositivos_ni_rutas(name, expected):
    """El nombre humano no puede escapar de data/plans ni convertirse en un dispositivo Windows."""
    assert plan_filename(name) == expected+".pass-plan.json"
    assert len(plan_filename("a"*500)) <= 95


def test_colision_crea_otro_archivo_y_revision_conserva_ruta(tmp_path, monkeypatch):
    """Mismo nombre no prueba identidad; renombrar un plan existente no crea otro maestro."""
    monkeypatch.setattr(connection, "DATA_DIR", tmp_path)
    document, config, request, result = document_fixture()
    first, digest = save_local_document(document)
    assert first == tmp_path/"plans"/"Plan sintético.pass-plan.json"
    other = make_document(config, request, result)
    second, _ = save_local_document(other)
    assert second.name == "Plan sintético (2).pass-plan.json"
    config = dict(config, name="Nombre nuevo")
    revision = make_document(config, request, result, document)
    path, new_digest = save_local_document(revision, {"path":str(first), "sha256":digest})
    assert path == first
    assert new_digest != digest
    assert read_document(first)[0]["editor"]["name"] == "Nombre nuevo"
    assert read_document(second)[0] == other
    assert len(list(first.parent.glob("*.pass-plan.json"))) == 2


def test_fuente_externa_se_conserva_y_se_referencia_copia_local(memory_db, tmp_path, monkeypatch):
    """Abrir un maestro antiguo fuera de data no autoriza moverlo ni sobrescribirlo al guardar."""
    monkeypatch.setattr(connection, "DATA_DIR", tmp_path/"data")
    document, config, request, result = document_fixture()
    external = tmp_path/"anterior.pass-plan.json"
    digest = write_document(external, document)
    original = external.read_bytes()
    index_document(external, document)
    revision = make_document(config, request, result, document)
    local, _ = save_local_document(revision, {"path":str(external), "sha256":digest})
    index_document(local, revision, previous_path=external)
    assert local.parent == tmp_path/"data"/"plans"
    assert external.read_bytes() == original
    index = json.loads(memory_db.execute("SELECT value FROM settings WHERE key='capture_plan_index_v1'").fetchone()[0])
    assert index["plans"][document["id"]] == str(local)


def test_revision_cambiada_no_crea_otra_copia(tmp_path, monkeypatch):
    """Un conflicto nunca se disimula como otro nombre libre ni cambia el archivo existente."""
    monkeypatch.setattr(connection, "DATA_DIR", tmp_path)
    document, config, request, result = document_fixture()
    path, digest = save_local_document(document)
    revised = make_document(config, request, result, document)
    write_document(path, revised, digest)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="cambió"):
        save_local_document(revised, {"path":str(path), "sha256":digest})
    assert path.read_bytes() == before
    assert len(list(path.parent.glob("*.json"))) == 1


def prepared_page(qt_app, memory_db):
    """Prepara el mismo flujo confirmado del editor con ventanas sintéticas, sin lanzar workers."""
    owner, page = editor(qt_app, memory_db)
    page.location.setCurrentIndex(1)
    page.name.setText("Plan local")
    page.start.setDate(QDate(2026, 10, 30))
    page.end.setDate(QDate(2026, 10, 31))
    page.policy.setCurrentIndex(page.policy.findData("chronological_order"))
    page._objectives = [editor_objective()]
    page._request = page.build_request()
    page._result = distribute(page._request, (window(page._request.objectives[0].key),))
    return owner, page


def test_cancelar_confirmacion_y_error_de_disco_conservan_borrador(qt_app, memory_db, tmp_path, monkeypatch):
    """No se crea un maestro por calcular, cancelar o fallar la publicación."""
    import planners.plan_document as documents

    monkeypatch.setattr(connection, "DATA_DIR", tmp_path)
    owner, page = prepared_page(qt_app, memory_db)
    try:
        before = work_drafts.read("planner")
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.No)
        page._save_master()
        assert not (tmp_path/"plans").exists()
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)

        def fail(*args):
            """Simula falta de espacio después de preparar el temporal, sin escribir fuera del sandbox."""
            raise OSError("disco lleno")

        monkeypatch.setattr(documents, "_publish_new", fail)
        page._save_master()
        assert "disco lleno" in page.status.text()
        assert owner._multinight_file is None
        assert work_drafts.read("planner") == before
        assert not list((tmp_path/"plans").iterdir())
    finally:
        page.close()
        owner.close()


def test_exportar_no_reemplaza_maestro_ni_exporta_ediciones_pendientes(qt_app, memory_db, tmp_path, monkeypatch):
    """Exportar transporta la última confirmación; no guarda por su cuenta ni mueve la autoridad."""
    monkeypatch.setattr(connection, "DATA_DIR", tmp_path/"data")
    owner, page = prepared_page(qt_app, memory_db)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    try:
        page._save_master()
        reference = dict(owner._multinight_file)
        original = Path(reference["path"]).read_bytes()
        page.name.setText("Edición no confirmada")
        draft = work_drafts.read("planner")
        target = tmp_path/"copia"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(target), ""))
        page._export_master()
        assert target.with_suffix(".pass-plan.json").read_bytes() == original
        assert owner._multinight_file == reference
        assert work_drafts.read("planner") == draft
        assert Path(reference["path"]).read_bytes() == original
        target.with_suffix(".pass-plan.json").write_bytes(b"ajeno")
        page._export_master()
        assert "No se pudo exportar" in page.status.text()
        assert target.with_suffix(".pass-plan.json").read_bytes() == b"ajeno"
        assert reference_scope() == read_document(reference["path"])[0]["reference_scope"]
    finally:
        page.close()
        owner.close()
