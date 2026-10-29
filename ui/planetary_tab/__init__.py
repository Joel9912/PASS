"""Carta independiente de exploración: reutiliza el lienzo vigente de Planificación sin compartir su navegación."""

import sqlite3
from datetime import UTC, datetime

from PyQt6.QtCore import QDate, QDateTime, Qt, QTime, QTimeZone, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from equipment.localizations import list_locations
from planners import personal_catalog
from planners.sky_state import civil_to_utc, location_clock
from planners.timezones import local_moment
from ui.planner_tab.planificacion.planetario_visual import PlanetarioVisual
from ui.sky_context import SkyContext


class PlanetaryPage(QWidget):
    """Explora fecha/sitio/objetos con estado propio durante esta apertura, sin guardar planes ni moverlos."""

    framing_saved = pyqtSignal(str, str)

    def __init__(self, parent=None):
        """Crea un lienzo independiente y controles locales; la ubicación inicial llega de Resumen."""
        super().__init__(parent)
        self._initialized = False
        self._location_id = None
        self._locations = {}
        self._state = None
        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.sky = PlanetarioVisual()
        root.addWidget(self.sky, 0, 0)
        self._toolbar = QFrame()
        self._toolbar.setStyleSheet("QFrame {background: #161e2b; border-radius: 8px;}")
        search = QHBoxLayout(self._toolbar)
        search.setContentsMargins(10, 8, 10, 8)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar objeto o alias…")
        self._search.setAccessibleName("Buscar objeto en la carta")
        find = QPushButton("Buscar")
        find.clicked.connect(self._find)
        self._search.returnPressed.connect(self._find)
        reset = QPushButton("Restablecer")
        reset.clicked.connect(self.sky.reset_view)
        self._options = QPushButton("Opciones")
        self._options.setCheckable(True)
        self._options.toggled.connect(self._toggle_options)
        self._details = QPushButton("Detalles")
        self._details.clicked.connect(self._show_details)
        search.addWidget(self._search, 1)
        for button in (find, reset, self._options, self._details):
            search.addWidget(button)
        root.addWidget(self._toolbar, 0, 0, Qt.AlignmentFlag.AlignTop)
        self._panel = QFrame(self)
        self._panel.setObjectName("PlanetaryOptions")
        self._panel.setStyleSheet("QFrame#PlanetaryOptions {background: #161e2b; border: 1px solid #30363d; border-radius: 8px;}"
                                 "QFrame#PlanetaryOptions QLabel, QFrame#PlanetaryOptions QCheckBox {background: transparent;}")
        panel = QFormLayout(self._panel)
        panel.setContentsMargins(14, 12, 14, 12)
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
        panel.addRow("Ubicación", self._location)
        clock = QHBoxLayout()
        clock.addWidget(self._date)
        clock.addWidget(now)
        panel.addRow("Fecha local", clock)
        self._ra = self._angle(0, 23.999999, 5, " h")
        self._dec = self._angle(-89.9, 89.9, 4, "°")
        panel.addRow("Centro RA J2000", self._ra)
        panel.addRow("Centro Dec J2000", self._dec)
        self._frame_enabled = QCheckBox("Mostrar encuadre manual")
        panel.addRow(self._frame_enabled)
        self._frame_width = self._angle(.001, 180, 3, "°")
        self._frame_height = self._angle(.001, 180, 3, "°")
        self._frame_width.setValue(1)
        self._frame_height.setValue(1)
        panel.addRow("FOV horizontal", self._frame_width)
        panel.addRow("FOV vertical", self._frame_height)
        self._tiles_x, self._tiles_y = QSpinBox(), QSpinBox()
        for spin in (self._tiles_x, self._tiles_y):
            spin.setRange(1, 20)
        tiles = QHBoxLayout()
        tiles.addWidget(self._tiles_x)
        tiles.addWidget(QLabel("×"))
        tiles.addWidget(self._tiles_y)
        panel.addRow("Teselas nominales", tiles)
        self._frame_enabled.toggled.connect(self._update_framing)
        for spin in (self._frame_width, self._frame_height, self._tiles_x, self._tiles_y):
            spin.valueChanged.connect(self._update_framing)
        self._ra.valueChanged.connect(self._move_center)
        self._dec.valueChanged.connect(self._move_center)
        self.sky.object_clicked.connect(self._select_object)
        self.sky.region_clicked.connect(self._select_region)
        self.sky.view_changed.connect(self._view_changed)
        bottom = QFrame()
        bottom.setStyleSheet("QFrame {background: #161e2b; border-radius: 8px;}")
        footer = QHBoxLayout(bottom)
        footer.setContentsMargins(10, 6, 10, 6)
        self._selection = QLabel()
        self._selection.setTextFormat(Qt.TextFormat.PlainText)
        self._selection.setWordWrap(True)
        footer.addWidget(self._selection, 1)
        self._coordinates = QLabel()
        self._coordinates.setAccessibleName("Centro y zoom de la carta")
        footer.addWidget(self._coordinates)
        self._send = QPushButton("Enviar encuadre al Planificador…")
        self._send.clicked.connect(self._send_framing)
        footer.addWidget(self._send)
        root.addWidget(bottom, 0, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        self._context_label = QLabel("Elige una ubicación en Opciones para consultar Sol y Luna.")
        self._context_label.setTextFormat(Qt.TextFormat.PlainText)
        self._context_label.setWordWrap(True)
        self._context_label.hide()
        self._context = SkyContext(self)
        self._context.ready.connect(self._context_ready)
        self._location.currentIndexChanged.connect(self._choose_location)
        self._date.dateTimeChanged.connect(self._update_context)
        self.reload_locations()
        self._panel.hide()
        self._view_changed(*self.sky.view)
        self._update_framing()

    def _angle(self, minimum, maximum, decimals, suffix):
        """Control numérico explícito, sin interpretar el zoom de exploración como campo de una cámara."""
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSuffix(suffix)
        return spin

    def _toggle_options(self, checked):
        """Muestra controles sobre el lienzo; el resto de su superficie sigue recibiendo arrastre y rueda."""
        self._panel.setVisible(checked)
        self._place_options()

    def _place_options(self):
        """Ancla el panel al borde sin reducir el área de la carta."""
        self._panel.adjustSize()
        self._panel.move(max(0, self.width()-self._panel.width()-12), self._toolbar.height()+8)
        self._panel.raise_()

    def resizeEvent(self, event):
        """Reubica únicamente la capa de opciones, no la cámara explorada."""
        super().resizeEvent(event)
        if hasattr(self, "_panel"):
            self._place_options()

    def _move_center(self):
        """Aplica coordenadas escritas por el usuario a esta carta independiente."""
        self.sky.set_center(self._ra.value(), self._dec.value())

    def _view_changed(self, ra, dec, _fov):
        """Sigue el centro durante el arrastre sin bucles ni escrituras persistentes."""
        for spin, value in ((self._ra, ra), (self._dec, dec)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self._coordinates.setText(f"RA {ra:.4f} h · Dec {dec:+.3f}° · Zoom {_fov:.1f}°")
        self._update_framing()

    def _update_framing(self, *_args):
        """Dibuja el rectángulo nominal definido explícitamente; no deduce equipo, solape ni integración."""
        enabled = self._frame_enabled.isChecked()
        for spin in (self._frame_width, self._frame_height, self._tiles_x, self._tiles_y):
            spin.setEnabled(enabled)
        if enabled:
            ra, dec, _zoom = self.sky.view
            self.sky.set_framing(ra, dec, self._frame_width.value(), self._frame_height.value(),
                                 self._tiles_x.value(), self._tiles_y.value())
        else:
            self.sky.clear_framing()

    def _select_region(self, ra, dec):
        """Un clic vacío elige un centro libre, sin crear todavía un objeto guardado."""
        self.sky.clear_target()
        self.sky.set_center(ra, dec)
        self._selection.setText("Encuadre libre")

    def _show_details(self):
        """Conserva ayuda y procedencia bajo demanda, sin ocupar permanentemente el cielo."""
        text = (self._context_label.text() + "\n\nCarta ecuatorial J2000; no simula horizonte, movimiento propio ni planetas.\n"
                "Arrastra para navegar; rueda para zoom; clic para centrar.\n"
                "El encuadre es manual y las teselas son nominales, sin solape calculado.")
        if self._state:
            text += "\n\n" + self._state.accuracy.details
        QMessageBox.information(self, "Detalles del Planetario", text)

    def _set_context_status(self, text, *, warning=False):
        """Señala errores sin una fila permanente de ayuda; el motivo completo sigue accesible en Detalles."""
        self._context_label.setText(text)
        self._details.setText("Detalles · aviso" if warning else "Detalles")
        self._details.setToolTip(text)

    def _send_framing(self):
        """Pide nombre y confirmación antes de guardar el encuadre como región, sin sustituir el plan abierto."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Enviar encuadre al Planificador")
        form = QFormLayout(dialog)
        name = QLineEdit(self.sky.center_label)
        name.setPlaceholderText("Nombre del objeto o encuadre")
        form.addRow("Nombre", name)
        info = QLabel("Se añadirá a Catálogo Personal como región de interés. No reemplaza el plan abierto.")
        info.setWordWrap(True)
        form.addRow(info)
        error = QLabel()
        error.setWordWrap(True)
        form.addRow(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        form.addRow(buttons)

        def save():
            """Mantiene el diálogo ante duplicados/fallos y conserva todas las regiones existentes."""
            if not name.text().strip():
                error.setText("Escribe un nombre.")
                return
            try:
                self.save_framing(name.text().strip())
            except (ValueError, sqlite3.Error) as exc:
                error.setText(str(exc))
                return
            dialog.accept()

        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()

    def save_framing(self, name):
        """Guarda el centro real y solo un FOV explícito, en las unidades del contrato de regiones existente."""
        if not name.strip():
            raise ValueError("Escribe un nombre.")
        ra, dec, _zoom = self.sky.view
        frame = self.sky.framing
        personal_catalog.add_region(name.strip(), ra, dec,
                                    fov_major_arcmin=frame[2]*60 if frame else None,
                                    fov_minor_arcmin=frame[3]*60 if frame else None,
                                    tiles_x=frame[4] if frame else None, tiles_y=frame[5] if frame else None)
        self.framing_saved.emit(name.strip(), "region")

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
                self._set_context_status(str(exc), warning=True)
                return
        self._update_context()

    def _update_context(self, *_args):
        """Valida reloj civil y solicita datos reales sin recolocar la cámara ni calcular ventanas de captura."""
        self._context.stop()
        self._state = None
        row = self._locations.get(self._location.currentData())
        if not row:
            self._set_context_status("Selecciona una ubicación guardada para el contexto solar/lunar.")
            return
        try:
            moment = civil_to_utc(self._date.dateTime().toPyDateTime(), row)
        except ValueError as exc:
            self._set_context_status(str(exc), warning=True)
            return
        clock = location_clock(row)
        self._date.setToolTip("Hora aproximada por longitud" if clock is None else f"Hora civil de la ubicación · {clock}")
        self._set_context_status("Leyendo contexto local…")
        self._context.request(row, moment)

    def _context_ready(self, state, error):
        """Muestra estado/avisos del cálculo actual sin mantener datos previos como si fueran vigentes."""
        self._state = state
        if error:
            self._set_context_status(f"Contexto no disponible: {error}", warning=True)
            return
        self._set_context_status(f"{state.title} · Luna {state.illumination:.0%} iluminada · {state.accuracy.summary}")
        self._context_label.setToolTip(state.accuracy.details)

    def _find(self):
        """Resuelve en la instantánea propia de la carta; ambiguos/ausentes no eligen un candidato al azar."""
        text = self._search.text().strip()
        if not text:
            return
        if self.sky.set_target(text):
            self._selection.setText(text)
        else:
            self._selection.setText("No hay una coincidencia única con coordenadas disponibles para esa búsqueda.")

    def reload_context(self):
        """Retira el rótulo del objeto descartado por recarga de carta y renueva la procedencia del contexto."""
        self._selection.clear()
        if self.isVisible():
            self._update_context()
        else:
            self._context.stop()
            self._state = None
            self._set_context_status("Contexto pendiente de actualizar tras cambiar catálogos.")

    def showEvent(self, event):
        """Renueva un contexto invalidado sin restaurar fecha, ubicación o cámara exploradas."""
        super().showEvent(event)
        if self._state is None and self._location.currentData() is not None:
            self._update_context()

    def _select_object(self, object_id, catalog):
        """Resalta un objeto pulsado solo en este lienzo."""
        self.sky.set_target(object_id, catalog)
        self._selection.setText(f"{object_id} · {catalog.upper()}")

    def closeEvent(self, event):
        """Invalida entregas pendientes, sin guardar la exploración para otro arranque."""
        self._context.stop()
        super().closeEvent(event)
