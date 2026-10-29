"""Portada de PASS: sesiones guardadas, actividad local y cielo ilustrado; sin procesado ni asociaciones supuestas."""

import sqlite3
from datetime import UTC, datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from db.settings import get_setting, set_setting
from equipment.localizations import list_locations
from planners.sky_state import location_clock
from planners.summary import (
    IntegrationProgress,
    Overview,
    read_overview,
    sessions_on_day,
)
from planners.timezones import local_moment
from ui.sky_context import SkyContext

from .widgets import IdleIllustration, ProgressDial, SkyScene

LOCATION_KEY = "summary_location_id"
SECTIONS = (
    ("planetary_tab", "Planetario"),
    ("equipment_tab", "Equipo"),
    ("planner_equip_tab", "Planificador de Equipo"),
    ("planner_tab", "Planificador"),
    ("stacker_tab", "Apilador"),
)


def _label(text="", *, size=None, muted=False):
    """Crea texto plano para no interpretar nombres/notas del usuario como HTML."""
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    style = "background: transparent;"
    if size:
        style += f"font-size: {size}pt;"
    if muted:
        style += "color: #94a3b8;"
    label.setStyleSheet(style)
    return label


def _card():
    """Tarjeta local: no cambia la tipografía ni el estilo de las demás pestañas."""
    frame = QFrame()
    frame.setObjectName("SummaryCard")
    frame.setStyleSheet("QFrame#SummaryCard {background: #161e2b; border: 1px solid #2b384a; border-radius: 16px;}"
                       "QFrame#SummaryCard QLabel {background: transparent; border: none;}")
    return frame


