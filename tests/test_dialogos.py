"""Tests de diálogos de la interfaz (regresiones de construcción y fugas)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

#: QApplication retenida a nivel de módulo: si la referencia se descarta,
#: PyQt6 la destruye al hacer GC y el siguiente widget crashea la proceso.
_APP = None


def _app():
    """QApplication única de los tests de diálogo (referencia retenida)."""
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_edit_session_dialog_constructs():
    """Regresión: `EditSessionDialog` usaba `QDateEdit` sin importarlo.

    Pulsar «Editar» en Sesiones Planificadas lanzaba `NameError` y el
    diálogo no se abría. Ningún test construía el diálogo, así que el
    fallo pasó desapercibido hasta la auditoría (Fase 2).
    """
    from ui.planner_tab.sesiones.tab import EditSessionDialog

    _app()
    dialog = EditSessionDialog(
        {"id": 1, "target_name": "M42", "session_date": "2026-10-15"}
    )

    values = dialog.values()
    assert values["target_name"] == "M42"
    assert values["session_date"] == "2026-10-15"
    dialog.deleteLater()


def test_region_dialog_does_not_accumulate(monkeypatch):
    """Regresión M-14: los diálogos por clic no se acumulan como hijos.

    `RegionDialog` se construye con padre y, sin `deleteLater`, quedaba
    como hijo oculto en cada clic (medido: 20/20 en la Fase 2).
    """
    from ui.planner_tab.catalogo_personal import tab as catalogo_tab

    app = _app()
    monkeypatch.setattr(
        catalogo_tab.RegionDialog, "exec", lambda self: 0  # Rejected
    )
    page = catalogo_tab.CatalogoPersonalTab()
    for _ in range(10):
        page._on_add_region()
    app.processEvents()

    assert page.findChildren(catalogo_tab.RegionDialog) == []
    page.deleteLater()


def test_edit_session_dialog_does_not_accumulate(monkeypatch):
    """Regresión M-14: «Editar» no acumula `EditSessionDialog` (fuga medida 20/20)."""
    from ui.planner_tab.sesiones import tab as sesiones_tab

    app = _app()
    row = {"id": 1, "target_name": "M42", "session_date": "2026-10-15"}
    monkeypatch.setattr(sesiones_tab.SesionesTab, "_selected", lambda _self: row)
    monkeypatch.setattr(
        sesiones_tab.EditSessionDialog, "exec", lambda self: 0  # Rejected
    )
    page = sesiones_tab.SesionesTab()
    for _ in range(10):
        page._on_edit()
    app.processEvents()

    assert page.findChildren(sesiones_tab.EditSessionDialog) == []
    page.deleteLater()
