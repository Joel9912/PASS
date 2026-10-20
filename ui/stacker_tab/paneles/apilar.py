"""Paso 4 «Apilar»: integración, norma, ponderación, rechazo y salida."""

import shlex
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from stacks.estimates import ProcessingEstimate, format_estimate
from stacks.stacker import (
    INTEGRACIONES,
    NORMS,
    PONDERACIONES,
    RECHAZOS,
    StackOptions,
)

from ..pasos_common import (
    _pista,
    _spin,
    _titulo,
)


class PanelApilar(QWidget):
    """Paso 4: registro final (drizzle/debayer), opciones de ``stack`` y salidas."""

    apilar = pyqtSignal()  # «Apilar»
    estimacion_cambiada = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta nombre, registro final, opciones de stack, botón y salidas."""
        super().__init__(parent)
        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        exterior.addWidget(self._scroll)
        contenido = QWidget()
        self._scroll.setWidget(contenido)
        layout = QVBoxLayout(contenido)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        cabecera = QHBoxLayout()
        cabecera.addWidget(_titulo("Apilado"))
        cabecera.addStretch(1)
        self._boton = QPushButton("Apilar")
        self._boton.setObjectName("PrimaryButton")
        self._boton.clicked.connect(self.apilar)
        cabecera.addWidget(self._boton)
        layout.addLayout(cabecera)
        layout.addWidget(_pista(
            "Configura el registro final y el apilado en SirIL. Solo se usan "
            "los frames aceptados; los originales no se modifican."
        ))

        nombre_fila = QHBoxLayout()
        nombre_fila.addWidget(QLabel("Nombre:"))
        self._nombre = QLineEdit()
        self._nombre.setPlaceholderText("Vacío: result_<tiempo de integración>s")
        nombre_fila.addWidget(self._nombre, 1)
        layout.addLayout(nombre_fila)

        def bloque(titulo: str, alto: int = 90) -> tuple[QGroupBox, QVBoxLayout]:
            """Agrupa controles como la referencia sin cambiar sus opciones."""
            caja = QGroupBox(titulo)
            caja.setMinimumHeight(alto)
            caja.setStyleSheet(
                "QGroupBox { border: 1px solid #26374f; border-radius: 6px; "
                "margin-top: 14px; background: #0e1625; } "
                "QGroupBox::title { color: #58a6ff; subcontrol-origin: margin; "
                "left: 12px; padding: 0 4px; }"
            )
            contenido = QVBoxLayout(caja)
            contenido.setContentsMargins(14, 10, 14, 10)
            contenido.setSpacing(8)
            layout.addWidget(caja)
            return caja, contenido

        _, metodo = bloque("1. Método de integración y ponderación", 100)
        fila_metodo = QHBoxLayout()
        fila_metodo.addWidget(QLabel("Método de apilado:"))
        self._integracion = QComboBox()
        nombres_metodo = {
            "mean": "Promedio con rechazo (mean)", "med": "Mediana (med)",
            "sum": "Suma (sum)", "min": "Mínimo (min)", "max": "Máximo (max)",
        }
        for modo in INTEGRACIONES:
            self._integracion.addItem(nombres_metodo[modo], modo)
        self._integracion.setCurrentIndex(INTEGRACIONES.index("mean"))
        fila_metodo.addWidget(self._integracion, 1)
        fila_metodo.addWidget(QLabel("Ponderación de tomas:"))
        self._ponderacion = QComboBox()
        self._ponderacion.addItem("(ninguna)", None)
        nombres_peso = {
            "noise": "Ruido de fondo (noise)", "wfwhm": "FWHM ponderado (wfwhm)",
            "nbstars": "Número de estrellas (nbstars)",
            "nbstack": "Número de integraciones (nbstack)",
        }
        for modo in PONDERACIONES:
            self._ponderacion.addItem(nombres_peso[modo], modo)
        fila_metodo.addWidget(self._ponderacion, 1)
        metodo.addLayout(fila_metodo)
        fila_norm = QHBoxLayout()
        fila_norm.addWidget(QLabel("Normalización de entrada:"))
        self._norm = QComboBox()
        self._norm.addItem("(la de SirIL)", None)
        nombres_norm = {
            "add": "Aditiva (add)", "addscale": "Aditiva + escala (addscale)",
            "mul": "Multiplicativa (mul)",
            "mulscale": "Multiplicativa + escala (mulscale)",
            "nonorm": "Ninguna (nonorm)",
        }
        for modo in (*NORMS, "nonorm"):
            self._norm.addItem(nombres_norm[modo], modo)
        fila_norm.addWidget(self._norm, 1)
        fila_norm.addWidget(QLabel("Modo de encuadre:"))
        self._framing = QComboBox()
        for texto, modo in (
            ("current — referencia", "current"),
            ("min — área común", "min"),
            ("max — área completa", "max"),
            ("cog — centro de gravedad", "cog"),
        ):
            self._framing.addItem(texto, modo)
        self._framing.setCurrentIndex(1)
        fila_norm.addWidget(self._framing, 1)
        metodo.addLayout(fila_norm)

        _, rechazo_bloque = bloque("2. Rechazo de píxeles", 90)
        fila_rechazo = QHBoxLayout()
        fila_rechazo.addWidget(QLabel("Algoritmo:"))
        self._rechazo = QComboBox()
        nombres_rechazo = {
            "none": "Sin rechazo", "percentile": "Percentile clipping",
            "sigma": "Sigma clipping", "median": "Median clipping",
            "winsorized": "Winsorized sigma clipping",
            "linear": "Linear fit clipping", "generalized": "Generalized ESD",
            "mad": "MAD clipping",
        }
        for modo in RECHAZOS:
            self._rechazo.addItem(nombres_rechazo[modo], modo)
        self._rechazo.setCurrentIndex(RECHAZOS.index("winsorized"))
        fila_rechazo.addWidget(self._rechazo, 1)
        fila_rechazo.addWidget(QLabel("Sigma bajo:"))
        self._sigma_low = _spin(0.1, 20.0, 3.0, paso=0.5, decimales=1)
        fila_rechazo.addWidget(self._sigma_low, 1)
        fila_rechazo.addWidget(QLabel("Sigma alto:"))
        self._sigma_high = _spin(0.1, 20.0, 3.0, paso=0.5, decimales=1)
        fila_rechazo.addWidget(self._sigma_high, 1)
        rechazo_bloque.addLayout(fila_rechazo)
        fila_mapas = QHBoxLayout()
        self._rejmaps = QCheckBox("Generar mapas de rechazo FITS")
        self._rejmaps.setToolTip("SirIL: -rejmaps genera dos mapas; -rejmap uno fusionado.")
        fila_mapas.addWidget(self._rejmaps)
        self._merge_rejmaps = QCheckBox("Fusionar alto y bajo")
        self._merge_rejmaps.setChecked(True)
        fila_mapas.addWidget(self._merge_rejmaps)
        fila_mapas.addStretch(1)
        rechazo_bloque.addLayout(fila_mapas)

        _, drizzle_bloque = bloque("3. Registro final y Bayer Drizzle", 90)

        registro_fila = QHBoxLayout()
        self._drizzle = QCheckBox("Bayer Drizzle")
        self._drizzle.setToolTip(
            "seqapplyreg -drizzle con la escala elegida. "
            "SirIL debayeriza solo al drizzlezar: sin drizzle, los CFA se "
            "debayerizan antes de registrar."
        )
        self._scale = QComboBox()
        for escala in (1.0, 1.4, 1.6, 2.0):
            self._scale.addItem(f"{escala:.1f}×", escala)
        self._pixfrac = _spin(0.1, 1.2, 1.0, paso=0.05, decimales=2)
        self._pixfrac.setToolTip("Pixfrac de drizzle (fracción del píxel de salida).")
        self._kernel = QComboBox()
        # Núcleos que documenta `help seqapplyreg` de SirIL 1.4.4.
        for nucleo in ("square", "gaussian", "point", "turbo", "lanczos2", "lanczos3"):
            self._kernel.addItem(nucleo)
        registro_fila.addWidget(self._drizzle)
        registro_fila.addWidget(QLabel("Escala:"))
        registro_fila.addWidget(self._scale, 1)
        registro_fila.addWidget(QLabel("Pixfrac:"))
        registro_fila.addWidget(self._pixfrac, 1)
        registro_fila.addWidget(QLabel("Kernel:"))
        registro_fila.addWidget(self._kernel, 1)
        drizzle_bloque.addLayout(registro_fila)
        flat_fila = QHBoxLayout()
        self._flat_drizzle = QCheckBox("Ponderar gotas por máster flat (-flat)")
        self._flat_drizzle.setToolTip(
            "Selecciona explícitamente un máster flat aplicable a todas las "
            "tomas; SirIL lo usa para ponderar gotas, no para recalibrar."
        )
        flat_fila.addWidget(self._flat_drizzle)
        self._ruta_flat = QLineEdit()
        self._ruta_flat.setPlaceholderText("Elige un máster flat FITS común a las tomas")
        flat_fila.addWidget(self._ruta_flat, 1)
        buscar_flat = QPushButton("Elegir…")
        buscar_flat.clicked.connect(self._elegir_flat)
        flat_fila.addWidget(buscar_flat)
        drizzle_bloque.addLayout(flat_fila)

        _, salida_bloque = bloque("4. Opciones de guardado del máster", 78)
        salida_fila = QHBoxLayout()
        self._bit32 = QCheckBox("FITS de 32 bits (-32b)")
        self._bit32.setChecked(True)
        salida_fila.addWidget(self._bit32)
        self._output_norm = QCheckBox("Normalizar salida [0, 1] (-output_norm)")
        salida_fila.addWidget(self._output_norm)
        self._rgb_equal = QCheckBox("Igualar fondo RGB (-rgb_equal)")
        salida_fila.addWidget(self._rgb_equal)
        salida_fila.addStretch(1)
        salida_bloque.addLayout(salida_fila)
        salida_fila = QHBoxLayout()
        self._fastnorm = QCheckBox("Normalización rápida de entrada (-fastnorm)")
        self._fastnorm.setToolTip("Solo con mean/med; no normaliza la salida.")
        salida_fila.addWidget(self._fastnorm)
        salida_fila.addStretch(1)
        salida_bloque.addLayout(salida_fila)
        salida_bloque.addWidget(_pista("Salida: data/working/apilados/<nombre>/."))

        extra_fila = QHBoxLayout()
        extra_fila.addWidget(QLabel("Argumentos extra:"))
        self._extra = QLineEdit()
        self._extra.setPlaceholderText("otros argumentos de stack, separados por espacios")
        self._extra.setToolTip("Avanzado: consulta help stack de tu versión de SirIL.")
        extra_fila.addWidget(self._extra, 1)
        layout.addLayout(extra_fila)

        _, guia_bloque = bloque("Guía de parámetros", 62)
        self._guia = _pista("")
        self._conteo_aceptados = 0
        guia_bloque.addWidget(self._guia)
        self._estimacion = _pista("Estimación pendiente de la auditoría y sus cabeceras.")
        self._estimacion.setAccessibleName("Estimación de espacio y tiempo del apilado")
        self._estimacion.setToolTip(
            "Aproximación con dimensiones de cabecera, registro/debayer a 32 bits, másters, mapas y exportación. "
            "No incluye calibrados ya existentes, temporales internos ni reserva espacio. El recorte o expansión "
            "del encuadre y la compresión de SirIL pueden cambiar el volumen. El tiempo usa una corrida completa "
            "comparable de esta apertura de PASS; hardware, disco, carga y drizzle afectan al resultado. "
            "Una recuperación de registro no sirve de muestra para una corrida completa."
        )
        guia_bloque.addWidget(self._estimacion)
        self._integracion.currentIndexChanged.connect(self._actualizar_guia)
        self._rechazo.currentIndexChanged.connect(self._actualizar_guia)
        self._drizzle.toggled.connect(self._actualizar_guia)
        self._scale.currentIndexChanged.connect(self._actualizar_guia)
        self._rejmaps.toggled.connect(self._merge_rejmaps.setEnabled)
        self._merge_rejmaps.setEnabled(False)
        self._drizzle.toggled.connect(self._scale.setEnabled)
        self._drizzle.toggled.connect(self._pixfrac.setEnabled)
        self._drizzle.toggled.connect(self._kernel.setEnabled)
        self._drizzle.toggled.connect(self._flat_drizzle.setEnabled)
        self._drizzle.toggled.connect(self._ruta_flat.setEnabled)
        self._drizzle.toggled.connect(buscar_flat.setEnabled)
        for control in (self._scale, self._pixfrac, self._kernel,
                        self._flat_drizzle, self._ruta_flat, buscar_flat):
            control.setEnabled(False)
        self._actualizar_guia()
        for control in (self._integracion, self._ponderacion, self._norm, self._framing,
                        self._rechazo, self._scale, self._kernel):
            control.currentIndexChanged.connect(self.estimacion_cambiada)
        for control in (self._drizzle, self._flat_drizzle, self._bit32, self._output_norm,
                        self._rgb_equal, self._fastnorm, self._rejmaps, self._merge_rejmaps):
            control.toggled.connect(self.estimacion_cambiada)
        for control in (self._sigma_low, self._sigma_high, self._pixfrac):
            control.valueChanged.connect(self.estimacion_cambiada)
        self._extra.textChanged.connect(self.estimacion_cambiada)

        self._salidas_titulo = QLabel("Salidas:")
        self._salidas_titulo.hide()
        layout.addWidget(self._salidas_titulo)
        self._salidas = QListWidget()
        self._salidas.setMaximumHeight(60)
        self._salidas.hide()
        layout.addWidget(self._salidas)

        self._siril_aviso = _pista("")
        layout.addWidget(self._siril_aviso)
        layout.addStretch(1)

    def _actualizar_guia(self) -> None:
        """Explica las dependencias del guion de SirIL sin imponer valores."""
        promedio = self._integracion.currentData() == "mean"
        self._guia.setText(
            f"{self._conteo_aceptados} tomas seleccionadas en Auditoría. "
            + ("Mean admite rechazo y ponderación. " if promedio else
             "Esta integración no aplica rechazo ni ponderación. ")
            + (f"Drizzle ×{self._scale.currentData():g} se aplica en el registro final. "
               if self._drizzle.isChecked() else
               "Sin drizzle se mantiene la escala del registro. ")
            + ("Con pocas tomas, revisa el rechazo antes de ejecutar. "
               if 0 < self._conteo_aceptados < 8 and promedio else "")
            + "Comprueba el log antes de apilar."
        )

    def actualizar_conteo(self, n: int) -> None:
        """Refleja el número real de casillas marcadas, nunca uno ficticio."""
        self._conteo_aceptados = n
        self._actualizar_guia()

    def mostrar_estimacion(self, estimate: ProcessingEstimate | None, message: str = "") -> None:
        """Presenta una previsión sin tocar opciones, casillas ni permisos de ejecución."""
        text = format_estimate(estimate) if estimate is not None else message
        self._estimacion.setText(text)
        self._estimacion.setAccessibleDescription(text + " " + self._estimacion.toolTip())

    def _elegir_flat(self) -> None:
        """Permite elegir explícitamente el flat de drizzle, sin tocar los originales."""
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Máster flat para drizzle", "", "FITS (*.fit *.fits *.fts)"
        )
        if ruta:
            self._ruta_flat.setText(ruta)

    def bloquear(self, bloqueado: bool) -> None:
        """Deshabilita el botón mientras corre una tarea en el hilo."""
        self._boton.setEnabled(not bloqueado)

    def limpiar(self) -> None:
        """Vacía las salidas de la corrida anterior (reinicio del asistente)."""
        self._salidas.clear()
        self._salidas.hide()
        self._salidas_titulo.hide()
        self.mostrar_estimacion(None, "Estimación pendiente de la auditoría y sus cabeceras.")

    def nombre(self) -> str:
        """Nombre escrito por el usuario, o vacío para generar uno con la exposición."""
        nombre = self._nombre.text().strip()
        if "/" in nombre or "\\" in nombre or nombre in (".", ".."):
            raise ValueError("El nombre del apilado no puede tener barras ni ser «.»/«..».")
        return nombre

    def opciones_registro(self) -> dict:
        """Opciones del registro final (drizzle y sus parámetros) para ``register_pool``."""
        flat = None
        if self._flat_drizzle.isChecked():
            flat = Path(self._ruta_flat.text().strip())
            if not self._drizzle.isChecked() or not flat.is_file():
                raise ValueError("El flat de drizzle requiere drizzle y un FITS existente.")
        return {
            "drizzle": self._drizzle.isChecked(),
            "scale": self._scale.currentData(),
            "framing": self._framing.currentData(),
            "pixfrac": self._pixfrac.value(),
            "kernel": self._kernel.currentText(),
            "flat": flat,
        }

    def opciones(self) -> StackOptions:
        """Opciones del formulario; valida ya mismo la combinación contra SirIL."""
        try:
            extra = shlex.split(self._extra.text())
        except ValueError as exc:
            raise ValueError(f"Argumentos extra: {exc}") from exc
        opciones = StackOptions(
            integration=self._integracion.currentData(),
            rejection=self._rechazo.currentData(),
            sigma_low=self._sigma_low.value(),
            sigma_high=self._sigma_high.value(),
            weighting=self._ponderacion.currentData(),
            norm=self._norm.currentData(),
            fastnorm=self._fastnorm.isChecked(),
            bit32=self._bit32.isChecked(),
            rejmaps=self._rejmaps.isChecked(),
            merge_rejmaps=self._merge_rejmaps.isChecked(),
            output_norm=self._output_norm.isChecked(),
            rgb_equal=self._rgb_equal.isChecked(),
            extra_args=extra,
        )
        opciones.to_siril_args()  # falla aquí, no a mitad de la corrida
        return opciones

    def mostrar_salidas(self, salidas: list[Path]) -> None:
        """Lista los FITS generados (la ruta completa va en la pista del ratón)."""
        self._salidas.clear()
        self._salidas.setVisible(bool(salidas))
        self._salidas_titulo.setVisible(bool(salidas))
        for ruta in salidas:
            item = QListWidgetItem(ruta.name)
            item.setToolTip(str(ruta))
            self._salidas.addItem(item)

    def avisar_siril(self, falta: bool) -> None:
        """Aviso persistente de que SirIL no está localizado (si no lo está)."""
        self._siril_aviso.setText(
            "SirIL no está en el PATH: al ejecutar te pediré que elijas su ruta."
            if falta
            else ""
        )
