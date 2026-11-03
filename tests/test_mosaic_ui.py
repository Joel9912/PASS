"""Mosaicos en la página nativa, borrador y maestro: geometría compartida y datos personales aislados."""

import copy
import json
from dataclasses import asdict, replace

import pytest
from test_multinight import document_fixture, editor, editor_objective, window

from db import work_drafts
from planners.mosaic import mosaic_tiles
from planners.multinight import (
    calculate,
    distribute,
    inspect_night,
    mosaic_fov,
    objective_from_data,
    tile_centers,
)
from planners.plan_document import (
    editor_calendar,
    make_document,
    read_document,
    validate_document,
    write_document,
)


def test_controles_de_encuadre_giran_conjunto_y_autoguardan(qt_app, memory_db):
    """Editar PA/solape cambia cámaras y centros del mismo objetivo, retira reparto y no toca el maestro."""
    owner, page = editor(qt_app, memory_db)
    try:
        value = editor_objective()
        value["source"] = "setup"
        value["objective"].update(fov_width=2, fov_height=1, tiles_x=2, tiles_y=3)
        page._objectives = [value]
        page._fill_objectives()
        page.objects_table.selectRow(0)
        initial = page.sky.mosaic_tiles
        assert len(initial) == 6
        page._result = object()
        owner._multinight_file = {"path":"maestro-no-abierto.pass-plan.json", "sha256":"0"*64}
        page.rotation_deg.setValue(37)
        page.overlap_x.setValue(20)
        page.overlap_y.setValue(30)
        assert page._result is None
        obj = objective_from_data(page._objectives[0]["objective"], page.exposure.value())
        assert obj.rotation_deg == 37 and obj.overlap_x == .2 and obj.overlap_y == .3
        assert page.sky.mosaic_tiles != initial
        assert [(t.ra_hours, t.dec_deg) for t in page.sky.mosaic_tiles] == list(tile_centers(obj))
        assert page.sky.mosaic_tiles == mosaic_tiles(obj.ra_hours, obj.dec_deg, 2, 1, 2, 3,
                                                    rotation_deg=37, overlap_x=.2, overlap_y=.3)
        saved = work_drafts.decode(work_drafts.read("planner"))
        assert saved["multinight"]["objectives"][0]["objective"]["rotation_deg"] == 37
        assert owner._multinight_file["path"] == "maestro-no-abierto.pass-plan.json"
        assert saved["multinight"]["version"] == 3
        page._restoring = True
        page.restore(saved["multinight"])
        page._restoring = False
        page.objects_table.selectRow(0)
        assert page.rotation_deg.value() == 37
        assert page.overlap_x.value() == 20
        assert page.overlap_y.value() == 30
        page.show_tiles.setChecked(False)
        assert len(page.sky.mosaic_tiles) == 6
        owner.show()
        page.show()
        qt_app.processEvents()
        assert not page.sky.grab().isNull()
    finally:
        page.close()
        owner.close()


def test_rotacion_y_solape_no_cambian_el_fov_del_equipo(qt_app):
    """La cámara sigue completa al cambiar filas/columnas; no se divide el FOV del sensor."""
    from ui.planner_tab.planificacion.multinight import ObjectiveDialog

    target = {"object_id":"Objeto", "catalog":"region", "ra_hours":1, "dec_deg":30}
    setup = {"telescope_focal_mm":500, "camera_width_px":4000, "camera_height_px":3000, "camera_pixel_size_um":4}
    dialog = ObjectiveDialog([target], setup, 60)
    try:
        dialog.source.setCurrentIndex(dialog.source.findData("setup"))
        dialog.mode.setCurrentIndex(dialog.mode.findData("per_tile"))
        dialog.filters.item(0, 1).setText("1")
        first = dialog.values()["objective"]
        dialog.tiles_x.setValue(2)
        dialog.tiles_y.setValue(3)
        dialog.overlap_x.setValue(20)
        dialog.overlap_y.setValue(20)
        dialog.rotation_deg.setValue(45)
        changed = dialog.values()["objective"]
        assert (changed["fov_width"], changed["fov_height"]) == (first["fov_width"], first["fov_height"])
        assert changed["rotation_deg"] == 45 and changed["overlap_x"] == .2
        assert "cobertura nominal" in dialog.fov_label.text()
    finally:
        dialog.close()


def test_campo_regional_total_conserva_cobertura_al_cambiar_solape(qt_app, memory_db):
    """La interpretación regional explícita se conserva, sin convertir la cobertura total en FOV de cámara."""
    owner, page = editor(qt_app, memory_db)
    try:
        value = editor_objective()
        value.update(source="region", region_fov_mode="whole_frame")
        value["objective"].update(fov_width=2, fov_height=1, tiles_x=2, tiles_y=3)
        before = mosaic_fov(2, 1, 2, 3)
        page._objectives = [value]
        page._fill_objectives()
        page.objects_table.selectRow(0)
        page.overlap_x.setValue(20)
        obj = page._objectives[0]["objective"]
        assert obj["fov_width"] > 2
        assert mosaic_fov(obj["fov_width"], obj["fov_height"], 2, 3, overlap_x=.2) == pytest.approx(before)
    finally:
        page.close()
        owner.close()


