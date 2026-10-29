"""Carta independiente de exploración: reutiliza el lienzo vigente de Planificación sin compartir su navegación."""

from datetime import UTC, datetime

from PyQt6.QtCore import QDate, QDateTime, Qt, QTime, QTimeZone
from PyQt6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from equipment.localizations import list_locations
from planners.sky_state import civil_to_utc, location_clock
from planners.timezones import local_moment
from ui.planner_tab.planificacion.planetario_visual import PlanetarioVisual
from ui.sky_context import SkyContext


class PlanetaryPage(QWidget):
    """Explora fecha/sitio/objetos con estado propio durante esta apertura, sin guardar planes ni moverlos."""

    def __init__(self, parent=None):
        """Crea un lienzo independiente y controles locales; la ubicación inicial llega de Resumen."""
        super().__init__(parent)
        self._initialized = False
        self._location_id = None
        self._locations = {}
        self._state = None
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        title = QLabel("Planetario")
        title.setStyleSheet("font-size: 22pt; font-weight: 600;")
        root.addWidget(title)
        root.addWidget(QLabel("Explora tu cielo · arrastra para navegar y usa la rueda para acercarte"))
        controls = QHBoxLayout()
        self._location = QComboBox()
        self._location.setAccessibleName("Ubicación de exploración del Planetario")
        self._location.setMinimumContentsLength(14)
        self._location.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._date = QDateTimeEdit()
        # El control conserva campos civiles sin normalizarlos por el huso del ordenador.
        self._date.setTimeZone(QTimeZone(b"UTC"))
        self._date.setDisplayFormat("dd/MM/yyyy HH:mm")
        self._date.setCalendarPopup(True)
        self._date.setDateTime(QDateTime.currentDateTimeUtc())
        self._date.setAccessibleName("Fecha y hora local de exploración")
        now = QPushButton("Ahora")
        now.clicked.connect(self._now)
        controls.addWidget(QLabel("Ubicación"))
        controls.addWidget(self._location, 1)
        controls.addWidget(self._date)
        controls.addWidget(now)
        root.addLayout(controls)
        search = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar un objeto o alias: M31, NGC 224…")
        self._search.setAccessibleName("Buscar objeto en la carta")
        find = QPushButton("Centrar objeto")
        find.clicked.connect(self._find)
        self._search.returnPressed.connect(self._find)
        reset = QPushButton("Restablecer vista")
        search.addWidget(self._search, 1)
        search.addWidget(find)
        search.addWidget(reset)
        root.addLayout(search)
        self.sky = PlanetarioVisual()
        reset.clicked.connect(self.sky.reset_view)
        self.sky.object_clicked.connect(self._select_object)
        root.addWidget(self.sky, 1)
        self._selection = QLabel("Selecciona un objeto para resaltarlo. Tu plan no se modificará.")
        self._selection.setTextFormat(Qt.TextFormat.PlainText)
        self._selection.setWordWrap(True)
        root.addWidget(self._selection)
        self._context_label = QLabel("Elige una ubicación en Resumen o en este selector.")
        self._context_label.setTextFormat(Qt.TextFormat.PlainText)
        self._context_label.setWordWrap(True)
        root.addWidget(self._context_label)
        note = QLabel("Carta ecuatorial J2000 compartida con Planificación. Fecha y sitio describen el contexto solar/lunar; "
                      "no se simula aquí un horizonte, movimiento propio ni posiciones planetarias.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #94a3b8; font-size: 11pt;")
        root.addWidget(note)
        self._context = SkyContext(self)
        self._context.ready.connect(self._context_ready)
        self._location.currentIndexChanged.connect(self._choose_location)
        self._date.dateTimeChanged.connect(self._update_context)
        self.reload_locations()

    def reload_locations(self):
        """Actualiza opciones conservando la elección local; no cambia Resumen ni Planificación."""
        selected = self._location.currentData()
        self._locations = {row["id"]: row for row in list_locations()}
        self._location.blockSignals(True)
        self._location.clear()
        self._location.addItem("Selecciona ubicación…", None)
        for key, row in self._locations.items():
            self._location.addItem(row["name"], key)
        index = self._location.findData(selected)
        self._location.setCurrentIndex(max(0, index))
        self._location.blockSignals(False)
        if self._initialized:
            self._choose_location()

    def set_initial_location(self, location_id):
        """Aplica referencia de Resumen una sola vez; no deshace la exploración tras cambiar de pestaña."""
        if self._initialized or location_id not in self._locations:
            return
        self._initialized = True
        self._location.setCurrentIndex(self._location.findData(location_id))
        self._now()

    def _choose_location(self, *_args):
        """Recuerda solo en memoria la ubicación de esta exploración."""
        initial = not self._initialized
        self._location_id = self._location.currentData()
        if self._location_id is not None:
            self._initialized = True
        if initial and self._location_id is not None:
            self._now()
            return
        self._update_context()

    def _now(self):
        """Lleva el control a la hora actual de la ubicación elegida, sin usar el huso del ordenador como sitio."""
        row = self._locations.get(self._location.currentData())
        if row:
            try:
                value = local_moment(datetime.now(UTC), row["longitude"], location_clock(row)).replace(tzinfo=None)
                self._date.setDateTime(QDateTime(QDate(value.year, value.month, value.day),
                                                QTime(value.hour, value.minute, value.second), QTimeZone(b"UTC")))
            except ValueError as exc:
                self._context_label.setText(str(exc))
                return
        self._update_context()

    def _update_context(self, *_args):
        """Valida reloj civil y solicita datos reales sin recolocar la cámara ni calcular ventanas de captura."""
        self._context.stop()
        self._state = None
        row = self._locations.get(self._location.currentData())
        if not row:
            self._context_label.setText("Selecciona una ubicación guardada para el contexto solar/lunar.")
            return
        try:
            moment = civil_to_utc(self._date.dateTime().toPyDateTime(), row)
        except ValueError as exc:
            self._context_label.setText(str(exc))
            return
        clock = location_clock(row)
        self._date.setToolTip("Hora aproximada por longitud" if clock is None else f"Hora civil de la ubicación · {clock}")
        self._context_label.setText("Leyendo contexto local… La carta se puede seguir explorando.")
        self._context.request(row, moment)

    def _context_ready(self, state, error):
        """Muestra estado/avisos del cálculo actual sin mantener datos previos como si fueran vigentes."""
        self._state = state
        if error:
            self._context_label.setText(f"Contexto no disponible: {error}")
            return
        self._context_label.setText(f"{state.title} · Luna {state.illumination:.0%} iluminada · {state.accuracy.summary}")
        self._context_label.setToolTip(state.accuracy.details)

    def _find(self):
        """Resuelve en la instantánea propia de la carta; ambiguos/ausentes no eligen un candidato al azar."""
        text = self._search.text().strip()
        if not text:
            return
        if self.sky.set_target(text):
            self._selection.setText(f"Objeto seleccionado: {text} · solo exploración")
        else:
            self._selection.setText("No hay una coincidencia única con coordenadas disponibles para esa búsqueda.")

    def reload_context(self):
        """Retira el rótulo del objeto descartado por recarga de carta y renueva la procedencia del contexto."""
        self._selection.setText("Catálogos recargados. Selecciona un objeto para explorarlo.")
        if self.isVisible():
            self._update_context()
        else:
            self._context.stop()
            self._state = None
            self._context_label.setText("Contexto pendiente de actualizar tras cambiar catálogos.")

    def showEvent(self, event):
        """Renueva un contexto invalidado sin restaurar fecha, ubicación o cámara exploradas."""
        super().showEvent(event)
        if self._state is None and self._location.currentData() is not None:
            self._update_context()

    def _select_object(self, object_id, catalog):
        """Resalta un objeto pulsado solo en este lienzo."""
        self.sky.set_target(object_id, catalog)
        self._selection.setText(f"{object_id} · {catalog.upper()} · solo exploración")

    def closeEvent(self, event):
        """Invalida entregas pendientes, sin guardar la exploración para otro arranque."""
        self._context.stop()
        super().closeEvent(event)
