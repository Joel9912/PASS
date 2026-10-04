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
