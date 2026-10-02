"""Ventana principal de PAS.S: barra lateral con iconos, contenido y pie de página.

- Barra lateral izquierda: pestañas apiladas verticalmente con icono (+ texto si
  está expandida), colapsable con animación y acceso a Configuración abajo.
- Contenido: pestañas sin subpestañas muestran una página; las que tienen
  subpestañas (p. ej. Planificador) usan QTabWidget horizontal con nombre.
- Pie: nombre del programa y versión.
"""
from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .planner_tab import (
    BusquedaTab,
    CatalogoPersonalTab,
    PlanificacionTab,
    SesionesTab,
)

APP_NAME = "Planning & Astronomical Stacking Suite"
APP_VERSION = "v0.1"

#: Orden y etiquetas de las pestañas (español; traducción vía i18n/*.ts)
TABS: list[tuple[str, str]] = [
    ("summary_tab", "Resumen"),
    ("planetary_tab", "Planetario"),
    ("equipment_tab", "Equipo"),
    ("planner_equip_tab", "Planificador de Equipo"),
    ("planner_tab", "Planificador"),
    ("stacker_tab", "Apilador"),
]

#: Glifo (emoji) del icono de cada pestaña en la barra lateral.
TAB_GLYPHS: dict[str, str] = {
    "summary_tab": "\U0001f4ca",        # 📊
    "planetary_tab": "\U0001f30c",       # 🌌
    "equipment_tab": "\U0001f52d",       # 🔭
    "planner_equip_tab": "⚖️",  # ⚖️
    "planner_tab": "\U0001f4c5",         # 📅
    "stacker_tab": "\U0001f4e6",         # 📦
}

_SETTINGS_GLYPH = "⚙️"  # ⚙️


def _glyph_icon(glyph: str, size: int = 28) -> QIcon:
    """Renderiza un glifo/emoji en un QIcon transparente."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setPen(QColor("#e6edf3"))
    font = QFont("Segoe UI Emoji")
    font.setPixelSize(int(size * 0.7))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)


def _placeholder_page(title: str) -> QWidget:
    """Página de una pestaña aún sin implementar."""
    page = QWidget()
    layout = QVBoxLayout(page)
    label = QLabel(f"{title}\nFuncionalidad en construcción", page)
    label.setObjectName("Placeholder")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    layout.addWidget(label)
    return page


class PlannerPage(QWidget):
    """Página del Planificador: sus 4 subpestañas (Búsqueda → … → Sesiones).

    Orden pedido por el usuario: **Búsqueda → Catálogo Personal →
    Planificación → Sesiones Planificadas**.

    Aquí se concentra todo el cableado entre subpestañas, que no deben
    importarse entre sí:

    - La ubicación vive en un panel de **Búsqueda** (tercera fila de la
      izquierda, junto a las condiciones meteorológicas). Su barra
      (``location_bar``, alias de ``busqueda.location_bar``) alimenta a
      Búsqueda directamente y a Planificación (curva, plan) por señal.
    - "Añadir a Mi Lista" de Búsqueda escribe en Catálogo Personal, que a su
      vez recarga los targets de Planificación.
    - Seleccionar fila en Catálogo Personal elige el target de Planificación.
    - Guardar sesión en Planificación refresca Sesiones Planificadas.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        # Márgenes justos: cada píxel de aquí es de la rejilla de Búsqueda.
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        self.busqueda = BusquedaTab()
        #: Barra de ubicación: vive en Búsqueda; se expone aquí para el cableado.
        self.location_bar = self.busqueda.location_bar
        self.catalogo = CatalogoPersonalTab()
        self.planificacion = PlanificacionTab()
        self.sesiones = SesionesTab()

        tabs = QTabWidget()
        tabs.addTab(self.busqueda, "Búsqueda")
        tabs.addTab(self.catalogo, "Catálogo Personal")
        tabs.addTab(self.planificacion, "Planificación")
        tabs.addTab(self.sesiones, "Sesiones Planificadas")
        layout.addWidget(tabs, 1)

        self._wire()

        # La barra emite dentro de su constructor, cuando aún no había
        # nadie conectado: con el cableado hecho se reenvía el estado.
        if self.location_bar.has_saved_location():
            self.location_bar.reemit()

    def _wire(self) -> None:
        # Ubicación (el panel vive en Búsqueda y ya la alimenta) → Planificación
        self.location_bar.location_changed.connect(self.planificacion.set_location)

        # Búsqueda → Catálogo personal (guardar) y Planificación (targets)
        self.busqueda.add_to_personal.connect(self._add_to_personal)

        # Catálogo personal → Planificación (elegir target / recargar lista)
        self.catalogo.target_selected.connect(self.planificacion.select_target)
        self.catalogo.region_added.connect(self._on_region_added)

        # Planificación → Sesiones (fila nueva recién guardada)
        self.planificacion.session_saved.connect(
            lambda _session_id: self.sesiones.refresh()
        )

    def _add_to_personal(self, object_id: str, catalog: str) -> None:
        self.catalogo.add_object(object_id, catalog)
        self.planificacion.reload_targets()

    def _on_region_added(self, _name: str) -> None:
        self.planificacion.reload_targets()


