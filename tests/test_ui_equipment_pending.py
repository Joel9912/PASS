"""Protección de borradores de Equipo sin modificar bases ni imágenes personales."""

import sqlite3

import pytest
from PyQt6.QtWidgets import QMessageBox, QWidget

from equipment import components, manager
from equipment.models import EquipmentSetup, Telescope
from ui.equipment_tab import EquipmentPage, componentes, equipos


@pytest.mark.parametrize("respuesta", ["Save", "Discard", "Cancel"])
def test_cambiar_equipo_resuelve_ediciones(qt_app, memory_db, monkeypatch, respuesta):
    """Guardar confirma el equipo anterior; descartar restaura y cancelar mantiene fila y ficha."""
    primero = manager.create(EquipmentSetup(name="Primero"))
    segundo = manager.create(EquipmentSetup(name="Segundo"))
    tab = equipos.EquiposTab()
    tab._nombre.setText("Editado")
    avisos = []
    monkeypatch.setattr(
        equipos, "confirmar_cambios",
        lambda *args: avisos.append(args[1]) or getattr(QMessageBox.StandardButton, respuesta),
        raising=False,
    )
    tab._lista.setCurrentRow(1)
    assert len(avisos) == 1
    assert manager.get(primero)["name"] == ("Editado" if respuesta == "Save" else "Primero")
    if respuesta == "Cancel":
        assert tab._setup_id == primero
        assert tab._lista.currentRow() == 0
        assert tab._nombre.text() == "Editado"
    else:
        assert tab._setup_id == segundo
        assert tab._nombre.text() == "Segundo"
    tab.deleteLater()


def test_nuevo_equipo_cancelado_conserva_borrador(qt_app, memory_db, monkeypatch):
    """Nuevo no borra lo tecleado cuando se cancela la salida."""
    tab = equipos.EquiposTab()
    tab._nombre.setText("Borrador")
    monkeypatch.setattr(equipos, "confirmar_cambios", lambda *args: QMessageBox.StandardButton.Cancel)
    tab._nuevo()
    assert tab._nombre.text() == "Borrador"
    assert manager.list_setups() == []
    tab.deleteLater()


def test_salida_sin_cambios_no_pregunta(qt_app, memory_db, monkeypatch):
    """Una carga y editar/deshacer manualmente no crean avisos falsos."""
    manager.create(EquipmentSetup(name="Equipo"))
    tab = equipos.EquiposTab()
    monkeypatch.setattr(equipos, "confirmar_cambios", lambda *args: pytest.fail("Aviso inesperado"))
    monkeypatch.setattr(componentes, "confirmar_cambios", lambda *args: pytest.fail("Aviso inesperado"))
    assert tab.preparar_salida()
    tab._notas.setText("Pendiente")
    assert "sin guardar" in tab._estado_guardado.text()
    tab._notas.clear()
    assert tab.preparar_salida()
    assert tab._estado_guardado.text() == "Guardado"
    tab.deleteLater()


@pytest.mark.parametrize("error", [ValueError("inválido"), OSError("copia"), sqlite3.Error("BD")])
def test_guardar_fallido_impide_salir(qt_app, memory_db, monkeypatch, error):
    """Los errores dejan el equipo y sus ediciones disponibles, sin anunciar éxito."""
    tab = equipos.EquiposTab()
    tab._nombre.setText("Borrador")
    monkeypatch.setattr(equipos, "confirmar_cambios", lambda *args: QMessageBox.StandardButton.Save)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)

    def fallar(*args):
        """Simula el fallo del backend sin escribir datos."""
        raise error

    monkeypatch.setattr(manager, "create", fallar)
    assert not tab.preparar_salida()
    assert tab._nombre.text() == "Borrador"
    assert "sin guardar" in tab._estado_guardado.text()
    tab.deleteLater()


@pytest.mark.parametrize("respuesta", ["Save", "Discard", "Cancel"])
def test_cambiar_componente_protege_pieza_correcta(qt_app, memory_db, monkeypatch, respuesta):
    """El diálogo guarda la pieza anterior, no la recién elegida en el combo."""
    primero = components.create_telescope(Telescope(name="Primero", price_eur=10))
    segundo = components.create_telescope(Telescope(name="Segundo", price_eur=20))
    tab = equipos.EquiposTab()
    editor = tab._tel_principal
    editor.cargar(primero)
    editor.form._precio.setValue(99)
    monkeypatch.setattr(
        componentes, "confirmar_cambios",
        lambda *args: getattr(QMessageBox.StandardButton, respuesta),
        raising=False,
    )
    editor.picker._combo.setCurrentIndex(editor.picker._combo.findData(segundo))
    assert components.get_telescope(primero)["price_eur"] == (99 if respuesta == "Save" else 10)
    assert components.get_telescope(segundo)["price_eur"] == 20
    assert editor.selected_id() == (primero if respuesta == "Cancel" else segundo)
    assert editor.form._precio.value() == (99 if respuesta == "Cancel" else 20)
    tab.deleteLater()


