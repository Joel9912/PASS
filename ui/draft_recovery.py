"""Guardado automático y consentimiento de recuperación compartidos por dos pestañas."""

import math
import sqlite3
from collections.abc import Callable
from functools import wraps

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from db import work_drafts


def refresh_without_starting_draft(function: Callable) -> Callable:
    """Un refresco programático actualiza un borrador activo pero no inicia uno ficticio."""
    @wraps(function)
    def refreshed(owner, *args, **kwargs):
        """Suspende señales de autoguardado durante el refresco y confirma al finalizar."""
        draft = getattr(owner, "_draft", None)
        if draft is None:
            return function(owner, *args, **kwargs)
        previous = draft.paused
        draft.paused = True
        try:
            return function(owner, *args, **kwargs)
        finally:
            draft.paused = previous
            if not previous and draft.active:
                draft.flush()

    return refreshed


def capture_controls(controls: dict[str, QWidget]) -> dict:
    """Captura valores explícitos, incluso combinaciones todavía no ejecutables."""
    result = {}
    for key, control in controls.items():
        if isinstance(control, QCheckBox):
            result[key] = control.isChecked()
        elif isinstance(control, QComboBox):
            result[key] = {"data": control.currentData(), "text": control.currentText()}
        elif isinstance(control, (QSpinBox, QDoubleSpinBox)):
            result[key] = control.value()
        elif isinstance(control, QLineEdit):
            result[key] = control.text()
        else:
            raise TypeError(f"Control no recuperable: {key}")
    return result


def validate_controls(controls: dict[str, QWidget], data: dict) -> None:
    """Prevalida todos los valores para evitar restauraciones parciales o truncadas."""
    if not isinstance(data, dict) or set(data) != set(controls):
        raise ValueError("Opciones de borrador incompatibles")
    for key, control in controls.items():
        value = data[key]
        if isinstance(control, QCheckBox):
            valid = type(value) is bool
        elif isinstance(control, QComboBox):
            valid = isinstance(value, dict) and set(value) == {"data", "text"}
            if valid:
                index = control.findData(value["data"]) if value["data"] is not None else control.findText(value["text"])
                valid = index >= 0
        elif isinstance(control, (QSpinBox, QDoubleSpinBox)):
            valid = (type(value) in (int, float) and math.isfinite(value)
                     and control.minimum() <= value <= control.maximum())
            if isinstance(control, QSpinBox):
                valid = valid and type(value) is int
        else:
            valid = isinstance(value, str)
        if not valid:
            raise ValueError(f"Opción no válida: {key}")


def restore_controls(controls: dict[str, QWidget], data: dict) -> None:
    """Restaura entradas conservando las señales que habilitan controles dependientes."""
    validate_controls(controls, data)
    for key, control in controls.items():
        value = data[key]
        if isinstance(control, QCheckBox):
            control.setChecked(value)
        elif isinstance(control, QComboBox):
            index = control.findData(value["data"]) if value["data"] is not None else control.findText(value["text"])
            control.setCurrentIndex(index)
        elif isinstance(control, (QSpinBox, QDoubleSpinBox)):
            control.setValue(value)
        else:
            control.setText(value)


def connect_controls(controls: dict[str, QWidget], callback: Callable) -> None:
    """Conecta solo entradas declaradas, no log, navegación ni campos ajenos."""
    for control in controls.values():
        if isinstance(control, QCheckBox):
            control.toggled.connect(callback)
        elif isinstance(control, QComboBox):
            control.currentIndexChanged.connect(callback)
        elif isinstance(control, (QSpinBox, QDoubleSpinBox)):
            control.valueChanged.connect(callback)
        else:
            control.textChanged.connect(callback)


def ask_recovery(parent: QWidget, title: str) -> str:
    """Ofrece continuar, aplazar o descartar solo el borrador; Escape aplaza."""
    dialog = QMessageBox(parent)
    dialog.setWindowTitle("Trabajo pendiente")
    dialog.setText(title)
    dialog.setInformativeText(
        "Continuar comprueba el estado guardado. No inicia procesamiento.\n"
        "Descartar borrador no elimina sesiones guardadas, originales ni resultados."
    )
    resume = dialog.addButton("Continuar", QMessageBox.ButtonRole.AcceptRole)
    later = dialog.addButton("Más tarde", QMessageBox.ButtonRole.RejectRole)
    discard = dialog.addButton("Descartar borrador", QMessageBox.ButtonRole.DestructiveRole)
    dialog.setDefaultButton(later)
    dialog.setEscapeButton(later)
    try:
        dialog.exec()
        selected = dialog.clickedButton()
        return "resume" if selected is resume else "discard" if selected is discard else "later"
    finally:
        dialog.deleteLater()


