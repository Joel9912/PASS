"""Portada y carta independiente: datos reales sin escrituras, ejemplos explícitos y contexto astronómico offline."""

from datetime import UTC, date, datetime

import pytest

from planners.ephemeris import EphemerisModel
from planners.sky_state import civil_to_utc, observe_sky
from planners.summary import IntegrationProgress, read_overview, sessions_on_day


@pytest.fixture
def no_sky(monkeypatch):
    """Retiene solicitudes de UI sin lanzar workers; los cálculos reales tienen sus pruebas separadas."""
    from ui.sky_context import SkyContext

    requests = []
    monkeypatch.setattr(SkyContext, "request", lambda self, location, moment=None: requests.append((dict(location), moment)))
    return requests


@pytest.mark.parametrize(("selected", "pending", "hours", "fraction", "extra"), [
    (4, 2, 6, .75, 0), (8, 2, 10, 1., 2), (0, 0, 0, 0, 0), (2, 0, 2, .25, 0),
])
def test_integracion_separa_provisional_y_acota_solo_indicador(selected, pending, hours, fraction, extra):
    """Las horas reales y las pendientes no desaparecen al llegar al objetivo."""
    result = IntegrationProgress(8, selected, pending)
    assert (result.total_hours, result.fraction, result.extra_hours) == (hours, fraction, extra)


@pytest.mark.parametrize("values", [(0, 1, 0), (-1, 0, 0), (8, -1, 0), (8, 0, -1),
                                    (float("nan"), 0, 0), (8, float("inf"), 0), (True, 0, 0)])
def test_integracion_rechaza_valores_que_falsean_el_progreso(values):
    """Ausencias, infinitos y objetivos inválidos no se convierten en porcentajes aparentes."""
    with pytest.raises(ValueError):
        IntegrationProgress(*values)


def test_overview_lee_sesiones_y_borradores_sin_escribir(memory_db):
    """La exposición legacy no se transforma en horas objetivo ni se recupera el borrador al leerlo."""
    memory_db.execute("INSERT INTO planned_sessions(object_id,target_name,session_date,planned_exposure_s) VALUES('M31','Noche','2026-10-29',45)")
    memory_db.execute("INSERT INTO planned_sessions(object_id,target_name,session_date,status) VALUES('M42','Terminada','2026-10-30','completada')")
    memory_db.execute("INSERT INTO work_drafts(workflow,format_version,revision,payload) VALUES('stacker',99,'ref','no interpretar')")
    memory_db.commit()
    before = list(memory_db.iterdump())
    result = read_overview(date(2026, 10, 29))
    assert list(memory_db.iterdump()) == before
    assert len(sessions_on_day(result, date(2026, 10, 29))) == 1
    assert result.sessions[0]["planned_exposure_s"] == 45
    assert [item.kind for item in result.activities] == ["continue", "upcoming"]


def test_summary_vacio_sin_ubicacion_supuesta(qt_app, memory_db, no_sky):
    """La portada permanece navegable incluso con una única ubicación que aún no eligió el usuario."""
    from ui.summary_tab import SummaryPage

    memory_db.execute("INSERT INTO locations(name,latitude,longitude) VALUES('Sitio',40,1)")
    memory_db.commit()
    before = list(memory_db.iterdump())
    page = SummaryPage()
    try:
        assert page.location_id is None
        assert "Sin sesión actual" == page._object.text()
        assert page._continue.text() == "Planificar captura"
        assert not page._dial.isVisible()
        assert len(page._cards) == 5
        assert not no_sky
        assert list(memory_db.iterdump()) == before
    finally:
        page.close()


def test_summary_ejemplo_no_crea_planes_ni_asocia_capturas(qt_app, memory_db, no_sky):
    """Solo el modo explícito permite ver cifras ficticias; volver retira todas sus etiquetas/progresos."""
    from ui.summary_tab import SummaryPage

    page = SummaryPage()
    before = list(memory_db.iterdump())
    try:
        page._demo.setChecked(True)
        assert "FICTICIOS" in page._demo.text().upper()
        assert page._hours.text() == "6 h de 8 h"
        assert page._dial.progress.pending_hours == 2
        assert not page._continue.isEnabled()
        page._demo.setChecked(False)
        assert page._object.text() == "Sin sesión actual"
        assert page._hours.text() == ""
        assert page._continue.isEnabled()
        assert list(memory_db.iterdump()) == before
    finally:
        page.close()


