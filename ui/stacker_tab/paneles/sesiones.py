"""Paso 1 «Sesiones»: banner, tabla de tomas y fichas FITS de solo lectura."""

from html import escape

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
)
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stacks.session_parser import FichaFITS, Session
from ui.style import FONT_FAMILY

from ..pasos_common import (
    _ESTILO_BANNER,
    _ESTILO_CAMPOS,
    _ESTILO_FLOTANTE,
    _ESTILO_GRUPO,
    _ESTILO_ROTACION,
    _ESTILO_TABLA,
    _ESTILO_TELESCOPIUS,
    _RESUMEN_INICIAL,
    _ayuda_fila,
    _banner,
    _campo,
    _equipo,
    _estilo_dato,
    _estilo_region,
    _formato_duracion,
    _formato_region,
    _formato_total,
    _numero,
    _optica,
    _poner_dato,
    _preview_fits,
    _rotacion_slider,
    _sensor,
    _sitio,
    _spin_dato,
    _texto_region,
)
from ..visor_sesiones import CieloCapturado, VisorSesiones


class PanelSesiones(QWidget):
    """Paso 1: sesiones a la izquierda y cielo capturado por FITS a la derecha."""

    escanear = pyqtSignal()  # «Escanear» (el Siguiente de la página también)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta ruta, resumen+tabla, carta con controles flotantes y dos fichas."""
        super().__init__(parent)
        self._ficha_actual: FichaFITS | None = None
        self._escala_cabecera: float | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        # 1. Ruta de sesiones: «Enter» en el campo lanza el escaneo.
        fila = QHBoxLayout()
        fila.setContentsMargins(2, 2, 2, 2)
        fila.setSpacing(8)
        etiqueta_dir = QLabel("Directorio Sesión:")
        etiqueta_dir.setStyleSheet(
            "font-weight: bold; color: #60a5fa; font-size: 12px;"
        )
        fila.addWidget(etiqueta_dir)
        self._raiz = QLineEdit()
        self._raiz.setPlaceholderText("Selecciona la carpeta con tus sesiones…")
        self._raiz.returnPressed.connect(self.escanear)
        self._boton_examinar = QPushButton("📁 Examinar…")
        self._boton_examinar.clicked.connect(self._examinar)
        self._boton_escanear = QPushButton("🔄 Re-escanear")
        self._boton_escanear.setObjectName("PrimaryButton")
        self._boton_escanear.clicked.connect(self.escanear)
        fila.addWidget(self._raiz, 8)
        fila.addWidget(self._boton_examinar, 2)
        fila.addWidget(self._boton_escanear, 1)
        layout.addLayout(fila)

        # 2. Desglose (izquierda) y carta del cielo (derecha).
        centro = QHBoxLayout()
        centro.setSpacing(10)

        grupo_ses = QGroupBox("Desglose de Sesiones e Integración")
        grupo_ses.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        grupo_ses.setStyleSheet(_ESTILO_GRUPO)
        lista_layout = QVBoxLayout(grupo_ses)
        lista_layout.setContentsMargins(10, 10, 10, 10)
        lista_layout.setSpacing(8)

        self._resumen = QLabel(_RESUMEN_INICIAL)
        self._resumen.setStyleSheet(_ESTILO_BANNER)
        lista_layout.addWidget(self._resumen)

        self._tabla = QTableWidget(0, 4)
        self._tabla.setHorizontalHeaderLabels(
            ["ID", "Tomas", "Exposición", "Tiempo"]
        )
        self._tabla.verticalHeader().setVisible(False)
        self._tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tabla.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tabla.setStyleSheet(_ESTILO_TABLA)
        cabecera = self._tabla.horizontalHeader()
        cabecera.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        cabecera.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tabla.installEventFilter(self)  # anchos al cambiar la anchura
        self._tabla.itemSelectionChanged.connect(self._al_elegir_sesion)
        lista_layout.addWidget(self._tabla, 1)
        centro.addWidget(grupo_ses, 5)

        grupo_fov = QGroupBox("Campo de Visión (FOV) y Planetario Interactivo")
        grupo_fov.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        grupo_fov.setStyleSheet(_ESTILO_GRUPO)
        visor_layout = QVBoxLayout(grupo_fov)
        visor_layout.setContentsMargins(6, 6, 6, 6)
        visor_layout.setSpacing(6)
        self._vistas = QStackedWidget()
        self._cielo = CieloCapturado()
        self._visor = VisorSesiones(_preview_fits)
        self._vistas.addWidget(self._cielo)
        self._vistas.addWidget(self._visor)
        visor_layout.addWidget(self._vistas, 1)
        centro.addWidget(grupo_fov, 6)
        layout.addLayout(centro, 1)

        # Controles flotantes: van encima de la carta, no en una fila aparte.
        self._telescopius = QPushButton("🌐 Telescopius", self._cielo)
        self._telescopius.setStyleSheet(_ESTILO_TELESCOPIUS)
        self._telescopius.setToolTip("Próximamente: integración con Telescopius.")
        self._telescopius.setEnabled(False)

        self._panel_rot = QWidget(self._cielo)
        self._panel_rot.setObjectName("PanelRotacion")
        self._panel_rot.setStyleSheet(_ESTILO_ROTACION)
        lay_rot = QHBoxLayout(self._panel_rot)
        lay_rot.setContentsMargins(8, 2, 8, 2)
        lay_rot.setSpacing(8)
        lay_rot.addWidget(QLabel("Rot:"))
        self._rotacion = QSlider(Qt.Orientation.Horizontal)
        self._rotacion.setRange(-180, 180)
        self._rotacion.setFixedWidth(180)
        lay_rot.addWidget(self._rotacion)
        self._rotacion_spin = QSpinBox()
        self._rotacion_spin.setRange(-180, 180)
        self._rotacion_spin.setSuffix("°")
        self._rotacion_spin.setFixedWidth(56)
        lay_rot.addWidget(self._rotacion_spin)
        self._rotacion.valueChanged.connect(self._al_rotar)
        self._rotacion_spin.valueChanged.connect(self._rotacion.setValue)
        self._panel_rot.hide()

        self._alternar_vista = QPushButton("Ver FITS", self._vistas)
        self._alternar_vista.setStyleSheet(_ESTILO_FLOTANTE)
        self._reiniciar = QPushButton("Reset Vista", self._vistas)
        self._reiniciar.setStyleSheet(_ESTILO_FLOTANTE)
        self._alternar_vista.clicked.connect(self._alternar)
        self._reiniciar.clicked.connect(self._reiniciar_vista)

        self._cielo.installEventFilter(self)
        self._vistas.installEventFilter(self)

        # 3. Las dos fichas inferiores: rejilla 2×2 con altura fija de 115 px.
        tarjetas = QHBoxLayout()
        tarjetas.setSpacing(10)

        self._grupo_opt = QGroupBox("Tren Óptico y Muestreo")
        self._grupo_opt.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._grupo_opt.setFixedHeight(115)
        self._grupo_opt.setStyleSheet(_ESTILO_GRUPO + _ESTILO_CAMPOS)
        grid_opt = QGridLayout(self._grupo_opt)
        grid_opt.setContentsMargins(14, 12, 14, 10)
        grid_opt.setVerticalSpacing(8)
        grid_opt.setHorizontalSpacing(12)
        grid_opt.setColumnMinimumWidth(0, 130)
        grid_opt.setColumnStretch(1, 1)
        grid_opt.setColumnMinimumWidth(2, 130)
        grid_opt.setColumnStretch(3, 1)

        # Todos los datos provienen del primer FITS y son solo lectura.
        self._optica_campos_0 = _spin_dato(0.0, 5000.0, decimales=2, paso=10.0)
        self._optica_campos_0.setToolTip(
            "Distancia focal (mm) del primer light (FOCALLEN)."
        )
        self._optica_campos_1 = _spin_dato(0.0, 25.0, decimales=2, paso=0.1)
        self._optica_campos_1.setToolTip(
            "Tamaño del píxel (µm) del primer light (PIXSIZE1/XPIXSZ)."
        )
        self._optica_campos_2 = QLabel("Pendiente FITS")
        self._optica_campos_2.setStyleSheet(_estilo_dato("#8092af"))
        self._optica_campos_3 = QLabel("Pendiente FITS")
        self._optica_campos_3.setStyleSheet(_estilo_dato("#8092af"))

        grid_opt.addWidget(_campo("Distancia Focal (mm):"), 0, 0)
        grid_opt.addWidget(self._optica_campos_0, 0, 1)
        grid_opt.addWidget(_campo("Tamaño Píxel (µm):"), 0, 2)
        grid_opt.addWidget(self._optica_campos_1, 0, 3)
        grid_opt.addWidget(_campo("Escala de Placa:"), 1, 0)
        grid_opt.addWidget(self._optica_campos_2, 1, 1)
        grid_opt.addWidget(_campo("Rotación Sensor:"), 1, 2)
        grid_opt.addWidget(self._optica_campos_3, 1, 3)
        # Texto completo (oculto): lo que no cabe en los campos sigue accesible
        # en el tooltip del grupo, no en una lista de cuatro filas más.
        self._detalle_optico = QLabel(self._grupo_opt)
        self._detalle_optico.hide()
        tarjetas.addWidget(self._grupo_opt, 5)

        self._grupo_sitio = QGroupBox(
            "Ubicación del Observatorio y Región Apuntada"
        )
        self._grupo_sitio.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._grupo_sitio.setFixedHeight(115)
        self._grupo_sitio.setStyleSheet(_ESTILO_GRUPO + _ESTILO_CAMPOS)
        grid_sitio = QGridLayout(self._grupo_sitio)
        grid_sitio.setContentsMargins(14, 12, 14, 10)
        grid_sitio.setVerticalSpacing(8)
        grid_sitio.setHorizontalSpacing(12)
        grid_sitio.setColumnMinimumWidth(0, 110)
        grid_sitio.setColumnStretch(1, 1)
        grid_sitio.setColumnMinimumWidth(2, 110)
        grid_sitio.setColumnStretch(3, 2)

        self._sitio_campos_0 = _spin_dato(
            -90.0, 90.0, decimales=5, paso=0.01, solo_lectura=True
        )
        self._sitio_campos_1 = _spin_dato(
            -180.0, 180.0, decimales=5, paso=0.01, solo_lectura=True
        )
        self._sitio_campos_2 = _spin_dato(
            -90.0, 90.0, decimales=1, paso=1.0, solo_lectura=True
        )
        self._sitio_campos_2.setToolTip(
            "Altura del objeto sobre el horizonte (OBJCTALT del primer light)."
        )
        self._sitio_campos_3 = QLineEdit()
        self._sitio_campos_3.setReadOnly(True)
        self._sitio_campos_3.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sitio_campos_3.setText("Pendiente FITS")
        self._sitio_campos_3.setStyleSheet(_estilo_region("#8092af"))

        grid_sitio.addWidget(_campo("Latitud (°):"), 0, 0)
        grid_sitio.addWidget(self._sitio_campos_0, 0, 1)
        grid_sitio.addWidget(_campo("Longitud (°):"), 0, 2)
        grid_sitio.addWidget(self._sitio_campos_1, 0, 3)
        grid_sitio.addWidget(_campo("Alt. objeto (°):"), 1, 0)
        grid_sitio.addWidget(self._sitio_campos_2, 1, 1)
        grid_sitio.addWidget(_campo("Coords:"), 1, 2)
        grid_sitio.addWidget(self._sitio_campos_3, 1, 3)
        self._detalle_sitio = QLabel(self._grupo_sitio)
        self._detalle_sitio.hide()
        tarjetas.addWidget(self._grupo_sitio, 5)
        layout.addLayout(tarjetas)

        self._sesiones_actuales: list[Session] = []
        self._fichas_actuales: dict[str, FichaFITS] = {}

    def raiz(self) -> str:
        """Carpeta raíz escrita por el usuario (vacío si aún no hay)."""
        return self._raiz.text().strip()

    def poner_raiz(self, raiz: str) -> None:
        """Fija la raíz (Configuración al abrir; la pestaña puede cambiarla)."""
        self._raiz.setText(raiz)

    def bloquear(self, bloqueado: bool) -> None:
        """Deshabilita sus botones mientras una tarea corre en el hilo."""
        self._boton_examinar.setEnabled(not bloqueado)
        self._boton_escanear.setEnabled(not bloqueado)
        self._raiz.setEnabled(not bloqueado)

    def mostrar(
        self,
        sesiones: list[Session],
        calibradas: set[str],
        exposiciones: dict[str, list[float]],
        fichas: dict[str, FichaFITS] | None = None,
    ) -> None:
        """Rellena la tabla y sincroniza el visor/fichas con la sesión elegida.

        ``exposiciones`` da la exposición por frame de cada sesión (segundos;
        lista vacía si no hay dato): de ahí salen «Exposición» (por frame) y
        «Tiempo» (acumulado). ``fichas`` son las cabeceras FITS del primer
        light de cada sesión (región apuntada y ficha del equipo); sin ella
        la región no sale y la ficha avisa de que no hay cabeceras.
        """
        fichas = fichas or {}
        self._sesiones_actuales = list(sesiones)
        self._fichas_actuales = fichas
        self._tabla.setRowCount(0)
        total_lights = 0
        total_segundos = 0.0
        negrita = QFont(FONT_FAMILY, 10)
        negrita.setBold(True)
        normal = QFont(FONT_FAMILY, 10)
        for sesion in sesiones:
            fila = self._tabla.rowCount()
            self._tabla.insertRow(fila)
            lights = sesion.n_lights
            duraciones = exposiciones.get(sesion.path.name, [])
            total = sum(duraciones)
            total_lights += lights
            total_segundos += total
            calibrada = sesion.path.name in calibradas
            ficha = fichas.get(sesion.path.name)
            # ID en azul y en negrita, tomas en blanco, exposición en azul
            # claro y tiempo en verde: el color codifica la columna.
            celdas = (
                (sesion.path.name, "#58a6ff", negrita),
                (str(lights), "#f0f6fc", normal),
                (_formato_duracion(duraciones), "#79c0ff", normal),
                (_formato_total(total), "#7ee787", negrita),
            )
            for columna, (texto, color, fuente) in enumerate(celdas):
                item = QTableWidgetItem(texto)
                item.setForeground(QColor(color))
                item.setFont(fuente)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if columna == 0:
                    item.setToolTip(_ayuda_fila(sesion, calibrada, ficha))
                self._tabla.setItem(fila, columna, item)
            self._tabla.setRowHeight(fila, 30)
        self._repartir_anchos()
        if sesiones:
            self._resumen.setText(
                _banner(len(sesiones), total_lights, _formato_total(total_segundos))
            )
            self._tabla.selectRow(0)
        else:
            self._resumen.setText(_banner(None))
            self._visor.mostrar(None, None)
            self._cielo.mostrar(None)
            self._poner_conmutador(False)
            self._poner_detalles("Sin escanear todavía.", "Sin escanear todavía.")
            self._rellenar_campos(None)

    def _al_elegir_sesion(self) -> None:
        """Muestra solo el FITS de la fila seleccionada; no modifica el origen."""
        indice = self._tabla.currentRow()
        if not 0 <= indice < len(self._sesiones_actuales):
            return
        sesion = self._sesiones_actuales[indice]
        ficha = self._fichas_actuales.get(sesion.path.name)
        lights = sesion.frames.get("lights", [])
        primer_fits = next(
            (f for f in lights if f.suffix.lower() in (".fit", ".fits", ".fts")),
            None,
        )
        self._visor.mostrar(primer_fits, ficha)
        self._cielo.mostrar(ficha)
        self._poner_conmutador(primer_fits is not None)
        self._rellenar_campos(ficha)
        self._actualizar_detalles(ficha)

    def _poner_conmutador(self, hay_fits: bool) -> None:
        """«Ver FITS» solo existe cuando hay imagen que enseñar.

        Sin FITS legible (RAW u otro formato que la cabecera no abre) no se
        deja un botón muerto: se oculta y la vista se queda en la carta.
        """
        self._alternar_vista.setVisible(hay_fits)
        if hay_fits:
            return
        self._alternar_vista.setText("Ver FITS")
        if self._vistas.currentWidget() is not self._cielo:
            self._vistas.setCurrentWidget(self._cielo)
            self._reiniciar.raise_()

    def _rellenar_campos(self, ficha: FichaFITS | None) -> None:
        """Rellena las dos fichas sin fabricar medidas ausentes del FITS.

        Todos los valores proceden del primer light y son de solo lectura.
        Lo que el FITS no trae se muestra como
        «--» o «Pendiente FITS», nunca con un valor por defecto.
        """
        self._ficha_actual = ficha
        self._escala_cabecera = ficha.escala_as_px if ficha else None
        _poner_dato(
            self._optica_campos_0,
            ficha.focal_mm if ficha else None, 0.0, 5000.0,
        )
        _poner_dato(
            self._optica_campos_1,
            ficha.pix_um if ficha else None, 0.0, 25.0,
        )
        _poner_dato(
            self._sitio_campos_0, ficha.lat if ficha else None, -90.0, 90.0
        )
        _poner_dato(
            self._sitio_campos_1, ficha.lon if ficha else None, -180.0, 180.0
        )
        _poner_dato(
            self._sitio_campos_2,
            ficha.altura_obj_deg if ficha else None, -90.0, 90.0,
        )

        rotacion = ficha.rotacion_deg if ficha and ficha.rotacion_deg is not None else None
        self._optica_campos_3.setText(
            f"{_numero(rotacion, 1)}°"
            if rotacion is not None else "Pendiente FITS"
        )
        self._optica_campos_3.setToolTip("Rotación de la cabecera (CROTA2).")
        self._optica_campos_3.setStyleSheet(
            _estilo_dato("#d2a8ff" if rotacion is not None else "#8092af")
        )

        region = _texto_region(ficha)
        self._sitio_campos_3.setText(region or "Pendiente FITS")
        self._sitio_campos_3.setToolTip(region or "Sin región en FITS")
        self._sitio_campos_3.setStyleSheet(
            _estilo_region("#f1fa8c" if region else "#8092af")
        )
        grados = ficha.rotacion_deg if ficha and ficha.rotacion_deg is not None else None
        self._rotacion.setValue(_rotacion_slider(grados))
        self._recalcular_escala()

    def _escala_de_spins(self) -> float | None:
        """Escala derivada de focal, píxel y binning (los que traiga el FITS)."""
        focal = self._optica_campos_0.value()
        pixel = self._optica_campos_1.value()
        if focal <= 0 or pixel <= 0:
            return None
        binning = self._ficha_actual.binning if self._ficha_actual else None
        return 206.265 * pixel * (binning or 1) / focal

    def _recalcular_escala(self) -> None:
        """Etiqueta de escala de placa, reencuadre de la carta y panel de rotación.

        El ``SCALE`` de la cabecera manda; si no está, se deriva de la
        óptica del FITS con la misma fórmula de ``campo_vision``. Sin ningún
        dato la etiqueta se queda en «Pendiente FITS» y no se dibuja un FOV.
        """
        escala = self._escala_cabecera
        if escala is None:
            escala = self._escala_de_spins()
        if escala is None:
            self._optica_campos_2.setText("Pendiente FITS")
            self._optica_campos_2.setStyleSheet(_estilo_dato("#8092af"))
        else:
            self._optica_campos_2.setText(f"{_numero(escala, 3)} arcsec/px")
            self._optica_campos_2.setStyleSheet(_estilo_dato("#58a6ff"))
        self._aplicar_campo(escala)
        if self._cielo.tiene_encuadre():
            self._colocar_flotantes()
            self._panel_rot.show()
        else:
            self._panel_rot.hide()

    def _aplicar_campo(self, escala: float | None) -> None:
        """Reencuadra la carta con la escala vigente y el sensor real del FITS."""
        ficha = self._ficha_actual
        if ficha is None:
            return  # sin sesión no hay centro que reanclar
        campo = None
        if escala and ficha.px_x and ficha.px_y:
            campo = (ficha.px_x * escala / 3600.0, ficha.px_y * escala / 3600.0)
        self._cielo.actualizar_campo(campo)

    def _actualizar_detalles(self, ficha: FichaFITS | None) -> None:
        """Textos auxiliares de la sesión elegida (visibles en el tooltip)."""
        if ficha is None:
            self._poner_detalles(
                "Sin cabecera FITS legible.",
                "Región y sitio: — (sin cabecera FITS).",
            )
            return
        self._poner_detalles(
            f"Óptica: {escape(_optica(ficha) or '—')}<br>"
            f"Sensor: {escape(_sensor(ficha) or '—')}<br>"
            f"Equipo: {escape(_equipo(ficha) or '—')}",
            f"Observatorio: {escape(_sitio(ficha) or '—')}<br>"
            f"Elevación del observatorio: "
            f"{escape(f'{_numero(ficha.altitud_m, 0)} m' if ficha.altitud_m is not None else 'No consta en FITS')}<br>"
            f"Región: {escape(_formato_region(ficha))}<br>"
            f"Objetivo FITS: {escape(ficha.objeto or '—')}",
        )

    def _poner_detalles(self, optico: str, sitio: str) -> None:
        """Guarda la ficha en los textos ocultos y la expone en los tooltip.

        Los dos grupos tienen la rejilla 2×2 y no admiten más filas: el
        detalle completo (sensor, equipo, objetivo) vive en el tooltip del
        propio grupo para no romper la maquetación.
        """
        self._detalle_optico.setText(optico)
        self._detalle_sitio.setText(sitio)
        self._grupo_opt.setToolTip(optico)
        self._grupo_sitio.setToolTip(sitio)

    def _al_rotar(self, valor: int) -> None:
        """El slider manda: espeja los grados en el spin y gira el contorno FOV."""
        if self._rotacion_spin.value() != valor:
            self._rotacion_spin.blockSignals(True)
            self._rotacion_spin.setValue(valor)
            self._rotacion_spin.blockSignals(False)
        self._cielo.set_rotation(valor)

    def _alternar(self) -> None:
        """Alterna entre carta de la captura y el light FITS original."""
        es_cielo = self._vistas.currentWidget() is self._cielo
        self._vistas.setCurrentWidget(self._visor if es_cielo else self._cielo)
        self._alternar_vista.setText("Ver cielo" if es_cielo else "Ver FITS")
        # QStackedWidget sube su página al cambiar: los botones flotantes
        # son hermanos de la página y tienen que volver a la cima.
        self._alternar_vista.raise_()
        self._reiniciar.raise_()

    def _reiniciar_vista(self) -> None:
        """Vuelve al encuadre de la sesión en ambas vistas."""
        self._cielo.reset_view()
        self._visor.reiniciar_vista()

    def _colocar_flotantes(self) -> None:
        """Sitúa los controles flotantes en las esquinas de la carta y del visor.

        Las mismas posiciones de la referencia: Telescopius arriba a la
        derecha, el panel de rotación abajo (a la izquierda de «Reset Vista»)
        y los dos botones flotando sobre la pila de vistas.
        """
        ancho, alto = self._cielo.width(), self._cielo.height()
        self._telescopius.setGeometry(max(0, ancho - 147), 10, 135, 30)
        panel_ancho = max(self._panel_rot.sizeHint().width(), 1)
        self._panel_rot.setGeometry(
            max(0, ancho - 105 - panel_ancho - 12),
            max(0, alto - 37),
            panel_ancho, 28,
        )
        ancho_v, alto_v = self._vistas.width(), self._vistas.height()
        # En la misma fila que Telescopius (arriba a la derecha): la leyenda
        # de la carta arranca justo debajo y no debe quedar tapada por él.
        self._alternar_vista.adjustSize()
        ancho_alt = self._alternar_vista.width()
        self._alternar_vista.setGeometry(
            max(0, ancho_v - 147 - 8 - ancho_alt), 10, ancho_alt, 30
        )
        self._reiniciar.setGeometry(max(0, ancho_v - 105), max(0, alto_v - 36), 95, 26)

    def _repartir_anchos(self, ancho: int | None = None) -> None:
        """El ID ocupa el 44 % y el resto reparte entre las tres columnas.

        Si el panel es más estrecho que los mínimos, se conservan los mínimos
        y Qt ofrece desplazamiento horizontal: mejor barras que cabeceras
        partidas («Exposición» y «Tiempo» tienen que leerse enteras).

        Args:
            ancho: anchura de la cabecera a repartir; si falta, se lee la real.
        """
        if ancho is None:
            ancho = self._tabla.horizontalHeader().width()
        columnas = self._tabla.columnCount()
        minimos = [145, 75, 110, 105][:columnas]
        if ancho <= 0 or columnas < 3:
            return
        if ancho < sum(minimos):
            for columna, minimo in enumerate(minimos):
                self._tabla.setColumnWidth(columna, minimo)
            return
        sesion = min(max(int(ancho * 0.44), minimos[0]), ancho - sum(minimos[1:]))
        resto = ancho - sesion
        reparto, sobrantes = divmod(resto - sum(minimos[1:]), columnas - 1)
        anchos = [sesion] + [
            minimos[columna] + reparto + (columna - 1 < sobrantes)
            for columna in range(1, columnas)
        ]
        for columna, ancho_columna in enumerate(anchos):
            self._tabla.setColumnWidth(columna, ancho_columna)

    def eventFilter(self, objeto, evento):
        """Recalcula anchos y posiciones de los controles al redimensionar.

        Va por event filter (y no por ``resizeEvent`` del panel) porque la
        tabla o la carta pueden redimensionarse sin que el panel lo haga: al
        asentarse el layout la primera vez, por ejemplo. El reencaje
        diferido cubre el caso en que la cabecera aún no tiene su ancho
        final dentro del propio evento.
        """
        if evento.type() == QEvent.Type.Resize:
            if objeto is self._tabla:
                self._repartir_anchos()
                QTimer.singleShot(0, self._repartir_anchos)
            elif objeto is getattr(self, "_cielo", None):
                self._colocar_flotantes()
            elif objeto is getattr(self, "_vistas", None):
                self._colocar_flotantes()
                self._alternar_vista.raise_()
                self._reiniciar.raise_()
        return super().eventFilter(objeto, evento)

    def _examinar(self) -> None:
        """Selector de carpeta del sistema, empezando en la raíz actual."""
        carpeta = QFileDialog.getExistingDirectory(
            self, "Carpeta raíz de sesiones", self.raiz()
        )
        if carpeta:
            self._raiz.setText(carpeta)