class SummaryPage(QWidget):
    """Portada funcional con límites explícitos del esquema legacy y muestra visual separada de los datos reales."""

    navigate_requested = pyqtSignal(str, str)
    location_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        """Construye la composición acordada; no lee fotografías, crea planes ni recupera borradores automáticamente."""
        super().__init__(parent)
        self._overview = Overview((), ())
        self._locations = {}
        self._sky_state = None
        self._sky_location_id = None
        self._sky_error = ""
        self._preference_error = ""
        self._cards = {}
        self._section_icons = {}
        self._reading_error = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self._body = body
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)
        header = QHBoxLayout()
        headings = QVBoxLayout()
        headings.addWidget(_label("Resumen", size=22))
        header.addLayout(headings, 1)
        self._demo = QPushButton("Vista de ejemplo")
        self._demo.setCheckable(True)
        self._demo.setToolTip("Datos ficticios para revisar el diseño; no crea ni modifica planes.")
        self._demo.toggled.connect(self._render_session)
        header.addWidget(self._demo)
        layout.addLayout(header)
        self._top = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._top.setSpacing(16)
        self._session_card = self._build_session()
        self._sky_card = self._build_sky()
        self._top.addWidget(self._session_card, 1)
        self._top.addWidget(self._sky_card, 1)
        layout.addLayout(self._top, 1)
        self._activity_grid = QGridLayout()
        self._activity_grid.setSpacing(12)
        for key, title in SECTIONS:
            card = _card()
            card.setMinimumWidth(150)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            heading = QHBoxLayout()
            icon = QLabel()
            icon.setFixedSize(28, 28)
            self._section_icons[key] = icon
            heading.addWidget(icon)
            heading.addWidget(_label(title), 1)
            card_layout.addLayout(heading)
            button = QPushButton("Sin pendientes")
            button.setAccessibleName(f"Actividad de {title}")
            button.clicked.connect(lambda _checked=False, section=key: self._show_activity(section))
            card_layout.addWidget(button)
            self._cards[key] = (card, button)
        layout.addLayout(self._activity_grid)
        scroll.setWidget(body)
        root.addWidget(scroll)
        self._context = SkyContext(self)
        self._context.ready.connect(self._sky_ready)
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self.refresh)
        self._sky_timer = QTimer(self)
        self._sky_timer.setInterval(300_000)
        self._sky_timer.timeout.connect(self._request_sky)
        self.reload_locations()
        self.refresh()
        self._arrange()

    def set_section_icons(self, icons: dict[str, QIcon]):
        """Recibe los mismos iconos de navegación, evitando otra colección de símbolos o recursos."""
        for key, label in self._section_icons.items():
            if key in icons:
                label.setPixmap(icons[key].pixmap(28, 28))

    def _build_session(self):
        """Organiza una sesión protagonista con selector, datos secundarios y progreso no ficticio por defecto."""
        frame = _card()
        frame.setMinimumWidth(300)
        box = QVBoxLayout(frame)
        box.setContentsMargins(20, 16, 20, 18)
        box.setSpacing(8)
        box.addWidget(_label("SESIÓN ACTUAL", size=11, muted=True))
        self._sessions = QComboBox()
        self._sessions.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._sessions.setMinimumContentsLength(12)
        self._sessions.setAccessibleName("Sesión que se consulta en Resumen")
        self._sessions.currentIndexChanged.connect(self._session_changed)
        box.addWidget(self._sessions)
        self._object = _label("Sin sesión actual", size=23)
        box.addWidget(self._object)
        self._idle = IdleIllustration()
        box.addWidget(self._idle)
        center = QHBoxLayout()
        self._dial = ProgressDial()
        self._dial.setMaximumSize(180, 180)
        center.addWidget(self._dial)
        facts = QVBoxLayout()
        self._hours = _label(size=21)
        self._pending = _label(muted=True)
        self._extra = _label(muted=True)
        facts.addWidget(self._hours)
        facts.addWidget(self._pending)
        facts.addWidget(self._extra)
        center.addLayout(facts, 1)
        box.addLayout(center)
        self._night_label = _label(muted=True)
        self._night_bar = QProgressBar()
        self._night_bar.setTextVisible(False)
        self._night_bar.setFixedHeight(6)
        self._night_bar.setAccessibleName("Progreso del objeto en la noche de ejemplo")
        self._plan_label = _label(muted=True)
        box.addWidget(self._night_label)
        box.addWidget(self._night_bar)
        box.addWidget(self._plan_label)
        self._equipment = _label(muted=True)
        self._site = _label(muted=True)
        box.addWidget(self._equipment)
        box.addWidget(self._site)
        box.addStretch(1)
        actions = QHBoxLayout()
        self._continue = QPushButton("Planificar captura")
        self._continue.clicked.connect(self._continue_work)
        self._breakdown = QPushButton("Ver desglose")
        self._breakdown.clicked.connect(self._show_breakdown)
        actions.addWidget(self._continue, 1)
        actions.addWidget(self._breakdown)
        box.addLayout(actions)
        return frame

    def _build_sky(self):
        """Mantiene la ilustración despejada y pone reloj/sitio/modelo en un detalle accesible por botón."""
        frame = _card()
        box = QVBoxLayout(frame)
        box.setContentsMargins(18, 18, 18, 18)
        box.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(_label("TU CIELO, AHORA", size=11, muted=True), 1)
        self._detail = QPushButton("Detalles")
        self._detail.clicked.connect(self._show_sky_details)
        header.addWidget(self._detail)
        box.addLayout(header)
        self._location = QComboBox()
        self._location.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._location.setMinimumContentsLength(12)
        self._location.setAccessibleName("Ubicación guardada para la ilustración de Resumen")
        self._location.currentIndexChanged.connect(self._location_selected)
        box.addWidget(self._location)
        self._scene = SkyScene()
        self._scene.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        box.addWidget(self._scene, 1)
        self._sky_note = _label(muted=True)
        self._sky_note.hide()
        box.addWidget(self._sky_note)
        self._location_action = QPushButton("Gestionar ubicaciones")
        self._location_action.clicked.connect(lambda: self.navigate_requested.emit("equipment_tab", "locations"))
        box.addWidget(self._location_action)
        return frame

    @property
    def location_id(self):
        """Identificador elegido explícitamente para esta portada, independiente del lugar del plan."""
        return self._location.currentData()

    def reload_locations(self):
        """Recarga ubicaciones recordando solo una elección válida; nunca adopta la única opción por inferencia."""
        previous = self.location_id
        if previous is None:
            try:
                previous = int(get_setting(LOCATION_KEY, ""))
            except (TypeError, ValueError):
                previous = None
        self._locations = {row["id"]: row for row in list_locations()}
        self._location.blockSignals(True)
        self._location.clear()
        self._location.addItem("Elige una ubicación…", None)
        for key, row in self._locations.items():
            self._location.addItem(row["name"], key)
        self._location.setCurrentIndex(max(0, self._location.findData(previous)))
        self._location.blockSignals(False)
        self._location_action.setVisible(not self._locations)
        self.location_changed.emit(self.location_id)
        if self.isVisible():
            self._request_sky()

    def _location_selected(self, *_args):
        """Guarda únicamente la preferencia explícita, no cambia datos de captura ni ubicaciones de otras pestañas."""
        try:
            set_setting(LOCATION_KEY, "" if self.location_id is None else str(self.location_id))
            self._preference_error = ""
        except sqlite3.Error as exc:
            self._preference_error = f"No se pudo recordar la ubicación: {exc}. "
        self.location_changed.emit(self.location_id)
        self._request_sky()

    def _request_sky(self):
        """Calcula fuera de Qt solo si existe sitio elegido; los resultados de otro sitio se retiran."""
        self._context.stop()
        self._sky_error = ""
        row = self._locations.get(self.location_id)
        fingerprint = (self.location_id, row["latitude"], row["longitude"], location_clock(row)) if row else None
        if self._sky_location_id != fingerprint:
            self._sky_state = None
            self._scene.set_state(None, animate=False)
        self._sky_location_id = fingerprint
        if not row:
            self._sky_note.setText(self._preference_error + "Elige una ubicación guardada. No se ha supuesto ninguna posición.")
            self._sky_note.setVisible(bool(self._preference_error))
            return
        self._sky_note.setText(self._preference_error + "Leyendo luz solar y fase lunar local…")
        self._sky_note.setVisible(bool(self._preference_error))
        self._context.request(row)

    def _sky_ready(self, state, error):
        """Publica contexto actual o ausencia explícita, nunca una escena calculada con otro sitio."""
        self._sky_state, self._sky_error = state, error
        self._scene.set_state(state)
        self._sky_note.setText(self._preference_error + (f"Cielo no disponible: {error}" if error else ""))
        self._sky_note.setVisible(bool(self._sky_note.text()))

    def reload_context(self):
        """Invalida una lectura de otra edición al cambiar catálogos, sin reusar un modelo antiguo como vigente."""
        self._sky_location_id = None
        if self.isVisible():
            self._request_sky()
        else:
            self._context.stop()
            self._sky_state = None
            self._scene.set_state(None, animate=False)

    def refresh(self):
        """Actualiza sesiones/actividad por lectura; no restaura borradores ni relaciona objetos con fotografías."""
        selected = self._sessions.currentData()
        try:
            self._overview = read_overview(datetime.now(UTC).astimezone().date())
            self._reading_error = ""
        except sqlite3.Error as exc:
            self._overview = Overview((), ())
            self._reading_error = f"No se pudieron leer las sesiones: {exc}"
        self._sessions.blockSignals(True)
        self._sessions.clear()
        self._sessions.addItem("Consulta una sesión guardada…", None)
        for row in self._overview.sessions:
            self._sessions.addItem(f"{row['object_id']} · {row['target_name']} · {row['session_date']}", row["id"])
        today = sessions_on_day(self._overview, datetime.now(UTC).astimezone().date())
        if selected is None and len(today) == 1:
            selected = today[0]["id"]
        self._sessions.setCurrentIndex(max(0, self._sessions.findData(selected)))
        self._sessions.blockSignals(False)
        self._sessions.setVisible(bool(self._overview.sessions) and not self._demo.isChecked())
        for section, (_card_widget, button) in self._cards.items():
            activities = [item for item in self._overview.activities if item.section == section]
            ongoing = sum(item.kind == "continue" for item in activities)
            upcoming = sum(item.kind == "upcoming" for item in activities)
            parts = ([f"{ongoing} por continuar"] if ongoing else []) + ([f"{upcoming} próximas"] if upcoming else [])
            button.setText(" · ".join(parts) if parts else "Abrir sección")
        self._render_session()

    def _session_changed(self, *_args):
        """El selector cambia únicamente lo consultado, sin tocar el plan ni el trabajo del Apilador."""
        self._render_session()

    def _render_session(self, *_args):
        """Distingue datos legacy sin integración de la maqueta explícita que permite revisar el diseño completo."""
        demo = self._demo.isChecked()
        self._demo.setText("Ejemplo · datos ficticios" if demo else "Vista de ejemplo")
        self._sessions.setVisible(bool(self._overview.sessions) and not demo)
        row = next((item for item in self._overview.sessions if item["id"] == self._sessions.currentData()), None)
        self._dial.setVisible(demo)
        self._night_label.setVisible(demo)
        self._night_bar.setVisible(demo)
        self._plan_label.setVisible(demo)
        self._breakdown.setVisible(demo)
        self._extra.setVisible(demo)
        self._idle.setVisible(not demo and row is None)
        self._equipment.setVisible(demo or row is not None)
        self._site.setVisible(demo or row is not None)
        self._hours.setVisible(demo or row is not None)
        if demo:
            progress = IntegrationProgress(8, 4, 2)
            self._object.setText("M31 · Andrómeda")
            self._dial.set_progress(progress)
            self._hours.setText("6 h de 8 h")
            self._pending.setText("2 h pendientes de auditoría")
            self._extra.setText("4 h seleccionadas")
            self._night_label.setText("Esta noche · 2 h de 3 h")
            self._night_bar.setValue(67)
            self._plan_label.setText("Plan · 3 objetos")
            self._equipment.setText("Equipo · Configuración de ejemplo")
            self._site.setText("Ubicación de captura · Sitio de ejemplo")
            self._continue.setText("Continuar trabajo")
            self._continue.setEnabled(False)
        else:
            self._continue.setEnabled(True)
            today = sessions_on_day(self._overview, datetime.now(UTC).astimezone().date())
            title = "Sesiones no disponibles" if self._reading_error else "Varias sesiones para hoy" if len(today) > 1 else "Sin sesión actual"
            self._object.setText(row["object_id"] if row else title)
            self._object.setToolTip(row["target_name"] if row else "")
            self._hours.setText("Integración no vinculada" if row else "")
            self._pending.setText(self._reading_error)
            self._equipment.setText(f"Equipo · {row.get('setup_name') or '—'}" if row else "")
            self._site.setText(f"Ubicación de captura · {row.get('location_name') or '—'}" if row else "")
            self._continue.setText("Continuar trabajo" if row else "Planificar captura")
        self._pending.setVisible(bool(self._pending.text()))

    def _continue_work(self):
        """Navega al flujo actual sin elegir un objetivo por nombre ni sobreescribir borradores."""
        if not self._demo.isChecked():
            identifier = self._sessions.currentData()
            self.navigate_requested.emit("planner_tab", f"saved:{identifier}" if identifier is not None else "planning")

    def _show_activity(self, section):
        """Lista hechos disponibles y permite continuar en la sección sin ejecutar tareas desde Resumen."""
        items = [item for item in self._overview.activities if item.section == section]
        if not items:
            self.navigate_requested.emit(section, "")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Actividad de la sección")
        dialog.resize(580, 330)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        for item in items:
            prefix = "Por continuar" if item.kind == "continue" else "Próxima"
            entry = QListWidgetItem(f"{prefix} · {item.title}")
            entry.setData(Qt.ItemDataRole.UserRole, "planning" if item.kind == "continue" else "sessions")
            listing.addItem(entry)
        listing.setCurrentRow(0)
        layout.addWidget(listing)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Open).setText("Abrir sección")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = listing.currentItem()
            self.navigate_requested.emit(section, selected.data(Qt.ItemDataRole.UserRole) if selected else "")

    def _show_breakdown(self):
        """Abre un ejemplo explícito; ninguna cifra se atribuye a fotografías personales."""
        self._text_dialog("Desglose de ejemplo", "DATOS FICTICIOS · M31\n\n"
                          "L: 4 h / 4 h (1 h pendiente de auditoría)\n"
                          "R: 1 h / 1 h (0,5 h pendientes)\nG: 0,5 h / 1 h\nB: 0,5 h / 2 h (0,5 h pendientes)\n\n"
                          "Total: 6 h / 8 h · 2 h pendientes de auditoría\n"
                          "No completado: faltan horas por filtro.\n"
                          "Tesela única de ejemplo. El desglose real depende de los archivos de plan futuros.")

    def _show_sky_details(self):
        """Separa reloj y procedencia de la ilustración, sin ocultar aproximación heredada ni avisos IERS."""
        row = self._locations.get(self.location_id)
        if not row:
            self._text_dialog("Detalle del cielo", "Elige una ubicación guardada. No se ha supuesto un sitio ni una fase lunar.")
            return
        try:
            moment = local_moment(datetime.now(UTC), row["longitude"], location_clock(row))
            clock = "Aproximación por longitud" if location_clock(row) is None else str(location_clock(row))
            text = f"Ubicación: {row['name']}\nHora local: {moment:%d/%m/%Y %H:%M %z}\nReloj: {clock}\n"
        except ValueError as exc:
            text = f"Ubicación: {row['name']}\nReloj no disponible: {exc}\n"
        if self._sky_state:
            state = self._sky_state
            text += (f"\nLectura UTC: {state.moment:%d/%m/%Y %H:%M}\n"
                     f"Altura solar geométrica: {state.sun_altitude:.1f}°\nLuna: {state.illumination:.0%} iluminada\n\n"
                     f"{state.accuracy.details}\n")
        else:
            text += "\nContexto no disponible. " + self._sky_error
        text += "\nIlustración decorativa: no indica posición/visibilidad de Sol o Luna ni clima real."
        text += "\nIluminación lunar por elongación y sentido por edad sinódica aproximados, como en Efemérides."
        self._text_dialog("Detalle del cielo", text)

    def _text_dialog(self, title, text):
        """Muestra detalle seleccionable con cierre por teclado y sin interpretar contenido como HTML."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(600, 410)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _arrange(self):
        """Apila tarjetas en ventanas estrechas sin subir el mínimo global ni recortar botones."""
        columns = 5 if self.width() >= 1200 else 3 if self.width() >= 1000 else 2 if self.width() >= 760 else 1
        self._top.setDirection(QBoxLayout.Direction.LeftToRight if self.width() >= 1050 else QBoxLayout.Direction.TopToBottom)
        for index, (card, _button) in enumerate(self._cards.values()):
            self._activity_grid.addWidget(card, index//columns, index % columns)

    def resizeEvent(self, event):
        """Recompone solo la portada; no altera tamaños de Planificación ni estilos globales."""
        super().resizeEvent(event)
        if hasattr(self, "_cards"):
            self._arrange()

    def showEvent(self, event):
        """Actualiza hechos al entrar y activa lectura puntual; los borradores siguen sin recuperarse automáticamente."""
        super().showEvent(event)
        self.reload_locations()
        self.refresh()
        self._timer.start()
        self._sky_timer.start()

    def hideEvent(self, event):
        """Pausa refrescos cuando no se ve la portada y descarta resultados tardíos."""
        self._timer.stop()
        self._sky_timer.stop()
        self._context.stop()
        super().hideEvent(event)
