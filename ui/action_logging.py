"""Observa acciones de interfaz sin registrar textos escritos ni credenciales."""

import logging

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QListWidget,
    QMessageBox,
    QTabWidget,
    QWidget,
)

from pass_logging import record_action


def _section(widget: QWidget) -> str:
    """Identifica la sección por sus padres, también para diálogos asociados."""
    current = widget
    while current is not None:
        module = type(current).__module__
        if module.startswith("ui.stacker_tab"):
            return "apilador"
        for name in ("equipment_tab", "planner_tab", "config_tab"):
            if module.startswith("ui." + name):
                return name
        current = current.parentWidget()
    return "interfaz"


class ActionLogger(QObject):
    """Cablea botones al mostrarse y registra avisos, sin guardar campos de entrada."""

    def __init__(self, app):
        """Retiene el observador en QApplication durante toda la sesión."""
        super().__init__(app)
        app.installEventFilter(self)

    def eventFilter(self, watched, event):
        """Observa clicks reales (incluido teclado) y errores mostrados por Qt."""
        if event.type() == QEvent.Type.Show:
            if isinstance(watched, (QAbstractButton, QComboBox, QListWidget, QTabWidget)) and not watched.property("pass_log_connected"):
                watched.setProperty("pass_log_connected", True)
                if isinstance(watched, QAbstractButton):
                    watched.clicked.connect(self._clicked)
                elif isinstance(watched, QComboBox):
                    watched.activated.connect(self._selected)
                elif isinstance(watched, QListWidget):
                    watched.currentRowChanged.connect(self._selected)
                else:
                    watched.currentChanged.connect(self._selected)
            elif isinstance(watched, QMessageBox):
                record_action(_section(watched), "Aviso: " + watched.text(), level=logging.WARNING)
        return False

    def _clicked(self, _checked=False):
        """Registra el control accionado, excluyendo botones de campos protegidos."""
        button = self.sender()
        if button.parentWidget() and button.parentWidget().inherits("QLineEdit"):
            return
        record_action(_section(button), "Acción: " + (button.text() or button.objectName() or type(button).__name__))

    def _selected(self, index):
        """Registra navegación y selección sin copiar valores personales del control."""
        control = self.sender()
        record_action(_section(control), f"Selección en {control.objectName() or type(control).__name__}: índice {index}")
