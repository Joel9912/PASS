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


def test_eje_horas_locales_cruza_medianoche_sin_cambiar_distancias(qt_app):
    """Las etiquetas usan reloj del sitio, no horas transcurridas ni la zona del ordenador."""
    from datetime import UTC, datetime, timedelta

    from ui.planner_tab.planificacion.plan_curve import LocalTimeAxis

    start = datetime(2026, 11, 2, 1, tzinfo=UTC)
    axis = LocalTimeAxis()
    axis.set_context(start, start+timedelta(hours=11), -100, -6)
    assert axis.tickStrings([0, 2, 4, 6, 11], 1, 2) == ["19:00", "21:00", "23:00", "01:00", "06:00"]
    assert "Hora local" in axis.labelText
    axis.set_context(start+timedelta(hours=1), start+timedelta(hours=12), -100, -6)
    assert axis.tickStrings([0], 1, 2) == ["20:00"]


def test_eje_dst_distingue_horas_repetidas(qt_app):
    """Dos posiciones separadas una hora real pueden compartir HH:MM sin perder su desfase."""
    from datetime import UTC, datetime, timedelta

    from ui.planner_tab.planificacion.plan_curve import LocalTimeAxis

    start = datetime(2026, 10, 25, tzinfo=UTC)
    axis = LocalTimeAxis()
    axis.set_context(start, start+timedelta(hours=4), 1, "Europe/Madrid")
    assert axis.tickStrings([0, 1, 2], 1, 1) == ["02:00\n+0200", "02:00\n+0100", "03:00\n+0100"]


def test_curva_marca_intervalo_real_y_retira_barras_al_limpiar(qt_app, memory_db, monkeypatch):
    """La selección muestra horas del reparto, no toda la franja verde como si estuviera asignada."""
    import pyqtgraph as pg
    from test_multinight import editor
    from test_planning_scheduler import scenario

    from planners.ephemeris import EphemerisModel
    from planners.multinight import inspect_night
    from planners.planning_scheduler import schedule

    owner, page = editor(qt_app, memory_db)
    request, windows, tracks = scenario(days=1, hours=1)
    try:
        result = schedule(request, windows, tracks)
        page._request, page._result = request, result
        frame = result.allocations[0]
        page._preview_key = frame.objective, frame.tile, frame.night
        page._preview_caption = "Objeto seleccionado"
        preview = inspect_night(request, frame.objective, frame.tile, frame.night, model=EphemerisModel())
        page._draw_preview(preview)
        assert "Planificado:" in page.curve_status.text()
        bars = [item for item in page.curve.listDataItems() if item.name() == "Planificado"]
        assert len(bars) == 1
        from planners.timezones import utc_moment

        origin = utc_moment(preview.times[0])
        own = next(v for v in result.visits if v.objective == frame.objective)
        assert bars[0].xData.tolist() == [(own.start-origin).total_seconds()/3600,
                                         (own.end-origin).total_seconds()/3600]
        assert any(isinstance(item, pg.LinearRegionItem) for item in page.curve.items())
        page._changed()
        assert not page.curve.listDataItems()
    finally:
        page.close()
        owner.close()


def test_barras_no_incluyen_tomas_de_otra_tesela(qt_app):
    """Si se vuelve a una tesela tras otra, la barra no presenta el intervalo intermedio como suyo."""
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    import pyqtgraph as pg

    from planners.multinight import Allocation
    from planners.planning_models import Visit
    from ui.planner_tab.planificacion.plan_curve import draw_schedule

    start = datetime(2026, 11, 1, 20, tzinfo=UTC)
    frames = tuple(Allocation("a", tile, "L", "2026-11-01", start+timedelta(minutes=index),
                              start+timedelta(minutes=index+1), 1, 60) for index, tile in enumerate((1, 2, 1)))
    result = SimpleNamespace(allocations=frames, operations=(),
                             visits=(Visit("a", "2026-11-01", start, frames[-1].end, 180, ""),))
    plot = pg.PlotWidget()
    try:
        assert draw_schedule(plot, result, ("a", 1, "2026-11-01"), start, SimpleNamespace(longitude=0, clock=0))
        bars = [item for item in plot.listDataItems() if len(item.xData) == 2]
        assert len(bars) == 2
        assert bars[0].xData.tolist() == [0, 1/60]
        assert bars[1].xData.tolist() == [2/60, 3/60]
        plot.clear()
        assert not draw_schedule(plot, result, ("a", 3, "2026-11-01"), start, SimpleNamespace(longitude=0, clock=0))
        assert not plot.listDataItems()
    finally:
        plot.close()
