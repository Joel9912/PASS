"""Subpestaña **Búsqueda** del Planificador.

Layout (rejilla de 3×2, reparto del programa original):

```
┌─ Filtros ──────────┐  ┌─ Catálogo ───────────── [⭐ Añadir] ──┐
│ Buscar / Tipo /    │  │ # ID Tipo Const Mag RA Dec Tamaño      │
│ Catálogo / Const /  │  │             Tránsito  Horas >30°       │
│ Mag / Altitud /     │  │                                       │
│ Orden  [Aplicar]    │  ├─ Curva de Tránsito (PyQtGraph) ───────┤
├─────────────────────┤  │ altitud + sep. lunar + ventanas        │
│ Efemérides Sol/Luna │  ├─ Condiciones meteorológicas ──────────┤
├─────────────────────┤  │ Seeing  Nubes  Humedad  Rocío  …       │
│ 📍 Ubicación        │  └───────────────────────────────────────┘
└─────────────────────┘
```

Señales hacia fuera: ``object_selected(object_id, catalog)`` al marcar una
fila y ``add_to_personal(object_id, catalog)`` al pulsar el botón.

La **barra de ubicación** (``self.location_bar``) vive en la tercera fila de
la izquierda: aquí alimenta efemérides, curva y clima, y `PlannerPage` la
reenvía a Planificación por señal. La fecha la aporta el panel de efemérides
(señal ``date_changed``).
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from planners.celestial_search import (
    CATALOGS,
    CONSTELLATIONS,
    SORT_OPTIONS,
    TYPE_GROUPS,
    SearchFilters,
    search,
)
from planners.transit import night_curve

from ...style import PALETTE
from ..widgets import (
    EphemerisPanel,
    LocationBar,
    TransitCurve,
    WeatherCards,
    _type_label,
    format_dec,
    format_ra,
    format_size,
)

#: Columnas de la tabla en el orden del mockup.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("#", "40"),
    ("ID", "90"),
    ("Tipo", "110"),
    ("Constelación", "140"),
    ("Mag", "60"),
    ("RA J2000", "100"),
    ("Dec J2000", "110"),
    ("Tamaño", "90"),
    ("Tránsito", "80"),
    ("Horas >30°", "90"),
)

#: Catálogos → etiqueta.
CATALOG_LABELS: dict[str, str] = {
    "messier": "Messier", "ngc": "NGC", "ic": "IC", "barnard": "Barnard",
    "caldwell": "Caldwell", "ldn": "LDN (nebulosas oscuras)", "other": "Otros",
}

#: Opciones de filtro con su valor (o None para "sin límite").
MAGNITUDE_OPTIONS: tuple[tuple[str, float | None], ...] = (
    ("Todas", None), ("≤ 6.0", 6.0), ("≤ 8.0", 8.0),
    ("≤ 10.0", 10.0), ("≤ 12.0", 12.0),
)
ALTITUDE_OPTIONS: tuple[tuple[str, float | None], ...] = (
    ("Todas", None), ("≥ 30°", 30.0), ("≥ 45°", 45.0), ("≥ 60°", 60.0),
)


# --------------------------------------------------------------------------- #
#          E T I Q E T A S   S Ó L O   D E   E S T A   S U B P E S T A Ñ A     #
# --------------------------------------------------------------------------- #
# El formato de datos compartido (format_ra/dec/size, _type_label, TYPE_LABELS)
# se mudó a `widgets.py` porque Catálogo Personal también lo necesita: aquí
# nadie importa de una subpestaña a otra.
def _constellation_label(code: str | None) -> str:
    if not code:
        return "--"
    return CONSTELLATIONS.get(code, code)


def _number(value: float | None, template: str) -> str:
    return template.format(value) if value is not None else "--"


# --------------------------------------------------------------------------- #
#                              S U B P E S T A Ñ A                             #
# --------------------------------------------------------------------------- #
class BusquedaTab(QWidget):
    """Filtros + tabla de resultados + efemérides + curva + tarjetas de clima."""

    object_selected = pyqtSignal(str, str)   # object_id, catalog
    add_to_personal = pyqtSignal(str, str)   # object_id, catalog

    #: Límite de filas: la tabla no debe perder la fluidez con 15k objetos.
    ROW_LIMIT = 500

    #: Altura fija de fila de la tabla de objetos (resizeRowsToContents
    #: daba 37 px, muy pegado; con 42 el texto respira).
    ROW_HEIGHT = 42

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._rows: list[dict] = []
        self._latitude: float | None = None
        self._longitude: float | None = None
        self._utc_offset_hours: float | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # Rejilla 3×2 (reparto del original, con la ubicación en la tercera
        # fila a la izquierda de las condiciones meteorológicas):
        #   fila 1: Filtros            | Catálogo
        #   fila 2: Efemérides Sol/Luna| Curva de tránsito
        #   fila 3: Ubicación          | Condiciones meteorológicas
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 3)
        grid.setRowStretch(0, 3)
        grid.setRowStretch(1, 3)
        grid.setRowStretch(2, 1)

        grid.addWidget(self._build_filters(), 0, 0, 1, 1)
        grid.addWidget(self._build_results(), 0, 1, 1, 1)
        grid.addWidget(self._build_ephemeris(), 1, 0, 1, 1)
        grid.addWidget(self._build_curve(), 1, 1, 1, 1)

        # Compartida con Planificación: aquí vive y el resto la consume.
        self.location_bar = LocationBar()
        self.location_bar.location_changed.connect(self.set_location)
        grid.addWidget(self.location_bar, 2, 0, 1, 1)
        grid.addWidget(self._build_weather(), 2, 1, 1, 1)
        root.addLayout(grid, 1)

        self.refresh()

    # -- Construcción de los paneles ----------------------------------------
    def _build_filters(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("GroupFrame")
        layout = QGridLayout(panel)
        # Compacto a propósito: esta fila compite por altura con Efemérides y
        # un campo más alto = texto cortado cuando la rejilla la estrangula.
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(3)
        layout.setColumnStretch(1, 1)

        title = QLabel("Filtros de búsqueda")
        title.setObjectName("PanelTitle")
        layout.addWidget(title, 0, 0, 1, 2)

        self._text = QLineEdit()
        self._text.setPlaceholderText("M31, orion, NGC 224…")
        self._text.returnPressed.connect(self.refresh)
        layout.addWidget(QLabel("Buscar objetivo"), 1, 0)
        layout.addWidget(self._text, 1, 1)

        self._type = QComboBox()
        self._type.addItem("Todos", None)
        for group in TYPE_GROUPS:
            self._type.addItem(group.capitalize(), group)
        layout.addWidget(QLabel("Tipo de objeto"), 2, 0)
        layout.addWidget(self._type, 2, 1)

        self._catalog = QComboBox()
        self._catalog.addItem("Todos", None)
        for catalog in CATALOGS:
            self._catalog.addItem(
                CATALOG_LABELS.get(catalog, catalog.capitalize()), catalog
            )
        layout.addWidget(QLabel("Catálogo"), 3, 0)
        layout.addWidget(self._catalog, 3, 1)

        self._constellation = QComboBox()
        self._constellation.addItem("Todas", None)
        for code, name in sorted(CONSTELLATIONS.items(), key=lambda kv: kv[1]):
            self._constellation.addItem(name, code)
        layout.addWidget(QLabel("Constelación"), 4, 0)
        layout.addWidget(self._constellation, 4, 1)

        self._magnitude = QComboBox()
        for label, value in MAGNITUDE_OPTIONS:
            self._magnitude.addItem(label, value)
        layout.addWidget(QLabel("Magnitud"), 5, 0)
        layout.addWidget(self._magnitude, 5, 1)

        self._altitude = QComboBox()
        for label, value in ALTITUDE_OPTIONS:
            self._altitude.addItem(label, value)
        layout.addWidget(QLabel("Altitud mínima"), 6, 0)
        layout.addWidget(self._altitude, 6, 1)

        self._sort = QComboBox()
        for label, key in SORT_OPTIONS.items():
            self._sort.addItem(label, key)
        layout.addWidget(QLabel("Ordenar por"), 7, 0)
        layout.addWidget(self._sort, 7, 1)

        apply_button = QPushButton("⚡ Aplicar filtros")
        apply_button.setObjectName("ApplyFilters")
        apply_button.clicked.connect(self.refresh)
        layout.addWidget(apply_button, 8, 0, 1, 2)

        layout.setRowStretch(9, 1)
        return panel

    def _build_results(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Catálogo")
        title.setObjectName("PanelTitle")
        header.addWidget(title)
        self._count = QLabel("0 objetos")
        self._count.setObjectName("HintLabel")
        header.addWidget(self._count)
        header.addStretch(1)

        # Botón arriba a la derecha, como en el original (estrella dorada).
        self._add_button = QPushButton("⭐ Añadir a Mi Lista")
        self._add_button.setObjectName("StarButton")
        self._add_button.setEnabled(False)
        self._add_button.setToolTip(
            "Guarda el objeto seleccionado en el catálogo personal"
        )
        self._add_button.clicked.connect(self._on_add_clicked)
        header.addWidget(self._add_button)
        layout.addLayout(header)

        # Ojo: QTableWidget(filas, 0) + setHorizontalHeaderLabels NO crea
        # columnas (solo etiqueta las existentes); hay que pasar las columnas.
        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels([label for label, _ in COLUMNS])
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(self.ROW_HEIGHT)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(False)
        self._table.setWordWrap(False)
        self._table.setMinimumHeight(220)

        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # Sin stretchLast: «Horas >30°» se quedaba con TODO el sobrante
        # (~366 px para ~75 de contenido). El reparto lo hace
        # _spread_surplus a partir de los anchos de contenido.
        header_view.setStretchLastSection(False)
        for index, (_, width) in enumerate(COLUMNS):
            self._table.setColumnWidth(index, int(width))
        # Base estable de reparto: anchos de contenido (los declarados
        # hasta la primera búsqueda; luego los medidos en _fill_table).
        self._content_widths: list[int] = [int(width) for _, width in COLUMNS]
        self._spreading = False
        self._table.viewport().installEventFilter(self)
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self._table, 1)
        return panel

    def _build_ephemeris(self) -> QWidget:
        # stretch=1: el panel llena su celda hasta la fila de Ubicación.
        # Antes iba un addStretch(1) después del panel, que se llevaba el
        # sobrante y dejaba el hueco que se veía sobre Ubicación. El
        # sizeHint del container no cambia, así que la altura de las
        # filas de Filtros y Ubicación tampoco.
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self._ephemeris = EphemerisPanel()
        self._ephemeris.date_changed.connect(self._on_date_changed)
        layout.addWidget(self._ephemeris, 1)
        return container

    def _build_curve(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self._curve = TransitCurve()
        layout.addWidget(self._curve)
        return container

    def _build_weather(self) -> QWidget:
        """Tercera fila, derecha: condiciones meteorológicas (caja del original)."""
        panel = QWidget()
        panel.setObjectName("GroupFrame")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Título a la izquierda y, a la derecha, el aviso de proveedores
        # sin conectar (así no estira las tarjetas ni les corta el título).
        self._weather = WeatherCards()
        title_row = QHBoxLayout()
        title = QLabel("Condiciones meteorológicas y seeing atmosférico")
        title.setObjectName("PanelTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self._weather.note_label)
        layout.addLayout(title_row)

        layout.addWidget(self._weather)
        layout.addStretch(1)
        return panel

    # -- API pública ---------------------------------------------------------
    def set_location(
        self, latitude: float, longitude: float, utc_offset_hours: float | None
    ) -> None:
        """Recibe la ubicación de la barra propia (compartida) y recalcula."""
        self._latitude = latitude
        self._longitude = longitude
        self._utc_offset_hours = utc_offset_hours
        self.refresh()

    def current_date_iso(self) -> str:
        """Fecha vigente en el panel de efemérides (``yyyy-MM-dd``)."""
        return self._ephemeris.current_date_iso()

    def refresh(self) -> None:
        """Aplica los filtros, refresca efemérides, curva y clima."""
        self._run_search()
        self._refresh_ephemeris()
        self._refresh_selected_curve()
        self._refresh_weather()

    def refresh_weather(self) -> None:
        """Solo las tarjetas de clima, sin repetir la búsqueda.

        Lo usa la ventana principal tras guardar API keys en
        Configuración, para que el «Falta conectar la API» desaparezca
        sin esperar al siguiente «Aplicar filtros».
        """
        self._refresh_weather()

    # -- Cálculos ------------------------------------------------------------
    def _filters(self) -> SearchFilters:
        max_magnitude = self._magnitude.currentData()
        min_altitude = self._altitude.currentData()
        return SearchFilters(
            catalogs=[self._catalog.currentData()]
            if self._catalog.currentData()
            else list(CATALOGS),
            max_magnitude=max_magnitude,
            object_types=[self._type.currentData()]
            if self._type.currentData()
            else [],
            constellation=self._constellation.currentData(),
            text=self._text.text().strip() or None,
            min_altitude=min_altitude,
            sort_by=self._sort.currentData(),
            latitude=self._latitude,
            longitude=self._longitude,
            date_iso=self.current_date_iso() or None,
            utc_offset_hours=self._utc_offset_hours,
        )

    def _run_search(self) -> None:
        rows = search(self._filters(), limit=self.ROW_LIMIT)
        self._rows = rows
        self._fill_table(rows)
        self._count.setText(
            f"{len(rows)} objetos"
            + (" (máx. {} fila)".format(self.ROW_LIMIT) if len(rows) == self.ROW_LIMIT else "")
        )

    def _fill_table(self, rows: list[dict]) -> None:
        header = self._table.horizontalHeader()
        # ResizeToContents recalcula el tamaño de TODAS las filas de la
        # columna en cada setItem (~36 ms/celda con 500 filas): la interfaz
        # se congelaba ~90 s. Solo interactivo durante el llenado.
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        try:
            self._table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                values = (
                    str(index + 1),
                    str(row.get("object_id") or "--"),
                    _type_label(row.get("type")),
                    _constellation_label(row.get("constellation")),
                    _number(row.get("magnitude"), "{:.2f}"),
                    format_ra(row.get("ra_hours")),
                    format_dec(row.get("dec_deg")),
                    format_size(row.get("size_major_arcmin"), row.get("size_minor_arcmin")),
                    str(row.get("transit_local") or "--"),
                    _number(row.get("hours_above_30"), "{:.1f} h"),
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 1:
                        # El ID va en azul, como en el original.
                        item.setForeground(QColor(PALETTE["accentLight"]))
                    # Todas las columnas centradas, igual que las
                    # cabeceras: antes Mag/Tránsito/Horas iban a la
                    # derecha y el resto a la izquierda.
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                    )
                    self._table.setItem(index, column, item)
            # Filas con aire: resizeRowsToContents daba 37 px.
            for index in range(len(rows)):
                self._table.setRowHeight(index, self.ROW_HEIGHT)
        finally:
            # Un solo pase de anchos de contenido y reparto del sobrante.
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            header.resizeSections()
            self._content_widths = [
                header.sectionSize(i) for i in range(len(COLUMNS))
            ]
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            self._spread_surplus()

    def _spread_surplus(self) -> None:
        """Anchuras de contenido más el sobrante repartido en proporción.

        Sin esto, con ``stretchLastSection`` la última columna
        («Horas >30°») se tragaba todo el ancho libre (~366 px para
        ~75 de contenido) y el resto de columnas quedaba justo. La base
        es siempre ``_content_widths`` (nunca los ya repartidos), para
        que cada reparto sea idempotente.
        """
        if self._spreading:
            return                          # no reentrar (barra ± viewport)
        self._spreading = True
        try:
            header = self._table.horizontalHeader()
            widths = self._content_widths
            total = sum(widths)
            if not total:
                return
            spare = self._table.viewport().width() - total
            if spare <= 16:
                # No sobra (o sobra migaja): los anchos de contenido,
                # con barra horizontal si hace falta.
                for index, width in enumerate(widths):
                    header.resizeSection(index, width)
                return
            for index, width in enumerate(widths):
                header.resizeSection(index, width + int(spare * width / total))
        finally:
            self._spreading = False

    def eventFilter(self, obj, event: QEvent) -> bool:
        """Al cambiar el ancho visible de la tabla, vuelve a repartir."""
        if obj is self._table.viewport() and event.type() == QEvent.Type.Resize:
            self._spread_surplus()
        return super().eventFilter(obj, event)

    def _refresh_ephemeris(self) -> None:
        if self._latitude is None or self._longitude is None:
            return
        self._ephemeris.refresh(
            self._latitude,
            self._longitude,
            self.current_date_iso(),
            self._utc_offset_hours,
        )

    def _refresh_weather(self) -> None:
        if self._latitude is None or self._longitude is None:
            return
        self._weather.refresh(
            self._latitude, self._longitude, self.current_date_iso()
        )

    def _refresh_selected_curve(self) -> None:
        row = self._selected_row()
        if row is None:
            self._curve.clear()
            return
        if row.get("ra_hours") is None:
            self._curve.clear("El objeto no tiene coordenadas")
            return
        if self._latitude is None or self._longitude is None:
            self._curve.clear(
                "Falta la ubicación: escribe lat/long en «📍 Ubicación»"
            )
            return
        self._curve.show_curve(
            night_curve(
                row["ra_hours"],
                row["dec_deg"],
                self._latitude,
                self._longitude,
                self.current_date_iso(),
                self._utc_offset_hours,
            ),
            target_label=str(row.get("object_id") or ""),
        )

    # -- Selección -----------------------------------------------------------
    def _selected_row(self) -> dict | None:
        rows = self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        if not rows:
            return None
        index = rows[0].row()
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def _on_row_selected(self) -> None:
        row = self._selected_row()
        has_row = row is not None
        self._add_button.setEnabled(has_row)
        if has_row:
            self.object_selected.emit(str(row["object_id"]), str(row["catalog"]))
        self._refresh_selected_curve()

    def _on_add_clicked(self) -> None:
        row = self._selected_row()
        if row is not None:
            self.add_to_personal.emit(str(row["object_id"]), str(row["catalog"]))

    def _on_date_changed(self, date_iso: str) -> None:
        self._run_search()
        self._refresh_ephemeris()
        self._refresh_selected_curve()
        self._refresh_weather()