def test_summary_sesion_legacy_no_inventa_integracion(qt_app, memory_db, no_sky):
    """Una sesión guardada se puede consultar sin confundir exposición por toma con un objetivo multinoches."""
    from ui.summary_tab import SummaryPage

    memory_db.execute("INSERT INTO planned_sessions(object_id,target_name,session_date,planned_exposure_s) VALUES('M31','Mi sesión','2026-10-29',28800)")
    memory_db.commit()
    page = SummaryPage()
    try:
        page._sessions.setCurrentIndex(1)
        assert page._object.text() == "M31"
        assert "no vinculada" in page._hours.text()
        assert not page._dial.isVisible()
        assert page._object.toolTip() == "Mi sesión"
    finally:
        page.close()


def test_ubicacion_resumen_recordada_sin_reescribir_la_eleccion(qt_app, memory_db, no_sky):
    """Persistir preferencia no cambia ubicaciones ajenas; al borrarla no se adopta otro sitio."""
    from db.settings import get_setting
    from ui.summary_tab import LOCATION_KEY, SummaryPage

    memory_db.execute("INSERT INTO locations(name,latitude,longitude,timezone_id) VALUES('Sitio A',40,1,'Europe/Madrid')")
    memory_db.execute("INSERT INTO locations(name,latitude,longitude) VALUES('Sitio B',10,-84)")
    memory_db.commit()
    page = SummaryPage()
    try:
        page._location.setCurrentIndex(1)
        assert get_setting(LOCATION_KEY) == "1"
        other = SummaryPage()
        try:
            assert other.location_id == 1
            memory_db.execute("DELETE FROM locations WHERE id=1")
            memory_db.commit()
            other.reload_locations()
            assert other.location_id is None
            assert get_setting(LOCATION_KEY) == "1"
        finally:
            other.close()
    finally:
        page.close()


def test_planetario_explora_sin_compartir_estado_y_reinicia_en_otra_instancia(qt_app, memory_db, no_sky):
    """Compartir el renderer no comparte cámara, selección, fecha o ubicación mutable con Planificación."""
    from ui.planetary_tab import PlanetaryPage
    from ui.planner_tab.planificacion.planetario_visual import PlanetarioVisual

    memory_db.execute("INSERT INTO locations(name,latitude,longitude,timezone_id) VALUES('A',40,1,'Europe/Madrid')")
    memory_db.execute("INSERT INTO locations(name,latitude,longitude,utc_offset_hours) VALUES('B',10,-84,-6)")
    memory_db.commit()
    page, planner = PlanetaryPage(), PlanetarioVisual()
    try:
        original = planner.view
        page.set_initial_location(1)
        page.sky.set_center(5, -12)
        page._location.setCurrentIndex(page._location.findData(2))
        page.set_initial_location(1)
        assert page._location.currentData() == 2
        assert page.sky.view[:2] == (5, -12)
        assert planner.view == original
        page.hide()
        assert page.sky.view[:2] == (5, -12)
        fresh = PlanetaryPage()
        try:
            fresh.set_initial_location(1)
            assert fresh._location.currentData() == 1
            assert fresh.sky.view[:2] == (0, 0)
        finally:
            fresh.close()
    finally:
        page.close()
        planner.close()


def test_planetario_busca_y_selecciona_en_su_instantanea(qt_app, no_sky):
    """La carta existente resuelve alias; una búsqueda ausente no carga un objetivo arbitrario."""
    from ui.planetary_tab import PlanetaryPage

    page = PlanetaryPage()
    try:
        page._search.setText("m31")
        page._find()
        assert page.sky._selected is not None
        assert "m31" in page._selection.text()
        page._search.setText("Objeto inexistente")
        page._find()
        assert page.sky._selected is None
        assert "coincidencia única" in page._selection.text()
    finally:
        page.close()


def test_navegacion_home_no_cambia_el_objetivo_del_plan(qt_app, memory_db, no_sky):
    """Botones de portada navegan por el cableado central, no ejecutan ni seleccionan por nombre."""
    from ui.main_window import MainWindow
    from ui.planetary_tab import PlanetaryPage
    from ui.summary_tab import SummaryPage

    window = MainWindow()
    try:
        assert isinstance(window._paginas["summary_tab"], SummaryPage)
        assert isinstance(window._paginas["planetary_tab"], PlanetaryPage)
        planner = window._paginas["planner_tab"]
        before = planner.planificacion._planetario.view
        window._paginas["summary_tab"]._continue.click()
        assert window.content.currentWidget() is planner
        assert planner.planificacion._planetario.view == before
        window._paginas["planetary_tab"].sky.set_center(3, 6)
        assert planner.planificacion._planetario.view == before
    finally:
        window.close()