def _planner_page() -> QWidget:
    """Comodidad para ``MainWindow``: la página del Planificador."""
    return PlannerPage()


class _Sidebar(QWidget):
    """Barra lateral colapsable: iconos de pestañas + Configuración abajo."""

    EXPANDED_W = 230
    COLLAPSED_W = 56

    def __init__(self, on_select, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self._expanded = True
        self._animation: QPropertyAnimation | None = None
        self.setFixedWidth(self.EXPANDED_W)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)

        self.toggle_button = QPushButton("☰")  # ☰
        self.toggle_button.setObjectName("SidebarToggle")
        self.toggle_button.setToolTip("Colapsar / expandir la barra lateral")
        self.toggle_button.clicked.connect(self.toggle)
        layout.addWidget(self.toggle_button)

        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.nav.setFrameShape(QFrame.Shape.NoFrame)
        self.nav.setIconSize(QSize(28, 28))
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setTextElideMode(Qt.TextElideMode.ElideRight)
        for key, title in TABS:
            item = QListWidgetItem(_glyph_icon(TAB_GLYPHS[key]), title)
            item.setSizeHint(QSize(0, 46))
            self.nav.addItem(item)
        self.nav.setFixedHeight(len(TABS) * 46 + 12)
        self.nav.currentRowChanged.connect(on_select)
        layout.addWidget(self.nav)
        layout.addStretch(1)

        self.settings_button = QPushButton()
        self.settings_button.setObjectName("SettingsButton")
        self.settings_button.setIcon(_glyph_icon(_SETTINGS_GLYPH, 26))
        self.settings_button.setIconSize(QSize(26, 26))
        self.settings_button.setFixedSize(44, 44)
        self.settings_button.setToolTip("Configuración")
        layout.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignHCenter)

    def toggle(self) -> None:
        """Colapsa (solo iconos) o expandiere (icono + texto) la barra."""
        self._expanded = not self._expanded
        target = self.EXPANDED_W if self._expanded else self.COLLAPSED_W
        for row, (_key, title) in enumerate(TABS):
            item = self.nav.item(row)
            if item is not None:
                item.setText(title if self._expanded else "")
        self._animate_width(target)

    def _animate_width(self, target: int) -> None:
        """Transición suave de ancho entre estado expandido y colapsado."""
        self._animation = QPropertyAnimation(self, b"maximumWidth")
        self._animation.setDuration(200)
        self._animation.setStartValue(self.width())
        self._animation.setEndValue(target)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._animation.valueChanged.connect(lambda value: self.setMinimumWidth(int(value)))
        self._animation.finished.connect(
            lambda: (self.setMinimumWidth(target), self.setMaximumWidth(target))
        )
        self._animation.start()


class MainWindow(QMainWindow):
    """Ventana principal de PAS.S."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"PAS.S {APP_VERSION}")
        self.setMinimumSize(1024, 640)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.content = QStackedWidget()
        for key, title in TABS:
            page = _planner_page() if key == "planner_tab" else _placeholder_page(title)
            self.content.addWidget(page)

        self.sidebar = _Sidebar(on_select=self._select_tab)
        self.sidebar.settings_button.clicked.connect(self._show_settings)

        body.addWidget(self.sidebar)
        body.addWidget(self.content, 1)
        root.addLayout(body, 1)

        footer = QLabel(f"{APP_NAME} {APP_VERSION}")
        footer.setObjectName("Footer")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(footer)

        self.setCentralWidget(central)
        self.sidebar.nav.setCurrentRow(0)
        # Maximizar tras el primer layout: evita el bug de render a tamaño incompleto
        QTimer.singleShot(0, self.showMaximized)

    def _select_tab(self, index: int) -> None:
        if 0 <= index < self.content.count():
            self.content.setCurrentIndex(index)

    def _show_settings(self) -> None:
        QMessageBox.information(self, "Configuración", "Ajustes del programa: próximamente.")
