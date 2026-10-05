"""Subpestaña **Equipos**: lista, cabecera, sub-subpestañas y bloque Cálculos.

Layout: ``QSplitter`` horizontal — a la izquierda la lista de equipos con
«Nuevo…»/«Eliminar»; a la derecha la cabecera (nombre*, categoría,
ubicación, precio, peso, notas y «Guardar equipo») **fuera del scroll**
para que su Guardar esté siempre visible, y en el panel con scroll las
sub-subpestañas Telescopio / Cámara / Montura / Filtros y el bloque
«Cálculos».

Regla UX global (§9): **nada se persiste hasta «Guardar equipo»**: lo que
toca las piezas globales lo decide su propio botón «Guardar componente»
(``componentes.py``). Cambiar de fila en la lista sin guardar descarta lo
tecleado (es el «cancelar» de D-5). El bloque «Cálculos» sí se recalcula en
vivo: es estado en memoria de lo que hay en pantalla, no una lectura de la
base.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from db.settings import get_float
from equipment import localizations, manager
from equipment.images import list_images
from equipment.metrics import calculos
from equipment.models import CATEGORIES, EquipmentSetup

from .componentes import CameraForm, FiltersPanel, MountForm, PartEditor, TelescopeForm


def _formato(valor: float | None, unidad: str = "") -> str:
    """Pinta una métrica: «—» si falta el dato, 2 decimales con unidad si no."""
    return "—" if valor is None else f"{valor:.2f}{unidad}"


class EquiposTab(QWidget):
    """Gestión de equipos: lista + ficha con sub-subpestañas y Cálculos.

    Señales: ``setups_changed`` tras alta/baja/guardado de un equipo **o de
    una pieza/filtro** (los componentes cambian lo que pinta Planificación);
    la ventana principal es quien decide a dónde reenviarla.
    """

    setups_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta el splitter lista/ficha y carga el primer equipo si hay."""
        super().__init__(parent)
        self._setup_id: int | None = None
        self._imagenes_setup: list[str] = []
        self._cargando = False
        self._editores: list[PartEditor] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Izquierda: lista + acciones (siempre visibles, no scrollean).
        izquierda = QWidget()
        vlay = QVBoxLayout(izquierda)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(8)
        self._lista = QListWidget()
        self._lista.currentRowChanged.connect(self._al_elegir_fila)
        vlay.addWidget(self._lista, 1)
        acciones = QHBoxLayout()
        boton_nuevo = QPushButton("➕ Nuevo…")
        boton_nuevo.clicked.connect(self._nuevo)
        acciones.addWidget(boton_nuevo)
        self._boton_eliminar = QPushButton("🗑 Eliminar")
        self._boton_eliminar.clicked.connect(self._eliminar)
        self._boton_eliminar.setEnabled(False)
        acciones.addWidget(self._boton_eliminar)
        vlay.addLayout(acciones)
        splitter.addWidget(izquierda)

        # Derecha: cabecera con «Guardar equipo» SIEMPRE visible (fuera del
        # scroll, igual que en Ubicaciones) y, debajo, sub-subpestañas y
        # cálculos en un panel con scroll vertical.
        derecha = QWidget()
        dlay = QVBoxLayout(derecha)
        dlay.setContentsMargins(0, 0, 0, 0)
        dlay.setSpacing(10)
        dlay.addWidget(self._cabecera())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contenido = QWidget()
        interior = QVBoxLayout(contenido)
        interior.setContentsMargins(0, 0, 6, 0)
        interior.setSpacing(10)
        interior.addWidget(self._subpestanas())
        interior.addWidget(self._bloque_calculos())
        interior.addStretch(1)
        scroll.setWidget(contenido)
        dlay.addWidget(scroll, 1)
        splitter.addWidget(derecha)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 760])
        layout.addWidget(splitter)

        # Cableado interno: los cálculos viven de cualquier cambio en
        # pantalla; las piezas guardadas refrescan combos y avisan fuera.
        for editor in self._editores:
            editor.changed.connect(self._recalcular)
            editor.saved.connect(self._tras_pieza_guardada)
        self._filtros.saved.connect(self.setups_changed.emit)
        self._recargar_lista(select_id=None)

    # -- construcción ------------------------------------------------------

    def _cabecera(self) -> QFrame:
        """Cabecera del equipo: identidad, precio/peso, notas y su «Guardar»."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(12, 6, 12, 10)
        lay.setSpacing(8)

        fila_titulo = QHBoxLayout()
        titulo = QLabel("Equipo")
        titulo.setObjectName("PanelTitle")
        fila_titulo.addWidget(titulo)
        fila_titulo.addStretch(1)
        self._boton_guardar = QPushButton("Guardar equipo")
        self._boton_guardar.setObjectName("PrimaryButton")
        self._boton_guardar.clicked.connect(self._guardar)
        fila_titulo.addWidget(self._boton_guardar)
        lay.addLayout(fila_titulo)

        form = QFormLayout()
        self._nombre = QLineEdit()
        self._nombre.setPlaceholderText("Equipo de viaje, montura fija…")
        form.addRow("Nombre *", self._nombre)
        self._categoria = QComboBox()
        for clave, etiqueta in CATEGORIES.items():
            self._categoria.addItem(etiqueta, clave)
        form.addRow("Categoría", self._categoria)
        self._ubicacion = QComboBox()
        form.addRow("Ubicación", self._ubicacion)
        self._precio = QDoubleSpinBox()
        self._precio.setRange(0.0, 100000.0)
        self._precio.setDecimals(0)
        self._precio.setSuffix(" €")
        self._precio.setSpecialValueText("—")
        form.addRow("Precio", self._precio)
        self._peso = QDoubleSpinBox()
        self._peso.setRange(0.0, 300.0)
        self._peso.setDecimals(1)
        self._peso.setSuffix(" kg")
        self._peso.setSpecialValueText("—")
        form.addRow("Peso", self._peso)
        self._notas = QLineEdit()
        self._notas.setPlaceholderText("Notas (opcional)")
        form.addRow("Notas", self._notas)
        lay.addLayout(form)
        self.reload_locations()
        return marco

    def _subpestanas(self) -> QTabWidget:
        """Telescopio y Cámara en dos columnas (Principal/Guía), Montura y Filtros."""
        tabs = QTabWidget()
        tabs.addTab(self._columna_doble("telescope", TelescopeForm), "Telescopio")
        tabs.addTab(self._columna_doble("camera", CameraForm), "Cámara")
        tabs.addTab(self._columna_montura(), "Montura")
        tabs.addTab(self._columna_filtros(), "Filtros")
        return tabs

    def _columna_doble(self, kind: str, formularios: type) -> QWidget:
        """Dos ``PartEditor`` del mismo tipo: pieza principal y pieza de guía."""
        contenedor = QWidget()
        fila = QHBoxLayout(contenedor)
        principal = PartEditor(kind, formularios(), "Principal")
        guia = PartEditor(kind, formularios(), "Guía")
        fila.addWidget(principal)
        fila.addWidget(guia)
        self._editores += [principal, guia]
        if kind == "telescope":
            self._tel_principal, self._tel_guia = principal, guia
        else:
            self._cam_principal, self._cam_guia = principal, guia
        return contenedor

    def _columna_montura(self) -> QWidget:
        """Un único editor de montura (no hay montura de guía)."""
        contenedor = QWidget()
        fila = QHBoxLayout(contenedor)
        montura = PartEditor("mount", MountForm(), "Montura")
        self._montura = montura
        self._editores.append(montura)
        fila.addWidget(montura)
        fila.addStretch(1)
        return contenedor

    def _columna_filtros(self) -> QWidget:
        """Tabla de filtros: casilla de asignación + CRUD de los globales."""
        contenedor = QWidget()
        fila = QHBoxLayout(contenedor)
        self._filtros = FiltersPanel()
        fila.addWidget(self._filtros)
        fila.addStretch(1)
        return contenedor

    def _bloque_calculos(self) -> QFrame:
        """«Cálculos» en solo lectura: escala, Dawes, F/d y veredicto."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(12, 6, 12, 10)
        lay.setSpacing(8)
        titulo = QLabel("Cálculos")
        titulo.setObjectName("PanelTitle")
        lay.addWidget(titulo)
        form = QFormLayout()
        self._escala = QLabel("—")
        self._dawes = QLabel("—")
        self._relacion = QLabel("—")
        self._muestreo = QLabel("—")
        form.addRow("Escala de imagen", self._escala)
        form.addRow("Resolución óptica (Dawes)", self._dawes)
        form.addRow("Relación focal", self._relacion)
        form.addRow("Muestreo", self._muestreo)
        lay.addLayout(form)
        self._pista_calculos = QLabel(
            "Sobre el telescopio y la cámara principales en pantalla."
        )
        self._pista_calculos.setObjectName("HintLabel")
        self._pista_calculos.setWordWrap(True)
        lay.addWidget(self._pista_calculos)
        return marco

    # -- lista y carga -----------------------------------------------------

    def reload_locations(self) -> None:
        """Repuebla el combo de ubicaciones (lo llama ``EquipmentPage``)."""
        actual = self._ubicacion.currentData()
        self._ubicacion.blockSignals(True)
        self._ubicacion.clear()
        self._ubicacion.addItem("(sin ubicación)", None)
        for lugar in localizations.list_locations():
            self._ubicacion.addItem(str(lugar["name"]), lugar["id"])
        self._ubicacion.setCurrentIndex(max(0, self._ubicacion.findData(actual)))
        self._ubicacion.blockSignals(False)

    def _recargar_lista(self, select_id: int | None) -> None:
        """Repuebla la lista y carga ``select_id`` (si no, la primera fila)."""
        self._cargando = True
        self._lista.clear()
        ids: list[int] = []
        for equipo in manager.list_setups():
            crudo = str(equipo.get("category") or "")
            etiqueta = CATEGORIES.get(crudo, crudo.replace("_", " "))
            texto = f"{equipo['name']} · {etiqueta}" if etiqueta else str(equipo["name"])
            item = QListWidgetItem(texto)
            item.setData(Qt.ItemDataRole.UserRole, equipo["id"])
            self._lista.addItem(item)
            ids.append(equipo["id"])
        objetivo = select_id if select_id in ids else (ids[0] if ids else None)
        if objetivo is not None:
            self._lista.setCurrentRow(ids.index(objetivo))
        self._cargando = False
        self._cargar(objetivo)

    def _al_elegir_fila(self, fila: int) -> None:
        """Selección del usuario: carga ese equipo (o la ficha en blanco)."""
        if self._cargando:
            return
        item = self._lista.item(fila)
        self._cargar(item.data(Qt.ItemDataRole.UserRole) if item else None)

    def _cargar(self, setup_id: int | None) -> None:
        """Vierte un equipo de la base en todo el panel (None = en blanco)."""
        self._cargando = True
        try:
            fila = manager.get(setup_id) if setup_id is not None else None
            if fila is None:
                self._setup_id = None
                self._imagenes_setup = []
                self._nombre.clear()
                self._categoria.setCurrentIndex(
                    max(0, self._categoria.findData("general"))
                )
                self._ubicacion.setCurrentIndex(0)
                self._precio.setValue(0.0)
                self._peso.setValue(0.0)
                self._notas.clear()
                for editor in self._editores:
                    editor.cargar(None)
                self._filtros.set_filter_ids([])
            else:
                self._setup_id = fila["id"]
                self._imagenes_setup = [
                    imagen["path"] for imagen in list_images("setup", fila["id"])
                ]
                self._nombre.setText(str(fila.get("name") or ""))
                self._asegurar_categoria(str(fila.get("category") or "general"))
                self._ubicacion.setCurrentIndex(
                    max(0, self._ubicacion.findData(fila.get("location_id")))
                )
                self._precio.setValue(float(fila.get("price_eur") or 0.0))
                self._peso.setValue(float(fila.get("weight_kg") or 0.0))
                self._notas.setText(str(fila.get("notes") or ""))
                self._tel_principal.cargar(fila.get("telescope_id"))
                self._tel_guia.cargar(fila.get("guide_telescope_id"))
                self._cam_principal.cargar(fila.get("camera_id"))
                self._cam_guia.cargar(fila.get("guide_camera_id"))
                self._montura.cargar(fila.get("mount_id"))
                self._filtros.set_filter_ids(list(fila.get("filter_ids") or []))
        finally:
            self._cargando = False
        self._boton_eliminar.setEnabled(self._setup_id is not None)
        self._recalcular()

    def _asegurar_categoria(self, categoria: str) -> None:
        """Selecciona la categoría en el combo (y la añade si venía de otra BD)."""
        if self._categoria.findData(categoria) == -1:
            self._categoria.addItem(categoria.replace("_", " ").capitalize(), categoria)
        self._categoria.setCurrentIndex(max(0, self._categoria.findData(categoria)))

    # -- acciones ----------------------------------------------------------

    def _nuevo(self) -> None:
        """Alta en memoria: pide nombre y deja la ficha lista para «Guardar»."""
        nombre, ok = QInputDialog.getText(self, "Nuevo equipo", "Nombre del equipo:")
        if not ok or not nombre.strip():
            return
        self._cargando = True
        self._lista.setCurrentRow(-1)  # ninguna fila seleccionada
        self._cargando = False
        self._setup_id = None
        self._imagenes_setup = []
        self._nombre.setText(nombre.strip())
        self._categoria.setCurrentIndex(max(0, self._categoria.findData("general")))
        self._ubicacion.setCurrentIndex(0)
        self._precio.setValue(0.0)
        self._peso.setValue(0.0)
        self._notas.clear()
        for editor in self._editores:
            editor.cargar(None)
        self._filtros.set_filter_ids([])
        self._boton_eliminar.setEnabled(False)
        self._recalcular()
        self._nombre.setFocus()

    def _guardar(self) -> None:
        """Persiste el equipo: create si es nuevo, update si venía de la base."""
        setup = EquipmentSetup(
            id=self._setup_id,
            name=self._nombre.text().strip(),
            category=self._categoria.currentData() or "general",
            location_id=self._ubicacion.currentData(),
            telescope_id=self._tel_principal.selected_id(),
            guide_telescope_id=self._tel_guia.selected_id(),
            camera_id=self._cam_principal.selected_id(),
            guide_camera_id=self._cam_guia.selected_id(),
            mount_id=self._montura.selected_id(),
            filter_ids=self._filtros.filter_ids(),
            price_eur=(self._precio.value() or None),
            weight_kg=(self._peso.value() or None),
            notes=self._notas.text().strip(),
            images=list(self._imagenes_setup),  # D-5: la lista es la verdad
        )
        try:
            if setup.id is None:
                manager.create(setup)
            else:
                manager.update(setup)
        except ValueError as exc:
            QMessageBox.warning(self, "No se pudo guardar", str(exc))
            return
        self._recargar_lista(select_id=setup.id)
        self.setups_changed.emit()

    def _eliminar(self) -> None:
        """Borra el equipo (no sus componentes) tras avisar de sesiones e imágenes."""
        if self._setup_id is None:
            return
        nombre = self._nombre.text().strip() or "este equipo"
        sesiones = manager.count_sessions(self._setup_id)
        imagenes = len(list_images("setup", self._setup_id))
        mensaje = f"¿Eliminar el equipo «{nombre}»?"
        if sesiones:
            mensaje += f"\n\n• {sesiones} sesiones planificadas quedarán desvinculadas."
        if imagenes:
            mensaje += f"\n• Se borrarán {imagenes} imágenes adjuntas."
        mensaje += "\n\nLos componentes no se borran: solo este equipo."
        boton = QMessageBox.StandardButton
        if (
            QMessageBox.question(
                self, "Eliminar equipo", mensaje, boton.Yes | boton.No, boton.No
            )
            != boton.Yes
        ):
            return
        manager.delete(self._setup_id)
        self._recargar_lista(select_id=None)
        self.setups_changed.emit()

    # -- cálculos ----------------------------------------------------------

    def _recalcular(self) -> None:
        """Repinta «Cálculos» con la pareja principal en pantalla (en vivo)."""
        telescopio = self._tel_principal.form.a_modelo()
        camara = self._cam_principal.form.a_modelo()
        filas = calculos(
            telescopio,
            camara,
            get_float("sampling_under_ratio", 1.0),
            get_float("sampling_over_ratio", 0.5),
        )
        self._escala.setText(_formato(filas["escala"], " ″/px"))
        self._dawes.setText(_formato(filas["dawes"], " ″"))
        self._relacion.setText(
            f"F/{filas['relacion_focal']:.1f}" if filas["relacion_focal"] else "—"
        )
        self._muestreo.setText(filas["muestreo"] or "—")
        faltan = []
        if telescopio.focal_mm is None:
            faltan.append("focal")
        if camara.pixel_size_um is None:
            faltan.append("píxel de la cámara")
        if telescopio.aperture_mm is None:
            faltan.append("apertura")
        base = "Sobre el telescopio y la cámara principales en pantalla."
        self._pista_calculos.setText(
            f"{base} Falta: {' · '.join(faltan)}." if faltan else base
        )

    def _tras_pieza_guardada(self) -> None:
        """Una pieza cambió en la base: repuebla combos y avisa a la ventana."""
        for editor in self._editores:
            editor.reload()  # conserva su selección y recalcula
        self.setups_changed.emit()