def test_contexto_descarta_entregas_tras_cambio_o_cierre(qt_app):
    """Un cálculo viejo no puede actualizar el cielo de otra ubicación o un widget ya retirado."""
    from ui.sky_context import SkyContext

    context = SkyContext()
    calls = []
    context.ready.connect(lambda result, error: calls.append(result))
    generation = context._generation
    context.stop()
    context._receive(generation, "viejo", "")
    assert not calls
    context._receive(context._generation, "vigente", "")
    assert calls == ["vigente"]


def test_continuar_sesion_guardada_selecciona_su_fila_sin_editar_plan(qt_app, memory_db, no_sky):
    """Los datos legacy se abren en su tabla real, no en un objetivo distinto con el mismo nombre."""
    from ui.main_window import MainWindow

    memory_db.execute("INSERT INTO planned_sessions(object_id,target_name,session_date) VALUES('M31','Una sesión','2026-10-29')")
    memory_db.commit()
    before = list(memory_db.iterdump())
    window = MainWindow()
    try:
        summary = window._paginas["summary_tab"]
        summary._sessions.setCurrentIndex(1)
        summary._continue.click()
        planner = window._paginas["planner_tab"]
        assert planner.sesiones._selected()["id"] == 1
        assert list(memory_db.iterdump()) == before
    finally:
        window.close()


def test_error_al_recordar_ubicacion_no_desaparece_con_el_contexto(qt_app, memory_db, no_sky, monkeypatch):
    """El aviso de persistencia sigue visible aunque el cálculo del cielo termine después."""
    import sqlite3

    import ui.summary_tab as module

    memory_db.execute("INSERT INTO locations(name,latitude,longitude) VALUES('Sitio',40,1)")
    memory_db.commit()
    page = module.SummaryPage()

    def fail(*args):
        """Simula escritura rechazada, sin alterar la base."""
        raise sqlite3.OperationalError("disco de ejemplo lleno")

    monkeypatch.setattr(module, "set_setting", fail)
    try:
        page._location.setCurrentIndex(1)
        page._sky_ready(None, "recurso no disponible")
        assert "No se pudo recordar" in page._sky_note.text()
        assert "recurso no disponible" in page._sky_note.text()
    finally:
        page.close()


def test_cambiar_ubicacion_descarta_fase_anterior_y_modelo(qt_app, memory_db, no_sky):
    """No muestra el cielo calculado para otra ubicación o edición como contexto vigente."""
    from ui.summary_tab import SummaryPage

    memory_db.execute("INSERT INTO locations(name,latitude,longitude) VALUES('A',40,1)")
    memory_db.execute("INSERT INTO locations(name,latitude,longitude) VALUES('B',10,-84)")
    memory_db.commit()
    page = SummaryPage()
    try:
        page._location.setCurrentIndex(1)
        page._sky_state = object()
        page._location.setCurrentIndex(2)
        assert page._sky_state is None
        page._sky_state = object()
        page.reload_context()
        assert page._sky_state is None
    finally:
        page.close()


def test_worker_real_contexto_solar_solo_lectura_conexion_propia(qt_app, tmp_path, monkeypatch):
    """Un executor real puede consultar el modelo sin usar SQLite de Qt ni escribir en el archivo sintético."""
    import hashlib
    import sqlite3

    from PyQt6.QtTest import QSignalSpy

    from db import connection
    from ui.sky_context import SkyContext

    db = tmp_path / "synthetic.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(connection.SCHEMA_PATH.read_text(encoding="utf-8"))
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    monkeypatch.setattr(connection, "DB_PATH", db)
    context = SkyContext()
    spy = QSignalSpy(context.ready)
    context.request({"latitude":40.02, "longitude":1.28}, datetime(2026, 1, 15, 12, tzinfo=UTC))
    try:
        assert spy.wait(10_000)
        assert spy[0][1] == ""
        assert spy[0][0].sun_altitude > 0
        assert hashlib.sha256(db.read_bytes()).hexdigest() == digest
    finally:
        context.stop()


