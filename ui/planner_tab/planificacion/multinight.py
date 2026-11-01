"""Espacio multinoches: encuadre/curva, restricciones y reparto; borrador automático y maestro confirmado explícitamente."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import date, timedelta
from threading import Event

import pyqtgraph as pg
from PyQt6.QtCore import QDate, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from equipment.localizations import list_locations, planning_location
from equipment.manager import get as get_setup
from equipment.manager import list_setups
from equipment.models import DIRECTIONS
from equipment.planning_profile import profile_from_data
from planners import personal_catalog
from planners.framing import calculate_fov
from planners.multinight import (
    Demand,
    Objective,
    Request,
    availability,
    calculate,
    inspect_night,
    mosaic_fov,
    objective_from_data,
    sampled_windows,
    validate,
    validate_editor,
)
from planners.plan_document import (
    editor_calendar,
    index_document,
    make_document,
    plan_filename,
    plans_directory,
    read_document,
    reference_scope,
    save_local_document,
    write_document,
)
from planners.planning_scheduler import select_alternative
from planners.sky_state import location_clock
from planners.timezones import local_moment, utc_moment

from .night_timeline import NightTimeline
from .plan_curve import LocalTimeAxis, draw_schedule
from .plan_results import CoverageCards
from .planetario_visual import PlanetarioVisual

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="multinight")


def _plain(text=""):
    """Usa texto plano para que nombres de objetos y notas no sean interpretados como HTML."""
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _table(headers):
    """Tabla compacta de filas de solo lectura, sin redimensionar cada celda al insertar."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().hide()
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _fill(table, rows):
    """Sustituye filas sin emitir selecciones intermedias ni ejecutar cálculos recursivos."""
    table.blockSignals(True)
    try:
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                table.setItem(i, j, QTableWidgetItem(str(value)))
                table.item(i, j).setToolTip(str(value))
    finally:
        table.blockSignals(False)


class PlanningJob(QObject):
    """Worker con cancelación por generación; nunca consulta SQLite desde el hilo de Qt para calcular."""

    delivered = pyqtSignal(int, str, object, str)
    progressed = pyqtSignal(int, int, int)

    def __init__(self, parent):
        """Retiene solo el trabajo vigente, entregando resultados mediante señales en Qt."""
        super().__init__(parent)
        self.generation = 0
        self.event = Event()
        self.future = None

    def stop(self):
        """Invalida entregas y pide detener el recorrido antes de la siguiente tesela/noche."""
        self.generation += 1
        self.event.set()
        if self.future:
            self.future.cancel()

    def start(self, kind, request, preview=None):
        """Las peticiones son dataclasses inmutables; ningún widget o conexión sale hacia el executor."""
        self.stop()
        generation = self.generation
        self.event = Event()
        event = self.event

        def work():
            """Calcula un plan o su inspección; los callbacks solo emiten señales."""
            try:
                if kind in ("plan", "extension"):
                    result = calculate(request, cancelled=event.is_set,
                                       progress=lambda done, total: self.progressed.emit(generation, done, total))
                else:
                    result = inspect_night(request, *preview)
                error = ""
            except Exception as exc:
                result, error = None, str(exc) or type(exc).__name__
            try:
                self.delivered.emit(generation, kind, result, error)
            except RuntimeError:
                pass

        self.future = _EXECUTOR.submit(work)


