"""Sección de catálogos: versiones comprobables y operaciones fuera del hilo Qt."""
import logging
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from db import connection
from pass_logging import record_action
from planners import catalog_packages

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="catalog-packages")


class CatalogsPage(QWidget):
    """Mantiene las descargas independientes de Guardar y pide consentimiento al actualizar."""

    completed = pyqtSignal(object, str)
    catalogs_changed = pyqtSignal()

    def __init__(self, parent=None):
        """Construye una página sin red; conserva el trabajo al cerrar Configuración."""
        super().__init__(parent)
        self._packages = None
        self._busy = False
        layout = QVBoxLayout(self)
        self._table = QTableWidget(len(catalog_packages.GROUPS), 3)
        self._table.setHorizontalHeaderLabels(["Catálogo", "Versión", "Actualizado"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().hide()
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table)
        self._status = QLabel("Comprueba si hay paquetes nuevos publicados por PASS.")
        self._status.setWordWrap(True)
        buttons = QHBoxLayout()
        self._check = QPushButton("Comprobar actualizaciones")
        self._check.clicked.connect(self.check)
        buttons.addWidget(self._check)
        self._update = QPushButton("Actualizar")
        self._update.clicked.connect(self.start_update)
        buttons.addWidget(self._update)
        layout.addLayout(buttons)
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)
        layout.addStretch()
        self.completed.connect(self._finished)
        self.refresh()

    def refresh(self):
        """No confunde catálogos heredados sin metadatos con una versión vigente."""
        versions = catalog_packages.installed(connection.get_connection())
        self._pending = []
        for row, group in enumerate(catalog_packages.GROUPS):
            version = versions[group]
            text = version["version"] if version else "Versión sin identificar o catálogo no instalado"
            state = "Vigencia no comprobada"
            if self._packages:
                item = self._packages[group]
                current = version and version.get("sha256") == item["sha256"]
                state = "Actualizado" if current else "Paquete disponible"
                if not current:
                    self._pending.append(group)
            for column, value in enumerate((group.upper(), text, version["date"] if version else "—")):
                item = QTableWidgetItem(value)
                item.setToolTip(state)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, column, item)
        self._check.setEnabled(not self._busy)
        self._update.setEnabled(not self._busy and bool(self._pending))

    def _submit(self, operation, *args):
        """Encola una sola operación y devuelve su resultado mediante señal Qt."""
        self._busy = True
        self._progress.setRange(0, 0)
        self.refresh()
        future = _EXECUTOR.submit(operation, *args)
        future.add_done_callback(self._deliver)

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
        record_action("catálogos", "Comprobar actualizaciones")
        self._status.setText("Comprobando paquetes publicados…")
        self._submit(catalog_packages.check_manifest)

    def start_update(self):
        """Solicita permiso para instalar únicamente los paquetes diferentes."""
        if self._busy or not self._packages or not self._pending:
            return
        answer = QMessageBox.question(self, "Actualizar catálogos",
                                      "¿Descargar e instalar los paquetes disponibles?\n"
                                      "Tus objetos guardados y equipos se conservarán.")
        if answer != QMessageBox.StandardButton.Yes:
            record_action("catálogos", "Actualización cancelada por el usuario")
            return
        record_action("catálogos", "Actualización autorizada: " + ", ".join(self._pending))
        self._status.setText("Descargando, verificando e instalando catálogos…")
        self._submit(catalog_packages.update_packages, connection.DB_PATH,
                     self._packages, tuple(self._pending))

    def _finished(self, result, error):
        """Actualiza el estado solo después de terminar o confirmar la transacción."""
        self._busy = False
        self._progress.setRange(0, 1)
        self._progress.setValue(0 if error else 1)
        if error:
            self._packages = None
            self._status.setText("No se pudo completar la operación. "
                                 "Los catálogos anteriores se conservan. " + error)
        elif isinstance(result, dict):
            self._packages = result
            self._status.setText("Comprobación completada.")
        else:
            self._status.setText("Catálogos actualizados.")
            self.catalogs_changed.emit()
        self.refresh()
        record_action("catálogos", self._status.text())
