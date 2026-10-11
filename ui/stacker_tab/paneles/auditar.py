"""Paso 3 «Auditar»: pesos, tabla de métricas, gráfica y visor FITS."""

from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QImage,
    QPixmap,
    QResizeEvent,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stacks.frame_metrics import Evaluacion, FrameMetrics, Pesos, evaluar
from stacks.global_pool import nombre_sesion
from stacks.registration import Registro
from ui.style import PALETTE

from ..pasos_common import (
    COLOR_DESCARTE,
    _pista,
    _preview_fits,
    _spin,
    _spin_entero,
    _tabla,
    _titulo,
)


class PanelAuditar(QWidget):
    """Paso 3: registro rápido, puntuación dinámica y descarte de frames.

    La auditoría NO repite el registro para cambiar de criterio: las
    métricas crudas ya están en el ``.seq`` y «Actualizar» repuntúa con
    los pesos/umbral/σ del momento, reordena la tabla (de mayor a menor
    puntuación) y repinta los motivos de descarte. La decisión final son
    las casillas: nadie descarta nada sin el usuario. Aquí NO se decide
    drizzle ni debayer: eso es del paso Apilar.
    """

    auditar = pyqtSignal()    # «Registrar y auditar»
    descartar = pyqtSignal()  # «Descartar recomendados»

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta registro, pesos, tabla+miniatura, gráfica y resumen."""
        super().__init__(parent)
        self._cargando = False
        self._registro: Registro | None = None
        self._metricas: list[FrameMetrics] = []
        self._evaluaciones: dict[str, Evaluacion] = {}  # ruta → veredicto
        self._previews: dict[str, QImage] = {}          # caché de miniaturas
        self._preview_img: QImage | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(_titulo("Auditoría"))
        intro_fila = QHBoxLayout()
        intro_fila.addWidget(_pista(
            "Mide con SirIL y revisa los frames. Ajusta pesos y pulsa "
            "«Actualizar» para repuntuar; tú decides qué casillas desmarcar."
        ), 1)
        self._boton = QPushButton("Registrar y auditar")
        self._boton.setObjectName("PrimaryButton")
        self._boton.clicked.connect(self.auditar)
        intro_fila.addWidget(self._boton)
        layout.addLayout(intro_fila)

        controles_fila = QHBoxLayout()
        controles_fila.setSpacing(4)
        controles_fila.addWidget(QLabel("Pesos:"))
        self._pesos: dict[str, QSpinBox] = {}
        valores = Pesos()
        for etiqueta, atributo in (
            ("FWHM", "fwhm"),
            ("Redondez", "redondez"),
            ("Transparencia", "transparencia"),
            ("Fondo", "fondo"),
        ):
            spin = _spin_entero(0, 100, int(getattr(valores, atributo)))
            spin.setFixedWidth(96)
            spin.setToolTip(
                f"Peso de {etiqueta.lower()} en la puntuación 0–100 "
                "(0 = no puntúa ni corta). "
                + (
                    "Transparencia es un indicador relativo derivado del fondo, "
                    "no una medición directa de transmisión atmosférica."
                    if atributo == "transparencia" else ""
                )
            )
            self._pesos[atributo] = spin
            controles_fila.addWidget(QLabel(etiqueta))
            controles_fila.addWidget(spin)
        controles_fila.addStretch(1)
        self._umbral = _spin(0.0, 100.0, 80.0, paso=5.0, decimales=0)
        self._umbral.setFixedWidth(96)
        self._umbral.setToolTip(
            "Puntuación mínima: por debajo, el frame se recomienda "
            "descartar (motivo «Puntuación»)."
        )
        controles_fila.addWidget(QLabel("Mín.:"))
        controles_fila.addWidget(self._umbral)
        self._sigma = _spin(0.5, 10.0, 3.0, paso=0.5, decimales=1)
        self._sigma.setFixedWidth(96)
        self._sigma.setToolTip(
            "Sigma de los cortes por métrica (mediana + σ×MAD, lado malo)."
        )
        controles_fila.addWidget(QLabel("σ:"))
        controles_fila.addWidget(self._sigma)
        self._boton_actualizar = QPushButton("Actualizar")
        self._boton_actualizar.setToolTip(
            "Repuntúa y reordena con los pesos/umbral/σ actuales, sin "
            "volver a registrar."
        )
        self._boton_actualizar.clicked.connect(self._al_actualizar)
        controles_fila.addWidget(self._boton_actualizar)
        self._boton_descartar = QPushButton("Descartar sugeridos")
        self._boton_descartar.setToolTip("Desmarca los frames recomendados para descartar.")
        self._boton_descartar.clicked.connect(self.descartar)
        controles_fila.addWidget(self._boton_descartar)
        layout.addLayout(controles_fila)

        self._tabla = _tabla([
            "Usar", "Frame", "Sesión", "FWHM", "Redondez", "Fondo",
            "Transparencia", "Puntuación", "Descartada",
        ], columna_ancha=1)
        # Frame tiene un ancho fijo suficiente para los nombres habituales;
        # el nombre completo permanece en el tooltip.
        cabecera = self._tabla.horizontalHeader()
        cabecera.setMinimumSectionSize(42)
        for columna, ancho in {
            0: 46, 1: 145, 2: 100, 3: 62, 4: 84, 5: 78,
            6: 112, 7: 88, 8: 100,
        }.items():
            cabecera.setSectionResizeMode(columna, QHeaderView.ResizeMode.Fixed)
            self._tabla.setColumnWidth(columna, ancho)
        # 815 px de columnas + scrollbar vertical (12) + marco (2): no
        # reservar un margen vacío que le quite anchura al visor FITS.
        self._tabla.setMinimumWidth(831)
        self._tabla.setMaximumWidth(831)
        self._tabla.verticalHeader().setDefaultSectionSize(31)
        self._tabla.horizontalHeaderItem(5).setToolTip(
            "Fondo en ADU equivalentes de 16 bits/s: el .seq de SirIL lo "
            "guarda normalizado (0–1). Se convierte con 65535 y se divide "
            "por la exposición para comparar sesiones de distintas duraciones."
        )
        self._tabla.itemChanged.connect(self._alCambiarItem)
        self._tabla.itemSelectionChanged.connect(self._alSeleccionar)

        preview = QWidget()
        preview.setMinimumWidth(300)
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_label = QLabel("Selecciona un frame para verlo.")
        # La miniatura llena el hueco entero (no su sizeHint): por eso
        # Explanding y el filtro de Resize, que la reescala cuando el
        # layout le da más o menos sitio.
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preview_label.setMinimumSize(200, 120)
        self._preview_label.installEventFilter(self)
        preview_layout.addWidget(self._preview_label, 1)
        self._preview_pie = QLabel("")
        self._preview_pie.setObjectName("HintLabel")
        self._preview_pie.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self._preview_pie)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._tabla)
        splitter.addWidget(preview)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([831, 719])
        splitter.setMinimumHeight(320)
        self._splitter = splitter
        layout.addWidget(splitter, 1)

        grafica_fila = QHBoxLayout()
        grafica_fila.addWidget(QLabel("Gráfica:"))
        self._metrica = QComboBox()
        for texto, atributo in (
            ("Puntuado", "weighted"),
            ("FWHM (px)", "fwhm"),
            ("Redondez", "roundness"),
            ("Transparencia", "transparency"),
            ("Fondo (ADU/s)", "background"),
        ):
            self._metrica.addItem(texto, atributo)
        self._metrica.currentIndexChanged.connect(self._pintar_grafica)
        grafica_fila.addWidget(self._metrica)
        grafica_fila.addStretch(1)
        layout.addLayout(grafica_fila)

        self._plot = pg.PlotWidget(enableMenu=False)
        # Conserva la gráfica alta cuando sobra sitio, pero cede altura a
        # la tabla/terminal en ventanas de 800 px con barra de título.
        self._plot.setMinimumHeight(110)
        self._plot.setMaximumHeight(130)
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        for eje in (self._plot.getPlotItem().getAxis("left"),
                    self._plot.getPlotItem().getAxis("bottom")):
            eje.setTextPen(QColor(PALETTE["textDim"]))
        self._curva = self._plot.plot(
            pen=pg.mkPen(QColor(PALETTE["accentLight"]), width=1.5),
            symbol="o",
            symbolSize=5,
            symbolBrush=pg.mkBrush(QColor(PALETTE["accentLight"])),
            symbolPen=pg.mkPen("transparent"),
        )
        self._descartados_plot = pg.ScatterPlotItem(
            pen=pg.mkPen(COLOR_DESCARTE),
            brush=pg.mkBrush(239, 68, 68, 140),
            size=9,
        )
        self._plot.addItem(self._descartados_plot)
        self._umbral_linea = pg.InfiniteLine(
            movable=False,
            pen=pg.mkPen(QColor(PALETTE["textDim"]), style=Qt.PenStyle.DashLine),
        )
        self._plot.addItem(self._umbral_linea)
        self._umbral_linea.hide()
        self._seleccion_plot = pg.ScatterPlotItem(
            size=13,
            pen=pg.mkPen(QColor("#ffffff"), width=2),
            brush=pg.mkBrush(0, 0, 0, 0),
        )
        self._plot.addItem(self._seleccion_plot)
        layout.addWidget(self._plot)

        self._resumen = _pista("Todavía no hay métricas: pulsa «Registrar y auditar».")
        layout.addWidget(self._resumen)

    def bloquear(self, bloqueado: bool) -> None:
        """Deshabilita sus botones y spins mientras corre una tarea en el hilo."""
        self._boton.setEnabled(not bloqueado)
        self._boton_actualizar.setEnabled(not bloqueado)
        self._boton_descartar.setEnabled(not bloqueado)
        for spin in self._pesos.values():
            spin.setEnabled(not bloqueado)
        self._umbral.setEnabled(not bloqueado)
        self._sigma.setEnabled(not bloqueado)

    def limpiar(self) -> None:
        """Borra métricas, veredictos, casillas, gráfica y miniatura."""
        self._cargando = True
        self._tabla.setRowCount(0)
        self._cargando = False
        self._registro = None
        self._metricas = []
        self._evaluaciones = {}
        self._previews.clear()
        self._limpiar_seleccion()
        self._curva.setData([], [])
        self._descartados_plot.setData([], [])
        self._umbral_linea.hide()
        self._resumen.setText(
            "Todavía no hay métricas: pulsa «Registrar y auditar»."
        )

    def pesos(self) -> Pesos:
        """Pesos del usuario para la puntuación; si suman 0, error claro."""
        pesos = Pesos(
            fwhm=float(self._pesos["fwhm"].value()),
            redondez=float(self._pesos["redondez"].value()),
            transparencia=float(self._pesos["transparencia"].value()),
            fondo=float(self._pesos["fondo"].value()),
        )
        if pesos.fwhm + pesos.redondez + pesos.transparencia + pesos.fondo <= 0:
            raise ValueError("Los pesos no pueden ser todos cero.")
        return pesos

    def sigma(self) -> float:
        """Sigma elegido para los cortes por métrica."""
        return self._sigma.value()

    def umbral(self) -> float:
        """Puntuación mínima para recomendar el descarte de un frame."""
        return self._umbral.value()

    def mostrar(self, registro: Registro, metricas: list[FrameMetrics]) -> None:
        """Guarda el registro y pinta la primera evaluación (una fila por frame)."""
        self._registro = registro
        self._metricas = list(metricas)
        self.actualizar()

    def actualizar(self) -> None:
        """Repuntúa con los pesos/umbral/σ actuales, ordena y repinta.

        Es el recálculo «barato»: no registra nada, solo relee las
        métricas que SirIL dejó en el ``.seq``. Conserva las casillas que
        el usuario hubiera desmarcado (van por índice de secuencia, no
        por fila). Falla claro si los pesos suman cero.
        """
        if self._registro is None:
            return
        evaluaciones = evaluar(
            self._metricas, self.pesos(), umbral=self.umbral(), sigma=self.sigma()
        )
        self._evaluaciones = {e.metricas.path: e for e in evaluaciones}
        # Filas de mayor a menor puntuación; lo que SirIL descartó (sin
        # métricas) va al final: no hay puntuación que darle.
        filas = sorted(
            (
                (
                    self._evaluaciones[str(ref.ruta)].metricas.weighted
                    if str(ref.ruta) in self._evaluaciones
                    else -1.0,
                    indice,
                    ref,
                )
                for indice, ref in enumerate(self._registro.frames, start=1)
            ),
            key=lambda fila: (-fila[0], fila[1]),
        )
        previos = set(self.aceptados()) if self._tabla.rowCount() else None
        self._cargando = True
        self._tabla.setRowCount(0)
        for _puntuacion, indice, ref in filas:
            ev = self._evaluaciones.get(str(ref.ruta))
            self._insertar_fila(indice, ref, ev, previos)
        self._cargando = False
        self._limpiar_seleccion()
        self._pintar_grafica()
        self._pintar_resumen()

    def _insertar_fila(
        self,
        indice: int,
        ref,
        ev: Evaluacion | None,
        previos: set[int] | None,
    ) -> None:
        """Una fila: casilla (con su índice de secuencia), métricas y motivo."""
        fila = self._tabla.rowCount()
        self._tabla.insertRow(fila)
        casilla = QTableWidgetItem()
        if ev is None:
            casilla.setFlags(casilla.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            casilla.setToolTip(
                "SirIL descartó este frame al registrar: no se puede apilar."
            )
        else:
            casilla.setFlags(casilla.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            marcada = previos is None or indice in previos
            casilla.setCheckState(
                Qt.CheckState.Checked if marcada else Qt.CheckState.Unchecked
            )
        # El índice de secuencia viaja en la propia fila: la tabla está
        # ordenada por puntuación, no por orden de registro.
        casilla.setData(Qt.ItemDataRole.UserRole, indice)
        casilla.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tabla.setItem(fila, 0, casilla)
        nombre = QTableWidgetItem(ref.ruta.name)
        nombre.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        nombre.setToolTip(str(ref.ruta))
        nombre.setData(Qt.ItemDataRole.UserRole, str(ref.ruta))
        self._tabla.setItem(fila, 1, nombre)
        # La sesión se guarda como ruta (identidad) y se pinta solo su nombre.
        sesion = QTableWidgetItem(nombre_sesion(ref))
        sesion.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        sesion.setToolTip(ref.sesion)
        self._tabla.setItem(fila, 2, sesion)
        celdas = (
            ["—"] * 5
            if ev is None
            else [
                f"{ev.metricas.fwhm:.2f}",
                f"{ev.metricas.roundness:.2f}",
                f"{ev.metricas.background:.1f}",
                f"{ev.metricas.transparency:.2f}",
                f"{ev.metricas.weighted:.1f}",
            ]
        )
        for columna, texto in enumerate(celdas, start=3):
            celda = QTableWidgetItem(texto)
            celda.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tabla.setItem(fila, columna, celda)
        if ev is None:
            motivo, color = "SirIL", QColor(COLOR_DESCARTE)
            ayuda = "SirIL descartó este frame al registrar: sin métricas."
        elif ev.descartada:
            motivo, color = f"Sí · {ev.motivo}", QColor(COLOR_DESCARTE)
            ayuda = f"Recomendado descartar por: {ev.motivo}. Tú decides (casilla)."
        else:
            motivo, color = "No", QColor(PALETTE["textDim"])
            ayuda = ""
        celda_motivo = QTableWidgetItem(motivo)
        celda_motivo.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        celda_motivo.setForeground(color)
        if ayuda:
            celda_motivo.setToolTip(ayuda)
        self._tabla.setItem(fila, 8, celda_motivo)

    def aceptados(self) -> list[int]:
        """Índices 1-based de la secuencia de los frames marcados (no de fila)."""
        indices = []
        for fila in range(self._tabla.rowCount()):
            item = self._tabla.item(fila, 0)
            if item is None or not item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                continue
            if item.checkState() == Qt.CheckState.Checked:
                indices.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return indices

    def descartar_recomendados(self) -> int:
        """Desmarca las casillas de los frames con veredicto «descartada»."""
        cambiados = 0
        self._cargando = True
        for fila in range(self._tabla.rowCount()):
            casilla = self._tabla.item(fila, 0)
            nombre = self._tabla.item(fila, 1)
            if casilla is None or nombre is None:
                continue
            ev = self._evaluaciones.get(nombre.data(Qt.ItemDataRole.UserRole))
            if (
                ev is not None
                and ev.descartada
                and casilla.flags() & Qt.ItemFlag.ItemIsUserCheckable
                and casilla.checkState() == Qt.CheckState.Checked
            ):
                casilla.setCheckState(Qt.CheckState.Unchecked)
                cambiados += 1
        self._cargando = False
        self._pintar_grafica()
        return cambiados

    def _al_actualizar(self) -> None:
        """Botón «Actualizar»: repuntúa al instante (sin registrar nada)."""
        try:
            self.actualizar()
        except ValueError as exc:
            self._resumen.setText(str(exc))

    def _alCambiarItem(self, _item: QTableWidgetItem) -> None:
        """Cambiaron casillas → repinta la gráfica (los rojos dependen de ellas)."""
        if not self._cargando:
            self._pintar_grafica()

    def _alSeleccionar(self) -> None:
        """Frame seleccionado → anillo en la gráfica + miniatura a la derecha."""
        if self._cargando:
            return
        fila = self._tabla.currentRow()
        casilla = self._tabla.item(fila, 0) if fila >= 0 else None
        nombre = self._tabla.item(fila, 1) if fila >= 0 else None
        if casilla is None or nombre is None:
            return
        ruta = nombre.data(Qt.ItemDataRole.UserRole)
        ev = self._evaluaciones.get(ruta)
        indice = int(casilla.data(Qt.ItemDataRole.UserRole))
        if ev is None:
            self._seleccion_plot.setData([], [])
            pie = f"{nombre.text()} · descartado por SirIL al registrar"
        else:
            atributo = self._metrica.currentData()
            self._seleccion_plot.setData(
                [indice], [float(getattr(ev.metricas, atributo))]
            )
            pie = f"{nombre.text()} · {ev.metricas.weighted:.1f} puntos"
            if ev.descartada:
                pie += f" · descartar: {ev.motivo}"
        self._mostrar_preview(Path(ruta), pie)

    def _mostrar_preview(self, ruta: Path, pie: str) -> None:
        """Carga (con caché de 3) y escala la miniatura del frame elegido."""
        qimg = self._previews.get(str(ruta))
        if qimg is None:
            qimg = _preview_fits(ruta)
            if qimg is not None:
                if len(self._previews) >= 3:
                    self._previews.clear()
                self._previews[str(ruta)] = qimg
        self._preview_img = qimg
        self._preview_pie.setText(pie)
        if qimg is None:
            self._preview_label.setText("Sin vista previa: ¿FITS ilegible?")
            return
        self._preview_label.setText("")
        self._escalar_preview()

    def _escalar_preview(self) -> None:
        """Escala la miniatura al hueco (se repite en cada resize del panel)."""
        if self._preview_img is None:
            return
        tam = self._preview_label.size()
        if tam.width() < 40 or tam.height() < 40:
            tam = self.size()
        self._preview_label.setPixmap(
            QPixmap.fromImage(self._preview_img).scaled(
                tam,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, evento: QResizeEvent) -> None:
        """Al cambiar el tamaño del panel, la miniatura se reescala."""
        super().resizeEvent(evento)
        self._escalar_preview()

    def eventFilter(self, objeto, evento) -> bool:
        """El label de la miniatura cambia de tamaño con el layout: reescalar ahí.

        Sin esto la imagen solo se reescalaba al redimensionar la ventana
        y se quedaba pequeña en el primer pintado (el sizeHint del label
        es el de la miniatura anterior).
        """
        if objeto is self._preview_label and evento.type() == QEvent.Type.Resize:
            self._escalar_preview()
        return super().eventFilter(objeto, evento)

    def _limpiar_seleccion(self) -> None:
        """Tras reordenar: sin anillo y la miniatura vuelve al texto inicial."""
        self._seleccion_plot.setData([], [])
        self._preview_img = None
        self._preview_label.setText("Selecciona un frame para verlo.")
        self._preview_pie.setText("")

    def _pintar_grafica(self) -> None:
        """Curva de la métrica elegida por frame; fuera de las casillas, en rojo.

        El eje x es el orden de registro (no el de la tabla ordenada):
        así se ve la evolución a lo largo de la noche.
        """
        atributo = self._metrica.currentData()
        self._plot.setLabel("left", self._metrica.currentText())
        puntos: list[tuple[int, float, bool]] = []
        for fila in range(self._tabla.rowCount()):
            casilla = self._tabla.item(fila, 0)
            nombre = self._tabla.item(fila, 1)
            if casilla is None or nombre is None:
                continue
            ev = self._evaluaciones.get(nombre.data(Qt.ItemDataRole.UserRole))
            if ev is None:
                continue
            indice = int(casilla.data(Qt.ItemDataRole.UserRole))
            marcada = casilla.checkState() == Qt.CheckState.Checked
            puntos.append(
                (indice, float(getattr(ev.metricas, atributo)), marcada)
            )
        # La tabla va ordenada por puntuación: la curva se reordena por
        # índice de registro para que la línea avance por la noche y no
        # zigzaguee saltando de un frame a otro.
        puntos.sort()
        xs = [indice for indice, valor, marcada in puntos if marcada]
        ys = [valor for indice, valor, marcada in puntos if marcada]
        xd = [indice for indice, valor, marcada in puntos if not marcada]
        yd = [valor for indice, valor, marcada in puntos if not marcada]
        self._curva.setData(xs, ys)
        self._descartados_plot.setData(xd, yd)
        if atributo == "weighted" and self._evaluaciones:
            self._umbral_linea.setValue(self.umbral())
            self._umbral_linea.show()
        else:
            self._umbral_linea.hide()
        if not self._cargando:
            self._alSeleccionar()  # recoloca el anillo del frame seleccionado

    def _pintar_resumen(self) -> None:
        """Resumen: con métricas, cuántos descartó SirIL y cuántos recomienda."""
        if self._registro is None:
            return
        descartados_siril = len(self._registro.frames) - len(self._metricas)
        recomendados = sum(1 for e in self._evaluaciones.values() if e.descartada)
        sigma = self.sigma()
        aviso = ""
        if self._metricas and recomendados == len(self._metricas):
            aviso = (
                " ⚠ El mínimo se lleva TODOS los frames: la puntuación es "
                "relativa al pool, baja «Mín.» o revisa los pesos."
            )
        self._resumen.setText(
            f"{len(self._metricas)} frames con métricas de "
            f"{len(self._registro.frames)}"
            + (
                f" · {descartados_siril} los descartó SirIL al registrar"
                if descartados_siril
                else ""
            )
            + f" · {recomendados} descartes recomendados (mínimo {self.umbral():g}, "
            f"σ={sigma:g}). El motivo está en la tabla; las casillas son tuyas."
            + aviso
        )
