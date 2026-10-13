"""Subpestaña **Planificación**: planetario, encuadre, tránsito y plan de captura.

Layout (según el mockup del usuario), dos columnas con el encuadre a la
izquierda y la parte temporal a la derecha:

```
Target: [M31 ▼]  Fecha: [📅]  Equipo: [Setup ▼]
┌─ Visual del Planetario ─────┐ ┌─ Curva de Tránsito ──────────────┐
│ estrellas · target · rejilla│ │ altitud + sep. lunar + ventanas  │
│ [rectángulo de encuadre]    │ ├─ Plan de Captura ────────────────┤
├─ Editor de Encuadre ────────┤ │ Top 5 fechas con su ventana ★   │
│ RA / Dec / FOV / teselas    │ ├─ Parámetros de Sesión ───────────┤
└─────────────────────────────┘ │ Nombre · Exposición · Notas      │
                                │        [💾 Guardar Sesión]       │
                                └───────────────────────────────────┘
```

La ubicación (lat/long/desfase) **no** vive aquí: la aporta la barra
compartida del Planificador vía :meth:`set_location`.

El encuadre solo se activa si el equipo seleccionado tiene focal, resolución
y tamaño de píxel; sin esos datos no se dibuja rectángulo alguno (decisión
del usuario: nunca se inventa un FOV).
"""
from __future__ import annotations

import sqlite3
from datetime import date

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from equipment.manager import list_setups
from equipment.models import CATEGORIES
from planners import personal_catalog, planned_sessions
from planners.capture_plan import best_dates
from planners.framing import calculate_fov
from planners.moon_distance import format_hour_range
from planners.session_draft import validate as validate_draft
from planners.transit import night_curve
from ui.draft_recovery import DraftRecovery, refresh_without_starting_draft

from ..widgets import TransitCurve, crear_tabla_filas, fila_seleccionada, window_lines
from .planetario_visual import PlanetarioVisual

#: Etiqueta de "sin encuadre" cuando el equipo no da FOV.
NO_FRAMING_TEXT = "Sin encuadre: faltan datos de la cámara o del telescopio"

#: Columnas del plan de captura. «Alt. noche» es la altura máxima que el
#: objeto alcanza dentro de la ventana de ESA noche: es lo que puntúa
#: (la culminación sola sería la misma en todas las filas).
PLAN_COLUMNS: tuple[str, ...] = (
    "#", "Fecha", "Tránsito", "Alt. noche", "Sep. lunar", "Luna", "★ Ideal",
)


