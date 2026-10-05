"""Subpestaña **Ubicaciones**: lista + ficha en panel (sin modal).

Layout simétrico al de Equipos: ``QSplitter`` con la lista y los botones
«Nueva…»/«Eliminar» a la izquierda; a la derecha, la cabecera con
«Guardar ubicación» (siempre visible) y, en scroll, la ficha completa —
Geografía, Horizonte (``HorizonWidget``) y Contaminación Lumínica
(``LightPollutionWidget``).

Regla UX global (§9): **nada se persiste hasta «Guardar ubicación»**:
«Nueva» deja la ficha en blanco en memoria y no se inserta fila hasta el
primer guardado; cambiar de fila descarta lo tecleado (cancelar no toca
la base, D-5).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from equipment import localizations, manager
from equipment.images import list_images
from equipment.models import Location

from .sitio import HorizonWidget, LightPollutionWidget


class UbicacionesTab(QWidget):
    """Gestión de ubicaciones: lista + ficha de sitio y CL en panel.

    Señales: ``locations_changed`` tras alta/baja/guardado; la ventana
    principal es quien decide a dónde reenviarla (barra de ubicación,
    combos de Equipo).
    """

    locations_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta el splitter lista/ficha y carga la primera ubicación si hay."""
        super().__init__(parent)
        self._ubicacion_id: int | None = None
        self._cargando = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Izquierda: lista + acciones.
        izquierda = QWidget()
        vlay = QVBoxLayout(izquierda)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(8)
        self._lista = QListWidget()
        self._lista.currentRowChanged.connect(self._al_elegir_fila)
        vlay.addWidget(self._lista, 1)
        # Botones apilados: en fila estrechaban el panel (mismos que Equipos).
        acciones = QVBoxLayout()
        boton_nueva = QPushButton("➕ Nueva…")
        boton_nueva.clicked.connect(self._nueva)
        acciones.addWidget(boton_nueva)
        self._boton_eliminar = QPushButton("🗑 Eliminar")
        self._boton_eliminar.clicked.connect(self._eliminar)
        self._boton_eliminar.setEnabled(False)
        acciones.addWidget(self._boton_eliminar)
        vlay.addLayout(acciones)
        splitter.addWidget(izquierda)

        # Derecha: cabecera (con su Guardar, siempre visible) + ficha en scroll.
        derecha = QWidget()
        dlay = QVBoxLayout(derecha)
        dlay.setContentsMargins(0, 0, 0, 0)
        dlay.setSpacing(10)
        dlay.addWidget(self._cabecera())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        ficha = QWidget()
        flay = QVBoxLayout(ficha)
        flay.setContentsMargins(0, 0, 6, 0)
        flay.setSpacing(10)
        flay.addWidget(self._geografia())
        self._horizonte = HorizonWidget()
        flay.addWidget(self._horizonte)
        self._cl = LightPollutionWidget()
        flay.addWidget(self._cl)
        flay.addStretch(1)
        scroll.setWidget(ficha)
        dlay.addWidget(scroll, 1)
        splitter.addWidget(derecha)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 780])
        layout.addWidget(splitter)

        self._recargar_lista(select_id=None)

    # -- construcción ------------------------------------------------------

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

    def _geografia(self) -> QFrame:
        """Coordenadas, altitud y huso horario (Auto = hora solar local)."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(12, 6, 12, 10)
        titulo = QLabel("Geografía")
        titulo.setObjectName("PanelTitle")
        lay.addWidget(titulo)
        form = QFormLayout()
        self._nombre = QLineEdit()
        self._nombre.setPlaceholderText("Casa, mirador del puerto…")
        form.addRow("Nombre *", self._nombre)
        self._latitud = QDoubleSpinBox()
        self._latitud.setRange(-90.0, 90.0)
        self._latitud.setDecimals(3)
        self._latitud.setSuffix("°")
        form.addRow("Latitud *", self._latitud)
        self._longitud = QDoubleSpinBox()
        self._longitud.setRange(-180.0, 180.0)
        self._longitud.setDecimals(3)
        self._longitud.setSuffix("°")
        form.addRow("Longitud *", self._longitud)
        self._altitud = QDoubleSpinBox()
        self._altitud.setRange(0.0, 9000.0)
        self._altitud.setDecimals(0)
        self._altitud.setSuffix(" m")
        self._altitud.setSpecialValueText("—")
        form.addRow("Altitud", self._altitud)

        huso = QHBoxLayout()
        self._auto = QCheckBox("Huso automático (hora solar local)")
        self._auto.setChecked(True)
        self._auto.setToolTip(
            "Sin desfase fijo se usa la longitud como hora local: una "
            "aproximación suficiente para sitios sin horario de verano."
        )
        huso.addWidget(self._auto)
        huso.addStretch(1)
        huso.addWidget(QLabel("Desfase"))
        self._huso = QDoubleSpinBox()
        self._huso.setRange(-12.0, 14.0)
        self._huso.setDecimals(1)
        self._huso.setSingleStep(0.5)
        self._huso.setSuffix(" h")
        self._huso.setEnabled(False)
        huso.addWidget(self._huso)
        lay.addLayout(huso)
        self._auto.toggled.connect(lambda marcado: self._huso.setEnabled(not marcado))
        lay.addLayout(form)
        return marco

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
                self._horizonte.set_obstacles({})
                self._cl.set_values({}, None, None, None, True)
            else:
                self._ubicacion_id = fila["id"]
                self._nombre.setText(str(fila.get("name") or ""))
                self._latitud.setValue(float(fila.get("latitude") or 0.0))
                self._longitud.setValue(float(fila.get("longitude") or 0.0))
                self._altitud.setValue(float(fila.get("altitude_m") or 0.0))
                desfase = fila.get("utc_offset_hours")
                self._auto.setChecked(desfase is None)
                if desfase is not None:
                    self._huso.setValue(float(desfase))
                self._horizonte.set_obstacles(fila.get("obstacles") or {})
                imagenes = list_images("location", fila["id"])
                self._cl.set_values(
                    fila.get("lp") or {},
                    fila.get("bortle"),
                    fila.get("sqm"),
                    imagenes[0]["path"] if imagenes else None,
                    bool(fila.get("consider_lp", True)),
                )
        finally:
            self._cargando = False
        self._boton_eliminar.setEnabled(self._ubicacion_id is not None)

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
        lp, bortle, sqm, mapa, considerar = self._cl.values()
        ubicacion = Location(
            id=self._ubicacion_id,
            name=self._nombre.text().strip(),
            latitude=self._latitud.value(),
            longitude=self._longitud.value(),
            altitude_m=(self._altitud.value() or None),
            utc_offset_hours=(None if self._auto.isChecked() else self._huso.value()),
            obstacles=self._horizonte.obstacles(),
            lp=lp,
            bortle=bortle,
            sqm=sqm,
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
