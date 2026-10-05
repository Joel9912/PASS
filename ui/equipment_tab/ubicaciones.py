"""Subpestaña **Ubicaciones**: sección «Ubicaciones guardados» + ficha.

Layout simétrico al de Equipos, **sin `QSplitter`**: dos filas — la
superior es `[sección «Ubicaciones guardados» (ancho fijo 280) | barra
«Ubicación» + fila Geografía|Cielo]`, con la fila Geografía|Cielo
**fuera del scroll** para que siempre esté visible (su orden es
contractual: Geografía primero); en la inferior, un scroll **a todo el
ancho** con el ``SitioPanel`` (rosácea + esquemático + mapa de CL).

Regla UX global (§9): **nada se persiste hasta «Guardar ubicación»**:
«Nueva» deja la ficha en blanco en memoria y no se inserta fila hasta el
primer guardado; cambiar de fila descarta lo tecleado (cancelar no toca
la base, D-5).
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
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

from .componentes import sin_botones
from .sitio import SitioPanel


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

        # Fila superior: la sección de la lista a la izquierda (ancho
        # fijo, a la misma altura que la ficha) y, a la derecha, la
        # barra «Ubicación» con su Guardar y la fila Geografía|Cielo,
        # **fuera del scroll** para que siempre se vean.
        fila_sup = QHBoxLayout()
        fila_sup.setSpacing(10)
        fila_sup.addWidget(self._seccion_lista())
        derecha = QVBoxLayout()
        derecha.setContentsMargins(0, 0, 0, 0)
        derecha.setSpacing(10)
        derecha.addWidget(self._cabecera())
        # Guardada como atributo: el orden Geografía|Cielo es contractual
        # (lo comprueba el test de regresión de la revisión).
        self._fila_superior = self._fila_cielo_geografia()
        derecha.addWidget(self._fila_superior)
        fila_sup.addLayout(derecha, 1)
        layout.addLayout(fila_sup)

        # Fila inferior: el sitio (rosácea + esquemático + mapa) en un
        # panel con scroll vertical, **a todo el ancho**.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        ficha = QWidget()
        flay = QVBoxLayout(ficha)
        flay.setContentsMargins(0, 0, 6, 0)
        flay.setSpacing(10)
        self._sitio = SitioPanel()
        flay.addWidget(self._sitio)
        flay.addStretch(1)
        scroll.setWidget(ficha)
        layout.addWidget(scroll, 1)

        # Conectado al final: el esquemático ya existe cuando se carga
        # la primera fila (los spins emiten al rellenarse).
        self._bortle.currentIndexChanged.connect(self._refrescar_cielo)
        self._sqm.valueChanged.connect(self._refrescar_cielo)
        self._recargar_lista(select_id=None)

    # -- construcción ------------------------------------------------------

    def _seccion_lista(self) -> QFrame:
        """Sección «Ubicaciones guardados»: su lista con scroll propio y sus botones.

        Réplica de la de Equipos: ancho fijo (280 px) para quedar a la
        misma altura que la ficha de la derecha (barra + Geografía|Cielo,
        ~199 px); el título con word-wrap (`PanelTitle` a 13 pt pediría
        ~370 px en una línea) y la lista con el alto limitado a 100 px
        para rellenar la fila sin superar el sizeHint de la ficha (su
        sizeHint natural es de 192 px y dispararía el scroll de abajo).
        Los botones van en fila porque en columna no caben a esa
        altura; «🗑» lleva el «Eliminar» en tooltip (en fila con
        «➕ Nueva…» no caben los dos textos).
        """
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        marco.setFixedWidth(280)
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(12, 4, 12, 6)
        lay.setSpacing(6)

        titulo = QLabel("Ubicaciones guardados")
        titulo.setObjectName("PanelTitle")
        titulo.setWordWrap(True)
        lay.addWidget(titulo)

        self._lista = QListWidget()
        # El sizeHint natural de QListWidget (192 px) dispararía la fila
        # superior; con tope la sección cabe a la altura de la ficha
        # (barra + Geografía|Cielo ≈ 199 px) y la lista la rellena.
        self._lista.setMinimumHeight(40)
        self._lista.setMaximumHeight(100)
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

    def _cabecera(self) -> QFrame:
        """Cabecera de la ficha: título + «Guardar ubicación» (siempre visible)."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        lay = QHBoxLayout(marco)
        lay.setContentsMargins(12, 6, 12, 6)
        titulo = QLabel("Ubicación")
        titulo.setObjectName("PanelTitle")
        lay.addWidget(titulo)
        lay.addStretch(1)
        boton = QPushButton("Guardar ubicación")
        boton.setObjectName("PrimaryButton")
        boton.clicked.connect(self._guardar)
        lay.addWidget(boton)
        return marco

    def _fila_cielo_geografia(self) -> QFrame:
        """Fila superior: Geografía a la izquierda y Cielo (Bortle/SQM) a medio ancho."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        lay = QHBoxLayout(marco)
        lay.setContentsMargins(12, 6, 12, 10)
        lay.setSpacing(12)
        lay.addWidget(self._geografia(), 1)
        lay.addWidget(self._cielo(), 1)
        return marco

    def _cielo(self) -> QWidget:
        """Bortle (obligatorio), SQM cenital y Seeing típico; sin pista, que pasó a tooltips."""
        caja = QWidget()
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        titulo = QLabel("Cielo")
        titulo.setObjectName("PanelTitle")
        lay.addWidget(titulo)

        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(8)
        rejilla.setVerticalSpacing(6)
        rejilla.addWidget(QLabel("Bortle *"), 0, 0)
        self._bortle = QComboBox()
        self._bortle.addItem("Elige un nivel…", None)
        for nivel in range(1, 10):
            self._bortle.addItem(str(nivel), nivel)
        self._bortle.setToolTip(
            "1 = cielo pristineo · 9 = centro urbano iluminado. "
            "Obligatorio: la CL alimenta las decisiones de captura."
        )
        rejilla.addWidget(self._bortle, 0, 1)
        rejilla.addWidget(QLabel("SQM cenital"), 0, 2)
        self._sqm = QDoubleSpinBox()
        self._sqm.setRange(0.0, 30.0)
        self._sqm.setDecimals(2)
        self._sqm.setSpecialValueText("—")
        self._sqm.setSuffix(" mag/arcsec²")
        self._sqm.setToolTip(
            "Magnitud por segundo de arco cuadrado en el cenit (opcional). "
            "El informado es la referencia de la gráfica; en «—» se asume "
            "con el Bortle."
        )
        sin_botones(self._sqm)
        # Para que el SQM pueda volver a vacío: ver `eventFilter`.
        self._sqm.installEventFilter(self)
        rejilla.addWidget(self._sqm, 0, 3)
        # Seeing típico en la fila donde estaba la pista de Bortle/SQM
        # (el usuario pidió sustituirla por este campo): «—» = sin dato y
        # el muestreo del equipo, si lo hay, recurre a su resolución.
        rejilla.addWidget(QLabel("Seeing típico"), 1, 0)
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
        rejilla.addWidget(self._seeing, 1, 1)
        rejilla.setColumnStretch(1, 1)
        rejilla.setColumnStretch(3, 1)
        lay.addLayout(rejilla)
        return caja

    def _geografia(self) -> QWidget:
        """Coordenadas y huso en parejas (Nombre|Altitud, Latitud|Longitud)."""
        caja = QWidget()
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        titulo = QLabel("Geografía")
        titulo.setObjectName("PanelTitle")
        lay.addWidget(titulo)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        self._nombre = QLineEdit()
        self._nombre.setPlaceholderText("Casa, mirador del puerto…")
        form.addWidget(QLabel("Nombre *"), 0, 0)
        form.addWidget(self._nombre, 0, 1)
        self._altitud = QDoubleSpinBox()
        self._altitud.setRange(0.0, 9000.0)
        self._altitud.setDecimals(0)
        self._altitud.setSuffix(" m")
        self._altitud.setSpecialValueText("—")
        sin_botones(self._altitud)
        form.addWidget(QLabel("Altitud"), 0, 2)
        form.addWidget(self._altitud, 0, 3)
        self._latitud = QDoubleSpinBox()
        self._latitud.setRange(-90.0, 90.0)
        self._latitud.setDecimals(3)
        self._latitud.setSuffix("°")
        sin_botones(self._latitud)
        form.addWidget(QLabel("Latitud *"), 1, 0)
        form.addWidget(self._latitud, 1, 1)
        self._longitud = QDoubleSpinBox()
        self._longitud.setRange(-180.0, 180.0)
        self._longitud.setDecimals(3)
        self._longitud.setSuffix("°")
        sin_botones(self._longitud)
        form.addWidget(QLabel("Longitud *"), 1, 2)
        form.addWidget(self._longitud, 1, 3)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        lay.addLayout(form)

        huso = QHBoxLayout()
        self._auto = QCheckBox("Huso automático (hora solar local)")
        self._auto.setChecked(True)
        self._auto.setToolTip(
            "El Desfase se calcula de la longitud (regla de 15) y queda "
            "fijo: desmárcalo para indicarlo a mano."
        )
        huso.addWidget(self._auto)
        huso.addStretch(1)
        huso.addWidget(QLabel("Desfase"))
        self._huso = QDoubleSpinBox()
        self._huso.setRange(-12.0, 14.0)
        self._huso.setDecimals(1)
        self._huso.setSuffix(" h")
        self._huso.setEnabled(False)
        self._huso.setToolTip(
            "Con «Huso automático» muestra round(longitud/15); sin él, se "
            "indica a mano y se guarda."
        )
        sin_botones(self._huso)
        huso.addWidget(self._huso)
        self._auto.toggled.connect(self._al_cambiar_auto)
        self._longitud.valueChanged.connect(self._refrescar_desfase)
        lay.addLayout(huso)
        return caja

    # -- lista y carga -----------------------------------------------------

    def _recargar_lista(self, select_id: int | None) -> None:
        """Repuebla la lista y carga ``select_id`` (si no, la primera fila)."""
        self._cargando = True
        self._lista.clear()
        ids: list[int] = []
        for lugar in localizations.list_locations():
            item = QListWidgetItem(str(lugar["name"]))
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
                self._auto.setChecked(True)
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
                self._auto.setChecked(desfase is None)
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
        self._refrescar_cielo()
        self._boton_eliminar.setEnabled(self._ubicacion_id is not None)

    def _refrescar_desfase(self) -> None:
        """Con huso automático, el Desfase muestra ``round(longitud/15)``.

        La misma regla que el planificador (``local_utc_offset``): lo que
        se ve en la ficha es exactamente lo que se usará al planificar.
        """
        if self._auto.isChecked():
            self._huso.setValue(local_utc_offset(self._longitud.value()))

    def _al_cambiar_auto(self, marcado: bool) -> None:
        """Huso automático activado: recalcular y bloquear; si no, editable."""
        self._huso.setEnabled(not marcado)
        if marcado:
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
            utc_offset_hours=(None if self._auto.isChecked() else self._huso.value()),
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
