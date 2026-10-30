"""Plan multinoches aislado: disponibilidad real, categorías, exclusión temporal y cálculo astronómico sin red."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from planners.ephemeris import EphemerisModel
from planners.multinight import (
    Demand,
    Objective,
    Opportunity,
    Request,
    availability,
    calculate,
    distribute,
    eligibility,
    horizon_at,
    inspect_night,
    mosaic_fov,
    sampled_windows,
    tile_centers,
    validate,
)


def request(**changes):
    """Petición sintética explícita; ningún dato procede del equipo o ubicación personales."""
    result = Request("2026-10-30", "2026-10-31", 40, 1, "Europe/Madrid", 19*60, 6*60,
                     tuple(range(7)), 30, (Objective("a", "M31", .712, 41.27, (Demand("L", 2, 60),)),),
                     "chronological_order")
    return replace(result, **changes)


def window(key="a", tile=1, hours=3, offset=0):
    """Una oportunidad controlada, no una supuesta ventana real de un objeto."""
    start = datetime(2026, 10, 30, 20, tzinfo=UTC)+timedelta(hours=offset)
    return Opportunity(key, tile, "2026-10-30", start, start+timedelta(hours=hours))


def test_multiobjeto_no_duplica_la_misma_hora_y_explica_deficit():
    """Dos objetivos compiten por el mismo recurso; el segundo no recibe horas ya ocupadas."""
    first = request().objectives[0]
    second = replace(first, key="b", name="Otro")
    result = distribute(request(objectives=(first, second)), (window(), window("b")))
    assert [balance.assigned_s for balance in result.balances] == [7200, 3600]
    for a, b in zip(result.allocations, result.allocations[1:]):
        assert a.end <= b.start
    reversed_result = distribute(request(objectives=(second, first)), (window(), window("b")))
    assert reversed_result.allocations[0].objective == "b"


def test_filtros_no_compensan_carencias_y_exposiciones_son_enteras():
    """Cada filtro conserva su objetivo y nunca se excede para redondear a una toma más."""
    obj = replace(request().objectives[0], demands=(Demand("L", 1.01, 120), Demand("R", 1, 60)))
    result = distribute(request(objectives=(obj,)), (window(hours=1.5),))
    assert [item.assigned_s for item in result.balances] == [3600, 1800]
    assert result.balances[0].requested_s > 3600
    assert all(item.end-item.start == timedelta(seconds=item.frames*item.exposure_s) for item in result.allocations)


@pytest.mark.parametrize(("mode", "seconds"), [("per_tile", 7200), ("total_equal", 3600)])
def test_integracion_por_tesela_o_total_equitativo_elegido(mode, seconds):
    """El denominador de un mosaico depende de la elección explícita, no del número de filas visibles."""
    obj = replace(request().objectives[0], tiles_x=2, fov_width=2, fov_height=1, integration_mode=mode)
    result = distribute(request(objectives=(obj,)), (window(tile=1, hours=4), window(tile=2, hours=4)))
    assert [item.requested_s for item in result.balances] == [seconds, seconds]
    assert sum(item.assigned_s for item in result.balances) == seconds*2


def test_solo_ventanas_no_inventa_un_reparto_y_vacio_no_es_exito():
    """La capacidad potencial no equivale a captura asignada ni objetivo cumplido."""
    result = distribute(request(policy="windows_only"), (window(),))
    assert not result.allocations
    assert result.balances[0].assigned_s == 0
    assert distribute(request(), ()).balances[0].assigned_s == 0


def test_ventanas_repetidas_no_se_suman_dos_veces_y_los_huecos_no_se_rellenan():
    """Oportunidades duplicadas y separadas siguen usando un único calendario de tomas enteras."""
    result = distribute(request(), (window(hours=.5), window(hours=.5), window(hours=.5, offset=2)))
    assert result.balances[0].assigned_s == 3600
    assert len(result.allocations) == 2


@pytest.mark.parametrize(("day", "hours"), [("2026-03-28", 10), ("2026-10-24", 12)])
def test_disponibilidad_cruza_medianoche_y_mide_dst_real(day, hours):
    """La noche mantiene su fecha de inicio y la duración real no se obtiene restando horas civiles."""
    item = availability(request(start=day, end=day))[0]
    assert item[0] == day
    assert (item[2]-item[1]).total_seconds()/3600 == hours


def test_dias_seleccionados_y_24_horas_civiles():
    """Una franja igual en ambos extremos abarca el día civil y no genera una ventana negativa."""
    windows = availability(request(start="2026-10-24", end="2026-10-25", weekdays=(5,), start_minute=12*60, end_minute=12*60))
    assert len(windows) == 1
    assert (windows[0][2]-windows[0][1]).total_seconds()/3600 == 25


@pytest.mark.parametrize("day", ["2026-03-29", "2026-10-25"])
def test_limite_civil_ambiguo_o_inexistente_se_rechaza(day):
    """No decide un fold ni desplaza a otra hora el límite elegido por el usuario."""
    with pytest.raises(ValueError, match="ambiguo|inexistente"):
        availability(request(start=day, end=day, start_minute=150))


@pytest.mark.parametrize("changes", [
    {"end":"1949-12-31"}, {"start":"2100-12-31", "end":"2100-12-31"}, {"latitude":float("nan")},
    {"weekdays":()}, {"policy":"inventada"}, {"minimum_altitude":-1},
    {"obstacles":(0,)*8}, {"start_minute":True},
])
def test_entradas_invalidas_no_se_recortan_ni_generan_plan(changes):
    """El rango completo y las decisiones pendientes se validan antes de calcular la primera noche."""
    with pytest.raises(ValueError):
        availability(request(**changes))


def test_centros_de_teselas_nominales_simetricos_y_ra_circular():
    """Las condiciones se consultan por centro de tesela, no repetidas en el centro maestro del mosaico."""
    obj = replace(request().objectives[0], ra_hours=0, dec_deg=0, tiles_x=3, fov_width=2, fov_height=1)
    centers = tile_centers(obj)
    assert centers[1] == (0, 0)
    assert centers[0][0] == pytest.approx(24-centers[2][0])
    assert centers[0][0] > 0
    assert centers[2][0] > 23


def test_horizonte_aplica_la_interpretacion_elegida_y_cierra_el_norte():
    """Sectores e interpolación no se confunden ni olvidan NO→N."""
    profile = (60, 0, 0, 0, 0, 0, 0, 0)
    assert horizon_at([359, 1, 44], profile, "sectors").tolist() == [60, 60, 0]
    assert horizon_at([337.5, 22.5], profile, "linear").tolist() == [30, 30]


def test_muestreo_exige_ambos_extremos_y_no_extrapola_el_ultimo():
    """Un cruce entre muestras no acredita automáticamente todo el intervalo."""
    assert sampled_windows([0, 60, 120, 180, 240], [True, True, False, True, True]) == ((0, 60), (180, 240))
    with pytest.raises(ValueError):
        sampled_windows([0, 60, 30], [True]*3)


def test_calculo_real_offline_aplica_dia_altura_y_horizonte():
    """Se sondea un lugar sintético con modelo interno explícito, sin SQLite personal ni red."""
    day = request(start="2026-10-30", end="2026-10-30", clock=0, start_minute=19*60, end_minute=23*60)
    result = calculate(day, model=EphemerisModel())
    assert result.opportunities
    assert result.accuracy
    blocked = calculate(replace(day, obstacles=(90,)*8, horizon_policy="sectors"), model=EphemerisModel())
    assert not blocked.opportunities
    daylight = calculate(replace(day, start_minute=11*60, end_minute=12*60), model=EphemerisModel())
    assert not daylight.opportunities


def test_cancelacion_no_publica_resultado_parcial():
    """La cancelación se comprueba antes de astronomía y durante la distribución."""
    with pytest.raises(InterruptedError):
        calculate(request(), model=EphemerisModel(), cancelled=lambda: True)
    with pytest.raises(InterruptedError):
        distribute(request(), (window(),), cancelled=lambda: True)


def test_validacion_rechaza_filtros_repetidos_y_mosaicos_sin_fov():
    """Las categorías de integración deben ser inequívocas antes de calcular."""
    obj = request().objectives[0]
    for changed in (replace(obj, demands=obj.demands*2), replace(obj, tiles_x=2)):
        with pytest.raises(ValueError):
            validate(request(objectives=(changed,)))


def test_regla_lunar_no_es_configurable_y_la_altura_minima_si():
    """Luna bajo 5° conserva Posible; al alcanzar 5° se exige distancia, independientemente del filtro."""
    assert eligibility([20, 20, 20], [0, 0, 180], [4.99, 5, 5], [-30]*3, [0]*3, 15, 100).tolist() == [True, False, True]
    assert not eligibility([20], [180], [-10], [-30], [0], 30, 100)[0]


def editor(qt_app, memory_db):
    """Monta el espacio de planificación con base sintética y ubicación nombrada, sin datos personales."""
    from ui.planner_tab.planificacion.multinight import MultiNightDialog
    from ui.planner_tab.planificacion.tab import PlanificacionTab

    memory_db.execute("INSERT INTO locations(name,latitude,longitude,timezone_id) VALUES('Prueba',40,1,'Europe/Madrid')")
    memory_db.execute("INSERT INTO personal_catalog(object_id,catalog,kind,ra_hours,dec_deg) VALUES('Objetivo','region','region',.712,41.27)")
    memory_db.commit()
    owner = PlanificacionTab()
    return owner, MultiNightDialog(owner)


def editor_objective():
    """Documento mínimo de un objeto, con identidad regional explícita y horas elegidas."""
    import json
    from dataclasses import asdict

    obj = replace(request().objectives[0], key=json.dumps(["region", "Objetivo"], ensure_ascii=False), name="Objetivo")
    return {"object_id":"Objetivo", "catalog":"region", "source":"none", "region_fov_mode":None, "objective":asdict(obj)}


def test_abrir_editor_no_crea_borrador_y_editar_autoguarda_el_mismo_flujo(qt_app, memory_db):
    """No existe una segunda autoridad ni un segundo borrador que pueda sustituir al anterior."""
    from db import work_drafts
    from planners.session_draft import validate as validate_draft

    owner, dialog = editor(qt_app, memory_db)
    try:
        assert work_drafts.read("planner") is None
        dialog.name.setText("Mi plan multinoches")
        data = work_drafts.decode(work_drafts.read("planner"))
        assert data["multinight"]["name"] == "Mi plan multinoches"
        validate_draft(data)
        assert memory_db.execute("SELECT COUNT(*) FROM planned_sessions").fetchone()[0] == 0
        assert owner._session_name.text() == ""
    finally:
        dialog.close()
        owner.close()


def test_editor_no_decide_reparto_fov_ni_horizonte_sin_eleccion(qt_app, memory_db):
    """Una propuesta de política en un combo no equivale a elegirla por el usuario."""
    owner, dialog = editor(qt_app, memory_db)
    try:
        assert dialog.policy.currentData() is None
        assert dialog.horizon_policy.currentData() is None
        assert dialog.location.currentData() is None
        dialog.location.setCurrentIndex(1)
        dialog._objectives = [editor_objective()]
        with pytest.raises(ValueError, match="política"):
            dialog.build_request()
        dialog.policy.setCurrentIndex(dialog.policy.findData("windows_only"))
        assert dialog.build_request().policy == "windows_only"
        dialog.use_obstacles.setChecked(True)
        with pytest.raises(ValueError, match="horizonte"):
            dialog.build_request()
    finally:
        dialog.close()
        owner.close()


def test_editor_invalidacion_rechaza_resultados_tardios_y_conserva_datos(qt_app, memory_db):
    """Editar el plan retira la propuesta calculada; no vuelve a publicarse al terminar un worker viejo."""
    owner, dialog = editor(qt_app, memory_db)
    try:
        generation = dialog.job.generation
        dialog._result = object()
        dialog.name.setText("Revisado")
        assert dialog._result is None
        dialog._delivered(generation, "plan", object(), "")
        assert dialog._result is None
        assert owner._multinight_data["name"] == "Revisado"
    finally:
        dialog.close()
        owner.close()


def test_editor_restaura_datos_sin_recalcular_y_rechaza_formato_futuro(qt_app, memory_db):
    """El autoguardado conserva entradas, pero no declara recuperada una distribución derivada antigua."""
    import copy

    from planners.multinight import validate_editor

    owner, dialog = editor(qt_app, memory_db)
    try:
        data = dialog.snapshot()
        data["objectives"] = [editor_objective()]
        data["name"] = "Restaurado"
        dialog._restoring = True
        dialog.restore(data)
        dialog._restoring = False
        assert dialog.snapshot() == data
        assert dialog._result is None
        future = copy.deepcopy(data)
        future["version"] = 99
        with pytest.raises(ValueError):
            validate_editor(future)
        assert dialog.snapshot() == data
    finally:
        dialog.close()
        owner.close()


def test_sesion_legacy_no_retira_el_borrador_multinoches(qt_app, memory_db, monkeypatch):
    """Guardar una sesión antigua no está autorizado a consumir la configuración del nuevo plan."""
    from PyQt6.QtWidgets import QMessageBox

    from db import work_drafts

    owner, dialog = editor(qt_app, memory_db)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    try:
        dialog.name.setText("Pendiente")
        before = work_drafts.read("planner")
        owner._on_save_session()
        assert work_drafts.read("planner") == before
        assert memory_db.execute("SELECT COUNT(*) FROM planned_sessions").fetchone()[0] == 0
    finally:
        dialog.close()
        owner.close()


def test_error_de_autoguardado_es_visible_y_escape_no_lo_descarta(qt_app, memory_db, monkeypatch):
    """Un fallo de escritura conserva el documento anterior y bloquea el cierre, también por Escape."""
    import sqlite3

    from db import work_drafts

    owner, dialog = editor(qt_app, memory_db)
    try:
        dialog.name.setText("Anterior")
        before = work_drafts.read("planner")

        def fail(*args, **kwargs):
            """Simula disco lleno sin modificar SQLite."""
            raise sqlite3.OperationalError("disco lleno")

        with monkeypatch.context() as patch:
            patch.setattr(work_drafts, "save", fail)
            dialog.name.setText("Último")
            assert "disco lleno" in dialog.status.text()
            dialog.show()
            dialog.reject()
            assert dialog.isVisible()
            assert work_drafts.read("planner") == before
    finally:
        dialog.close()
        owner.close()


def test_fov_total_y_por_tesela_comparten_plano_tangente():
    """El rectángulo completo mostrado corresponde a los centros calculados, sin sumar grados linealmente."""
    total = mosaic_fov(2, 1, 3, 2)
    assert total[0] < 6
    assert mosaic_fov(*total, 3, 2, inverse=True) == pytest.approx((2, 1))


def test_edicion_de_objetivo_pide_fov_regional_y_no_prefiere_equipo(qt_app):
    """Región/equipo e interpretación del FOV no se resuelven por inferencia."""
    from ui.planner_tab.planificacion.multinight import ObjectiveDialog

    target = {"object_id":"Región", "catalog":"region", "kind":"region", "ra_hours":1, "dec_deg":30,
              "fov_major_arcmin":120, "fov_minor_arcmin":60}
    setup = {"telescope_focal_mm":500, "camera_width_px":4000, "camera_height_px":3000, "camera_pixel_size_um":4}
    dialog = ObjectiveDialog([target], setup, 60)
    try:
        assert dialog.source.currentData() is None
        dialog.mode.setCurrentIndex(dialog.mode.findData("per_tile"))
        dialog.filters.item(0, 1).setText("2")
        with pytest.raises(ValueError):
            dialog.values()
        dialog.source.setCurrentIndex(dialog.source.findData("region"))
        with pytest.raises(ValueError):
            dialog.values()
        dialog.region_mode.setCurrentIndex(dialog.region_mode.findData("whole_frame"))
        dialog.tiles_x.setValue(2)
        data = dialog.values()
        assert data["objective"]["fov_width"] < 2
        assert data["objective"]["fov_width"] != pytest.approx(2)
        dialog.region_mode.setCurrentIndex(dialog.region_mode.findData("per_tile"))
        assert dialog.values()["objective"]["fov_width"] == 2
    finally:
        dialog.close()


def test_inspeccion_y_plan_comparten_exactamente_sus_condiciones():
    """La banda admisible de la curva procede de la misma malla que las oportunidades, no del ranking viejo."""
    data = request(start="2026-10-30", end="2026-10-30", clock=0, start_minute=19*60, end_minute=23*60)
    result = calculate(data, model=EphemerisModel())
    preview = inspect_night(data, "a", 1, "2026-10-30", model=EphemerisModel())
    start = datetime.fromisoformat(preview.times[0]).replace(tzinfo=UTC)
    seconds = [(datetime.fromisoformat(value).replace(tzinfo=UTC)-start).total_seconds() for value in preview.times]
    spans = sampled_windows(seconds, preview.allowed)
    assert [(item.start, item.end) for item in result.opportunities] == [
        (start+timedelta(seconds=a), start+timedelta(seconds=b)) for a, b in spans]


def test_worker_real_sin_sqlite_de_ui_y_sin_escribir(qt_app, tmp_path, monkeypatch):
    """Un worker real entrega plan completo con una conexión readonly propia y deja intacta la SQLite sintética."""
    import hashlib
    import sqlite3

    from PyQt6.QtTest import QSignalSpy
    from PyQt6.QtWidgets import QWidget

    from db import connection
    from ui.planner_tab.planificacion.multinight import PlanningJob

    path = tmp_path/"synthetic.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(connection.SCHEMA_PATH.read_text(encoding="utf-8"))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(connection, "DB_PATH", path)
    owner = QWidget()
    job = PlanningJob(owner)
    spy = QSignalSpy(job.delivered)
    try:
        job.start("plan", request(start="2026-10-30", end="2026-10-30"))
        assert spy.wait(10_000)
        job.future.result(timeout=10)
        assert spy[0][3] == ""
        assert spy[0][2].opportunities
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    finally:
        job.stop()
        owner.close()


def test_distribuidor_rechaza_ventanas_fuera_de_disponibilidad():
    """La API pura no permite asignar una ventana ajena al calendario confirmado por el usuario."""
    with pytest.raises(ValueError, match="disponibilidad"):
        distribute(request(), (window(offset=-15),))


def document_fixture():
    """Maestro sintético con geometría y horas explícitas, sin referencias a fotografías ni base personal."""
    from planners.multinight import objective_from_data
    from planners.plan_document import make_document

    value = editor_objective()
    obj = objective_from_data(value["objective"], 60)
    data = request(objectives=(obj,))
    result = distribute(data, (window(obj.key),))
    config = {"version":1, "start":data.start, "end":data.end, "start_minute":data.start_minute,
              "end_minute":data.end_minute, "weekdays":list(data.weekdays), "minimum_altitude":30, "policy":data.policy,
              "location_id":None, "setup_id":None, "use_obstacles":False, "horizon_policy":None,
              "exposure":60, "notes":"", "name":"Plan sintético", "objectives":[value]}
    return make_document(config, data, result), config, data, result


def test_maestro_portable_conserva_identidades_revision_y_horas(tmp_path):
    """El archivo confirmado es la autoridad y sus objetivos no se identifican por carpeta o nombre."""
    from planners.plan_document import make_document, read_document, write_document

    document, config, data, result = document_fixture()
    path = tmp_path/"plan.pass-plan.json"
    digest = write_document(path, document)
    loaded, sha = read_document(path)
    assert loaded == document
    assert sha == digest
    assert loaded["request"]["objectives"][0]["key"] != data.objectives[0].key
    assert loaded["result"]["allocations"][0]["objective"] == loaded["request"]["objectives"][0]["key"]
    changed = make_document(dict(config, name="Otro nombre"), data, result, loaded)
    write_document(path, changed, digest)
    assert changed["id"] == loaded["id"]
    assert changed["objective_ids"] == loaded["objective_ids"]
    assert changed["revision"] != loaded["revision"]


def test_maestro_no_reemplaza_destino_ajeno_o_revision_cambiada(tmp_path):
    """Ni seleccionar una ruta existente ni una huella antigua autorizan a descartar el archivo actual."""
    import json

    from planners.plan_document import make_document, write_document

    document, config, data, result = document_fixture()
    path = tmp_path/"ajeno.txt"
    path.write_bytes(b"original externo")
    with pytest.raises(FileExistsError):
        write_document(path, document)
    assert path.read_bytes() == b"original externo"
    target = tmp_path/"plan.pass-plan.json"
    digest = write_document(target, document)
    document["editor"]["notes"] = "Edición externa"
    target.write_text(json.dumps(document), encoding="utf-8")
    before = target.read_bytes()
    changed = make_document(config, data, result, document)
    with pytest.raises(ValueError, match="cambió"):
        write_document(target, changed, digest)
    assert target.read_bytes() == before


@pytest.mark.parametrize("operation", ["new", "replace"])
def test_guardado_atomico_fallido_conserva_original_y_limpia_solo_temporales_propios(tmp_path, monkeypatch, operation):
    """Un error al publicar no deja un maestro truncado ni borra archivos ajenos."""
    import planners.plan_document as module

    document, config, data, result = document_fixture()
    path = tmp_path/"plan.pass-plan.json"
    digest = module.write_document(path, document) if operation == "replace" else None
    before = path.read_bytes() if path.exists() else None

    def fail(*args):
        """Simula destino no publicable sin operaciones destructivas."""
        raise OSError("publicación rechazada")

    if operation == "new":
        monkeypatch.setattr(module, "_publish_new", fail)
    else:
        monkeypatch.setattr(module.os, operation, fail)
    changed = module.make_document(config, data, result, document) if before else document
    with pytest.raises(OSError):
        module.write_document(path, changed, digest)
    assert (path.read_bytes() if path.exists() else None) == before
    assert not list(tmp_path.glob(".pass-plan-*.tmp"))
    assert not path.with_name(path.name+".lock").exists()


def test_bloqueo_de_otra_instancia_no_se_borra(tmp_path):
    """Un bloqueo ajeno se respeta, no se atribuye automáticamente a un cierre viejo."""
    from planners.plan_document import write_document

    document, _config, _data, _result = document_fixture()
    path = tmp_path/"plan.pass-plan.json"
    lock = path.with_name(path.name+".lock")
    lock.write_text("otro proceso", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_document(path, document)
    assert lock.read_text(encoding="utf-8") == "otro proceso"
    assert not path.exists()


@pytest.mark.parametrize("mutation", ["version", "schedule", "identity", "timezone", "configuration"])
def test_maestro_incompatible_o_incoherente_no_se_adopta(tmp_path, mutation):
    """La lectura rechaza formatos futuros, horas sin zona y calendarios que no corresponden a sus objetivos."""
    import json

    from planners.plan_document import read_document

    document, _config, _data, _result = document_fixture()
    if mutation == "version":
        document["version"] = 99
    elif mutation == "schedule":
        document["result"]["allocations"][0]["frames"] += 1
    elif mutation == "identity":
        document["request"]["objectives"][0]["key"] = "0"*32
    elif mutation == "timezone":
        document["result"]["opportunities"][0]["start"] = "2026-10-30T20:00:00"
    else:
        document["editor"]["minimum_altitude"] = 45
    path = tmp_path/"plan.pass-plan.json"
    raw = json.dumps(document).encode("utf-8")
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        read_document(path)
    assert path.read_bytes() == raw


def test_indice_solo_guarda_rutas_y_no_adopta_dos_maestros_del_mismo_plan(memory_db, tmp_path):
    """El índice no contiene objetivos ni calendario, y no elige silenciosamente entre copias accesibles."""
    import json

    from planners.plan_document import index_document, write_document

    document, _config, _data, _result = document_fixture()
    first, other = tmp_path/"primero.json", tmp_path/"otro.json"
    write_document(first, document)
    index_document(first, document)
    value = memory_db.execute("SELECT value FROM settings WHERE key='capture_plan_index_v1'").fetchone()[0]
    assert json.loads(value) == {"version":1, "plans":{document["id"]:str(first.absolute())}}
    write_document(other, document)
    with pytest.raises(ValueError, match="otro maestro"):
        index_document(other, document)
    assert memory_db.execute("SELECT value FROM settings WHERE key='capture_plan_index_v1'").fetchone()[0] == value
    first.unlink()
    index_document(other, document)
    updated = json.loads(memory_db.execute("SELECT value FROM settings WHERE key='capture_plan_index_v1'").fetchone()[0])
    assert updated["plans"][document["id"]] == str(other.absolute())


def test_confirmar_maestro_desde_ui_no_crea_sesiones_legacy(qt_app, memory_db, tmp_path, monkeypatch):
    """Solo el botón confirmado crea el archivo; el calendario no se degrada a registros legacy sin horas."""
    from PyQt6.QtCore import QDate
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

    from db import work_drafts
    from planners.plan_document import read_document

    owner, dialog = editor(qt_app, memory_db)
    path = tmp_path/"plan.pass-plan.json"
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))
    try:
        dialog.location.setCurrentIndex(1)
        dialog.name.setText("Plan confirmado")
        dialog.start.setDate(QDate(2026, 10, 30))
        dialog.end.setDate(QDate(2026, 10, 31))
        dialog.policy.setCurrentIndex(dialog.policy.findData("chronological_order"))
        dialog._objectives = [editor_objective()]
        dialog._request = dialog.build_request()
        key = dialog._request.objectives[0].key
        dialog._result = distribute(dialog._request, (window(key),))
        assert not path.exists()
        dialog._save_master()
        document, digest = read_document(path)
        assert document["state"] == "created"
        assert document["editor"]["name"] == "Plan confirmado"
        assert owner._multinight_file == {"path":str(path), "sha256":digest}
        draft = work_drafts.decode(work_drafts.read("planner"))
        assert draft["multinight_file"]["sha256"] == digest
        assert memory_db.execute("SELECT COUNT(*) FROM planned_sessions").fetchone()[0] == 0
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))
        dialog.name.setText("Cambio sin guardar")
        assert dialog._result is None
        dialog._open_master()
        assert dialog.name.text() == "Plan confirmado"
        assert dialog._result is None
        assert read_document(path)[1] == digest
    finally:
        dialog.close()
        owner.close()


@pytest.mark.parametrize("raw", [None, "no-json", "{}", '{"N":90}'])
def test_horizonte_ausente_o_corrupto_no_se_interpreta_como_libre(memory_db, raw):
    """El cálculo no hereda el fallback visual de alturas cero cuando se piden obstrucciones."""
    from equipment.localizations import planning_location

    memory_db.execute("INSERT INTO locations(name,latitude,longitude,obstacles) VALUES('Prueba',40,1,?)", (raw,))
    memory_db.commit()
    before = list(memory_db.iterdump())
    with pytest.raises(ValueError):
        planning_location(1, require_obstacles=True)
    assert list(memory_db.iterdump()) == before
    assert planning_location(1, require_obstacles=False)["latitude"] == 40


def test_crear_plan_solo_ventanas_se_rechaza_sin_archivos():
    """Una consulta de oportunidades no se puede marcar como calendario confirmado sin reparto."""
    from planners.plan_document import make_document

    _document, config, data, _result = document_fixture()
    data = replace(data, policy="windows_only")
    config["policy"] = "windows_only"
    result = distribute(data, (window(data.objectives[0].key),))
    with pytest.raises(ValueError, match="ventanas"):
        make_document(config, data, result)


def test_json_con_claves_duplicadas_se_conserva_sin_adoptarlo(tmp_path):
    """No se elige entre valores incompatibles por el orden de las claves del archivo."""
    from planners.plan_document import read_document

    path = tmp_path/"plan.pass-plan.json"
    path.write_bytes(b'{"format":"pass-capture-plan","format":"otro"}')
    before = path.read_bytes()
    with pytest.raises(ValueError, match="duplicadas"):
        read_document(path)
    assert path.read_bytes() == before


def test_un_resto_menor_que_una_toma_no_se_redondea_hacia_arriba():
    """La tolerancia flotante no crea una exposición que exceda el objetivo declarado."""
    obj = replace(request().objectives[0], demands=(Demand("L", (120-1e-8)/3600, 60),))
    result = distribute(request(objectives=(obj,)), (window(),))
    assert result.balances[0].assigned_s == 60
    assert result.balances[0].assigned_s < result.balances[0].requested_s
