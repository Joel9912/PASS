"""Paso 2 «Calibrar»: material disponible por sesión y acceso al calibrado."""


from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stacks.session_parser import Session

from ..pasos_common import (
    _material,
    _pista,
    _tabla,
    _titulo,
    clave_sesion,
)


class PanelCalibrar(QWidget):
    """Paso 2: opciones de calibración (SirIL) y estado por sesión."""

    calibrar = pyqtSignal()  # «Calibrar todas»

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta opciones, botón de calibrado y tabla de material/estado/avisos."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(_titulo("Calibración"))
        layout.addWidget(_pista(
            "SirIL calibra cada sesión SIN debayerizar (crudo), con sus "
            "másters (o los de la carpeta global de calibrado) y escribe "
            "SOLO en data/working/calibrados/<sesión>/. Si faltan flats se "
            "usa bias+dark y se avisa. El debayer lo decides al apilar."
        ))

        fila = QHBoxLayout()
        self._opt = QCheckBox("-opt=exp")
        self._opt.setToolTip(
            "Optimiza la sustracción de dark por exposición (solo con bias+dark)."
        )
        self._cc = QCheckBox("-cc=dark")
        self._cc.setToolTip("Corrección cosmética con el dark.")
        fila.addWidget(self._opt)
        fila.addWidget(self._cc)
        fila.addStretch(1)
        self._boton = QPushButton("Calibrar todas")
        self._boton.setObjectName("PrimaryButton")
        self._boton.clicked.connect(self.calibrar)
        fila.addWidget(self._boton)
        layout.addLayout(fila)

        self._tabla = _tabla(["Sesión", "Material", "Másters", "Estado", "Avisos"])
        layout.addWidget(self._tabla, 1)

    def bloquear(self, bloqueado: bool) -> None:
        """Deshabilita el botón mientras corre una tarea en el hilo."""
        self._boton.setEnabled(not bloqueado)
        self._opt.setEnabled(not bloqueado)
        self._cc.setEnabled(not bloqueado)

    def opciones(self) -> dict:
        """Opciones elegidas (``opt``/``cc``) para ``calibrate_session``."""
        return {
            "opt": self._opt.isChecked(),
            "cc": self._cc.isChecked(),
        }

    def mostrar_pendientes(self, sesiones: list[Session], calibradas: set[str]) -> None:
        """Estado inicial: material, másters y qué sesiones ya están en la BD.

        ``calibradas`` contiene **rutas de origen**: el nombre no basta para
        distinguir dos sesiones homónimas de raíces distintas.
        """
        self._tabla.setRowCount(0)
        for sesion in sesiones:
            self._poner_fila(
                sesion.path.name,
                _material(sesion),
                ", ".join(sorted(sesion.masters)) or "—",
                "Calibrada ✓" if clave_sesion(sesion) in calibradas
                else "Pendiente",
                "",
            )

    def mostrar_resultados(self, resultados: list, avisos: dict[str, list[str]]) -> None:
        """Estado tras la corrida: hecha/error por sesión y sus avisos.

        ``avisos`` está indexado con :func:`clave_sesion`: dos sesiones con el
        mismo nombre no pueden quedarse con los avisos la una de la otra.
        """
        self._tabla.setRowCount(0)
        for resultado in resultados:
            sesion = resultado.session
            texto_avisos = " · ".join(avisos.get(clave_sesion(sesion), [])) or "—"
            self._poner_fila(
                sesion.path.name,
                _material(sesion),
                ", ".join(sorted(sesion.masters)) or "—",
                "Calibrada ✓",
                texto_avisos,
            )

    def _poner_fila(self, *celdas: str) -> None:
        """Añade una fila de estado (usada por los dos pintados)."""
        fila = self._tabla.rowCount()
        self._tabla.insertRow(fila)
        for columna, texto in enumerate(celdas):
            self._tabla.setItem(fila, columna, QTableWidgetItem(texto))
