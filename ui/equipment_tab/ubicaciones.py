"""Subpestaña **Ubicaciones**: sección «Ubicaciones guardados» + ficha.

Layout **sin `QSplitter` y con un solo scroll, nada fijo** (pedido del
usuario): dentro de la zona con scroll va `[sección «Ubicaciones
guardados» sin rótulo, con el ancho que le deja la ficha
(`_ancho_lista`: la ficha determina el mínimo necesario) | sección
«Ubicación»]` y, debajo, el ``SitioPanel`` (rosácea + esquemático +
mapa de CL) a todo el ancho: sin cabecera fija, las gráficas tienen
toda la altura que sobra en vez de quedar cortadas.

La sección «Ubicación» mantiene un solo marco con identidad/coordenadas,
cielo y horario en filas separadas. El horario permite zona IANA según fecha
o desfase fijo; el modo aproximado heredado se identifica sin inferir una zona.

Regla UX global (§9): **nada se persiste hasta «Guardar ubicación»**:
«Nueva» deja la ficha en blanco en memoria y no se inserta fila hasta el
primer guardado; cambiar de fila descarta lo tecleado (cancelar no toca
la base, D-5).
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from equipment import localizations, manager
from equipment.images import list_images
from equipment.models import Location
from planners.analytical_transit import local_utc_offset
from planners.timezones import rules_label, zone_names

from .componentes import ListaGuardados, sin_botones
from .sitio import SitioPanel

#: Suelo del ancho de la sección de la lista: más estrecho, deja de ser útil.
_ANCHO_LISTA_MIN = 200
#: Techo del ancho de la sección de la lista: el mismo que la de Equipos.
_ANCHO_LISTA_MAX = 450


class UbicacionesTab(QWidget):
    """Gestión de ubicaciones: lista + ficha de sitio y CL en panel.

    Señales: ``locations_changed`` tras alta/baja/guardado; la ventana
    principal es quien decide a dónde reenviarla (barra de ubicación,
    combos de Equipo).
    """

    locations_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta las dos filas (lista + cabecera/fila de ficha / scroll del sitio) y carga la primera ubicación si hay."""
        super().__init__(parent)
        self._ubicacion_id: int | None = None
        self._cargando = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        # Un solo scroll, nada fijo (pedido del usuario): la lista, la
        # ficha y el sitio viven dentro de la misma zona con scroll, así
        # las gráficas tienen toda la altura que sobra en vez de quedar
        # cortadas bajo una cabecera fija. La ficha se construye
        # primero: el ancho de la lista depende del mínimo de la ficha.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        contenido = QWidget()
        flay = QVBoxLayout(contenido)
        flay.setContentsMargins(0, 0, 0, 0)
        flay.setSpacing(10)

        self._ficha = self._seccion_ubicacion()
        fila_sup = QHBoxLayout()
        fila_sup.setSpacing(10)
        self._marco_lista = self._seccion_lista()
        fila_sup.addWidget(self._marco_lista)
        fila_sup.addWidget(self._ficha, 1)
        flay.addLayout(fila_sup)

        self._sitio = SitioPanel()
        flay.addWidget(self._sitio)
        flay.addStretch(1)

        self._scroll.setWidget(contenido)
        layout.addWidget(self._scroll, 1)

        # Conectado al final: el esquemático ya existe cuando se carga
        # la primera fila (los spins emiten al rellenarse).
        self._bortle.currentIndexChanged.connect(self._refrescar_cielo)
        self._sqm.valueChanged.connect(self._refrescar_cielo)
        self._recargar_lista(select_id=None)

    # -- construcción ------------------------------------------------------

    def _ancho_lista(self) -> int:
        """Ancho de la sección de la lista: lo que queda tras el mínimo de la ficha.

        La ficha manda (el usuario pidió que la lista se ajuste para
        que «Ubicación» no se recorte): hueco real del scroll —el
        **viewport**, que ya descuenta márgenes, marco y barra vertical;
        contar solo el ancho de la pestaña dejaría la fila sin esos
        ~22 px y saldría barra horizontal incluso en la ventana de
        1536— menos el ancho mínimo que piden sus campos, con suelo
        `_ANCHO_LISTA_MIN` (más estrecho deja de ser útil) y techo
        `_ANCHO_LISTA_MAX` (el mismo que la sección de Equipos). Si el
        hueco no llega ni al suelo, manda el suelo: la fila se queda
        corta y el scroll de la pestaña enseña su barra horizontal.

        Returns:
            Ancho fijo que hay que darle a la sección.
        """
        area = getattr(self, "_scroll", None)
        if area is not None and area.viewport().width() > 0:
            hueco = area.viewport().width()
        else:
            # Aún sin viewport (construcción): estimo con la pestaña y
            # `resizeEvent` lo corrige en cuanto hay medidas reales.
            hueco = max(0, self.width() - 22)
        min_ficha = self._ficha.minimumSizeHint().width()
        return max(_ANCHO_LISTA_MIN, min(_ANCHO_LISTA_MAX, hueco - 10 - min_ficha))

    def resizeEvent(self, ev: QResizeEvent) -> None:
        """Recalcula el ancho de la sección de la lista al redimensionar.

        El ancho depende del viewport del scroll (hueco real tras el
        mínimo de la ficha), que a su vez cambia con el tamaño de la
        ventana; sin esto, la lista se quedaría en el valor del
        arranque. Se recalcula en cada resize, también de alto, porque
        la barra vertical del scroll solo aparece cuando el contenido
        no cabe y eso estrecha el viewport.
        """
        super().resizeEvent(ev)
        marco = getattr(self, "_marco_lista", None)
        if marco is None:
            return
        ancho = self._ancho_lista()
        if marco.width() != ancho:
            marco.setFixedWidth(ancho)

    def _seccion_lista(self) -> QFrame:
        """Sección «Ubicaciones guardados»: su lista y sus botones, sin rótulo.

        Réplica de la de Equipos, con el mismo rótulo quitado:
        «Ubicaciones guardados» a `PanelTitle` (13 pt) robaba dos
        líneas y la pestaña ya se llama «Ubicaciones». El ancho lo da
        `_ancho_lista` —la ficha determina el ancho necesario— y la
        lista va con stretch **sin tope de alto**
        (`ListaGuardados.sizeHint()` es pequeño a propósito: su
        sizeHint natural de 192 px hincharía la fila). Los botones van
        en fila; «🗑» lleva el «Eliminar» en tooltip (en fila con
        «➕ Nueva…» no caben los dos textos).
        """
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        marco.setFixedWidth(self._ancho_lista())
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(12, 4, 12, 6)
        lay.setSpacing(6)

        self._lista = ListaGuardados()
        self._lista.currentRowChanged.connect(self._al_elegir_fila)
        lay.addWidget(self._lista, 1)

        acciones = QHBoxLayout()
        acciones.setSpacing(6)
        boton_nueva = QPushButton("➕ Nueva…")
        boton_nueva.clicked.connect(self._nueva)
        acciones.addWidget(boton_nueva, 1)
        self._boton_eliminar = QPushButton("🗑")
        self._boton_eliminar.setToolTip("Eliminar la ubicación seleccionada")
        self._boton_eliminar.clicked.connect(self._eliminar)
        self._boton_eliminar.setEnabled(False)
        acciones.addWidget(self._boton_eliminar)
        lay.addLayout(acciones)
        return marco

    def _seccion_ubicacion(self) -> QFrame:
        """Marco único con Guardar e identidad, cielo y horario separados para mantener legibles sus controles."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(12, 6, 12, 10)
        lay.setSpacing(8)

        fila_titulo = QHBoxLayout()
        titulo = QLabel("Ubicación")
        titulo.setObjectName("PanelTitle")
        fila_titulo.addWidget(titulo)
        fila_titulo.addStretch(1)
        boton = QPushButton("Guardar ubicación")
        boton.setObjectName("PrimaryButton")
        boton.clicked.connect(self._guardar)
        fila_titulo.addWidget(boton)
        lay.addLayout(fila_titulo)

        # Fila 1: identidad y coordenadas, en parejas etiqueta|campo.
        fila1 = QHBoxLayout()
        fila1.setSpacing(12)
        self._nombre = QLineEdit()
        self._nombre.setPlaceholderText("Casa, mirador del puerto…")
        fila1.addWidget(QLabel("Nombre"))
        fila1.addWidget(self._nombre, 1)
        self._altitud = QDoubleSpinBox()
        self._altitud.setRange(0.0, 9000.0)
        self._altitud.setDecimals(0)
        self._altitud.setSuffix(" m")
        self._altitud.setSpecialValueText("—")
        sin_botones(self._altitud)
        fila1.addWidget(QLabel("Altitud"))
        fila1.addWidget(self._altitud, 1)
        self._latitud = QDoubleSpinBox()
        self._latitud.setRange(-90.0, 90.0)
        self._latitud.setDecimals(3)
        self._latitud.setSuffix("°")
        sin_botones(self._latitud)
        fila1.addWidget(QLabel("Latitud"))
        fila1.addWidget(self._latitud, 1)
        self._longitud = QDoubleSpinBox()
        self._longitud.setRange(-180.0, 180.0)
        self._longitud.setDecimals(3)
        self._longitud.setSuffix("°")
        sin_botones(self._longitud)
        fila1.addWidget(QLabel("Longitud"))
        fila1.addWidget(self._longitud, 1)
        lay.addLayout(fila1)

        # Cielo separado del horario para mantener legibles sus controles.
        fila2 = QHBoxLayout()
        fila2.setSpacing(12)
        self._bortle = QComboBox()
        self._bortle.addItem("Elige un nivel…", None)
        for nivel in range(1, 10):
            self._bortle.addItem(str(nivel), nivel)
        self._bortle.setToolTip(
            "1 = cielo pristineo · 9 = centro urbano iluminado. "
            "Obligatorio: la CL alimenta las decisiones de captura."
        )
        fila2.addWidget(QLabel("Bortle"))
        fila2.addWidget(self._bortle, 1)
        self._sqm = QDoubleSpinBox()
        self._sqm.setRange(0.0, 30.0)
        self._sqm.setDecimals(2)
        self._sqm.setSpecialValueText("—")
        self._sqm.setSuffix(" mag/arcsec²")
        self._sqm.setToolTip(
            "SQM cenital: magnitud por segundo de arco cuadrado en el "
            "cenit (opcional). El informado es la referencia de la "
            "gráfica; en «—» se asume con el Bortle."
        )
        sin_botones(self._sqm)
        # Para que el SQM pueda volver a vacío: ver `eventFilter`.
        self._sqm.installEventFilter(self)
        fila2.addWidget(QLabel("SQM"))
        fila2.addWidget(self._sqm, 1)
        self._seeing = QDoubleSpinBox()
        self._seeing.setRange(0.0, 30.0)
        self._seeing.setDecimals(1)
        self._seeing.setSpecialValueText("—")
        self._seeing.setSuffix(" ″ FWHM")
        self._seeing.setToolTip(
            "Seeing típico (FWHM) de este sitio: el muestreo del equipo "
            "se evalúa contra él. «—» = sin dato, no se inventa."
        )
        sin_botones(self._seeing)
        fila2.addWidget(QLabel("Seeing"))
        fila2.addWidget(self._seeing, 1)
        lay.addLayout(fila2)
        horario = QHBoxLayout()
        horario.addWidget(QLabel("Horario"))
        self._clock_mode = QComboBox()
        self._clock_mode.addItem("Desfase fijo", "fixed")
        self._clock_mode.addItem("Zona según fecha", "zone")
        self._clock_mode.addItem("Aprox. heredada", "legacy")
        self._clock_mode.setToolTip("Zona según fecha: recomendada. El modo fijo no ajusta verano. La aproximación heredada no es hora legal.")
        horario.addWidget(self._clock_mode)
        self._timezone = QComboBox()
        self._timezone.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._timezone.setMinimumContentsLength(16)
        self._timezone.addItem("Elige una zona IANA…", None)
        for key in zone_names():
            self._timezone.addItem(key, key)
        self._timezone.setToolTip("Zona seleccionada explícitamente, sin usar la del ordenador. " + rules_label())
        self._timezone.setAccessibleName("Zona horaria IANA")
        horario.addWidget(self._timezone, 1)
        self._offset_label = QLabel("Desfase")
        horario.addWidget(self._offset_label)
        self._huso = QDoubleSpinBox()
        self._huso.setRange(-12.0, 14.0)
        self._huso.setDecimals(2)
        self._huso.setSingleStep(0.25)
        self._huso.setSuffix(" h")
        self._huso.setToolTip(
            "Desfase fijo frente a UTC: no cambia con la fecha. En modo heredado se aproxima por longitud."
        )
        sin_botones(self._huso)
        horario.addWidget(self._huso)
        lay.addLayout(horario)

        self._clock_mode.currentIndexChanged.connect(self._al_cambiar_auto)
        self._longitud.valueChanged.connect(self._refrescar_desfase)
        self._al_cambiar_auto()
        return marco

    # -- lista y carga -----------------------------------------------------

    def _recargar_lista(self, select_id: int | None) -> None:
        """Repuebla la lista y carga ``select_id`` (si no, la primera fila)."""
        self._cargando = True
        self._lista.clear()
        ids: list[int] = []
        for lugar in localizations.list_locations():
            item = QListWidgetItem(str(lugar["name"]))
            # La lista elige al medio: el nombre completo va al tooltip.
            item.setToolTip(str(lugar["name"]))
            item.setData(Qt.ItemDataRole.UserRole, lugar["id"])
            self._lista.addItem(item)
            ids.append(lugar["id"])
        objetivo = select_id if select_id in ids else (ids[0] if ids else None)
        if objetivo is not None:
            self._lista.setCurrentRow(ids.index(objetivo))
        self._cargando = False
        self._cargar(objetivo)

    def _al_elegir_fila(self, fila: int) -> None:
        """Selección del usuario: carga esa ubicación (o la ficha en blanco)."""
        if self._cargando:
            return
        item = self._lista.item(fila)
        self._cargar(item.data(Qt.ItemDataRole.UserRole) if item else None)

    def _cargar(self, ubicacion_id: int | None) -> None:
        """Vierte una ubicación de la base en la ficha (None = en blanco)."""
        self._cargando = True
        try:
            fila = None
            if ubicacion_id is not None:
                fila = next(
                    (
                        lugar
                        for lugar in localizations.list_locations()
                        if lugar["id"] == ubicacion_id
                    ),
                    None,
                )
            if fila is None:
                self._ubicacion_id = None
                self._nombre.clear()
                self._latitud.setValue(0.0)
                self._longitud.setValue(0.0)
                self._altitud.setValue(0.0)
                self._clock_mode.setCurrentIndex(0)
                self._huso.setValue(0)
                self._timezone.setCurrentIndex(0)
                self._bortle.setCurrentIndex(0)
                self._sqm.setValue(0.0)
                self._seeing.setValue(0.0)
                self._sitio.set_valores({}, {}, None, True)
            else:
                self._ubicacion_id = fila["id"]
                self._nombre.setText(str(fila.get("name") or ""))
                self._latitud.setValue(float(fila.get("latitude") or 0.0))
                self._longitud.setValue(float(fila.get("longitude") or 0.0))
                self._altitud.setValue(float(fila.get("altitude") or 0.0))
                desfase = fila.get("utc_offset_hours")
                key = fila.get("timezone_id")
                if key is not None and self._timezone.findData(key) < 0:
                    self._timezone.addItem(key + " (no disponible)", key)
                self._timezone.setCurrentIndex(max(0, self._timezone.findData(key)))
                mode = "zone" if key is not None else ("legacy" if desfase is None else "fixed")
                self._clock_mode.setCurrentIndex(self._clock_mode.findData(mode))
                if desfase is not None:
                    self._huso.setValue(float(desfase))
                self._bortle.setCurrentIndex(
                    max(0, self._bortle.findData(fila.get("bortle")))
                )
                self._sqm.setValue(float(fila.get("sqm") or 0.0))
                self._seeing.setValue(float(fila.get("seeing_arcsec") or 0.0))
                imagenes = list_images("location", fila["id"])
                self._sitio.set_valores(
                    fila.get("obstacles") or {},
                    fila.get("lp") or {},
                    imagenes[0]["path"] if imagenes else None,
                    bool(fila.get("consider_lp", True)),
                )
        finally:
            self._cargando = False
        self._refrescar_desfase()
        self._al_cambiar_auto()
        self._refrescar_cielo()
        self._boton_eliminar.setEnabled(self._ubicacion_id is not None)

    def _refrescar_desfase(self) -> None:
        """Solo el modo heredado aproxima el desfase mediante ``round(longitud/15)``.

        La misma regla que el planificador (``local_utc_offset``): lo que
        se ve en la ficha es exactamente lo que se usará al planificar.
        """
        if self._clock_mode.currentData() == "legacy":
            self._huso.setValue(local_utc_offset(self._longitud.value()))

    def _al_cambiar_auto(self, *_args) -> None:
        """Activa solo el control del modo elegido; zona y desfase nunca se suman."""
        mode = self._clock_mode.currentData()
        self._huso.setEnabled(mode == "fixed")
        self._huso.setVisible(mode != "zone")
        self._offset_label.setVisible(mode != "zone")
        self._timezone.setEnabled(mode == "zone")
        self._refrescar_desfase()

    def eventFilter(self, objeto, evento):
        """Antes de que Qt interprete el SQM: texto vacío o inválido → «—».

        QDoubleSpinBox revierte al último valor válido al salir del campo,
        así que con «-» o vacío el SQM no podía volver a quedarse sin
        informar (lo pidió el usuario); al no poder leerse el texto se
        pone 0, que es el valor especial «—».
        """
        # FocusOut, o las teclas que hacen interpretar el texto (Enter/Tab).
        sale_o_interpreta = evento.type() == QEvent.Type.FocusOut or (
            evento.type() == QEvent.Type.KeyPress
            and evento.key()
            in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab)
        )
        if objeto is self._sqm and sale_o_interpreta:
            self._sqm_a_vacio_si_invalido()
        return super().eventFilter(objeto, evento)

    def _sqm_a_vacio_si_invalido(self) -> None:
        """Si el texto del SQM no es número (vacío, «-»…), lo deja en «—»."""
        cuerpo = self._sqm.lineEdit().text().replace(self._sqm.suffix(), "").strip()
        try:
            float(cuerpo.replace(",", "."))
        except ValueError:
            self._sqm.setValue(0.0)

    def _refrescar_cielo(self) -> None:
        """Bortle/SQM cambiados (o ficha cargada) → esquemático al día."""
        self._sitio.set_cielo(self._bortle.currentData(), self._sqm_actual())

    def _sqm_actual(self) -> float | None:
        """SQM informado (``None`` si está en «—», que es 0)."""
        return self._sqm.value() if self._sqm.value() > 0 else None

    def _seeing_actual(self) -> float | None:
        """Seeing informado (``None`` si está en «—», que es 0)."""
        return self._seeing.value() if self._seeing.value() > 0 else None

    # -- acciones ----------------------------------------------------------

    def _nueva(self) -> None:
        """Ficha en blanco en memoria: no se inserta nada hasta «Guardar»."""
        self._cargando = True
        self._lista.setCurrentRow(-1)
        self._cargando = False
        self._cargar(None)
        self._nombre.setFocus()

    def _guardar(self) -> None:
        """Persiste la ubicación: create si es nueva, update si venía de la base."""
        obstaculos, fuentes, mapa, considerar = self._sitio.valores()
        ubicacion = Location(
            id=self._ubicacion_id,
            name=self._nombre.text().strip(),
            latitude=self._latitud.value(),
            longitude=self._longitud.value(),
            altitude_m=(self._altitud.value() or None),
            utc_offset_hours=(self._huso.value() if self._clock_mode.currentData() == "fixed" else None),
            timezone_id=((self._timezone.currentData() or "") if self._clock_mode.currentData() == "zone" else None),
            obstacles=obstaculos,
            lp=fuentes,
            bortle=self._bortle.currentData(),
            sqm=self._sqm_actual(),
            seeing_arcsec=self._seeing_actual(),
            consider_lp=considerar,
            lp_map=mapa,
        )
        try:
            if ubicacion.id is None:
                ubicacion.id = localizations.create(ubicacion)
            else:
                localizations.update(ubicacion)
        except ValueError as exc:
            QMessageBox.warning(self, "No se pudo guardar", str(exc))
            return
        self._recargar_lista(select_id=ubicacion.id)
        self.locations_changed.emit()

    def _eliminar(self) -> None:
        """Borra la ubicación tras avisar de equipos y mapa de CL afectados."""
        if self._ubicacion_id is None:
            return
        nombre = self._nombre.text().strip() or "esta ubicación"
        equipos = manager.count_setups_using("location", self._ubicacion_id)
        mapas = len(list_images("location", self._ubicacion_id))
        mensaje = f"¿Eliminar la ubicación «{nombre}»?"
        if equipos:
            mensaje += f"\n\n• {equipos} equipos quedarán sin ubicación (se desvinculan)."
        if mapas:
            mensaje += "\n• Se borra su mapa de CL."
        mensaje += "\n\nLas sesiones planificadas no se borran."
        boton = QMessageBox.StandardButton
        if (
            QMessageBox.question(
                self, "Eliminar ubicación", mensaje, boton.Yes | boton.No, boton.No
            )
            != boton.Yes
        ):
            return
        localizations.delete(self._ubicacion_id)
        self._recargar_lista(select_id=None)
        self.locations_changed.emit()