class PlanificacionTab(QWidget):
    """Planetario + encuadre + curva + plan de captura + sesión a guardar."""

    session_saved = pyqtSignal(int)          # id de la sesión creada
    # API pública prevista (A-14): sin consumidor hoy; el Planetario/
    # Resumen se suscribirán a los cambios de target cuando se implementen.
    target_changed = pyqtSignal(str, str)    # object_id, catalog

    #: Noches evaluadas en el plan de captura.
    PLAN_DAYS = 30
    #: Fechas que se muestran (los primeros N del ranking).
    PLAN_TOP = 5

    def __init__(self, parent: QWidget | None = None) -> None:
        """Estado inicial, barra de herramientas y las dos columnas (planetario | temporal)."""
        super().__init__(parent)

        self._latitude: float | None = None
        self._longitude: float | None = None
        self._utc_offset_hours: float | None = None
        self._fov: tuple[float, float] | None = None   # grados, del equipo
        self._targets: list[dict] = []
        self._setups: list[dict] = []
        self._plan: list[dict] = []
        self._updating_view = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        root.addLayout(self._build_toolbar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        root.addWidget(splitter, 1)

        self.reload_targets()
        self.reload_setups()
        self._draft = DraftRecovery(
            self, "planner", "Hay una sesión sin terminar de planificar. ¿Deseas continuar?",
            self._draft_snapshot, self._restore_draft, self._block_draft,
        )
        root.addWidget(self._draft.label)
        root.addWidget(self._draft.button)
        self._draft_location_label = QLabel("")
        self._draft_location_label.setObjectName("HintLabel")
        self._draft_location_label.setWordWrap(True)
        root.addWidget(self._draft_location_label)
        for control, signal in (
            (self._session_name, "textChanged"), (self._notes, "textChanged"),
            (self._exposure, "valueChanged"), (self._date, "dateChanged"),
            (self._target, "currentIndexChanged"), (self._setup, "currentIndexChanged"),
            (self._ra, "valueChanged"), (self._dec, "valueChanged"),
            (self._tiles_x, "valueChanged"), (self._tiles_y, "valueChanged"),
        ):
            getattr(control, signal).connect(self._draft.changed)

    def showEvent(self, event) -> None:
        """Ofrece continuar solo al entrar en Planificación, no al arrancar PASS."""
        super().showEvent(event)
        self._draft.entered()

    def _block_draft(self, blocked: bool) -> None:
        """Impide reemplazar un borrador aplazado con una sesión nueva."""
        for control in (
            self._target, self._date, self._setup, self._ra, self._dec,
            self._tiles_x, self._tiles_y, self._session_name, self._exposure,
            self._notes, self._save_button, self._plan_button, self._planetario,
        ):
            control.setEnabled(not blocked)
        if not blocked:
            self._tiles_x.setEnabled(bool(self._fov))
            self._tiles_y.setEnabled(bool(self._fov))

    def _draft_snapshot(self) -> dict:
        """Captura entradas y encuadre; las recomendaciones se recalculan, no se certifican."""
        target, setup = self._current_target(), self._current_setup()
        return {
            "target": [str(target["object_id"]), str(target["catalog"])] if target else None,
            "setup_id": setup["id"] if setup else None,
            "date": self._date_iso(), "ra": self._ra.value(), "dec": self._dec.value(),
            "tiles_x": self._tiles_x.value(), "tiles_y": self._tiles_y.value(),
            "name": self._session_name.text(), "exposure": self._exposure.value(),
            "notes": self._notes.text(),
            "location": [self._latitude, self._longitude, self._utc_offset_hours],
            "view_fov": self._planetario.view[2],
            "frame_fov": list(self._fov) if self._fov else None,
        }

    def _restore_draft(self, data: dict) -> None:
        """Prevalida referencias para no sustituir objetivo o equipo por el primero de la lista."""
        validate_draft(data)
        target_index = -1
        if data["target"] is not None:
            target_index = next((
                i for i, row in enumerate(self._targets)
                if [str(row["object_id"]), str(row["catalog"])] == data["target"]
            ), -1)
            if target_index < 0:
                raise ValueError("El objetivo ya no está en el catálogo personal")
        setup_index = -1
        if data["setup_id"] is not None:
            setup_index = next((i for i, row in enumerate(self._setups) if row["id"] == data["setup_id"]), -1)
            if setup_index < 0:
                raise ValueError("El equipo ya no existe")
        controls = (self._target, self._setup, self._date, self._ra, self._dec,
                    self._tiles_x, self._tiles_y, self._session_name, self._exposure, self._notes)
        for control in controls:
            control.blockSignals(True)
        try:
            self._target.setCurrentIndex(target_index)
            self._setup.setCurrentIndex(setup_index)
            self._date.setDate(QDate.fromString(data["date"], "yyyy-MM-dd"))
            self._latitude, self._longitude, self._utc_offset_hours = data["location"]
            if self._latitude is not None:
                self._draft_location_label.setText(
                    f"Ubicación recuperada: {self._latitude:g}°, {self._longitude:g}°; "
                    f"desfase UTC: {self._utc_offset_hours if self._utc_offset_hours is not None else 'inferido'}. "
                    "Para cambiarla, elige una ubicación en Búsqueda."
                )
            self._session_name.setText(data["name"])
            self._exposure.setValue(data["exposure"])
            self._notes.setText(data["notes"])
            self._on_target_changed()
            self._on_setup_changed()
            current_fov = list(self._fov) if self._fov else None
            if current_fov != data["frame_fov"]:
                self._draft_location_label.setText(
                    self._draft_location_label.text() + "\n"
                    "El campo de visión del equipo cambió; se recalculó con sus datos actuales. "
                    "Revisa el encuadre antes de guardar la sesión."
                )
            self._ra.setValue(data["ra"])
            self._dec.setValue(data["dec"])
            self._tiles_x.setValue(data["tiles_x"])
            self._tiles_y.setValue(data["tiles_y"])
            self._updating_view = True
            try:
                self._planetario.set_center(data["ra"], data["dec"])
                self._planetario.set_fov_deg(data["view_fov"])
            finally:
                self._updating_view = False
            self._apply_framing()
        finally:
            for control in controls:
                control.blockSignals(False)

    # ------------------------------------------------------------------ #
    #                            B A R R A                                #
    # ------------------------------------------------------------------ #
    def _build_toolbar(self) -> QHBoxLayout:
        """Barra superior: Target, Fecha y Equipo (los tres disparan recálculos)."""
        bar = QHBoxLayout()
        bar.setSpacing(8)

        bar.addWidget(QLabel("Target"))
        self._target = QComboBox()
        self._target.setMinimumWidth(230)
        self._target.currentIndexChanged.connect(self._on_target_changed)
        bar.addWidget(self._target)

        bar.addWidget(QLabel("Fecha"))
        # Fecha propia de Planificación: independiente de la de Búsqueda
        # (efemérides) a propósito (A-33): cada pantalla se ajusta por su
        # cuenta; sincronizarlas sería una decisión futura.
        self._date = QDateEdit()
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("dd/MM/yyyy")
        self._date.setDate(QDate.currentDate())
        self._date.dateChanged.connect(self._on_date_changed)
        bar.addWidget(self._date)

        bar.addWidget(QLabel("Equipo"))
        self._setup = QComboBox()
        self._setup.setMinimumWidth(230)
        self._setup.currentIndexChanged.connect(self._on_setup_changed)
        bar.addWidget(self._setup)

        bar.addStretch(1)
        return bar

    # ------------------------------------------------------------------ #
    #                        C O L U M N A   I Z Q                        #
    # ------------------------------------------------------------------ #
    def _build_left(self) -> QWidget:
        """Columna izquierda: planetario (con «Reset vista») y editor de encuadre."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Visual del planetario")
        title.setObjectName("PanelTitle")
        header.addWidget(title)
        header.addStretch(1)
        reset = QPushButton("Reset vista")
        reset.clicked.connect(lambda: self._planetario.reset_view())
        header.addWidget(reset)
        layout.addLayout(header)

        self._planetario = PlanetarioVisual()
        self._planetario.setMinimumHeight(340)
        self._planetario.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._planetario.view_changed.connect(self._on_view_changed)
        self._planetario.object_clicked.connect(self._on_planet_object_clicked)
        layout.addWidget(self._planetario, 1)

        layout.addWidget(self._build_framing_editor())
        return panel

    def _build_framing_editor(self) -> QGroupBox:
        """RA/Dec y teselas a mano, aviso de FOV y «Actualizar desde planetario»."""
        box = QGroupBox("Editor de encuadre")
        form = QFormLayout(box)
        form.setSpacing(8)

        self._ra = QDoubleSpinBox()
        self._ra.setRange(0.0, 24.0)
        self._ra.setDecimals(4)
        self._ra.setSingleStep(0.1)
        self._ra.setSuffix(" h")
        self._ra.valueChanged.connect(self._on_editor_changed)
        form.addRow("Centro RA (J2000)", self._ra)

        self._dec = QDoubleSpinBox()
        self._dec.setRange(-90.0, 90.0)
        self._dec.setDecimals(4)
        self._dec.setSingleStep(0.5)
        self._dec.setSuffix("°")
        self._dec.valueChanged.connect(self._on_editor_changed)
        form.addRow("Centro Dec (J2000)", self._dec)

        self._fov_label = QLabel(NO_FRAMING_TEXT)
        self._fov_label.setObjectName("HintLabel")
        self._fov_label.setWordWrap(True)
        form.addRow("FOV", self._fov_label)

        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(6)
        self._tiles_x = QSpinBox()
        self._tiles_x.setRange(1, 20)
        self._tiles_x.setSuffix(" ×")
        self._tiles_x.valueChanged.connect(self._on_editor_changed)
        self._tiles_y = QSpinBox()
        self._tiles_y.setRange(1, 20)
        self._tiles_y.valueChanged.connect(self._on_editor_changed)
        tiles_row.addWidget(self._tiles_x)
        tiles_row.addWidget(self._tiles_y)
        tiles_row.addStretch(1)
        form.addRow("Teselas", tiles_row)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        from_planet = QPushButton("Actualizar desde planetario")
        from_planet.clicked.connect(self._copy_from_planetarium)
        actions.addWidget(from_planet)
        actions.addStretch(1)
        form.addRow("", actions)
        return box

    # ------------------------------------------------------------------ #
    #                       C O L U M N A   D E R E C H A                 #
    # ------------------------------------------------------------------ #
    def _build_right(self) -> QWidget:
        """Columna derecha: curva de tránsito, plan de captura y formulario de sesión."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._curve = TransitCurve()
        layout.addWidget(self._curve)

        layout.addWidget(self._build_capture_plan())
        layout.addWidget(self._build_session_form())
        return panel

    def _build_capture_plan(self) -> QGroupBox:
        """Tabla de las mejores noches con su botón «Calcular plan» y ventana ★."""
        box = QGroupBox("Plan de captura")
        layout = QVBoxLayout(box)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        hint = QLabel(f"Ranking de las próximas {self.PLAN_DAYS} noches")
        hint.setObjectName("HintLabel")
        head.addWidget(hint)
        head.addStretch(1)
        self._plan_button = QPushButton("Calcular plan")
        self._plan_button.setObjectName("ApplyFilters")
        self._plan_button.setToolTip(
            "Recorre 30 noches con la malla gruesa y detalla las "
            f"mejores {self.PLAN_TOP}: puede tardar unos segundos."
        )
        self._plan_button.clicked.connect(self._calculate_plan)
        head.addWidget(self._plan_button)
        layout.addLayout(head)

        self._plan_table = crear_tabla_filas(list(PLAN_COLUMNS), altura_min=150)
        self._plan_table.itemSelectionChanged.connect(self._on_plan_selected)
        layout.addWidget(self._plan_table)

        self._window_label = QLabel("Pulsa «Calcular plan» para ver las noches.")
        self._window_label.setObjectName("HintLabel")
        self._window_label.setWordWrap(True)
        layout.addWidget(self._window_label)
        return box

    def _build_session_form(self) -> QGroupBox:
        """Nombre, exposición y notas con el botón «💾 Guardar sesión»."""
        box = QGroupBox("Parámetros de sesión")
        form = QFormLayout(box)
        # Espaciado justito: la columna derecha está al límite de su altura
        # y el marco de la curva ha consumido píxeles de más.
        form.setSpacing(6)

        self._session_name = QLineEdit()
        self._session_name.setPlaceholderText("Nombre de la sesión")
        form.addRow("Nombre", self._session_name)

        self._exposure = QSpinBox()
        self._exposure.setRange(1, 7200)
        self._exposure.setValue(300)
        self._exposure.setSuffix(" s")
        form.addRow("Exposición", self._exposure)

        self._notes = QLineEdit()
        self._notes.setPlaceholderText("Notas opcionales")
        form.addRow("Notas", self._notes)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        save = QPushButton("💾 Guardar sesión")
        self._save_button = save
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self._on_save_session)
        actions.addWidget(save)
        actions.addStretch(1)
        form.addRow("", actions)
        return box

    # ------------------------------------------------------------------ #
    #                           A P I   P Ú B L I C A                     #
    # ------------------------------------------------------------------ #
    @refresh_without_starting_draft
    def set_location(
        self, latitude: float, longitude: float, utc_offset_hours: float | None
    ) -> None:
        """Recibe la ubicación de la barra compartida: refresca curva e invalida plan."""
        self._latitude = latitude
        self._longitude = longitude
        self._utc_offset_hours = utc_offset_hours
        if hasattr(self, "_draft_location_label"):
            self._draft_location_label.clear()
        self._refresh_curve()
        self._invalidate_plan()
        if hasattr(self, "_draft") and self._draft.active:
            self._draft.flush()

    @refresh_without_starting_draft
    def reload_targets(self, keep_current: bool = True) -> None:
        """Vuelve a leer el catálogo personal (objetos y regiones)."""
        current = self._current_target()
        self._targets = personal_catalog.list_objects()
        self._target.blockSignals(True)
        self._target.clear()
        for row in self._targets:
            label = str(row.get("object_id") or "")
            if row.get("kind") == "region":
                label += "  · región"
            self._target.addItem(label, row)
        self._target.blockSignals(False)

        index = -1
        if keep_current and current is not None:
            for i, row in enumerate(self._targets):
                if (
                    row["object_id"] == current["object_id"]
                    and row["catalog"] == current["catalog"]
                ):
                    index = i
                    break
        if self._targets:
            # blockSignals durante setCurrentIndex: si no, salta también
            # por la señal y _on_target_changed corre dos veces (M-04).
            self._target.blockSignals(True)
            self._target.setCurrentIndex(max(0, index))
            self._target.blockSignals(False)
            self._on_target_changed()
        else:
            self._target.addItem("(sin elementos)", None)
            self._on_target_changed()

    @refresh_without_starting_draft
    def reload_setups(self) -> None:
        """Vuelve a leer los setups de equipo (para el FOV del encuadre)."""
        actual = self._setup.currentData()
        actual_id = actual.get("id") if isinstance(actual, dict) else None
        self._setups = [s for s in list_setups() if s.get("id") is not None]
        self._setup.blockSignals(True)
        self._setup.clear()
        seleccion = -1
        for position, setup in enumerate(self._setups):
            name = str(setup.get("name") or f"Setup {setup.get('id')}")
            # Etiqueta con acentos desde la fuente única (CATEGORIES, R2);
            # una categoría de otra BD (si la hubiera) se pinta tal cual.
            crudo = str(setup.get("category") or "")
            category = CATEGORIES.get(crudo, crudo.replace("_", " "))
            self._setup.addItem(f"{name} · {category}" if category else name, setup)
            if setup.get("id") == actual_id:
                seleccion = position
        # Reseleccionar por id: sin esto, repoblar saltaba al primer
        # setup y revalidaba el FOV/plan de un equipo que no era (M-19).
        if seleccion >= 0:
            self._setup.setCurrentIndex(seleccion)
        self._setup.blockSignals(False)
        self._on_setup_changed()

    def select_target(self, object_id: str, catalog: str) -> None:
        """Elige ``object_id``/``catalog`` como target (si está guardado).

        Lo usa la subpestaña Catálogo Personal al seleccionar una fila.
        """
        for index, row in enumerate(self._targets):
            if row["object_id"] == object_id and row["catalog"] == catalog:
                self._target.setCurrentIndex(index)
                return

    # ------------------------------------------------------------------ #
    #                        E S T A D O   I N T E R N O                  #
    # ------------------------------------------------------------------ #
    def _current_target(self) -> dict | None:
        """Fila del combo Target (``None`` si no hay o es «(sin elementos)»)."""
        data = self._target.currentData()
        return data if isinstance(data, dict) else None

    def _current_setup(self) -> dict | None:
        """Fila del combo Equipo (``None`` si no hay setup seleccionado)."""
        data = self._setup.currentData()
        return data if isinstance(data, dict) else None

    def _date_iso(self) -> str:
        """Fecha visible en ISO ``yyyy-MM-dd`` (el formato que usan los cálculos)."""
        return self._date.date().toString("yyyy-MM-dd")

    def _has_location(self) -> bool:
        """¿Hay lat y long? Sin ellas no hay curva ni plan (nunca se inventa ubicación)."""
        return self._latitude is not None and self._longitude is not None

    # ------------------------------------------------------------------ #
    #                        R E A C C I O N E S                          #
    # ------------------------------------------------------------------ #
    def _on_target_changed(self, *_args) -> None:
        """Nuevo target: centra el planetario, vuelca RA/Dec y recalcula curva y plan.

        Emite ``target_changed`` al final para que el resto de la página
        (p. ej. Búsqueda) pueda reaccionar.
        """
        target = self._current_target()
        if target is None:
            self._curve.clear()
            self._invalidate_plan()
            self._planetario.clear_target()
            self._planetario.clear_framing()
            self._session_name.setPlaceholderText("")
            return
        object_id = str(target["object_id"])
        catalog = str(target["catalog"])
        self._planetario.set_target(object_id, catalog)
        ra = target.get("ra_hours")
        dec = target.get("dec_deg")
        if ra is not None and dec is not None:
            self._updating_view = True
            self._ra.setValue(float(ra))
            self._dec.setValue(float(dec))
            self._updating_view = False
        if not self._session_name.text().strip():
            self._session_name.setPlaceholderText(
                f"Sesión de {object_id} · {self._date_iso()}"
            )
        self._apply_framing()
        self._refresh_curve()
        self._invalidate_plan()
        self.target_changed.emit(object_id, catalog)

    def _on_date_changed(self, _qdate: QDate) -> None:
        """Cambio de fecha: la curva se recalcula y el plan calculado deja de valer."""
        self._refresh_curve()
        self._invalidate_plan()

    def _on_setup_changed(self, *_args) -> None:
        """Nuevo equipo: recalcula el FOV, habilita/deshabilita teselas y redibuja el encuadre."""
        setup = self._current_setup()
        self._fov = calculate_fov(setup) if setup else None
        if self._fov:
            major, minor = self._fov
            self._fov_label.setText(
                f"{major:.3f}° × {minor:.3f}° (calculado del equipo)"
            )
            self._tiles_x.setEnabled(True)
            self._tiles_y.setEnabled(True)
        else:
            self._fov_label.setText(NO_FRAMING_TEXT)
            self._tiles_x.setEnabled(False)
            self._tiles_y.setEnabled(False)
            self._planetario.clear_framing()
        self._apply_framing()
        self._invalidate_plan()

    def _on_editor_changed(self, *_args) -> None:
        """El usuario mueve el centro a mano → recoloca el planetario.

        ``_updating_view`` corta el bucle con ``_on_view_changed``: quien
        pinta el estado no vuelve a escribirlo.
        """
        if self._updating_view:
            return
        self._updating_view = True
        self._planetario.set_center(self._ra.value(), self._dec.value())
        self._updating_view = False
        self._apply_framing()

    def _on_view_changed(self, ra_hours: float, dec_deg: float, _fov: float) -> None:
        """El planetario se mueve → refleja el centro en el editor."""
        if self._updating_view:
            return
        self._updating_view = True
        self._ra.blockSignals(True)
        self._dec.blockSignals(True)
        self._ra.setValue(ra_hours)
        self._dec.setValue(dec_deg)
        self._dec.blockSignals(False)
        self._ra.blockSignals(False)
        self._updating_view = False
        self._apply_framing()

        if hasattr(self, "_draft"):
            self._draft.changed()

    def _on_planet_object_clicked(self, object_id: str, catalog: str) -> None:
        """Clic en un objeto del cielo → lo coloca como target si está guardado."""
        self.select_target(object_id, catalog)   # misma búsqueda (A-29)

    def _copy_from_planetarium(self) -> None:
        """«Actualizar desde planetario»: el centro del cielo pasa al editor de encuadre."""
        ra_hours, dec_deg, _fov = self._planetario.view
        self._updating_view = True
        self._ra.setValue(ra_hours)
        self._dec.setValue(dec_deg)
        self._updating_view = False
        self._apply_framing()

    def _apply_framing(self) -> None:
        """Dibuja el encuadre si el equipo aporta FOV; si no, lo limpia."""
        if not self._fov:
            self._planetario.clear_framing()
            return
        major, minor = self._fov
        self._planetario.set_framing(
            self._ra.value(),
            self._dec.value(),
            major,
            minor,
            self._tiles_x.value(),
            self._tiles_y.value(),
        )

    # ------------------------------------------------------------------ #
    #                         C Á L C U L O S                             #
    # ------------------------------------------------------------------ #
    def _refresh_curve(self) -> None:
        """Redibuja la curva; si faltan datos, explica el motivo en vez de dejarla vacía.

        Motivos en orden: sin target, sin ubicación, sin coordenadas.
        """
        target = self._current_target()
        if target is None:
            self._curve.clear()
            return
        if not self._has_location():
            self._curve.clear(
                "Falta la ubicación: elígela en la pestaña Búsqueda"
            )
            return
        ra, dec = target.get("ra_hours"), target.get("dec_deg")
        if ra is None or dec is None:
            self._curve.clear("El objeto no tiene coordenadas")
            return
        self._curve.show_curve(
            night_curve(
                ra, dec, self._latitude, self._longitude,
                self._date_iso(), self._utc_offset_hours,
            ),
            target_label=str(target["object_id"]),
        )

    def _invalidate_plan(self) -> None:
        """Vacía el plan cuando cambian los datos que lo condicionan."""
        self._plan = []
        self._plan_table.setRowCount(0)
        self._window_label.setText(
            "Cambia target, fecha o ubicación y pulsa «Calcular plan»."
        )

    def _calculate_plan(self) -> None:
        """Ranking de las próximas 30 noches, con espera visible (puede tardar unos s)."""
        target = self._current_target()
        if target is None:
            return
        if not self._has_location():
            QMessageBox.information(
                self,
                "Falta ubicación",
                "Elige una ubicación en la pestaña Búsqueda "
                "(panel «📍 Ubicación»).",
            )
            return
        ra, dec = target.get("ra_hours"), target.get("dec_deg")
        if ra is None or dec is None:
            return

        self._window_label.setText("Calculando…")
        # Botón desactivado ANTES de processEvents: si no, el clic
        # encolado se entrega dentro de este mismo método y el plan se
        # calcula dos veces en reentrada (M-08).
        self._plan_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            self._plan = best_dates(
                ra,
                dec,
                self._latitude,
                self._longitude,
                start_date=self._date_iso(),
                date_range_days=self.PLAN_DAYS,
                top_n=self.PLAN_TOP,
                utc_offset_hours=self._utc_offset_hours,
            )
        finally:
            QApplication.restoreOverrideCursor()
            self._plan_button.setEnabled(True)
        self._fill_plan()

    def _fill_plan(self) -> None:
        """Vuelca ``self._plan`` a la tabla y selecciona la primera noche."""
        self._plan_table.setRowCount(len(self._plan))
        for index, item in enumerate(self._plan):
            ideal = item.get("windows", {}).get("ideal") or {}
            ideal_text = (
                " · ".join(
                    format_hour_range(start, end)
                    for start, end in ideal.get("ranges", [])
                )
                or "sin ventana"
            )
            values = (
                str(index + 1),
                self._format_date(item["date"]),
                str(item.get("transit_local") or "--"),
                f"{item['night_altitude_deg']:.0f}°",
                f"{item['moon_separation_deg']:.0f}°",
                f"{item['moon_illumination']:.0f} %",
                ideal_text,
            )
            for column, value in enumerate(values):
                self._plan_table.setItem(index, column, QTableWidgetItem(value))
        self._plan_table.resizeRowsToContents()
        if self._plan:
            self._plan_table.selectRow(0)
        else:
            self._window_label.setText(
                "Sin noches aprovechables en los próximos días."
            )

    @staticmethod
    def _format_date(date_iso: str) -> str:
        """``2026-10-15`` → ``15 oct`` (sin año, como en el mockup)."""
        months = (
            "ene", "feb", "mar", "abr", "may", "jun",
            "jul", "ago", "sep", "oct", "nov", "dic",
        )
        try:
            moment = date.fromisoformat(date_iso)
        except ValueError:
            return date_iso
        return f"{moment.day} {months[moment.month - 1]}"

    def _on_plan_selected(self) -> None:
        """Fila elegida → desglose de esa noche (noche, luna y ventanas) bajo la tabla."""
        item = fila_seleccionada(self._plan_table, self._plan)
        if item is None:
            return
        windows = item.get("windows", {})
        ideal, possible = window_lines(windows)
        self._window_label.setText(
            f'{item["date"]} · noche {item["astronomical_hours"]:.1f} h · '
            f'luna {item["moon_illumination"]:.0f} % · '
            f"umbral {item['min_moon_distance_deg']:.0f}°\n"
            f"{ideal}\n{possible}"
        )

    # ------------------------------------------------------------------ #
    #                       G U A R D A R   S E S I Ó N                   #
    # ------------------------------------------------------------------ #
    def _on_save_session(self) -> None:
        """Crea la sesión en ``planned_sessions`` y avisa a Sesiones (``session_saved``).

        Sin nombre propio se usa «objeto · fecha»; el FOV y las teselas solo
        se guardan si el equipo aporta encuadre.
        """
        if self._draft.pending:
            self._draft.offer()
            return
        target = self._current_target()
        if target is None:
            QMessageBox.information(
                self, "Sin target", "Elige un target antes de guardar la sesión."
            )
            return

        name = self._session_name.text().strip()
        if not name:
            name = f"{target['object_id']} · {self._date_iso()}"
            self._session_name.setText(name)

        setup = self._current_setup()
        is_region = target.get("kind") == "region"
        arcmin = None
        if self._fov:
            arcmin = (
                round(self._fov[0] * 60.0, 3),
                round(self._fov[1] * 60.0, 3),
            )

        if not self._draft.flush():
            return
        params = dict(
            object_id=str(target["object_id"]),
            target_name=name,
            session_date=self._date_iso(),
            setup_id=setup.get("id") if setup else None,
            planned_exposure_s=int(self._exposure.value()),
            target_kind="region" if is_region else "catalog",
            ra_hours=self._ra.value() if target.get("ra_hours") is not None else None,
            dec_deg=self._dec.value() if target.get("dec_deg") is not None else None,
            fov_major_arcmin=arcmin[0] if arcmin else None,
            fov_minor_arcmin=arcmin[1] if arcmin else None,
            tiles_x=self._tiles_x.value() if arcmin else None,
            tiles_y=self._tiles_y.value() if arcmin else None,
            notes=self._notes.text().strip(),
            draft_revision=self._draft.revision,
        )
        try:
            session_id = planned_sessions.add(**params)
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "No se pudo guardar la sesión", str(exc))
            return
        self._draft.revision = None
        self._draft.active = False
        self._draft.paused = True
        try:
            self._session_name.clear()
            self._notes.clear()
        finally:
            self._draft.paused = False
        self._draft.label.setText("Sesión guardada · sin borrador pendiente.")
        self.session_saved.emit(session_id)
        QMessageBox.information(
            self,
            "Sesión guardada",
            f"«{name}» se guardó en Sesiones planificadas.",
        )