def test_maestro_v3_conserva_geometria_y_lector_v1_v2_no_inventa_solape(tmp_path):
    """La nueva geometría viaja por valor; datos antiguos sin esos campos siguen norte-arriba y a cero."""
    document, config, request, result = document_fixture()
    obj = replace(request.objectives[0], fov_width=2, fov_height=1, tiles_x=2, tiles_y=3,
                  rotation_deg=37, overlap_x=.2, overlap_y=.3)
    request = replace(request, objectives=(obj,))
    config["objectives"][0]["objective"] = asdict(obj)
    config["version"] = 3
    result = distribute(request, (window(obj.key),))
    geometry = make_document(config, request, result)
    assert geometry["version"] == 3
    path = tmp_path/"mosaico.pass-plan.json"
    digest = write_document(path, geometry)
    assert read_document(path)[1] == digest
    restored, calendar = editor_calendar(geometry)
    assert restored == request and calendar == result
    future = copy.deepcopy(geometry)
    future["version"] = 2
    with pytest.raises(ValueError, match="geometría"):
        validate_document(future)
    for key in ("rotation_deg", "overlap_x", "overlap_y"):
        document["request"]["objectives"][0].pop(key)
        document["editor"]["objectives"][0]["objective"].pop(key)
    restored, _ = validate_document(document)
    assert restored.objectives[0].rotation_deg == restored.objectives[0].overlap_x == restored.objectives[0].overlap_y == 0
    assert json.loads(path.read_text(encoding="utf-8"))["request"]["objectives"][0]["rotation_deg"] == 37


def test_calculo_y_curva_usan_centros_del_mosaico_rotado():
    """La ventana y su inspección usan la tesela movida, no repiten el centro maestro del campo."""
    from test_multinight import request as fixture_request

    from planners.ephemeris import EphemerisModel

    request = fixture_request(start="2026-10-30", end="2026-10-30", start_minute=19*60, end_minute=23*60)
    obj = replace(request.objectives[0], tiles_x=2, tiles_y=3, fov_width=2, fov_height=1, rotation_deg=43, overlap_x=.2, overlap_y=.3)
    request = replace(request, objectives=(obj,), policy="windows_only")
    model = EphemerisModel()
    result = calculate(request, model=model)
    preview = inspect_night(request, obj.key, 1, request.start, model=model)
    center = tile_centers(obj)[0]
    single = replace(obj, ra_hours=center[0], dec_deg=center[1], tiles_x=1, tiles_y=1)
    reference = inspect_night(replace(request, objectives=(single,)), obj.key, 1, request.start, model=model)
    assert preview == reference
    assert any(w.tile == 1 for w in result.opportunities)


def test_maestro_operativo_v3_y_original_v2_hacen_roundtrip(tmp_path):
    """El calendario equilibrado guarda geometría sin reoptimizar; v2 sin campos nuevos mantiene cero."""
    from planners.planning_scheduler import schedule

    _document, config, request, _result = document_fixture()
    request = replace(request, policy="balanced")
    config.update(policy="balanced", version=2)
    result = schedule(request, (window(request.objectives[0].key),))
    previous = make_document(config, request, result)
    assert previous["version"] == 2
    for key in ("rotation_deg", "overlap_x", "overlap_y"):
        previous["request"]["objectives"][0].pop(key)
        previous["editor"]["objectives"][0]["objective"].pop(key)
    restored, _ = validate_document(previous)
    assert restored.objectives[0].rotation_deg == restored.objectives[0].overlap_x == 0
    obj = replace(request.objectives[0], fov_width=2, fov_height=1, tiles_x=2, tiles_y=3,
                  rotation_deg=37, overlap_x=.2, overlap_y=.2)
    request = replace(request, objectives=(obj,))
    config = copy.deepcopy(config)
    config["version"] = 3
    config["objectives"][0]["objective"] = asdict(obj)
    result = schedule(request, (window(obj.key),))
    document = make_document(config, request, result, previous)
    assert document["version"] == 3
    assert document["id"] == previous["id"]
    path = tmp_path/"mosaico-operativo.pass-plan.json"
    write_document(path, document)
    assert editor_calendar(read_document(path)[0]) == (request, result)


def test_editor_geometria_mantiene_fila_de_filtro_visible(qt_app):
    """Añadir PA/solape no puede comprimir las horas objetivo hasta dejar solo la cabecera de filtros."""
    from PyQt6.QtGui import QFont

    from ui.planner_tab.planificacion.multinight import ObjectiveDialog
    from ui.style import QSS

    dialog = ObjectiveDialog([{"object_id":"Objeto", "catalog":"region", "ra_hours":1, "dec_deg":30}], None, 60)
    try:
        dialog.setFont(QFont("Segoe UI", 16))
        dialog.setStyleSheet(QSS)
        dialog.show()
        qt_app.processEvents()
        assert dialog.filters.viewport().height() >= dialog.filters.rowHeight(0)
        first = dialog.filters.visualItemRect(dialog.filters.item(0, 1))
        assert dialog.filters.viewport().rect().contains(first)
    finally:
        dialog.close()
