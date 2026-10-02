"""Estilo visual de PAS.S: tema oscuro azulado, tipografía y pie de aplicación.

Un único lugar para la hoja de estilos QSS y la fuente base (13pt, rango 12-14).
Los colores del QSS salen del diccionario PALETTE (fuente única de verdad).
"""
from string import Template

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

#: Paleta: azules oscuros casi negros.
PALETTE = {
    "bg": "#0d1117",          # fondo general
    "panel": "#161b22",       # barra lateral, cabeceras, pie
    "surface": "#1f2937",     # tarjetas, hover
    "border": "#30363d",      # bordes
    "text": "#e6edf3",        # texto principal
    "textDim": "#8b949e",     # texto secundario
    "accent": "#3b82f6",      # acento azul
    "accentLight": "#60a5fa",  # acento claro (selección)
    "accentSoft": "rgba(59, 130, 246, 0.25)",
    "accentSoftStrong": "rgba(59, 130, 246, 0.3)",
    "pressed": "#17202b",
}

FONT_FAMILY = "Segoe UI"
FONT_SIZE_PT = 13  # rango pedido: 12-14

_QSS_TEMPLATE = """
/* ===================== Base ===================== */
QWidget {
    background-color: $bg;
    color: $text;
}
QMainWindow {
    background-color: $bg;
}

/* ================ Barra lateral ================ */
#Sidebar {
    background-color: $panel;
    border-right: 1px solid $border;
}
#SidebarToggle {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: $textDim;
    font-size: 16pt;
    padding: 6px;
}
#SidebarToggle:hover {
    background-color: $surface;
    color: $text;
}
#NavList {
    background-color: transparent;
    border: none;
    outline: none;
}
#NavList::item {
    color: $textDim;
    padding: 10px 8px;
    margin: 2px 6px;
    border-radius: 8px;
}
#NavList::item:hover {
    background-color: $surface;
    color: $text;
}
#NavList::item:selected {
    background-color: $accentSoft;
    color: $accentLight;
}
#SettingsButton {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 8px;
}
#SettingsButton:hover {
    background-color: $surface;
}

/* ============== Pie de página ============== */
#Footer {
    background-color: $panel;
    color: $textDim;
    border-top: 1px solid $border;
    padding: 2px;
    font-size: 11pt;
}

/* ====== Subpestañas horizontales (con nombre) ====== */
QTabWidget::pane {
    background-color: $bg;
    border: 1px solid $border;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background-color: $panel;
    color: $textDim;
    border: 1px solid $border;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 6px 14px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    background-color: $surface;
    color: $accentLight;
    border-color: $accent;
}
QTabBar::tab:hover:!selected {
    color: $text;
}

/* ================== Botones ================== */
QPushButton {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 6px;
    color: $text;
    padding: 3px 14px;
}
QPushButton:hover {
    border-color: $accent;
}
QPushButton:pressed {
    background-color: $pressed;
}

/* ============= Campos de entrada ============= */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: $panel;
    border: 1px solid $border;
    border-radius: 6px;
    color: $text;
    padding: 3px 8px;
    selection-background-color: $accent;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: $accent;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: $panel;
    color: $text;
    border: 1px solid $border;
    selection-background-color: $accentSoftStrong;
}

/* ================== Tablas ================== */
QTableView, QTableWidget {
    background-color: $bg;
    alternate-background-color: $panel;
    gridline-color: $border;
    border: 1px solid $border;
    selection-background-color: $accentSoftStrong;
}
QHeaderView::section {
    background-color: $panel;
    color: $text;
    border: none;
    border-bottom: 1px solid $border;
    border-right: 1px solid $border;
    padding: 6px;
}

/* ================ Scrollbars ================ */
QScrollBar:vertical {
    background: $bg;
    width: 12px;
    margin: 0;
    border: none;
}
QScrollBar::handle:vertical {
    background: $border;
    border-radius: 6px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: $accent;
}
QScrollBar:horizontal {
    background: $bg;
    height: 12px;
    margin: 0;
    border: none;
}
QScrollBar::handle:horizontal {
    background: $border;
    border-radius: 6px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: $accent;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
    width: 0;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

/* ================ Tooltips ================ */
QToolTip {
    background-color: $surface;
    color: $text;
    border: 1px solid $accent;
    padding: 4px 6px;
}

/* ================ Etiquetas ================ */
#Placeholder {
    color: $textDim;
    font-size: 14pt;
}

/* ============ Componentes del Planificador ============ */
#PanelTitle {
    color: $accentLight;
    font-weight: bold;
    font-size: 13pt;
    padding: 2px 0;
}
#SectionTitle {
    color: $accentLight;
    font-weight: bold;
}
#MetricCard {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 8px;
}
#MetricCard[unavailable="true"] {
    border-color: $border;
    background-color: $panel;
}
#MetricTitle {
    color: $textDim;
    font-size: 11pt;
}
#MetricValue {
    color: $text;
    font-size: 15pt;
    font-weight: bold;
}
#MetricValue[unavailable="true"] {
    color: $textDim;
    font-weight: normal;
}
#ApplyFilters {
    background-color: #166534;
    border-color: #22c55e;
}
#ApplyFilters:hover {
    background-color: #15803d;
}
#PrimaryButton {
    background-color: $accent;
    border-color: $accentLight;
}
#PrimaryButton:hover {
    background-color: $accentLight;
}
#CurveTitle {
    color: $accentLight;
    font-weight: bold;
    font-size: 13pt;
}
#CurveSubtitle {
    color: $accentLight;
    font-size: 11pt;
}
#CurveLegend {
    color: $textDim;
    font-size: 11pt;
}
#MoonPhase {
    color: $text;
    font-weight: bold;
    font-size: 13pt;
}
#StarButton {
    background-color: $panel;
    border: 1px solid #ca8a04;
    color: #eab308;
}
#StarButton:hover {
    background-color: #2a2410;
    border-color: #eab308;
}
#StarButton:disabled {
    background-color: $panel;
    border-color: $border;
    color: $textDim;
}
#GroupFrame {
    background-color: $panel;
    border: 1px solid $border;
    border-radius: 8px;
}
#HintLabel {
    color: $textDim;
    font-size: 11pt;
}
"""

#: Hoja de estilos completa con la paleta ya sustituida.
QSS = Template(_QSS_TEMPLATE).substitute(PALETTE)


def apply_style(app: QApplication) -> None:
    """Aplica la fuente base (13pt) y la hoja de estilos a toda la aplicación."""
    app.setFont(QFont(FONT_FAMILY, FONT_SIZE_PT))
    app.setStyleSheet(QSS)