class DraftRecovery(QObject):
    """Coordina la UI sin interpretar datos de negocio ni acceder a originales."""

    status_changed = pyqtSignal(str)

    def __init__(
        self, owner: QWidget, workflow: str, title: str,
        snapshot: Callable[[], dict], restore: Callable[[dict], None],
        block: Callable[[bool], None],
    ) -> None:
        """Carga solo metadatos; ofrece la recuperación cuando se entra en la pestaña."""
        super().__init__(owner)
        self.owner = owner
        self.workflow = workflow
        self.title = title
        self.snapshot = snapshot
        self.restore = restore
        self.block = block
        self.active = False
        self.paused = False
        self.error = None
        self.revision = None
        self.row = None
        try:
            self.row = work_drafts.read(workflow)
            self.revision = self.row["revision"] if self.row else None
        except sqlite3.Error as exc:
            self.error = str(exc)
        self.pending = self.row is not None or self.error is not None
        self.label = QLabel("", owner)
        self.label.setObjectName("HintLabel")
        self.label.setWordWrap(True)
        self.button = QPushButton("Recuperar borrador…", owner)
        self.button.clicked.connect(self.offer)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.offer)
        self._status("Hay un borrador pendiente." if self.pending else "Sin borrador pendiente.")
        self.block(self.pending)

    def entered(self) -> None:
        """Pospone el aviso hasta terminar el evento de mostrar la página."""
        if self.pending:
            self.timer.start(0)

    def offer(self) -> None:
        """No reemplaza lo pendiente hasta que el usuario lo recupera o descarta."""
        if not self.pending:
            return
        choice = ask_recovery(self.owner, self.title)
        if choice == "later":
            self._status("Borrador conservado. Recupéralo o descártalo antes de empezar otro.")
            return
        try:
            if self.error:
                raise work_drafts.DraftError(self.error)
            if choice == "discard":
                work_drafts.delete(self.workflow, self.revision)
                self.revision = None
                self.active = False
            else:
                data = work_drafts.decode(self.row)
                self.paused = True
                try:
                    self.restore(data)
                finally:
                    self.paused = False
                self.active = True
            self.pending = False
            self.block(False)
            self._status("Borrador recuperado." if self.active else "Borrador descartado.")
            if self.active:
                self.flush()
        except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
            self._status(f"No se pudo recuperar: {exc}. El borrador se conserva.")

    def changed(self, *_args) -> bool:
        """Guarda solo ediciones reales, sin sobreescribir una recuperación aplazada."""
        if self.paused or self.pending:
            return True
        self.active = True
        return self.flush()

    def flush(self) -> bool:
        """Confirma la instantánea; un fallo conserva la anterior y deja aviso persistente."""
        if self.paused or self.pending or not self.active:
            return True
        try:
            self.revision = work_drafts.save(self.workflow, self.snapshot(), self.revision)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._status(f"No se pudo guardar el borrador: {exc}. Las últimas ediciones están solo en memoria.")
            return False
        self._status("Borrador guardado automáticamente · trabajo pendiente.")
        return True

    def clear(self) -> bool:
        """Retira el borrador confirmado y evita recrearlo al limpiar controles."""
        try:
            work_drafts.delete(self.workflow, self.revision)
        except (ValueError, sqlite3.Error) as exc:
            self._status(f"No se pudo retirar el borrador: {exc}.")
            return False
        self.revision = None
        self.active = False
        self.pending = False
        self._status("Sin borrador pendiente.")
        return True

    def _status(self, text: str) -> None:
        """Explica el estado con texto, sin afirmar éxito cuando hubo un error."""
        self.label.setText(text)
        self.status_changed.emit(text)
        self.button.setVisible(self.pending)
