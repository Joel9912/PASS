"""Sección de catálogos: versiones comprobables y operaciones fuera del hilo Qt."""
import logging
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from db import connection
from db.catalog_editions import restore_previous, status
from pass_logging import record_action
from planners import catalog_packages, data_packages
from ui.style import PALETTE

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="catalog-packages")


class CatalogsPage(QWidget):
    """Mantiene las descargas independientes de Guardar y pide consentimiento al actualizar."""

    completed = pyqtSignal(object, str)
    catalogs_changed = pyqtSignal()

    def __init__(self, parent=None):
        """Construye una página sin red; conserva el trabajo al cerrar Configuración."""
        super().__init__(parent)
        self._packages = None
        self._global_manifest = None
        self._busy = False
        self._restoring = False
        self._notices_dialog = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._panel = QFrame()
        self._panel.setObjectName("GroupFrame")
        self._panel.setProperty("catalogPanel", True)
        layout.addWidget(self._panel)
        layout.addStretch()
        layout = QVBoxLayout(self._panel)
        layout.setContentsMargins(12, 6, 12, 10)
        layout.setSpacing(8)
        title = QLabel("Catálogos de datos")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)
        hint = QLabel("Versiones locales y actualizaciones de los paquetes PASS.")
        hint.setObjectName("HintLabel")
        layout.addWidget(hint)
        self._edition_label = QLabel()
        self._edition_label.setObjectName("HintLabel")
        self._edition_label.setWordWrap(True)
        self._edition_label.hide()
        layout.addWidget(self._edition_label)
        self._table = QTableWidget(len(catalog_packages.GROUPS), 3)
        self._table.setObjectName("CatalogPackagesTable")
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setHorizontalHeaderLabels(["Catálogo", "Versión", "Actualizado"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().hide()
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setDefaultSectionSize(2 * self.fontMetrics().height() + 16)
        layout.addWidget(self._table)
        self._status = QLabel("Comprueba si hay paquetes nuevos publicados por PASS.")
        self._status.setObjectName("HintLabel")
        self._status.setWordWrap(True)
        buttons = QHBoxLayout()
        self._check = QPushButton("Comprobar actualizaciones")
        self._check.clicked.connect(self.check)
        buttons.addWidget(self._check)
        self._update = QPushButton("Actualizar")
        self._update.setObjectName("PrimaryButton")
        self._update.clicked.connect(self.start_update)
        buttons.addWidget(self._update)
        layout.addLayout(buttons)
        self._restore = QPushButton("Recuperar edición anterior")
        self._restore.setToolTip("Cambia solo el catálogo; conserva equipos, ubicaciones, notas y sesiones posteriores.")
        self._restore.clicked.connect(self.start_restore)
        secondary = QHBoxLayout()
        secondary.addWidget(self._restore)
        self._notices = QPushButton("Fuentes y licencias")
        self._notices.clicked.connect(self.show_notices)
        secondary.addWidget(self._notices)
        layout.addLayout(secondary)
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.hide()
        layout.addWidget(self._progress)
        layout.addWidget(self._status)
        self.completed.connect(self._finished)
        self.refresh()
        self._table.setFixedHeight(
            self._table.horizontalHeader().sizeHint().height()
            + sum(self._table.rowHeight(row) for row in range(self._table.rowCount()))
            + 2 * self._table.frameWidth() + 4
        )

    def refresh(self):
        """No confunde catálogos heredados sin metadatos con una versión vigente."""
        versions = catalog_packages.installed(connection.get_connection())
        health = status(connection.get_connection())
        try:
            edition = data_packages.describe(connection.get_connection())
        except (ValueError, KeyError, TypeError):
            edition = None
        self._edition_label.setVisible(edition is not None)
        if edition:
            text = f"Edición {edition['edition']} · recursos seleccionados: {len(edition['selected'])}"
            if edition["absent_optional"]:
                text += " · opcionales no instalados: " + ", ".join(edition["absent_optional"])
            self._edition_label.setText(text)
        self._pending = []
        for row, group in enumerate(catalog_packages.GROUPS):
            version = versions[group]
            text = version["version"] if version else "Sin identificar"
            state = "Vigencia no comprobada"
            if self._packages:
                item = self._packages[group]
                current = health["available"] and version and version.get("sha256") == item["sha256"]
                state = "Actualizado" if current else "Paquete disponible"
                if not current:
                    self._pending.append(group)
            if not health["available"]:
                state = "Edición no disponible"
            date = version["date"] if version else "—"
            for column, value in enumerate((group.upper(), text, f"{date}\n{state}")):
                item = QTableWidgetItem(value)
                item.setToolTip(state)
                if not version:
                    item.setToolTip(state + ". Versión sin identificar o catálogo no instalado.")
                if not health["available"]:
                    item.setToolTip(health["error"])
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                color = PALETTE["accentLight"] if column == 0 else PALETTE["textDim"]
                if column == 0:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                elif version:
                    color = PALETTE["text"]
                if column == 2 and (self._packages or not health["available"]):
                    color = PALETTE["ok"] if state == "Actualizado" else PALETTE["warn"]
                item.setForeground(QColor(color))
                item.setBackground(QColor(PALETTE["panel"] if row % 2 else PALETTE["bg"]))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, column, item)
        self._check.setEnabled(not self._busy)
        if self._global_manifest and (not edition or edition["manifest"] != self._global_manifest or not health["available"]):
            self._pending.append("edición y recursos")
        self._update.setEnabled(not self._busy and bool(self._pending))
        self._restore.setEnabled(not self._busy and health["previous"])
        if health["prepared"] and self._status.text().startswith("Comprueba si"):
            self._status.setText("Hay archivos preparados sin activar; no se adoptarán ni borrarán automáticamente.")

    def _submit(self, operation, *args):
        """Encola una sola operación y devuelve su resultado mediante señal Qt."""
        self._busy = True
        self._progress.setRange(0, 0)
        self._progress.show()
        self.refresh()
        future = _EXECUTOR.submit(operation, *args)
        future.add_done_callback(self._deliver)

    def show_notices(self):
        """Muestra procedencia y documentos offline como texto seleccionable, sin ejecutar HTML ni abrir enlaces."""
        if self._notices_dialog is not None:
            self._notices_dialog.raise_()
            self._notices_dialog.activateWindow()
            return
        try:
            text = data_packages.notices(connection.get_connection())
        except (OSError, ValueError, KeyError, TypeError) as error:
            text = f"No se pueden verificar los avisos de la edición seleccionada.\n{error}"
        dialog = QDialog(self)
        dialog.setWindowTitle("Fuentes y licencias de los datos")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.resize(720, 480)
        layout = QVBoxLayout(dialog)
        contents = QPlainTextEdit()
        contents.setReadOnly(True)
        contents.setAccessibleName("Procedencia, atribuciones y licencias de los datos")
        contents.setPlainText(text)
        layout.addWidget(contents)
        buttons = QDialogButtonBox()
        close = buttons.addButton("Cerrar", QDialogButtonBox.ButtonRole.RejectRole)
        close.setDefault(True)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.finished.connect(self._notices_closed)
        self._notices_dialog = dialog
        dialog.open()
        contents.setFocus()

    def _notices_closed(self, _result):
        """Libera la referencia del visor al cerrar para no acumular diálogos invisibles."""
        self._notices_dialog = None

    def _deliver(self, future):
        """Entrega errores sin tocar widgets desde el hilo de trabajo."""
        try:
            result, error = future.result(), ""
        except Exception as exc:
            logging.getLogger(__name__).exception("Error de operación de catálogos")
            result, error = None, str(exc)
        try:
            self.completed.emit(result, error)
        except RuntimeError:
            pass

    def check(self):
        """Consulta solo metadatos; nunca inicia una descarga de catálogos."""
        if self._busy:
            return
        self._packages = None
        self._global_manifest = None
        record_action("catálogos", "Comprobar actualizaciones")
        self._status.setText("Comprobando paquetes publicados…")
        self._submit(catalog_packages.check_manifest)

    def start_update(self):
        """Solicita permiso para instalar únicamente los paquetes diferentes."""
        if self._busy or not self._packages or not self._pending:
            return
        answer = QMessageBox.question(self, "Actualizar catálogos",
                                      "¿Descargar e instalar los paquetes disponibles?\n"
                                      "Tus objetos guardados y equipos se conservarán.\n"
                                      "Las ediciones anteriores se conservan y ocuparán espacio adicional.\n"
                                      "Una edición global incluye sus recursos obligatorios y opciones ya instaladas; no añade opcionales nuevos.")
        if answer != QMessageBox.StandardButton.Yes:
            record_action("catálogos", "Actualización cancelada por el usuario")
            return
        record_action("catálogos", "Actualización autorizada: " + ", ".join(self._pending))
        self._status.setText("Descargando, verificando e instalando catálogos…")
        if self._global_manifest:
            self._submit(data_packages.install, connection.DB_PATH, self._global_manifest)
        else:
            self._submit(catalog_packages.update_packages, connection.DB_PATH,
                         self._packages, tuple(self._pending))

    def start_restore(self):
        """Recupera únicamente el catálogo anterior, siempre con consentimiento y sin restaurar pass.db."""
        if self._busy or not status(connection.get_connection())["previous"]:
            return
        answer = QMessageBox.question(
            self, "Recuperar catálogo",
            "¿Activar la edición anterior del catálogo y sus recursos asociados?\n"
            "Se conservan tus equipos, ubicaciones, notas, regiones y sesiones, incluidas las posteriores a la actualización.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._restoring = True
        self._status.setText("Verificando y recuperando la edición anterior…")
        self._submit(restore_previous, connection.DB_PATH)

    def _finished(self, result, error):
        """Actualiza el estado solo después de terminar o confirmar la transacción."""
        self._busy = False
        self._progress.setRange(0, 1)
        self._progress.setValue(0 if error else 1)
        self._progress.hide()
        if error:
            self._packages = None
            self._global_manifest = None
            self._status.setText("⚠ No se pudo completar la operación. Los catálogos anteriores se conservan.")
            self._status.setToolTip(error)
        elif self._restoring:
            self._status.setText("Edición anterior recuperada; tus datos personales se conservan.")
            self._status.setToolTip("")
            self.catalogs_changed.emit()
        elif isinstance(result, dict):
            self._global_manifest = result if result.get("format") == 2 else None
            self._packages = result["packages"] if self._global_manifest else result
            self._status.setText("Comprobación completada.")
            self._status.setToolTip("")
        else:
            self._status.setText("Catálogos actualizados.")
            self._status.setToolTip("")
            self.catalogs_changed.emit()
        self._restoring = False
        self.refresh()
        record_action("catálogos", self._status.text())
        if error:
            record_action("catálogos", error, level=logging.ERROR)
