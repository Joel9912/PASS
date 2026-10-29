"""Subpestaña **Sesiones Planificadas**: las sesiones concretadas por el usuario.

Tabla de ``planned_sessions`` con las acciones del mockup: editar, marcar
completada y eliminar. La pestaña Resumen (y más adelante el Apilador) leen
esta misma tabla, así que aquí solo se gestiona el ciclo de vida.

Las sesiones se crean en Planificación (``session_saved``); al llegar esa
señal se llama a :meth:`refresh` para que aparezca la fila nueva.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from equipment.manager import list_setups
from planners import planned_sessions

from ...style import PALETTE
from ..widgets import crear_tabla_filas, fila_seleccionada

#: Columnas de la tabla (mockup del usuario).
COLUMNS: tuple[str, ...] = (
    "#", "Nombre", "Target", "Fecha", "Equipo", "Exp", "Estado",
)

#: Estado de la fila → color del texto (de la paleta única, A-28).
STATUS_COLORS: dict[str, str] = {
    "planificada": PALETTE["accentLight"],
    "completada": PALETTE["ok"],
}


def _setup_names() -> dict[int, str]:
    """Mapa ``setup_id`` → nombre (``manager.get`` es stub, se usa el listado)."""
    try:
        setups = list_setups()
    except sqlite3.Error:  # tabla vacía o recién creada
        return {}
    return {
        int(row["id"]): str(row.get("name") or f"Setup {row['id']}")
        for row in setups
        if row.get("id") is not None
    }


def _brush(color: str) -> QBrush:
    """Color en hexadecimal como ``QBrush`` para pintar una celda."""
    return QBrush(QColor(color))


def _format_date(date_iso: str | None) -> str:
    """``2026-10-15`` → ``15/10/26`` (vacío si no hay fecha)."""
    if not date_iso:
        return "--"
    try:
        moment = date.fromisoformat(str(date_iso))
    except ValueError:
        return str(date_iso)
    return moment.strftime("%d/%m/%y")


class EditSessionDialog(QDialog):
    """Edita los parámetros editables de una sesión (nombre, fecha, exp…)."""

    def __init__(self, session: dict, parent: QWidget | None = None) -> None:
        """Formulario con los campos editables precargados de ``session``."""
        super().__init__(parent)
        self.setWindowTitle(f"Editar sesión — {session.get('target_name') or ''}")
        self.setMinimumWidth(420)
        self._session = session

        form = QFormLayout(self)
        form.setSpacing(10)

        self._name = QLineEdit(str(session.get("target_name") or ""))
        form.addRow("Nombre", self._name)

        self._date = QDateEdit()
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("yyyy-MM-dd")
        current = str(session.get("session_date") or "")
        parsed = QDate.fromString(current, "yyyy-MM-dd")
        self._date.setDate(parsed if parsed.isValid() else QDate.currentDate())
        form.addRow("Fecha", self._date)

        self._setup = QComboBox()
        self._setup.addItem("(sin equipo)", None)
        names = _setup_names()
        for setup_id in sorted(names):
            self._setup.addItem(names[setup_id], setup_id)
        selected = self._setup.findData(session.get("setup_id"))
        if selected >= 0:
            self._setup.setCurrentIndex(selected)
        form.addRow("Equipo", self._setup)

        self._exposure = QSpinBox()
        self._exposure.setRange(1, 7200)
        self._exposure.setSuffix(" s")
        self._exposure.setValue(int(session.get("planned_exposure_s") or 300))
        form.addRow("Exposición", self._exposure)

        self._tiles_x = QSpinBox()
        self._tiles_x.setRange(1, 20)
        self._tiles_x.setValue(int(session.get("tiles_x") or 1))
        self._tiles_y = QSpinBox()
        self._tiles_y.setRange(1, 20)
        self._tiles_y.setValue(int(session.get("tiles_y") or 1))
        tiles = QHBoxLayout()
        tiles.addWidget(self._tiles_x)
        tiles.addWidget(QLabel("×"))
        tiles.addWidget(self._tiles_y)
        tiles.addStretch(1)
        holder = QWidget()
        holder.setLayout(tiles)
        form.addRow("Teselas", holder)

        self._notes = QLineEdit(str(session.get("notes") or ""))
        form.addRow("Notas", self._notes)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        """Columnas modificadas, listas para ``update_session(**values)``."""
        return {
            "target_name": self._name.text().strip(),
            "session_date": self._date.date().toString("yyyy-MM-dd"),
            "setup_id": self._setup.currentData(),
            "planned_exposure_s": int(self._exposure.value()),
            "tiles_x": int(self._tiles_x.value()),
            "tiles_y": int(self._tiles_y.value()),
            "notes": self._notes.text().strip(),
        }


class SesionesTab(QWidget):
    """Tabla de sesiones planificadas con editar / completar / eliminar."""

    sessions_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta tabla, botones y aviso; arranca con ``refresh()`` (lee la base)."""
        super().__init__(parent)
        self._rows: list[dict] = []
        self._setup_names: dict[int, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("Sesiones planificadas")
        title.setObjectName("PanelTitle")
        head.addWidget(title)
        self._count = QLabel("0 sesiones")
        self._count.setObjectName("HintLabel")
        head.addWidget(self._count)
        head.addStretch(1)
        layout.addLayout(head)

        self._table = crear_tabla_filas(list(COLUMNS), altura_min=280)
        self._table.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self._table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self._edit = QPushButton("Editar")
        self._edit.clicked.connect(self._on_edit)
        self._edit.setEnabled(False)
        actions.addWidget(self._edit)

        self._complete = QPushButton("Marcar completada")
        self._complete.clicked.connect(self._on_complete)
        self._complete.setEnabled(False)
        actions.addWidget(self._complete)

        self._delete = QPushButton("Eliminar")
        self._delete.clicked.connect(self._on_delete)
        self._delete.setEnabled(False)
        actions.addWidget(self._delete)

        actions.addStretch(1)
        layout.addLayout(actions)

        hint = QLabel(
            "Las sesiones completadas pasan al flujo del Apilador; "
            "sus originales se leen solo desde la carpeta indicada."
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.refresh()

    # -- API pública ---------------------------------------------------------
    def refresh(self) -> None:
        """Relee las sesiones y repuebla la tabla."""
        self._rows = planned_sessions.list_sessions()
        self._setup_names = _setup_names()
        self._fill()
        self._count.setText(f"{len(self._rows)} sesiones")
        self.sessions_changed.emit()

    # -- Relleno -------------------------------------------------------------
    def select_session(self, session_id: int) -> bool:
        """Localiza por identidad guardada desde Resumen, sin editar la sesión ni el objetivo de Planificación."""
        self.refresh()
        for index, row in enumerate(self._rows):
            if row["id"] == session_id:
                self._table.selectRow(index)
                self._table.scrollToItem(self._table.item(index, 0))
                return True
        self._table.clearSelection()
        return False

    def _fill(self) -> None:
        """Vuelca ``self._rows`` con el color de estado y la alineación de columnas."""
        self._table.setRowCount(len(self._rows))
        for index, row in enumerate(self._rows):
            values = (
                str(index + 1),
                str(row.get("target_name") or "--"),
                str(row.get("object_id") or "--"),
                _format_date(row.get("session_date")),
                self._setup_names.get(
                    int(row["setup_id"]) if row.get("setup_id") else -1, "--"
                ),
                f"{row['planned_exposure_s']} s"
                if row.get("planned_exposure_s")
                else "--",
                str(row.get("status") or "planificada"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 6:
                    item.setForeground(
                        _brush(STATUS_COLORS.get(value, PALETTE["text"]))
                    )
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                    )
                elif column in (4, 5):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self._table.setItem(index, column, item)
        self._table.resizeRowsToContents()

    # -- Selección -----------------------------------------------------------
    def _selected(self) -> dict | None:
        """Fila seleccionada (``None`` si no hay)."""
        return fila_seleccionada(self._table, self._rows)

    def _on_selection(self) -> None:
        """Habilita los botones según la fila: la ya «completada» no se puede completar."""
        row = self._selected()
        has_row = row is not None
        self._edit.setEnabled(has_row)
        self._delete.setEnabled(has_row)
        self._complete.setEnabled(
            has_row and row.get("status") != "completada"
        )

    # -- Acciones ------------------------------------------------------------
    def _on_edit(self) -> None:
        """Abre el diálogo con la fila y, si se acepta, actualiza la sesión y refresca."""
        row = self._selected()
        if row is None:
            return
        dialog = EditSessionDialog(row, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            planned_sessions.update_session(int(row["id"]), **dialog.values())
            self.refresh()
        # El diálogo se construye con padre: sin borrarlo se acumula como
        # hijo oculto en cada clic (fuga medida en la auditoría, M-14).
        dialog.deleteLater()

    def _on_complete(self) -> None:
        """Pasa la sesión a «completada» (entra en el flujo del Apilador) y refresca."""
        row = self._selected()
        if row is None:
            return
        planned_sessions.mark_completed(int(row["id"]))
        self.refresh()

    def _on_delete(self) -> None:
        """Elimina la sesión **tras confirmar** (no se puede deshacer) y refresca."""
        row = self._selected()
        if row is None:
            return
        name = row.get("target_name") or row.get("object_id") or ""
        answer = QMessageBox.question(
            self,
            "Eliminar sesión",
            f'¿Eliminar la sesión «{name}»? No se puede deshacer.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            planned_sessions.delete_session(int(row["id"]))
            self.refresh()
