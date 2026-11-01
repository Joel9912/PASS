"""Calendario visual y maestro operativo: datos sintéticos, sin fotografías ni ejecución de hardware."""

from dataclasses import asdict, replace

from PyQt6.QtWidgets import QMessageBox

from equipment.planning_profile import PlanningProfile
from planners.multinight import effective_horizon


def test_margen_solo_sobre_obstruccion():
    """El norte libre no adquiere una barrera artificial y el este sí incorpora seguridad."""
    from test_planning_scheduler import scenario

    request, _windows, _tracks = scenario(days=1)
    request = replace(request, obstacles=(0, 0, 30, 0, 0, 0, 0, 0), horizon_policy="sectors", horizon_margin=5)
    assert effective_horizon(request, [0, 90]).tolist() == [0, 35]


def test_pagina_presenta_calendario_y_cobertura_con_alternativas(qt_app, memory_db, monkeypatch):
    """Seleccionar una excepción pide consentimiento y no sustituye el motor por una tabla decorada."""
    from test_multinight import editor
    from test_planning_scheduler import scenario

    from planners.planning_scheduler import schedule

    owner, page = editor(qt_app, memory_db)
    request, windows, tracks = scenario(days=1, hours=1)
    try:
        page._request = request
        page.job.start = lambda *args: None
        monkeypatch.setattr(page, "refresh_references", lambda: True)
        result = schedule(request, windows, tracks)
        page._delivered(page.job.generation, "plan", result, "")
        assert page.timeline.count() == 1
        assert page.result_views.currentWidget() is page.timeline
        assert page.alternative.count() == 3
        assert "operación" in page.summary.text()
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
        page.alternative.setCurrentIndex(2)
        assert page._result.selected == "recommended"
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
        page.alternative.setCurrentIndex(2)
        assert page._result.selected == "exception"
        page.resize(1200, 720)
        owner.show()
        page.show()
        qt_app.processEvents()
        assert not page.grab().isNull()
    finally:
        page.close()
        owner.close()


def test_maestro_v2_guarda_operacion_y_no_invoca_scheduler_al_leer(tmp_path, monkeypatch):
    """La alternativa confirmada es autoridad; abrirla no ejecuta de nuevo la optimización."""
    import json

    from test_multinight import document_fixture
    from test_planning_scheduler import scenario

    from planners.plan_document import (
        editor_calendar,
        make_document,
        read_document,
        write_document,
    )
    from planners.planning_scheduler import schedule

    request, windows, tracks = scenario(days=1, hours=1)
    old, config, _data, _result = document_fixture()
    identities = [json.dumps(["region", obj.name], ensure_ascii=False) for obj in request.objectives]
    mapping = dict(zip([obj.key for obj in request.objectives], identities))
    request = replace(request, objectives=tuple(replace(obj, key=mapping[obj.key]) for obj in request.objectives))
    windows = tuple(replace(w, objective=mapping[w.objective]) for w in windows)
    tracks = tuple(replace(t, objective=mapping[t.objective]) for t in tracks)
    config.update(version=2, start=request.start, end=request.end, policy="balanced", minimum_altitude=request.minimum_altitude,
                  horizon_margin=0, max_filters=1, filter_order=[], exposure=120)
    config["objectives"] = [dict(object_id=obj.name, catalog="region", source="none", region_fov_mode=None, objective=asdict(obj)) for obj in request.objectives]
    result = schedule(request, windows, tracks)
    document = make_document(config, request, result)
    assert document["version"] == 2
    path = tmp_path/"plan.pass-plan.json"
    digest = write_document(path, document)
    monkeypatch.setattr("planners.planning_scheduler.schedule", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("No optimizar")))
    assert read_document(path)[1] == digest
    restored_request, restored_result = editor_calendar(document)
    assert restored_request == request
    assert restored_result == result
    assert document["request"]["profile"]["pause_s"] == 2
    assert document["result"]["operations"]
    assert old["version"] == 1


def test_perfil_formulario_preserva_ausencias(qt_app):
    """Nuevo formulario no transforma desconocido en cero ni pierde disparadores al restaurar."""
    from ui.equipment_tab.planning_profile import PlanningProfileForm

    form = PlanningProfileForm()
    try:
        assert form.data()["pause_s"] is None
        profile = PlanningProfile(pause_s=2, focus_s=30, focus_start=True).data()
        form.restore(profile)
        assert form.data() == profile
    finally:
        form.close()


def test_ampliacion_se_evalua_sin_adoptar_fechas(qt_app, memory_db, monkeypatch):
    """El cálculo propuesto conserva fechas/borrador hasta que el usuario acepta su resultado."""
    from PyQt6.QtWidgets import QInputDialog
    from test_multinight import editor
    from test_planning_scheduler import scenario

    from planners.planning_scheduler import schedule

    owner, page = editor(qt_app, memory_db)
    request, windows, tracks = scenario(days=1, hours=1)
    try:
        result = schedule(request, windows, tracks)
        page._request, page._result = request, result
        calls = []
        monkeypatch.setattr(page.job, "start", lambda *args: calls.append(args))
        monkeypatch.setattr(QInputDialog, "getInt", lambda *args: (7, True))
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
        before = page.end.date()
        page._consider_extension()
        assert calls[0][0] == "extension"
        assert page.end.date() == before
        page._delivered(page.job.generation, "extension", result, "")
        assert page._request == request
        assert page.end.date() == before
        assert "no se adoptaron" in page.status.text()
    finally:
        page.close()
        owner.close()


def test_lector_maestro_original_sin_campos_nuevos():
    """Un v1 real carece de perfiles, preferencias y alternativas, pero conserva exactamente sus balances."""
    from test_multinight import document_fixture

    from planners.plan_document import validate_document

    document, _config, _request, result = document_fixture()
    for name in ("horizon_margin", "max_filters", "filter_order", "profile"):
        document["request"].pop(name)
    for obj in document["request"]["objectives"]+[v["objective"] for v in document["editor"]["objectives"]]:
        for name in ("night_mode", "night_hours", "max_tiles"):
            obj.pop(name)
    for name in ("operations", "visits", "alternatives", "selected", "tracks"):
        document["result"].pop(name)
    _request, restored = validate_document(document)
    assert [b.assigned_s for b in restored.balances] == [b.assigned_s for b in result.balances]


def test_prioridad_incompleta_es_recuperable_pero_no_calculable(qt_app, memory_db):
    """Editar temporalmente filtros repetidos no convierte el autoguardado en un borrador irrecuperable."""
    import pytest
    from test_multinight import editor
    from test_planning_scheduler import scenario

    from planners.multinight import validate, validate_editor

    owner, page = editor(qt_app, memory_db)
    try:
        page.filter_order.setText("L, L")
        data = page.snapshot()
        validate_editor(data)
        page._restoring = True
        page.restore(data)
        page._restoring = False
        assert page._filters() == ["L", "L"]
        request, _windows, _tracks = scenario(days=1)
        with pytest.raises(ValueError, match="filtros"):
            validate(replace(request, filter_order=("L", "L")))
    finally:
        page.close()
        owner.close()