def test_portada_estrecha_con_fuente_grande_no_impone_desplazamiento_horizontal(qt_app, memory_db, no_sky):
    """La portada se apila y permite scroll vertical sin ampliar mínimos ni ocultar controles por el ancho."""
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QScrollArea

    from ui.summary_tab import SummaryPage

    previous = qt_app.font()
    font = QFont(previous)
    font.setPointSize(16)
    qt_app.setFont(font)
    page = SummaryPage()
    try:
        page._demo.setChecked(True)
        page.resize(780, 600)
        page.show()
        for _ in range(3):
            qt_app.processEvents()
        scroll = page.findChild(QScrollArea)
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().maximum() > 0
        assert len(page._cards) == 5
        assert page.minimumWidth() < 780
    finally:
        page.close()
        qt_app.setFont(previous)


def test_resumen_completo_sin_bajar_en_escritorio_125(qt_app, memory_db, no_sky):
    """La sesión de ejemplo y todos los accesos caben a la vez en el área útil de escritorio."""
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QScrollArea

    from ui.summary_tab import SummaryPage

    previous = qt_app.font()
    font = QFont(previous)
    font.setPointSize(16)
    qt_app.setFont(font)
    page = SummaryPage()
    try:
        page._demo.setChecked(True)
        page.resize(1280, 730)
        page.show()
        for _ in range(3):
            qt_app.processEvents()
        scroll = page.findChild(QScrollArea)
        assert scroll.verticalScrollBar().maximum() == 0
        assert scroll.horizontalScrollBar().maximum() == 0
        for card, button in page._cards.values():
            assert card.isVisible() and button.isVisible()
            assert scroll.viewport().rect().contains(button.mapTo(scroll.viewport(), button.rect().bottomRight()))
    finally:
        page.close()
        qt_app.setFont(previous)


def test_planetario_ocupa_toda_la_pagina_con_controles_superpuestos(qt_app, no_sky):
    """Mostrar opciones no reduce el cielo ni desplaza la cámara; los errores conservan una señal visible."""
    from ui.planetary_tab import PlanetaryPage

    page = PlanetaryPage()
    try:
        page.resize(1280, 730)
        page.show()
        qt_app.processEvents()
        assert page.sky.geometry() == page.rect()
        view = page.sky.view
        page._options.click()
        qt_app.processEvents()
        assert page._panel.isVisible()
        assert page.sky.geometry() == page.rect()
        assert page.sky.view == view
        assert page.rect().contains(page._panel.geometry())
        page._options.click()
        assert not page._panel.isVisible()
        assert page.childAt(700, 400) is page.sky
        page._context_ready(None, "modelo no disponible")
        assert "aviso" in page._details.text()
        assert "modelo no disponible" in page._details.toolTip()
    finally:
        page.close()


def test_encuadre_manual_sigue_el_centro_y_se_envia_sin_perder_campos(qt_app, memory_db, no_sky):
    """Solo la confirmación persiste; centro, FOV y teselas no se confunden con el zoom de exploración."""
    from planners import personal_catalog
    from ui.planetary_tab import PlanetaryPage

    page = PlanetaryPage()
    try:
        before = list(memory_db.iterdump())
        page._frame_enabled.setChecked(True)
        page._frame_width.setValue(2.4)
        page._frame_height.setValue(1.6)
        page._tiles_x.setValue(3)
        page._tiles_y.setValue(2)
        page.sky.set_center(5.25, -12)
        assert page.sky.framing == (78.75, -12, 2.4, 1.6, 3, 2)
        assert list(memory_db.iterdump()) == before
        page.save_framing("Mi encuadre")
        row = personal_catalog.list_objects()[0]
        assert row["kind"] == "region"
        assert (row["ra_hours"], row["dec_deg"]) == (5.25, -12)
        assert row["fov_major_arcmin"] == pytest.approx(144)
        assert row["fov_minor_arcmin"] == pytest.approx(96)
        assert (row["tiles_x"], row["tiles_y"]) == (3, 2)
        saved = personal_catalog.list_objects()
        with pytest.raises(ValueError):
            page.save_framing("Mi encuadre")
        assert personal_catalog.list_objects() == saved
    finally:
        page.close()


