"""Sección de catálogos: versiones comprobables y operaciones fuera del hilo Qt."""
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from db import connection
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
        self._labels = {}
        for group in catalog_packages.GROUPS:
            label = QLabel()
            self._labels[group] = label
            layout.addWidget(label)
        self._status = QLabel("Comprueba si hay paquetes nuevos publicados por PASS.")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._check = QPushButton("Comprobar actualizaciones")
        self._check.clicked.connect(self.check)
        layout.addWidget(self._check)
        self._update = QPushButton("Actualizar")
        self._update.clicked.connect(self.start_update)
        layout.addWidget(self._update)
        layout.addStretch()
        self.completed.connect(self._finished)
        self.refresh()

    def refresh(self):
        """No confunde catálogos heredados sin metadatos con una versión vigente."""
        versions = catalog_packages.installed(connection.get_connection())
        self._pending = []
        for group, label in self._labels.items():
            version = versions[group]
            text = (f"{version['version']} ({version['date']})" if version
                    else "Versión sin identificar o catálogo no instalado")
            state = "Vigencia no comprobada"
            if self._packages:
                item = self._packages[group]
                current = version and version.get("sha256") == item["sha256"]
                state = "Actualizado" if current else "Paquete disponible"
                if not current:
                    self._pending.append(group)
            label.setText(f"{group.upper()}: {text} — {state}")
        self._check.setEnabled(not self._busy)
        self._update.setEnabled(not self._busy and bool(self._pending))

    def _submit(self, operation, *args):
        """Encola una sola operación y devuelve su resultado mediante señal Qt."""
        self._busy = True
        self.refresh()
        future = _EXECUTOR.submit(operation, *args)
        future.add_done_callback(self._deliver)

    def _deliver(self, future):
        """Entrega errores sin tocar widgets desde el hilo de trabajo."""
        try:
            result, error = future.result(), ""
        except Exception as exc:
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
            return
        self._status.setText("Descargando, verificando e instalando catálogos…")
        self._submit(catalog_packages.update_packages, connection.DB_PATH,
                     self._packages, tuple(self._pending))

    def _finished(self, result, error):
        """Actualiza el estado solo después de terminar o confirmar la transacción."""
        self._busy = False
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
