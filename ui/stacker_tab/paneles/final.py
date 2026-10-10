"""Paso 5 «Final»: resumen del apilado y apertura del FITS en SirIL."""

import subprocess
from pathlib import Path

from PyQt6.QtCore import QEvent, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QDesktopServices,
    QImage,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from db.settings import get_setting
from stacks.siril_finder import SETTINGS_KEY, find_siril, find_siril_gui

from ..pasos_common import (
    _pista,
    _preview_fits,
    _titulo,
)


class PanelFinal(QWidget):
    """Paso 5: resumen del flujo, salidas y acción de empezar de nuevo."""

    reiniciar = pyqtSignal()  # «Empezar de nuevo»

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta resumen, lista de salidas y los dos botones de cierre."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(_titulo("Final"))
        self._resumen = QLabel("Todavía no hay apilados.")
        self._resumen.setObjectName("PanelTitle")
        self._resumen.setWordWrap(True)
        layout.addWidget(self._resumen)

        self._salidas = QListWidget()
        self._salidas.setMaximumHeight(70)
        self._salidas.currentItemChanged.connect(self._seleccionar_salida)
        layout.addWidget(self._salidas)
        self._preview_label = QLabel("El apilado se mostrará aquí.")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumHeight(200)
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preview_label.installEventFilter(self)
        layout.addWidget(self._preview_label, 1)
        self._imagen: QImage | None = None

        fila = QHBoxLayout()
        self._abrir_boton = QPushButton("Abrir carpeta de apilados")
        self._abrir_boton.clicked.connect(self._abrir)
        self._abrir_boton.setEnabled(False)
        self._reiniciar_boton = QPushButton("Empezar de nuevo")
        self._reiniciar_boton.clicked.connect(self.reiniciar)
        fila.addWidget(self._abrir_boton)
        self._siril_boton = QPushButton("Abrir en SirIL")
        self._siril_boton.setEnabled(False)
        self._siril_boton.clicked.connect(self._abrir_siril)
        fila.addWidget(self._siril_boton)
        fila.addWidget(self._reiniciar_boton)
        fila.addStretch(1)
        layout.addLayout(fila)

        layout.addWidget(_pista(
            "Si algo salió raro, revisa el log de abajo: SirIL escribe ahí "
            "lo que hace (y lo que le falta)."
        ))
        self._carpeta: Path | None = None

    def bloquear(self, bloqueado: bool) -> None:
        """Mientras corre una tarea no se puede reiniciar el asistente."""
        self._reiniciar_boton.setEnabled(not bloqueado)

    def limpiar(self) -> None:
        """Borra resumen y salidas (reinicio del asistente)."""
        self._resumen.setText("Todavía no hay apilados.")
        self._salidas.clear()
        self._imagen = None
        self._preview_label.setText("El apilado se mostrará aquí.")
        self._carpeta = None
        self._abrir_boton.setEnabled(False)
        self._siril_boton.setEnabled(False)

    def mostrar(
        self,
        *,
        nombre: str,
        sesiones: int,
        registrados: int,
        descartados: int,
        salidas: list[Path],
    ) -> None:
        """Pinta el resumen del apilado terminado y sus imágenes."""
        self._resumen.setText(
            f"«{nombre}» listo: {sesiones} sesiones · {registrados} frames "
            f"registrados · {descartados} descartados por ti · "
            f"{len(salidas)} imagen(es) generada(s)."
        )
        self._salidas.clear()
        for ruta in salidas:
            item = QListWidgetItem(ruta.name)
            item.setToolTip(str(ruta))
            self._salidas.addItem(item)
        if salidas:
            self._salidas.setCurrentRow(len(salidas) - 1)
        else:
            self._seleccionar_salida(None)
        self._carpeta = salidas[0].parent if salidas else None
        self._abrir_boton.setEnabled(self._carpeta is not None)
        self._siril_boton.setEnabled(bool(salidas))

    def _seleccionar_salida(self, item, _anterior=None) -> None:
        """Muestra la salida elegida, sin cambiar datos ni archivos FITS."""
        self._imagen = _preview_fits(Path(item.toolTip())) if item else None
        if self._imagen is None:
            self._preview_label.setText("Vista previa no disponible; abre el FITS desde la carpeta.")
        else:
            self._mostrar_imagen()

    def eventFilter(self, objeto, evento):
        """Reescala la vista previa al cambiar el tamaño de la ventana."""
        if objeto is self._preview_label and evento.type() == QEvent.Type.Resize:
            self._mostrar_imagen()
        return super().eventFilter(objeto, evento)

    def _mostrar_imagen(self) -> None:
        """Ajusta la miniatura FITS al espacio disponible sin modificar el archivo."""
        if self._imagen is not None:
            self._preview_label.setPixmap(QPixmap.fromImage(self._imagen).scaled(
                self._preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def _abrir(self) -> None:
        """Abre la carpeta de salida en el gestor de archivos del sistema."""
        if self._carpeta is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._carpeta)))

    def _abrir_siril(self) -> None:
        """Abre el FITS seleccionado en la aplicación gráfica de SirIL."""
        item = self._salidas.currentItem() or self._salidas.item(self._salidas.count() - 1)
        if item is None:
            return
        ruta = Path(item.toolTip())
        cli = find_siril(get_setting(SETTINGS_KEY) or None)
        candidato = Path(cli).with_name("siril.exe") if cli else None
        ejecutable = candidato if candidato and candidato.is_file() else find_siril_gui()
        if not ejecutable or not ruta.is_file():
            QMessageBox.warning(self, "SirIL", "No se encontró SirIL gráfico o el FITS ya no existe.")
            return
        try:
            subprocess.Popen([str(ejecutable), str(ruta)])
        except OSError as exc:
            QMessageBox.warning(self, "SirIL", f"No se pudo abrir el FITS: {exc}")