def test_enviar_centro_sin_fov_no_guarda_el_zoom_como_encuadre(qt_app, memory_db, no_sky):
    """Sin rectángulo habilitado se guarda solo una coordenada, nunca el campo visible como sensor."""
    from planners import personal_catalog
    from ui.planetary_tab import PlanetaryPage

    page = PlanetaryPage()
    try:
        page.sky.set_center(12, 30)
        page.sky.set_fov_deg(40)
        page.save_framing("Centro libre")
        row = personal_catalog.list_objects()[0]
        assert (row["ra_hours"], row["dec_deg"]) == (12, 30)
        assert row["fov_major_arcmin"] is None
        assert row["fov_minor_arcmin"] is None
        assert row["tiles_x"] is None
    finally:
        page.close()


def test_cancelar_envio_no_crea_objeto_ni_modifica_planes(qt_app, memory_db, no_sky):
    """Abrir el diálogo no autoriza persistencia y Cancelar conserva la base completa."""
    from PyQt6.QtCore import QTimer

    from ui.planetary_tab import PlanetaryPage

    page = PlanetaryPage()
    before = list(memory_db.iterdump())
    try:
        QTimer.singleShot(0, lambda: qt_app.activeModalWidget().reject())
        page._send_framing()
        assert list(memory_db.iterdump()) == before
    finally:
        page.close()


def test_enviar_desde_planetario_conserva_editor_y_borrador(qt_app, memory_db, no_sky):
    """Añadir a la lista ofrece el nuevo destino sin recargar el target y perder su centro editado."""
    from ui.main_window import MainWindow

    window = MainWindow()
    try:
        planner = window._paginas["planner_tab"]
        editor = planner.planificacion
        editor._planetario.set_center(3.75, 22)
        editor._session_name.setText("Trabajo previo")
        before = editor._draft_snapshot()
        draft_before = list(memory_db.execute("SELECT * FROM work_drafts"))
        page = window._paginas["planetary_tab"]
        page.sky.set_center(7, -20)
        page.save_framing("Destino nuevo")
        assert editor._draft_snapshot() == before
        assert list(memory_db.execute("SELECT * FROM work_drafts")) == draft_before
        assert any(row["object_id"] == "Destino nuevo" for row in editor._targets)
        assert window.content.currentWidget() is planner
        editor.select_target("Destino nuevo", "region")
        assert editor._current_target()["object_id"] == "Destino nuevo"
        assert editor._ra.value() == 7
        assert editor._dec.value() == -20
    finally:
        window.close()


def test_iconos_del_resumen_son_los_de_navegacion(qt_app, no_sky):
    """Todos los accesos comparten icono real, no solo la balanza del Planificador de Equipo."""
    from ui.main_window import TAB_GLYPHS, MainWindow, _glyph_icon

    window = MainWindow()
    try:
        summary = window._paginas["summary_tab"]
        for key, label in summary._section_icons.items():
            assert not label.pixmap().isNull()
            assert label.pixmap().toImage() == _glyph_icon(TAB_GLYPHS[key]).pixmap(28, 28).toImage()
    finally:
        window.close()


@pytest.mark.parametrize("value", ["2026-03-29T02:30", "2026-10-25T02:30"])
def test_reloj_de_exploracion_rechaza_limites_dst_no_univocos(value):
    """No convierte una hora local inexistente o repetida en otro instante silenciosamente."""
    with pytest.raises(ValueError):
        civil_to_utc(datetime.fromisoformat(value), {"latitude":40, "longitude":1, "timezone_id":"Europe/Madrid"})


@pytest.mark.parametrize("hour", [0, 12])
def test_contexto_solar_lunar_real_offline_sin_ventanas_nocturnas(hour):
    """Se calcula en el instante solicitado con modelo explícito y se conserva procedencia/limitaciones."""
    state = observe_sky(40.02, 1.28, datetime(2026, 1, 15, hour, tzinfo=UTC), model=EphemerisModel())
    assert -90 <= state.sun_altitude <= 90
    assert (state.sun_altitude > 0) == (hour == 12)
    assert 0 <= state.illumination <= 1
    assert state.accuracy.summary
    assert state.moment.hour == hour


@pytest.mark.parametrize("coordinates", [(91,0), (0,181), (float("nan"),0)])
def test_contexto_no_inventa_ubicacion(coordinates):
    """Una ubicación inválida falla antes de calcular o abrir recursos astronómicos."""
    with pytest.raises(ValueError):
        observe_sky(*coordinates, datetime(2026, 1, 15, tzinfo=UTC), model=EphemerisModel())
