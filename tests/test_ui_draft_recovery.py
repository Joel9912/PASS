"""Recuperación consentida del Planificador y fallos de autoguardado en sandbox."""

import sqlite3

import pytest
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QMessageBox

from db import work_drafts
from planners import personal_catalog, planned_sessions
from ui import draft_recovery
from ui.planner_tab.planificacion.tab import PlanificacionTab


@pytest.fixture
def planner(qt_app, memory_db, monkeypatch):
    """Región sintética; no calcula efemérides para probar persistencia de entradas."""
    personal_catalog.add_region("Región", 4.0, 40.0)
    monkeypatch.setattr(PlanificacionTab, "_refresh_curve", lambda self: None)
    page = PlanificacionTab()
    yield page
    page.deleteLater()


def test_planificador_no_crea_borrador_al_construir(planner, monkeypatch):
    """No confunde los valores iniciales y una ubicación recibida con trabajo del usuario."""
    planner.set_location(10, -84, -6)
    monkeypatch.setattr(planner._planetario, "set_target", lambda *args: planner._on_view_changed(4, 40, 20))
    planner.reload_targets()
    planner.reload_setups()
    assert work_drafts.read("planner") is None
    assert planned_sessions.list_sessions() == []


def test_planificador_recupera_entradas_sin_crear_sesion(planner, monkeypatch):
    """Reabrir conserva centro, teselas, texto, exposición, fecha y ubicación del borrador."""
    planner._session_name.setText("Mi noche")
    planner._notes.setText("Pendiente")
    planner._exposure.setValue(90)
    planner._date.setDate(QDate(2026, 10, 20))
    planner.set_location(10, -84, -6)
    planner._ra.setValue(5.5)
    planner._dec.setValue(30)
    planner._tiles_x.setValue(3)
    saved = work_drafts.decode(work_drafts.read("planner"))
    page = PlanificacionTab()
    assert page._draft.pending
    monkeypatch.setattr(draft_recovery, "ask_recovery", lambda *args: "resume")
    page._draft.offer()
    assert not page._draft.pending
    assert page._draft_snapshot() == saved
    assert page._session_name.text() == "Mi noche"
    assert planned_sessions.list_sessions() == []
    page.deleteLater()


@pytest.mark.parametrize("choice", ["later", "discard"])
def test_aplazar_o_descartar_no_crea_sesion(planner, monkeypatch, choice):
    """Más tarde no permite reemplazar el borrador; descartar solo retira esa fila."""
    planner._notes.setText("Conservar")
    row = work_drafts.read("planner")
    page = PlanificacionTab()
    monkeypatch.setattr(draft_recovery, "ask_recovery", lambda *args: choice)
    page._draft.offer()
    if choice == "later":
        assert not page._notes.isEnabled()
        page._notes.setText("No sobrescribir")
        assert work_drafts.read("planner") == row
    else:
        assert work_drafts.read("planner") is None
        assert page._notes.isEnabled()
    assert planned_sessions.list_sessions() == []
    page.deleteLater()


def test_objetivo_ausente_no_se_sustituye(planner, monkeypatch):
    """Una referencia desaparecida no se cambia por otra ni elimina el texto pendiente."""
    planner._notes.setText("Conservar")
    row = work_drafts.read("planner")
    personal_catalog.remove("Región", "region")
    personal_catalog.add_region("Otra", 8, 10)
    page = PlanificacionTab()
    monkeypatch.setattr(draft_recovery, "ask_recovery", lambda *args: "resume")
    page._draft.offer()
    assert page._draft.pending
    assert "ya no está" in page._draft.label.text()
    assert work_drafts.read("planner") == row
    page.deleteLater()


def test_guardar_sesion_retira_borrador(planner, monkeypatch):
    """Solo Guardar sesión crea una fila definitiva; los campos limpiados no generan otro borrador."""
    planner._session_name.setText("Noche")
    planner._ra.setValue(5.5)
    planner._dec.setValue(30)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    planner._on_save_session()
    assert work_drafts.read("planner") is None
    assert len(planned_sessions.list_sessions()) == 1
    assert planned_sessions.list_sessions()[0]["ra_hours"] == 5.5
    assert planned_sessions.list_sessions()[0]["dec_deg"] == 30
    assert not planner._draft.active


def test_autoguardado_fallido_no_anuncia_exito(planner, monkeypatch):
    """Un fallo al escribir deja el anterior intacto y avisa de las ediciones solo en memoria."""
    planner._notes.setText("Antes")
    row = work_drafts.read("planner")

    def fail(*args):
        """Simula disco o SQLite sin modificar los datos confirmados."""
        raise sqlite3.OperationalError("disco lleno")

    monkeypatch.setattr(work_drafts, "save", fail)
    planner._notes.setText("Después")
    assert "solo en memoria" in planner._draft.label.text()
    assert not planner._draft.flush()
    assert work_drafts.read("planner") == row


def test_guardar_no_inventa_coordenadas_desconocidas(planner, memory_db, monkeypatch):
    """El arreglo del centro editado no convierte coordenadas ausentes en ceros del editor."""
    memory_db.execute("UPDATE personal_catalog SET ra_hours=NULL,dec_deg=NULL")
    memory_db.commit()
    planner.reload_targets()
    planner._session_name.setText("Sin coordenadas")
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    planner._on_save_session()
    session = planned_sessions.list_sessions()[0]
    assert session["ra_hours"] is None and session["dec_deg"] is None


def test_equipo_modificado_avisa_de_fov_recalculado(planner, monkeypatch):
    """La recuperación no presenta un encuadre distinto como si fuera el original."""
    from equipment import components, manager
    from equipment.models import Camera, EquipmentSetup, Telescope

    telescope = components.create_telescope(Telescope(name="Óptica", focal_mm=1000))
    camera = components.create_camera(Camera(name="Cámara", pixel_size_um=3, width_px=2000, height_px=2000))
    manager.create(EquipmentSetup(name="Equipo", telescope_id=telescope, camera_id=camera))
    planner.reload_setups()
    planner._notes.setText("Pendiente")
    old = planner._fov
    components.update_telescope(Telescope(id=telescope, name="Óptica", focal_mm=2000))
    page = PlanificacionTab()
    monkeypatch.setattr(draft_recovery, "ask_recovery", lambda *args: "resume")
    page._draft.offer()
    assert not page._draft.pending
    assert page._fov != old
    assert "campo de visión" in page._draft_location_label.text()
    page.deleteLater()


@pytest.mark.parametrize("field,value", [("exposure", 999999), ("date", "20261015")])
def test_datos_invalidos_no_restauran_parcialmente(planner, monkeypatch, field, value):
    """Se valida todo antes de tocar nombre o notas; un dato truncable queda pendiente."""
    planner._notes.setText("Antes")
    row = work_drafts.read("planner")
    payload = work_drafts.decode(row)
    payload[field] = value
    revision = work_drafts.save("planner", payload, row["revision"])
    page = PlanificacionTab()
    monkeypatch.setattr(draft_recovery, "ask_recovery", lambda *args: "resume")
    page._draft.offer()
    assert page._draft.pending
    assert page._notes.text() == ""
    assert work_drafts.read("planner")["revision"] == revision
    page.deleteLater()