def test_componentes_y_equipo_tienen_guardados_separados(qt_app, memory_db, monkeypatch):
    """Descartar el equipo no revierte una pieza confirmada en el primer diálogo."""
    pieza = components.create_telescope(Telescope(name="Óptica", price_eur=10))
    setup = manager.create(EquipmentSetup(name="Equipo", telescope_id=pieza, price_eur=10))
    tab = equipos.EquiposTab()
    tab._tel_principal.form._precio.setValue(99)
    tab._nombre.setText("Pendiente")
    orden = []
    monkeypatch.setattr(componentes, "confirmar_cambios", lambda *args: orden.append("pieza") or QMessageBox.StandardButton.Save)
    monkeypatch.setattr(equipos, "confirmar_cambios", lambda *args: orden.append("equipo") or QMessageBox.StandardButton.Discard)
    assert tab.preparar_salida()
    assert orden == ["pieza", "equipo"]
    assert components.get_telescope(pieza)["price_eur"] == 99
    assert manager.get(setup)["name"] == "Equipo"
    assert manager.get(setup)["price_eur"] == 10
    assert tab._nombre.text() == "Equipo"
    assert tab._precio.value() == 10
    assert tab._estado_guardado.text() == "Guardado"
    assert tab.preparar_salida()
    tab.deleteLater()


def test_fallo_componente_no_guarda_equipo(qt_app, memory_db, monkeypatch):
    """Guardar equipo no descarta un componente fallido ni confirma totales parciales."""
    tab = equipos.EquiposTab()
    tab._nombre.setText("Equipo")
    tab._tel_principal.form._nombre.setText("Óptica")
    monkeypatch.setattr(componentes, "confirmar_cambios", lambda *args: QMessageBox.StandardButton.Save)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)

    def fallar(*args):
        """Simula un fallo de copia de la pieza global."""
        raise OSError("copia")

    monkeypatch.setitem(tab._tel_principal._pieza, "crear", fallar)
    assert not tab._guardar()
    assert manager.list_setups() == []
    assert tab._tel_principal.form._nombre.text() == "Óptica"
    tab.deleteLater()


def test_ediciones_del_otro_rol_no_se_pierden(qt_app, memory_db):
    """Guardar una pieza compartida no sobreescribe el borrador del otro rol."""
    pieza = components.create_telescope(Telescope(name="Óptica", price_eur=10))
    tab = equipos.EquiposTab()
    tab._tel_principal.cargar(pieza)
    tab._tel_guia.cargar(pieza)
    tab._tel_guia.form._notas.setText("Pendiente")
    tab._tel_principal.form._precio.setValue(99)
    assert tab._tel_principal._guardar()
    assert tab._tel_guia.form._notas.text() == "Pendiente"
    assert tab._tel_guia.tiene_cambios()
    tab.deleteLater()


def test_subpestana_cancelada_conserva_ediciones(qt_app, memory_db, monkeypatch):
    """Salir hacia Ubicaciones respeta Cancelar y restaura Equipos."""
    pagina = EquipmentPage()
    pagina.equipos._nombre.setText("Borrador")
    monkeypatch.setattr(equipos, "confirmar_cambios", lambda *args: QMessageBox.StandardButton.Cancel, raising=False)
    pagina._tabs.setCurrentIndex(1)
    assert pagina._tabs.currentIndex() == 0
    assert pagina.equipos._nombre.text() == "Borrador"
    pagina.deleteLater()


def test_navegacion_y_cierre_respetan_cancelar(qt_app, memory_db, monkeypatch):
    """La ventana restaura navegación y rechaza cerrar sin resolver el equipo."""
    from PyQt6.QtGui import QCloseEvent

    from ui import main_window

    for clave, _ in main_window.TABS:
        monkeypatch.setitem(
            main_window._PAGE_BUILDERS, clave,
            EquipmentPage if clave == "equipment_tab" else QWidget,
        )
    monkeypatch.setattr(main_window.MainWindow, "_install_bundled_catalogs", lambda self: None)
    monkeypatch.setattr(main_window.MainWindow, "showMaximized", lambda self: None)
    ventana = main_window.MainWindow()
    indice = next(i for i, (clave, _) in enumerate(main_window.TABS) if clave == "equipment_tab")
    ventana.sidebar.nav.setCurrentRow(indice)
    ventana._paginas["equipment_tab"].equipos._nombre.setText("Borrador")
    monkeypatch.setattr(equipos, "confirmar_cambios", lambda *args: QMessageBox.StandardButton.Cancel, raising=False)
    ventana.sidebar.nav.setCurrentRow(0)
    assert ventana.content.currentIndex() == indice
    assert ventana.sidebar.nav.currentRow() == indice
    evento = QCloseEvent()
    ventana.closeEvent(evento)
    assert not evento.isAccepted()
    monkeypatch.setattr(equipos, "confirmar_cambios", lambda *args: QMessageBox.StandardButton.Discard)
    ventana.closeEvent(evento)
    assert evento.isAccepted()
    ventana.deleteLater()


def test_dialogo_tiene_acciones_explicitas_y_escape_seguro(qt_app, monkeypatch):
    """Los botones están en español y cerrar o pulsar Escape equivale a Cancelar."""
    boton = QMessageBox.StandardButton

    def comprobar(dialogo):
        """Inspecciona el diálogo real sin bloquear la suite offscreen."""
        assert dialogo.button(boton.Save).text() == "Guardar"
        assert dialogo.button(boton.Discard).text() == "Descartar"
        assert dialogo.button(boton.Cancel).text() == "Cancelar"
        assert dialogo.defaultButton() == dialogo.button(boton.Cancel)
        assert dialogo.escapeButton() == dialogo.button(boton.Cancel)
        return boton.Cancel

    monkeypatch.setattr(QMessageBox, "exec", comprobar)
    padre = QWidget()
    assert componentes.confirmar_cambios(padre, "Cambios pendientes") == boton.Cancel
    padre.deleteLater()