class ObjectiveDialog(QDialog):
    """Un objeto del plan con horas por filtro y elección explícita de FOV y reparto entre teselas."""

    def __init__(self, targets, setup, exposure, parent=None, existing=None, filters=None):
        """Presenta referencias personales reales; no guarda catálogo ni selecciona un encuadre por inferencia."""
        super().__init__(parent)
        self.setWindowTitle("Objetivo de captura")
        self.resize(570, 530)
        self._targets = targets
        self._setup_fov = calculate_fov(setup) if setup else None
        self._exposure = exposure
        self._existing = existing
        self._common_filters = filters
        form = QFormLayout(self)
        self.target = QComboBox()
        for item in targets:
            self.target.addItem(f"{item['object_id']} · {item['catalog']}", item)
        form.addRow("Objeto", self.target)
        self.source = QComboBox()
        self.source.addItem("Elegir encuadre…", None)
        self.source.addItem("Solo centro, sin FOV", "none")
        self.source.addItem("Equipo seleccionado", "setup")
        self.source.addItem("Región guardada", "region")
        form.addRow("Fuente del FOV", self.source)
        self.region_mode = QComboBox()
        self.region_mode.addItem("Elegir significado del FOV regional…", None)
        self.region_mode.addItem("Campo de una tesela", "per_tile")
        self.region_mode.addItem("Campo total para dividir en teselas", "whole_frame")
        self.region_mode.currentIndexChanged.connect(self._show_fov)
        form.addRow("FOV de la región", self.region_mode)
        self.fov_label = _plain()
        form.addRow("FOV de lectura", self.fov_label)
        self.source.currentIndexChanged.connect(self._show_fov)
        self.target.currentIndexChanged.connect(self._show_fov)
        self.tiles_x, self.tiles_y = QSpinBox(), QSpinBox()
        tiles = QHBoxLayout()
        for spin in (self.tiles_x, self.tiles_y):
            spin.setRange(1, 20)
            spin.valueChanged.connect(self._show_fov)
            tiles.addWidget(spin)
        form.addRow("Teselas nominales ×/y", tiles)
        self.mode = QComboBox()
        self.mode.addItem("Elegir integración…", None)
        self.mode.addItem("Horas por cada tesela", "per_tile")
        self.mode.addItem("Horas totales · repartir igual entre teselas", "total_equal")
        form.addRow("Integración", self.mode)
        self.night_mode = QComboBox()
        self.night_mode.addItem("Automático recomendado", "auto")
        self.night_mode.addItem("Horas deseadas por noche", "desired")
        self.night_mode.addItem("Máxima integración por noche", "maximum")
        self.night_hours = QDoubleSpinBox()
        self.night_hours.setRange(.01, 24)
        self.night_hours.setValue(1)
        self.night_hours.setSuffix(" h / noche")
        self.night_hours.setEnabled(False)
        self.night_mode.currentIndexChanged.connect(lambda: self.night_hours.setEnabled(self.night_mode.currentData() == "desired"))
        self.max_tiles = QSpinBox()
        self.max_tiles.setRange(1, 400)
        form.addRow("Reparto de este objeto", self.night_mode)
        form.addRow("Integración orientativa", self.night_hours)
        form.addRow("Hasta N teselas / noche", self.max_tiles)
        self.filters = QTableWidget(0, 2)
        self.filters.setHorizontalHeaderLabels(["Filtro (o Sin filtro)", "Horas objetivo"])
        self.filters.horizontalHeader().setStretchLastSection(True)
        form.addRow(self.filters)
        actions = QHBoxLayout()
        add, remove = QPushButton("Añadir filtro"), QPushButton("Quitar filtro")
        add.clicked.connect(lambda: self._add_filter("", ""))
        remove.clicked.connect(lambda: self.filters.removeRow(self.filters.currentRow()) if self.filters.currentRow() >= 0 else None)
        actions.addWidget(add)
        actions.addWidget(remove)
        form.addRow(actions)
        self.error = _plain()
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        if existing:
            index = next((i for i, item in enumerate(targets)
                          if item["object_id"] == existing["object_id"] and item["catalog"] == existing["catalog"]), -1)
            self.target.setCurrentIndex(index)
            self.source.setCurrentIndex(self.source.findData(existing["source"]))
            self.region_mode.setCurrentIndex(self.region_mode.findData(existing["region_fov_mode"]))
            self.tiles_x.setValue(existing["objective"]["tiles_x"])
            self.tiles_y.setValue(existing["objective"]["tiles_y"])
            self.mode.setCurrentIndex(self.mode.findData(existing["objective"]["integration_mode"]))
            self.night_mode.setCurrentIndex(self.night_mode.findData(existing["objective"].get("night_mode", "auto")))
            self.night_hours.setValue(existing["objective"].get("night_hours") or 1)
            self.max_tiles.setValue(existing["objective"].get("max_tiles", 1))
            for demand in existing["objective"]["demands"]:
                self._add_filter(demand["filter_name"], str(demand["hours"]))
        else:
            self._add_filter("Sin filtro", "")
        self._show_fov()

    def _add_filter(self, name, hours):
        """Crea una categoría explícita; no asigna automáticamente pesos LRGB ni horas iniciales."""
        row = self.filters.rowCount()
        self.filters.insertRow(row)
        self.filters.setItem(row, 0, QTableWidgetItem(name))
        if self._common_filters is not None:
            combo = QComboBox()
            combo.addItem("Elegir filtro común…", None)
            for value in self._common_filters:
                combo.addItem(value, value)
            if name and name not in self._common_filters:
                combo.addItem(f"Referencia no definida: {name}", name)
            combo.setCurrentIndex(max(0, combo.findData(name)))
            self.filters.setCellWidget(row, 0, combo)
        self.filters.setItem(row, 1, QTableWidgetItem(hours))

    def _fov(self):
        """Resuelve solo la fuente elegida; una región y un equipo distintos nunca compiten silenciosamente."""
        target = self.target.currentData() or {}
        if self.source.currentData() == "setup":
            return self._setup_fov
        if self.source.currentData() == "region":
            width, height = target.get("fov_major_arcmin"), target.get("fov_minor_arcmin")
            if not width or not height or self.region_mode.currentData() is None:
                return None
            fov = float(width)/60, float(height)/60
            if self.region_mode.currentData() == "whole_frame":
                return mosaic_fov(*fov, self.tiles_x.value(), self.tiles_y.value(), inverse=True)
            return fov
        return None

    def _show_fov(self):
        """Muestra datos ausentes sin rellenar ejes ni escoger otro equipo."""
        if not hasattr(self, "tiles_x"):
            return
        self.region_mode.setEnabled(self.source.currentData() == "region")
        fov = self._fov()
        self.fov_label.setText(f"{fov[0]:.3f}° × {fov[1]:.3f}° por tesela" if fov else "Sin FOV disponible para esta elección")

    def values(self):
        """Recoge la geometría real y filtros del usuario en un documento de borrador versionable."""
        target = self.target.currentData()
        if not target or target.get("ra_hours") is None or target.get("dec_deg") is None:
            raise ValueError("El objeto necesita coordenadas conocidas.")
        if self.source.currentData() is None or self.mode.currentData() is None:
            raise ValueError("Elige fuente del encuadre e interpretación de integración.")
        fov = self._fov()
        if self.source.currentData() != "none" and not fov:
            raise ValueError("La fuente elegida no aporta los dos ejes del FOV.")
        demands = []
        for row in range(self.filters.rowCount()):
            name = self.filters.item(row, 0).text().strip() if self.filters.item(row, 0) else ""
            if self.filters.cellWidget(row, 0):
                name = self.filters.cellWidget(row, 0).currentData() or ""
            if self._common_filters is not None and name not in self._common_filters:
                raise ValueError("Define el filtro común en Valores del plan antes de asignarlo al objeto.")
            raw = self.filters.item(row, 1).text() if self.filters.item(row, 1) else ""
            demands.append(Demand(name, float(raw.replace(",", ".")), self._exposure))
        key = json.dumps([target["catalog"], target["object_id"]], ensure_ascii=False)
        objective = Objective(key, str(target["object_id"]), float(target["ra_hours"]), float(target["dec_deg"]), tuple(demands),
                              self.tiles_x.value(), self.tiles_y.value(), fov[0] if fov else None, fov[1] if fov else None,
                              self.mode.currentData(), self.night_mode.currentData(),
                              self.night_hours.value() if self.night_mode.currentData() == "desired" else None, self.max_tiles.value())
        return {"object_id": target["object_id"], "catalog": target["catalog"], "source": self.source.currentData(),
                "region_fov_mode":self.region_mode.currentData() if self.source.currentData() == "region" else None,
                "objective": asdict(objective)}

    def _accept(self):
        """Mantiene abierto el editor ante objetivos incompletos o categorías inválidas."""
        try:
            value = self.values()
            obj = objective_from_data(value["objective"], self._exposure)
            validate(Request("2026-01-01", "2026-01-01", 0, 0, 0, 0, 60, (0,), 30, (obj,), "windows_only"))
        except (ValueError, TypeError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class MultiNightPage(QWidget):
    """Página nativa de Planificación con borrador y maestro, sin ejecución modal del espacio de trabajo."""

    def __init__(self, owner):
        """Usa el mismo borrador protegido del Planificador; no abre un segundo flujo editable competidor."""
        super().__init__(owner)
        self.owner = owner
        self._restoring = True
        self._result = None
        self._master_readonly_view = False
        self._request = None
        self._extension_request = None
        self._editor_version = 2
        self._preview_caption = ""
        self._preview_key = None
        self._objectives = []
        self._targets = personal_catalog.list_objects()
        self._locations = {row["id"]: row for row in list_locations()}
        self._setups = {row["id"]: row for row in list_setups()}
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(_plain("Encuadre de sesión"))
        self.sky = PlanetarioVisual()
        self.sky.setMinimumSize(280, 210)
        left_layout.addWidget(self.sky, 3)
        self.fov_label = _plain("Selecciona un objetivo")
        self.show_tiles = QCheckBox("Mostrar teselas")
        self.show_tiles.setChecked(True)
        frame_row = QHBoxLayout()
        frame_row.addWidget(self.fov_label, 1)
        frame_row.addWidget(self.show_tiles)
        self.show_tiles.toggled.connect(self._show_objective)
        left_layout.addLayout(frame_row)
        self.curve_axis = LocalTimeAxis()
        self.curve = pg.PlotWidget(axisItems={"bottom": self.curve_axis})
        self.curve.setMinimumHeight(170)
        self.curve.setBackground("#0d1117")
        self.curve.addLegend(offset=(10, 10))
        self.curve.setLabel("left", "Altura", units="°")
        self.curve.setLabel("bottom", "Hora local")
        self.curve.showGrid(x=True, y=True, alpha=.2)
        left_layout.addWidget(self.curve, 2)
        self.curve_status = _plain("La curva usa la franja y las restricciones del plan.")
        left_layout.addWidget(self.curve_status)
        split.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self._build_objectives()
        self._build_availability()
        self._build_values()
        self._build_result()
        right_layout.addWidget(self.tabs, 1)
        actions = QHBoxLayout()
        self.calculate_button = QPushButton("Diseñar distribución")
        self.cancel_button = QPushButton("Cancelar cálculo")
        self.calculate_button.clicked.connect(self._calculate)
        self.cancel_button.clicked.connect(self._cancel)
        actions.addWidget(self.calculate_button)
        actions.addWidget(self.cancel_button)
        right_layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.hide()
        right_layout.addWidget(self.progress)
        summary = QGroupBox("Parámetros de sesión · consolidador")
        summary_layout = QVBoxLayout(summary)
        self.summary = _plain("Borrador · sin distribución calculada")
        summary_layout.addWidget(self.summary)
        self.save_button = QPushButton("Guardar borrador")
        self.save_button.clicked.connect(self._save_draft)
        file_actions = QHBoxLayout()
        file_actions.addWidget(self.save_button)
        self.save_plan_button = QPushButton("Guardar plan creado…")
        self.save_plan_button.setEnabled(False)
        self.save_plan_button.clicked.connect(self._save_master)
        file_actions.addWidget(self.save_plan_button)
        self.open_plan_button = QPushButton("Abrir maestro…")
        self.open_plan_button.clicked.connect(self._open_master)
        file_actions.addWidget(self.open_plan_button)
        more = QToolButton()
        more.setText("⋯")
        more.setAccessibleName("Más acciones del plan")
        more.setToolTip("Exportar una copia del maestro guardado")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Exportar copia…", self._export_master)
        more.setMenu(menu)
        file_actions.addWidget(more)
        summary_layout.addLayout(file_actions)
        right_layout.addWidget(summary)
        self.status = _plain()
        right_layout.addWidget(self.status)
        split.addWidget(right)
        split.setSizes([600, 760])
        root.addWidget(split, 1)
        self.job = PlanningJob(self)
        self.job.delivered.connect(self._delivered)
        self.job.progressed.connect(self._progressed)
        self.restore(owner._multinight_data or self._defaults())
        self._restoring = False
        self._set_busy(False)

    def _build_objectives(self):
        """La lista establece el orden propuesto solo cuando el usuario escoge esa política."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.objects_table = _table(["Objeto", "Filtros", "Teselas", "Integración"])
        self.objects_table.itemSelectionChanged.connect(self._show_objective)
        layout.addWidget(self.objects_table, 1)
        actions = QHBoxLayout()
        for text, callback in (("Añadir", self._add_objective), ("Editar", self._edit_objective),
                               ("Quitar", self._remove_objective), ("↑", lambda: self._move_objective(-1)),
                               ("↓", lambda: self._move_objective(1))):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        form = QFormLayout()
        self.policy = QComboBox()
        self.policy.addItem("Elegir política…", None)
        self.policy.addItem("Consultar ventanas, sin repartir", "windows_only")
        self.policy.addItem("Sesiones equilibradas · tránsito y operación", "balanced")
        self.policy.addItem("Cronológico por orden de objetos y filtros", "chronological_order")
        self.policy.setToolTip("Propuesta explícita, no optimizador global. El orden puede cambiar el déficit de otros objetos.")
        form.addRow("Reparto", self.policy)
        self.policy.currentIndexChanged.connect(self._changed)
        layout.addLayout(form)
        self.tabs.addTab(widget, "Objetivos")

    def _build_availability(self):
        """Horas propias mediante sliders, fechas y días reales; no confunde disponibilidad con tránsito."""
        widget = QWidget()
        form = QFormLayout(widget)
        self.location = QComboBox()
        self.location.addItem("Elegir ubicación…", None)
        for key, item in self._locations.items():
            self.location.addItem(item["name"], key)
        self.location.currentIndexChanged.connect(self._changed)
        form.addRow("Ubicación guardada", self.location)
        self.clock_label = _plain()
        form.addRow("Reloj", self.clock_label)
        self.start, self.end = QDateEdit(), QDateEdit()
        for control in (self.start, self.end):
            control.setCalendarPopup(True)
            control.setDisplayFormat("dd/MM/yyyy")
            control.dateChanged.connect(self._changed)
        dates = QHBoxLayout()
        dates.addWidget(self.start)
        dates.addWidget(self.end)
        form.addRow("Fechas de inicio de franja", dates)
        self.days = []
        days = QHBoxLayout()
        for name in ("L", "M", "X", "J", "V", "S", "D"):
            check = QCheckBox(name)
            check.toggled.connect(self._changed)
            self.days.append(check)
            days.addWidget(check)
        form.addRow("Días disponibles", days)
        self.start_slider, self.end_slider = QSlider(Qt.Orientation.Horizontal), QSlider(Qt.Orientation.Horizontal)
        self.start_text, self.end_text = _plain(), _plain()
        for slider, label, title in ((self.start_slider, self.start_text, "Desde"), (self.end_slider, self.end_text, "Hasta")):
            slider.setRange(0, 1439)
            slider.setSingleStep(15)
            slider.setPageStep(60)
            slider.valueChanged.connect(self._changed)
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            row.addWidget(label)
            form.addRow(title, row)
        self.end_text.setToolTip("Hasta menor o igual a Desde termina al día siguiente; iguales = 24 horas civiles.")
        self.minimum_altitude = QDoubleSpinBox()
        self.minimum_altitude.setRange(0, 90)
        self.minimum_altitude.setSuffix("°")
        self.minimum_altitude.valueChanged.connect(self._changed)
        form.addRow("Altura mínima", self.minimum_altitude)
        self.horizon_margin = QDoubleSpinBox()
        self.horizon_margin.setRange(0, 90)
        self.horizon_margin.setSuffix("°")
        self.horizon_margin.valueChanged.connect(self._changed)
        form.addRow("Margen de obstrucciones", self.horizon_margin)
        self.use_obstacles = QCheckBox("Aplicar obstrucciones de la ubicación")
        self.use_obstacles.toggled.connect(self._changed)
        form.addRow(self.use_obstacles)
        self.horizon_policy = QComboBox()
        self.horizon_policy.addItem("Elegir interpretación…", None)
        self.horizon_policy.addItem("Sectores de 45° centrados en cada dirección", "sectors")
        self.horizon_policy.addItem("Interpolación lineal entre direcciones", "linear")
        self.horizon_policy.currentIndexChanged.connect(self._changed)
        form.addRow("Perfil del horizonte", self.horizon_policy)
        self.tabs.addTab(widget, "Disponibilidad")

    def _build_values(self):
        """Nombre/exposición/notas se configuran aquí, no en el consolidador inferior."""
        widget = QWidget()
        form = QFormLayout(widget)
        self.name, self.notes = QLineEdit(), QLineEdit()
        self.name.textChanged.connect(self._changed)
        self.notes.textChanged.connect(self._changed)
        self.exposure = QSpinBox()
        self.exposure.setRange(1, 7200)
        self.exposure.setSuffix(" s/toma")
        self.exposure.valueChanged.connect(self._changed)
        self.setup = QComboBox()
        self.setup.addItem("Sin equipo seleccionado", None)
        for key, item in self._setups.items():
            self.setup.addItem(item["name"], key)
        self.setup.currentIndexChanged.connect(self._changed)
        form.addRow("Nombre del plan", self.name)
        form.addRow("Equipo del plan", self.setup)
        self.profile_label = _plain("Tiempos operativos del equipo seleccionado; los no informados se indicarán al calcular.")
        form.addRow(self.profile_label)
        form.addRow("Exposición", self.exposure)
        form.addRow("Notas del plan", self.notes)
        self.filter_order = QLineEdit("Sin filtro")
        self.filter_order.setPlaceholderText("L, R, G, B · de mayor a menor prioridad")
        self.filter_order.setToolTip("Definiciones comunes del plan, separadas por comas. Cada nombre identifica un único filtro; usa etiquetas distintas para filtros físicos diferentes.")
        self.filter_order.textChanged.connect(self._changed)
        self.max_filters = QSpinBox()
        self.max_filters.setRange(1, 100)
        self.max_filters.valueChanged.connect(self._changed)
        form.addRow("Filtros comunes · prioridad", self.filter_order)
        form.addRow("Hasta N filtros / noche", self.max_filters)
        equipment_filters = QPushButton("Definir filtros desde el equipo")
        equipment_filters.clicked.connect(self._equipment_filters)
        form.addRow(equipment_filters)
        self.new_plan_button = QPushButton("Nuevo plan…")
        self.new_plan_button.clicked.connect(self._new_plan)
        form.addRow(self.new_plan_button)
        self.tabs.addTab(widget, "Valores del plan")

    def _build_result(self):
        """El calendario conjunto y los déficits se separan de la capacidad potencial de las ventanas."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.result_views = QTabWidget()
        self.alternative = QComboBox()
        self.alternative.setAccessibleName("Alternativa de distribución")
        self.alternative.currentIndexChanged.connect(self._choose_alternative)
        layout.addWidget(self.alternative)
        self.timeline = NightTimeline()
        self.timeline.visit_selected.connect(self._inspect_visit)
        self.result_views.addTab(self.timeline, "Noches")
        self.coverage_cards = CoverageCards()
        self.result_views.addTab(self.coverage_cards, "Resumen")
        self.allocations_table = _table(["Fecha", "Objeto", "Tesela", "Filtro", "Desde", "Hasta", "Tomas"])
        self.balance_table = _table(["Objeto", "Tesela", "Filtro", "Objetivo h", "Asignadas h", "Faltan h"])
        self.windows_table = _table(["Fecha", "Objeto", "Tesela", "Desde", "Hasta"])
        for table, widths in ((self.allocations_table, (100, 85, 55, 50, 160, 160, 55)),
                              (self.windows_table, (95, 100, 55, 170, 170)),
                              (self.balance_table, (100, 55, 60, 110, 110))):
            for index, width in enumerate(widths):
                table.setColumnWidth(index, width)
        self.allocations_table.itemSelectionChanged.connect(self._inspect_allocation)
        self.windows_table.itemSelectionChanged.connect(self._inspect_window)
        self.result_views.addTab(self.allocations_table, "Distribución")
        self.result_views.addTab(self.balance_table, "Cobertura")
        self.result_views.addTab(self.windows_table, "Ventanas")
        layout.addWidget(self.result_views)
        self.block_details = _plain("Selecciona una noche y un bloque; las franjas tramadas indican maniobras.")
        layout.addWidget(self.block_details)
        detail = QPushButton("Condiciones y límites del cálculo")
        detail.clicked.connect(self._details)
        extension = QPushButton("Estudiar ampliación…")
        extension.clicked.connect(self._consider_extension)
        secondary = QHBoxLayout()
        secondary.addWidget(detail)
        secondary.addWidget(extension)
        layout.addLayout(secondary)
        self.tabs.addTab(widget, "Resultado")

    def _defaults(self):
        """Toma solo entradas actuales del editor, sin adoptar automáticamente una ubicación por ser única."""
        setup = self.owner._current_setup()
        choices = [key for key, row in self._locations.items()
                   if (row["latitude"], row["longitude"], location_clock(row)) ==
                   (self.owner._latitude, self.owner._longitude, self.owner._utc_offset_hours)]
        return {"version":2, "start":self.owner._date_iso(), "end":self.owner._date.date().addDays(29).toString("yyyy-MM-dd"),
                "start_minute":19*60, "end_minute":6*60, "weekdays":list(range(7)), "minimum_altitude":30,
                "policy":None, "location_id":choices[0] if len(choices) == 1 else None,
                "setup_id":setup["id"] if setup else None, "use_obstacles":False, "horizon_policy":None,
                "exposure":self.owner._exposure.value(), "notes":"", "name":"", "objectives":[],
                "horizon_margin":5., "max_filters":1, "filter_order":["Sin filtro"]}

    def snapshot(self):
        """Recoge configuración incluso incompleta, sin persistir resultados como autoridad de un plan creado."""
        data = {"version":self._editor_version, "start":self.start.date().toString("yyyy-MM-dd"), "end":self.end.date().toString("yyyy-MM-dd"),
                "start_minute":self.start_slider.value(), "end_minute":self.end_slider.value(),
                "weekdays":[i for i, check in enumerate(self.days) if check.isChecked()],
                "minimum_altitude":self.minimum_altitude.value(), "policy":self.policy.currentData(),
                "location_id":self.location.currentData(), "setup_id":self.setup.currentData(),
                "use_obstacles":self.use_obstacles.isChecked(), "horizon_policy":self.horizon_policy.currentData(),
                "exposure":self.exposure.value(), "notes":self.notes.text(), "name":self.name.text(),
                "objectives":copy.deepcopy(self._objectives)}
        if self._editor_version >= 2:
            data.update(horizon_margin=self.horizon_margin.value(), max_filters=self.max_filters.value(),
                        filter_order=self._filters())
        return data

    def _filters(self):
        """Lee las definiciones compartidas sin unir filtros de distintos objetos por inferencia."""
        return [value.strip() for value in self.filter_order.text().split(",") if value.strip()]

    def _equipment_filters(self):
        """Asigna etiquetas inequívocas del equipo solo mediante una acción explícita del usuario."""
        from equipment.components import get_filter

        setup = get_setup(self.setup.currentData()) if self.setup.currentData() is not None else None
        if setup is None:
            self.status.setText("Elige un equipo guardado antes de definir sus filtros.")
            return
        values = [get_filter(identity) for identity in setup["filter_ids"]]
        labels = [f"{value['name']} [#{value['id']}]" for value in values if value]
        if labels:
            self.filter_order.setText(", ".join(labels))
            self.status.setText("Filtros definidos; revisa su prioridad y asígnalos explícitamente a los objetivos.")
        else:
            self.status.setText("Este equipo no tiene filtros asignados. Puedes definirlos manualmente en el plan.")

    def validate_references(self, data):
        """Prevalida referencias locales sin modificar el editor ni sustituir ausencias por otro elemento."""
        validate_editor(data)
        if data["location_id"] is not None and data["location_id"] not in self._locations:
            raise ValueError("La ubicación del borrador ya no existe.")
        if data["setup_id"] is not None and data["setup_id"] not in self._setups:
            raise ValueError("El equipo del borrador ya no existe.")
        references = {(str(item["object_id"]), str(item["catalog"])) for item in self._targets}
        for item in data["objectives"]:
            if (item["object_id"], item["catalog"]) not in references:
                raise ValueError(f"El objetivo {item['object_id']} ya no está en Catálogo Personal; el borrador se conserva.")

    def restore(self, data):
        """Prevalida el documento y referencias antes de escribir controles, conservando ausencias como error."""
        self.validate_references(data)
        self._editor_version = data["version"]
        self.start.setDate(QDate.fromString(data["start"], "yyyy-MM-dd"))
        self.end.setDate(QDate.fromString(data["end"], "yyyy-MM-dd"))
        self.start_slider.setValue(data["start_minute"])
        self.end_slider.setValue(data["end_minute"])
        for index, check in enumerate(self.days):
            check.setChecked(index in data["weekdays"])
        self.minimum_altitude.setValue(data["minimum_altitude"])
        self.horizon_margin.setValue(data.get("horizon_margin", 0))
        self.max_filters.setValue(data.get("max_filters", 1))
        self.filter_order.setText(", ".join(data.get("filter_order", ["Sin filtro"])))
        self.policy.setCurrentIndex(self.policy.findData(data["policy"]))
        self.location.setCurrentIndex(self.location.findData(data["location_id"]))
        self.setup.setCurrentIndex(self.setup.findData(data["setup_id"]))
        self.use_obstacles.setChecked(data["use_obstacles"])
        self.horizon_policy.setCurrentIndex(self.horizon_policy.findData(data["horizon_policy"]))
        self.exposure.setValue(data["exposure"])
        self.name.setText(data["name"])
        self.notes.setText(data["notes"])
        self._objectives = copy.deepcopy(data["objectives"])
        self._fill_objectives()
        self._show_hours()

    def _show_hours(self):
        """Etiqueta la disponibilidad del usuario, no una ventana astronómica calculada."""
        for control, label in ((self.start_slider, self.start_text), (self.end_slider, self.end_text)):
            minute = control.value()
            label.setText(f"{minute//60:02d}:{minute%60:02d}")
        location = self._locations.get(self.location.currentData())
        clock = location_clock(location) if location else None
        self.clock_label.setText(str(clock) if isinstance(clock, str) else f"UTC {clock:+g}" if clock is not None else
                                 "≈ por longitud" if location else "—")
        setup = self._setups.get(self.setup.currentData())
        profile = profile_from_data(setup.get("planning_profile") if setup else None)
        pause = f"{profile.pause_s:g} s" if profile.pause_s is not None else "no informada"
        flip = f"{profile.meridian_s/60:g} min totales" if profile.meridian_flip else "no requerido"
        self.profile_label.setText(f"Pausa: {pause} · meridiano: {flip}. Configura maniobras y enfoque en Equipo.")

    def _changed(self, *_args):
        """Invalida reparto/curva al editar, cancela entregas tardías y guarda únicamente borrador."""
        if self._restoring:
            return
        self._editor_version = 2
        self.job.stop()
        self._set_busy(False)
        self._result = self._request = None
        self._master_readonly_view = False
        self._extension_request = None
        self.timeline.clear()
        self.coverage_cards.set_message("Sin propuesta vigente")
        self.block_details.setText("Selecciona un bloque después de calcular.")
        self.alternative.blockSignals(True)
        self.alternative.clear()
        self.alternative.blockSignals(False)
        self.save_plan_button.setEnabled(False)
        self.curve.clear()
        for table in (self.allocations_table, self.balance_table, self.windows_table):
            table.setRowCount(0)
        self._show_hours()
        self.summary.setText(f"{self.name.text() or 'Sin nombre'} · {len(self._objectives)} objetos · borrador sin recalcular")
        self.owner._multinight_data = self.snapshot()
        if not self.owner._draft.changed():
            self.status.setText(self.owner._draft.label.text())
        else:
            self.status.setText("Borrador guardado · calcula para actualizar la distribución")

    def _fill_objectives(self):
        """Resume filtros y teselas conservando el orden elegido para el reparto."""
        rows = []
        for value in self._objectives:
            item = value["objective"]
            rows.append((item["name"], ", ".join(goal["filter_name"] for goal in item["demands"]),
                         f"{item['tiles_x']}×{item['tiles_y']}", "Por tesela" if item["integration_mode"] == "per_tile" else "Total equitativo"))
        _fill(self.objects_table, rows)

    def _add_objective(self):
        """Añade solo tras confirmar el editor; duplicados requieren editar el objetivo existente."""
        self._edit_objective(adding=True)

    def _edit_objective(self, _checked=False, *, adding=False):
        """Modificar geometría no cambia el catálogo personal ni mueve el encuadre del flujo legacy."""
        if not self.refresh_references():
            return
        row = self.objects_table.currentRow()
        if not adding and row < 0:
            return
        existing = None if adding else self._objectives[row]
        dialog = ObjectiveDialog(self._targets, self._setups.get(self.setup.currentData()), self.exposure.value(), self, existing,
                                 filters=self._filters() if self.policy.currentData() == "balanced" else None)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        value = dialog.values()
        others = [item for i, item in enumerate(self._objectives) if adding or i != row]
        if any(item["objective"]["key"] == value["objective"]["key"] for item in others):
            QMessageBox.warning(self, "Objetivo repetido", "Edita el objetivo existente para cambiar sus filtros o teselas.")
            return
        if adding:
            self._objectives.append(value)
            row = len(self._objectives)-1
        else:
            self._objectives[row] = value
        self._fill_objectives()
        self.objects_table.selectRow(row)
        self._changed()

    def _remove_objective(self):
        """Retira solo del borrador actual, nunca del catálogo ni de un plan confirmado externo."""
        row = self.objects_table.currentRow()
        if row >= 0:
            self._objectives.pop(row)
            self._fill_objectives()
            if self._objectives:
                self.objects_table.selectRow(min(row, len(self._objectives)-1))
            else:
                self.sky.clear_target()
                self.sky.clear_framing()
                self.fov_label.setText("Selecciona un objetivo")
            self._changed()

    def _move_objective(self, step):
        """El orden es explícitamente editable; no se inventa una métrica de prioridad científica."""
        row = self.objects_table.currentRow()
        if 0 <= row+step < len(self._objectives) and row >= 0:
            self._objectives[row], self._objectives[row+step] = self._objectives[row+step], self._objectives[row]
            self._fill_objectives()
            self.objects_table.selectRow(row+step)
            self._changed()

    def _show_objective(self, *_args):
        """Vista de consulta del objeto seleccionado; no reescribe el centro del objetivo por arrastrar el cielo."""
        row = self.objects_table.currentRow()
        if row < 0 or row >= len(self._objectives):
            return
        obj = self._objectives[row]["objective"]
        if not _args:
            self.sky.clear_target()
            self.sky.set_center(obj["ra_hours"], obj["dec_deg"], obj["name"])
        if obj["fov_width"] is not None:
            width, height = mosaic_fov(obj["fov_width"], obj["fov_height"], obj["tiles_x"], obj["tiles_y"])
            self.sky.set_framing(obj["ra_hours"], obj["dec_deg"], width, height,
                                 obj["tiles_x"] if self.show_tiles.isChecked() else 1,
                                 obj["tiles_y"] if self.show_tiles.isChecked() else 1)
            self.fov_label.setText(f"FOV por tesela {obj['fov_width']:.3f}° × {obj['fov_height']:.3f}°")
            if not _args:
                self.sky.set_fov_deg(max(1., min(180., max(width, height)*2.5)))
        else:
            self.sky.clear_framing()
            self.fov_label.setText("Sin FOV · centro del objeto")

    def build_request(self):
        """Construye una petición completa solo desde elecciones explícitas y ubicaciones guardadas."""
        self.validate_references(self.snapshot())
        location = self._locations.get(self.location.currentData())
        if location is None:
            raise ValueError("Elige una ubicación guardada.")
        location = planning_location(self.location.currentData(), require_obstacles=self.use_obstacles.isChecked())
        obstacles = tuple(location["obstacles"][direction] for direction in DIRECTIONS) if self.use_obstacles.isChecked() else None
        data = self.snapshot()
        profile = profile_from_data(None)
        if data["policy"] == "balanced":
            if data["setup_id"] is not None:
                setup = get_setup(data["setup_id"])
                if setup is None:
                    raise ValueError("El equipo ya no existe.")
                profile = profile_from_data(setup.get("planning_profile"))
            names = {d["filter_name"] for value in self._objectives for d in value["objective"]["demands"]}
            if not names <= set(self._filters()):
                raise ValueError("Asigna a cada objetivo filtros comunes definidos en Valores del plan; no se fusionan nombres automáticamente.")
        request = Request(data["start"], data["end"], location["latitude"], location["longitude"], location_clock(location),
                          data["start_minute"], data["end_minute"], tuple(data["weekdays"]), data["minimum_altitude"],
                          tuple(objective_from_data(item["objective"], data["exposure"]) for item in self._objectives),
                          data["policy"], obstacles, data["horizon_policy"],
                          data.get("horizon_margin", 0), data.get("max_filters", 1), tuple(data.get("filter_order", ())), profile)
        availability(request)
        return request

    def _calculate(self):
        """No reutiliza un resultado de entradas anteriores; calcula en segundo plano con cancelación."""
        self._changed()
        try:
            self._request = self.build_request()
        except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            self.status.setText(str(exc))
            return
        self.status.setText("Calculando franjas reales y restricciones…")
        self._set_busy(True)
        self.job.start("plan", self._request)

    def _set_busy(self, busy):
        """El cálculo no bloquea la ventana; se puede cancelar o editar, lo que invalida su entrega."""
        self.calculate_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)

    def _cancel(self):
        """Conserva configuración y retira el trabajo calculado a medias."""
        self.job.stop()
        self._set_busy(False)
        self.status.setText("Cálculo cancelado · borrador conservado")

    def _progressed(self, generation, done, total):
        """La barra solo atiende a la generación vigente, no a señales de una solicitud retirada."""
        if generation == self.job.generation:
            self.progress.setRange(0, total)
            self.progress.setValue(done)

    def _clock(self, moment):
        """Fecha y desfase explícitos también al cruzar medianoche o repetir hora civil."""
        return local_moment(moment, self._request.longitude, self._request.clock).strftime("%d/%m %H:%M %z")

    def _delivered(self, generation, kind, result, error):
        """Rechaza resultados tardíos; nunca convierte un fallo en cero horas disponibles."""
        if generation != self.job.generation:
            return
        if error:
            self._set_busy(False)
            self.status.setText(error)
            return
        if kind == "preview":
            self._draw_preview(result)
            return
        if kind == "extension":
            self._set_busy(False)
            request = self._extension_request
            self._extension_request = None
            if request is None:
                return
            assigned = sum(balance.assigned_s for balance in result.balances)/3600
            previous = sum(balance.assigned_s for balance in self._result.balances)/3600 if self._result else 0
            choice = QMessageBox.question(self, "Ampliación calculada",
                                          f"Hasta {request.end}: {assigned:.2f} h propuestas frente a {previous:.2f} h actuales.\n"
                                          "¿Adoptar el nuevo rango y su propuesta? El maestro guardado no cambia hasta confirmarlo.",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if choice != QMessageBox.StandardButton.Yes:
                self.status.setText(f"Ampliación evaluada: {assigned:.2f} h; no se adoptaron fechas ni se modificó el plan.")
                return
            self._restoring = True
            try:
                self.end.setDate(QDate.fromString(request.end, "yyyy-MM-dd"))
            finally:
                self._restoring = False
            self._request = request
            self.owner._multinight_data = self.snapshot()
            self.owner._draft.changed()
        self._set_busy(False)
        self._result = result
        self.alternative.blockSignals(True)
        self.alternative.clear()
        for choice in result.alternatives:
            hours = sum(balance.assigned_s for balance in choice.balances)/3600
            nights = len({visit.night for visit in choice.visits})
            self.alternative.addItem(f"{choice.label} · {hours:.2f} h · {nights} noches", choice.key)
        self.alternative.setCurrentIndex(self.alternative.findData(result.selected))
        self.alternative.blockSignals(False)
        self.alternative.setVisible(bool(result.alternatives))
        self.timeline.set_plan(self._request, result)
        self.coverage_cards.set_plan(self._request, result)
        self.result_views.setCurrentWidget(self.timeline if result.visits else self.windows_table if self._request.policy == "windows_only" else self.allocations_table)
        self.save_plan_button.setEnabled(bool(result.allocations) and self._request.policy != "windows_only" and not self._master_readonly_view)
        names = {obj.key:obj.name for obj in self._request.objectives}
        _fill(self.allocations_table, [(item.night, names[item.objective], item.tile, item.filter_name,
                                       self._clock(item.start), self._clock(item.end), item.frames) for item in result.allocations])
        _fill(self.balance_table, [(names[item.objective], item.tile, item.filter_name, f"{item.requested_s/3600:.3f}",
                                   f"{item.assigned_s/3600:.3f}", f"{(item.requested_s-item.assigned_s)/3600:.3f}") for item in result.balances])
        _fill(self.windows_table, [(item.night, names[item.objective], item.tile, self._clock(item.start), self._clock(item.end))
                                  for item in result.opportunities])
        requested = sum(item.requested_s for item in result.balances)/3600
        assigned = sum(item.assigned_s for item in result.balances)/3600
        operational = sum((event.end-event.start).total_seconds() for event in result.operations)/3600
        self.summary.setText(f"{self.name.text() or 'Sin nombre'} · {len(names)} objetos\n"
                             f"{assigned:.2f} h propuestas / {requested:.2f} h solicitadas · faltan {requested-assigned:.2f} h\n"
                             f"{operational:.2f} h operación · {assigned+operational:.2f} h ocupadas · sin confirmar")
        self.status.setText("Revisa la cobertura por objeto, filtro y tesela antes de confirmar el plan.")
        if not result.opportunities:
            self.status.setText("No hay ventanas que cumplan todas las restricciones. Revisa disponibilidad y condiciones.")
        elif not result.allocations:
            self.status.setText("No hay reparto normal con los mínimos y límites elegidos; revisa cobertura, excepciones o una ampliación.")
            if self._request.policy == "balanced":
                self.result_views.setCurrentWidget(self.coverage_cards)
        self.tabs.setCurrentIndex(3)
        if result.visits:
            self.timeline.setCurrentRow(0)
        elif result.opportunities:
            self.windows_table.selectRow(0)

    def _choose_alternative(self, _index):
        """Las excepciones requieren una elección confirmada y nunca se adoptan al recibir el cálculo."""
        if self._result is None or not self.alternative.currentData():
            return
        key = self.alternative.currentData()
        choice = next(value for value in self._result.alternatives if value.key == key)
        if choice.requires_consent and QMessageBox.question(
            self, "Alternativa excepcional", "Esta propuesta permite fragmentación y/o un resto final corto. "
            "¿Quieres seleccionarla?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            self.alternative.blockSignals(True)
            self.alternative.setCurrentIndex(self.alternative.findData(self._result.selected))
            self.alternative.blockSignals(False)
            return
        self._delivered(self.job.generation, "plan", select_alternative(self._result, key), "")

    def _consider_extension(self):
        """Evalúa días adicionales elegidos por el usuario; no cambia el rango sin aceptar el resultado calculado."""
        if self._master_readonly_view:
            self.status.setText("Recalcula con las condiciones actuales antes de estudiar otra revisión del maestro.")
            return
        if self._request is None or self._result is None:
            self.status.setText("Calcula primero la propuesta actual antes de comparar una ampliación.")
            return
        days, accepted = QInputDialog.getInt(self, "Estudiar ampliación", "Días adicionales a evaluar", 7, 1, 365)
        if not accepted:
            return
        request = replace(self._request, end=(date.fromisoformat(self._request.end)+timedelta(days=days)).isoformat())
        try:
            availability(request)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._extension_request = request
        self.status.setText("Evaluando ampliación sin modificar el rango actual…")
        self._set_busy(True)
        self.job.start("extension", request)

    def _inspect_visit(self, visit):
        """Sincroniza selección visual, detalle textual y curva de la tesela de ese bloque."""
        if self._result is None:
            return
        frame = next((value for value in self._result.allocations if value.objective == visit.objective
                      and visit.start <= value.start < value.end <= visit.end and value.night == visit.night), None)
        if frame:
            name = next(obj.name for obj in self._request.objectives if obj.key == visit.objective)
            self.block_details.setText(f"{name} · {self._clock(visit.start)} → {self._clock(visit.end)}\n{visit.reason}")
            self._inspect(frame)

    def _inspect_allocation(self):
        """Seleccionar un bloque consulta su franja real, no el top del ranking legacy."""
        index = self.allocations_table.currentRow()
        if self._result and index >= 0:
            item = self._result.allocations[index]
            self._inspect(item)

    def _inspect_window(self):
        """La capacidad potencial sigue consultable aunque no haya tomas asignadas."""
        index = self.windows_table.currentRow()
        if self._result and index >= 0:
            self._inspect(self._result.opportunities[index])

    def _inspect(self, item):
        """Inspecciona la noche en worker, sin cambiar entradas ni autoguardar resultados derivados."""
        index = next((i for i, value in enumerate(self._objectives) if value["objective"]["key"] == item.objective), -1)
        if index >= 0:
            self.objects_table.selectRow(index)
        name = next(obj.name for obj in self._request.objectives if obj.key == item.objective)
        self._preview_caption = f"{name} · {item.night} · tesela {item.tile}"
        self._preview_key = item.objective, item.tile, item.night
        self.curve.clear()
        self.job.start("preview", self._request, (item.objective, item.tile, item.night))
        self.curve_status.setText(self._preview_caption + " · leyendo curva…")

    def _draw_preview(self, preview):
        """Altura, Luna, horizonte y admisibilidad se dibujan sobre tiempo real, incluyendo DST."""
        self.curve.clear()
        first = utc_moment(preview.times[0])
        hours = [(utc_moment(value)-first).total_seconds()/3600 for value in preview.times]
        self.curve_axis.set_context(first, utc_moment(preview.times[-1]), self._request.longitude, self._request.clock)
        self.curve.plot(hours, preview.altitude, pen=pg.mkPen("#60a5fa", width=2), name="Objeto")
        self.curve.plot(hours, preview.moon_altitude, pen=pg.mkPen("#9ca3af"), name="Luna")
        self.curve.plot(hours, preview.horizon, pen=pg.mkPen("#f59e0b"), name="Horizonte")
        self.curve.addItem(pg.InfiniteLine(pos=self._request.minimum_altitude, angle=0, pen=pg.mkPen("#94a3b8", style=Qt.PenStyle.DashLine)))
        for start, end in sampled_windows(hours, preview.allowed):
            band = pg.LinearRegionItem((start, end), movable=False, brush=pg.mkBrush(34, 197, 94, 35), pen=pg.mkPen(None))
            band.setZValue(-10)
            self.curve.addItem(band)
        if self._result is not None and self._request.profile.meridian_flip:
            track = next((track for track in self._result.tracks if (track.objective, track.tile, track.night) == self._preview_key), None)
            if track:
                for transit in track.transits:
                    center = (transit-first).total_seconds()/3600
                    half = self._request.profile.meridian_s/7200
                    if center+half >= 0 and center-half <= hours[-1]:
                        veto = pg.LinearRegionItem((center-half, center+half), movable=False,
                                                   brush=pg.mkBrush(148, 163, 184, 100), pen=pg.mkPen("#94a3b8"))
                        self.curve.addItem(veto)
        self.curve.setYRange(0, 90)
        blocks = draw_schedule(self.curve, self._result, self._preview_key, first, self._request)
        detail = f"\nPlanificado: {blocks}" if blocks else "\nSin bloque asignado a esta tesela y noche."
        self.curve_status.setText(f"{self._preview_caption}\nVerde: admisible · banda/barra: plan · trama: maniobras"+detail)
        self.curve_status.setToolTip(preview.accuracy)

    def _details(self):
        """Expone hipótesis, procedencia y límites sin saturar la superficie de trabajo."""
        text = "Calcula distribución o consulta ventanas para ver sus condiciones."
        if self._result:
            text = "\n\n".join(self._result.warnings+self._result.accuracy)
        QMessageBox.information(self, "Condiciones del cálculo", text)

    def _save_draft(self):
        """Confirma el autoguardado del editor, sin convertirlo en plan creado ni generar sesiones legacy."""
        self.owner._multinight_data = self.snapshot()
        if self.owner._draft.changed():
            self.status.setText("Borrador guardado; no convierte esta propuesta en plan creado.")
        else:
            self.status.setText(self.owner._draft.label.text())

    def _new_plan(self):
        """Empieza otro borrador solo tras consentimiento, sin editar ni retirar el maestro anterior."""
        choice = QMessageBox.question(self, "Nuevo plan", "Hay un único borrador activo. Empezar otro reemplazará "
                                      "la configuración de este editor; guarda el maestro si quieres conservar el plan. "
                                      "Los archivos ya guardados no se modifican. ¿Continuar?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return
        self.job.stop()
        self._restoring = True
        try:
            self.restore(self._defaults())
        finally:
            self._restoring = False
        self.owner._multinight_file = None
        self.sky.clear_target()
        self.sky.clear_framing()
        self.fov_label.setText("Selecciona un objetivo")
        self._changed()

    def _save_master(self):
        """Confirma las horas pendientes antes de guardar el único maestro externo, sin vincular capturas."""
        if self._master_readonly_view:
            self.status.setText("Calendario guardado en consulta; recalcula antes de confirmar una nueva revisión.")
            return
        if self._result is None or self._request is None or not self._result.allocations:
            self.status.setText("Calcula una distribución vigente antes de guardar el plan creado.")
            return
        if not self.name.text().strip():
            self.status.setText("Escribe el nombre en Valores del plan.")
            self.tabs.setCurrentIndex(2)
            return
        requested = sum(item.requested_s for item in self._result.balances)/3600
        assigned = sum(item.assigned_s for item in self._result.balances)/3600
        choice = QMessageBox.question(self, "Confirmar plan creado",
                                      f"{assigned:.2f} h distribuidas / {requested:.2f} h solicitadas.\n"
                                      f"Quedan {requested-assigned:.2f} h pendientes.\n"
                                       "Incluye los tiempos operativos informados; no pronóstico meteorológico.\n"
                                       "Se guardará en data/plans; un maestro externo abierto se conserva sin modificar.\n"
                                      "¿Confirmar y guardar el maestro del plan?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return
        reference = self.owner._multinight_file
        try:
            if self.build_request() != self._request:
                raise ValueError("La ubicación o sus restricciones cambiaron; recalcula antes de confirmar.")
            previous = None
            if reference:
                previous, digest = read_document(reference["path"])
                if digest != reference["sha256"]:
                    raise ValueError("El maestro cambió desde su apertura. Ábrelo de nuevo antes de guardar.")
                if not previous.get("reference_scope") or previous["reference_scope"] != reference_scope():
                    raise ValueError("Las referencias son de otra base o de origen no verificado; requieren revinculación explícita.")
            scope = reference_scope(create=True)
            document = make_document(self.snapshot(), self._request, self._result, previous, scope=scope)
            path, digest = save_local_document(document, reference)
        except (ValueError, TypeError, OSError, KeyError, sqlite3.Error) as exc:
            self.status.setText(f"No se pudo guardar el maestro: {exc}")
            return
        self.owner._multinight_file = {"path":str(path), "sha256":digest}
        self.owner._multinight_data = self.snapshot()
        indexed = ""
        try:
            index_document(path, document, previous_path=reference["path"] if reference else None)
        except (ValueError, OSError, sqlite3.Error) as exc:
            indexed = f" · Índice local no actualizado: {exc}"
        saved_draft = self.owner._draft.changed()
        self.summary.setText(f"{self.name.text()} · plan creado\n{assigned:.2f} h distribuidas · {requested-assigned:.2f} h pendientes")
        draft_error = "" if saved_draft else " · No se pudo guardar la referencia en el borrador"
        self.status.setText(f"Maestro guardado: {path}{indexed}{draft_error}")

    def _export_master(self):
        """Exporta el maestro confirmado sin cambiar su identidad, revisión, ruta activa ni borrador."""
        reference = self.owner._multinight_file
        if not reference:
            self.status.setText("Guarda primero el plan creado; exportar no confirma una propuesta pendiente.")
            return
        try:
            document, digest = read_document(reference["path"])
            if digest != reference["sha256"]:
                raise ValueError("El maestro cambió desde su apertura; ábrelo de nuevo antes de exportar.")
            path = QFileDialog.getSaveFileName(self, "Exportar copia del maestro guardado",
                                               str(plans_directory()/plan_filename(document["editor"]["name"])),
                                               "Plan PASS (*.pass-plan.json)")[0]
            if not path:
                return
            if not path.lower().endswith(".pass-plan.json"):
                path += ".pass-plan.json"
            write_document(path, document)
        except (ValueError, TypeError, OSError, sqlite3.Error) as exc:
            self.status.setText(f"No se pudo exportar la copia: {exc}")
            return
        self.status.setText(f"Copia exportada: {path}. El maestro activo no cambia.")

    def _open_master(self):
        """Abre por elección explícita; valida todo antes de reemplazar la configuración del borrador actual."""
        path = QFileDialog.getOpenFileName(self, "Abrir maestro", str(plans_directory()), "Plan PASS (*.pass-plan.json)")[0]
        if not path:
            return
        try:
            document, digest = read_document(path)
            if not document.get("reference_scope") or document["reference_scope"] != reference_scope():
                self.status.setText("Maestro portable legible, pero sus referencias locales requieren revinculación explícita. "
                                    "No se adoptan objetos/equipos/ubicaciones por IDs o nombres coincidentes.")
                return
        except (ValueError, TypeError, OSError, sqlite3.Error) as exc:
            self.status.setText(f"No se pudo abrir el maestro: {exc}. El borrador actual se conserva.")
            return
        choice = QMessageBox.question(self, "Abrir plan", "Sustituirá la configuración de este editor. "
                                      "No modifica el archivo ni el trabajo del Apilador. ¿Continuar?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return
        try:
            self._restoring = True
            self.restore(document["editor"])
        except (ValueError, KeyError, TypeError) as exc:
            self.status.setText(f"No se pudo recuperar la configuración: {exc}")
            return
        finally:
            self._restoring = False
        self.owner._multinight_file = {"path":path, "sha256":digest}
        self._changed()
        if document["version"] == 2:
            self._request, result = editor_calendar(document)
            self._master_readonly_view = True
            self._delivered(self.job.generation, "plan", result, "")
        self.status.setText("Maestro abierto por valor. Recalcula las condiciones actuales antes de confirmar una nueva revisión.")

    def closeEvent(self, event):
        """Cancela entregas y evita cerrar si no se pueden confirmar las últimas ediciones del borrador."""
        self.job.stop()
        if not self.owner._draft.flush():
            self.status.setText(self.owner._draft.label.text())
            event.ignore()
            return
        super().closeEvent(event)

    def refresh_references(self):
        """Refresca opciones sin elegir sustitutos ni borrar referencias desaparecidas del borrador."""
        try:
            targets = personal_catalog.list_objects()
            locations = {row["id"]:row for row in list_locations()}
            setups = {row["id"]:row for row in list_setups()}
        except sqlite3.Error as exc:
            self.job.stop()
            self._request = self._result = None
            self.timeline.clear()
            self.coverage_cards.set_message("Referencias no disponibles · configuración conservada")
            self.save_plan_button.setEnabled(False)
            self._set_busy(False)
            self.curve.clear()
            for table in (self.allocations_table, self.balance_table, self.windows_table):
                table.setRowCount(0)
            self.summary.setText("Referencias no disponibles · configuración conservada")
            self.status.setText(f"No se pudieron leer las referencias: {exc}")
            return False
        self._targets, self._locations, self._setups = targets, locations, setups
        for combo, rows, placeholder in ((self.location, self._locations, "Elegir ubicación…"),
                                          (self.setup, self._setups, "Sin equipo seleccionado")):
            selected = combo.currentData()
            combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItem(placeholder, None)
                for key, item in rows.items():
                    combo.addItem(item["name"], key)
                if selected is not None and selected not in rows:
                    combo.addItem(f"Referencia {selected} no disponible", selected)
                combo.setCurrentIndex(combo.findData(selected))
            finally:
                combo.blockSignals(False)
        self._show_hours()
        if self._request is not None:
            try:
                changed = self.build_request() != self._request
            except (ValueError, TypeError, KeyError, sqlite3.Error):
                changed = True
            if changed:
                self._changed()
                self.status.setText("Las referencias cambiaron; revisa las entradas y recalcula.")
        return True

    def showEvent(self, event):
        """Relee referencias al volver a la pestaña; no recupera automáticamente un borrador aplazado."""
        super().showEvent(event)
        self.refresh_references()

    def hideEvent(self, event):
        """Al salir de la vista cancela trabajo pendiente y entregas tardías, sin borrar entradas o resultados completos."""
        calculating = self.cancel_button.isEnabled()
        self.job.stop()
        self._set_busy(False)
        if calculating:
            self.status.setText("Cálculo cancelado al salir · borrador conservado")
        super().hideEvent(event)
