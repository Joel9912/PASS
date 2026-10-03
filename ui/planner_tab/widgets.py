"""Componentes compartidos por las subpestañas del Planificador.

Aquí vive lo que aparece en más de una pantalla (tarjetas de métrica, efemérides
Sol/Luna, barra día/noche, icono de fase lunar y la curva de tránsito de
PyQtGraph), para que `busqueda.py`, `planificacion.py`, etc. solo compongan.

Reglas aplicables:
- La estética sale de ``ui/style.py`` (PALETTE + QSS); aquí solo se usan
  objectNames ya definidos allí (``MetricCard``, ``PanelTitle``...).
- Sin datos de clima el valor es "Sin datos": nunca se inventan números.
- Las horas de efemérides llegan en UTC y aquí se pasan a hora local con la
  longitud del lugar (``longitude``); la conversión es un único sitio.
"""
from __future__ import annotations

from datetime import datetime

import pyqtgraph as pg
from PyQt6.QtCore import QPointF, QRectF, Qt, QDate, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from planners.analytical_transit import local_utc_offset
from planners.moon_distance import (
    WINDOW_IDEAL,
    WINDOW_POSSIBLE,
    capture_window_summary,
    capture_windows,
    format_hour_range,
    min_moon_distance,
    unwrap_hours,
)
from planners.transit import NightCurve, NightInfo, night_info
from planners.weather import ClearOutside, Meteoblue

from ..style import PALETTE

pg.setConfigOptions(antialias=True, background=PALETTE["bg"])

#: Colores de la curva de tránsito (coherentes con el resto del tema).
COLOR_ALTITUDE = PALETTE["accent"]        # azul: altitud del objeto
COLOR_MOON = "#94a3b8"                    # gris: altitud de la Luna
COLOR_LIMIT = "#ef4444"                   # rojo: línea de 30°
COLOR_IDEAL = (34, 197, 94, 55)           # verde: ventana ideal
COLOR_POSSIBLE = (245, 158, 11, 45)       # ámbar: ventana posible
COLOR_NIGHT = (255, 255, 255, 26)         # gris: noche astronómica
COLOR_ZONE = (251, 191, 36, 55)           # amarillo: zona ±2° (luna/45°)

COLOR_DAY = "#94a3b8"                     # barra: día
COLOR_TWILIGHT = "#475569"                # barra: crepúsculo
COLOR_NIGHT_BAR = "#0b1220"               # barra: noche

#: Eje horario del estado inicial: la malla de `night_curve` va de las 16:00
#: hora local a las 08:00 del día siguiente (16 h).
NIGHT_X_RANGE = (16.0, 32.0)

#: Título fijo de la curva: no cambia con la selección (como el original).
CURVE_TITLE = "Curva de Tránsito, Altitud y Separación Lunar"
#: Subtítulo del estado vacío (texto del programa original).
CURVE_EMPTY_SUBTITLE = "Tránsito: Sin selección (Máx: 0.0°)"


# --------------------------------------------------------------------------- #
#                                H O R A S                                     #
# --------------------------------------------------------------------------- #
def fmt_hhmm(hour_decimal: float) -> str:
    """Decimal de horas (0-24) a ``HH:MM`` local, envuelto en 24 h."""
    hours = int(hour_decimal) % 24
    minutes = int(round((hour_decimal % 1) * 60))
    if minutes == 60:                       # 18:59.9 -> 19:00
        hours = (hours + 1) % 24
        minutes = 0
    return f"{hours:02d}:{minutes:02d}"


def iso_to_local_hours(
    iso_utc: str | None,
    longitude: float,
    utc_offset_hours: float | None = None,
) -> float | None:
    """Instante ISO en UTC a horas decimales locales (``None`` si falta).

    El paso a hora local lo hace :func:`local_utc_offset`: si la ubicación
    tiene desfase guardado se usa (hora de reloj); si no, la longitud
    (hora solar).
    """
    if not iso_utc:
        return None
    moment = datetime.fromisoformat(iso_utc)
    utc_hours = moment.hour + moment.minute / 60.0 + moment.second / 3600.0
    offset = local_utc_offset(longitude, utc_offset_hours)
    return (utc_hours + offset) % 24.0


def format_duration(hours: float) -> str:
    """Horas decimales a texto corto (``5h 37min``; sub-hora a minutos)."""
    total = int(round(hours * 60))
    return (
        f"{total // 60}h {total % 60:02d}min" if total >= 60 else f"{total}min"
    )


def window_lines(summary: dict[str, dict]) -> tuple[str, str]:
    """Textos de las ventanas Ideal y Posible a partir del resumen.

    Devuelve una tupla ``(ideal, posible)`` lista para la leyenda; una ventana
    sin tramos se describe como "sin ventana" para no dejar la línea vacía.
    """
    return (
        _window_text(summary, WINDOW_IDEAL, "★ Captura Ideal"),
        _window_text(summary, WINDOW_POSSIBLE, "⚠ Captura Posible"),
    )


def _window_text(summary: dict[str, dict], key: str, prefix: str) -> str:
    entry = summary.get(key) or {}
    ranges = entry.get("ranges") or []
    if not ranges:
        return f"{prefix}: sin ventana"
    text = " y ".join(
        format_hour_range(start, end) for start, end in ranges
    )
    return f"{prefix}: {text} ({format_duration(entry.get('hours', 0.0))})"


def _local_label(local_hours: float | None) -> str:
    """Horas locales a ``HH:MM`` (o ``--:--`` si no hay dato)."""
    return fmt_hhmm(local_hours) if local_hours is not None else "--:--"


#: Husos horarios ofrecidos en el selector (frente a UTC, horas).
UTC_OFFSETS: tuple[float, ...] = tuple(
    (step * 0.5 for step in range(-24, 29))   # -12.0 … +14.0 en pasos de 0.5
)


def _system_offset_hours() -> float:
    """Desfase UTC del reloj del sistema, en horas (verano incluido)."""
    offset = datetime.now().astimezone().utcoffset()
    return offset.total_seconds() / 3600.0 if offset else 0.0


class LocationBar(QFrame):
    """Selector de ubicación de las subpestañas del Planificador.

    Un único control para latitud, longitud y desfase horario: así Búsqueda
    (efemérides, curva, clima) y Planificación (curva, ranking) no pueden
    divergir. Emite ``location_changed(lat, lon, utc_offset|None)``.

    Vive en la **tercera fila de la izquierda de Búsqueda** (a la izquierda
    de las condiciones meteorológicas), compactado en tres filas para caber
    en la columna izquierda; el resto de subpestañas lo consumen por señal.

    El desfase puede quedar en «Auto» (la hora del reloj del sistema, con
    horario de verano), «Solar (longitud)» (hora solar local) o fijado a
    una hora de reloj concreta.
    """

    location_changed = pyqtSignal(float, float, object)  # lat, lon, offset|None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GroupFrame")

        layout = QVBoxLayout(self)
        # Compacto: la 3ª fila cede altura a Filtros y Efemérides.
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(4)

        # Fila 1: etiqueta + selector de ubicación guardada (o manual).
        head = QHBoxLayout()
        head.setSpacing(6)
        label = QLabel("📍 Ubicación")
        label.setObjectName("SectionTitle")
        label.setToolTip("Ubicación de los cálculos de altitud, tránsito y horarios")
        head.addWidget(label)
        self._combo = QComboBox()
        self._combo.setMinimumWidth(170)
        self._combo.setToolTip(
            "Ubicación guardada, o «Manual» para escribir lat/long a mano.\n"
            "Sin ubicaciones guardadas: escribe lat/long aquí mismo."
        )
        self._combo.currentIndexChanged.connect(self._on_combo)
        head.addWidget(self._combo, 1)
        layout.addLayout(head)

        # Fila 2: latitud y longitud.
        coords = QHBoxLayout()
        coords.setSpacing(6)
        coords.addWidget(QLabel("Lat"))
        self._latitude = QDoubleSpinBox()
        self._latitude.setRange(-90.0, 90.0)
        self._latitude.setDecimals(3)
        self._latitude.setSingleStep(0.1)
        self._latitude.setSuffix("°")
        # Ancho mínimo real: «-90,000°» + botones pide 120 px.
        # Con 92 el valor salía cortado.
        self._latitude.setFixedWidth(124)
        self._latitude.valueChanged.connect(self._on_manual)
        coords.addWidget(self._latitude)

        coords.addWidget(QLabel("Lon"))
        self._longitude = QDoubleSpinBox()
        self._longitude.setRange(-180.0, 180.0)
        self._longitude.setDecimals(3)
        self._longitude.setSingleStep(0.1)
        self._longitude.setSuffix("°")
        self._longitude.setFixedWidth(136)     # «-180,000°» pide 132 px
        self._longitude.valueChanged.connect(self._on_manual)
        coords.addWidget(self._longitude)
        layout.addLayout(coords)

        # Fila 3: huso horario.
        offset_row = QHBoxLayout()
        offset_row.setSpacing(6)
        offset_row.addWidget(QLabel("Huso"))
        self._offset = QComboBox()
        # «Auto» (None) se resuelve a la hora del sistema en
        # utc_offset_hours(); «Solar» (None aguas abajo) usa la longitud.
        self._offset.addItem("Auto", None)
        self._offset.addItem("Solar (longitud)", "solar")
        for value in UTC_OFFSETS:
            self._offset.addItem(f"{value:+.1f} h", value)
        # 170 px: «Solar (longitud)» + desplegable pedían 158; margen de sobra.
        self._offset.setFixedWidth(170)
        self._offset.setToolTip(
            "Desfase horario de la ubicación.\n"
            "«Auto» usa la hora de tu reloj (horario de verano incluido);\n"
            "«Solar (longitud)» calcula la hora solar local desde la longitud;\n"
            "o fija una hora de reloj concreta."
        )
        self._offset.currentIndexChanged.connect(self._emit)
        offset_row.addWidget(self._offset)
        offset_row.addStretch(1)
        layout.addLayout(offset_row)

        # Estado inicial: ubicación guardada si la hay; si no, a la espera
        # de que el usuario escriba lat/long (no se inventa un punto en 0,0).
        self._loading = True
        self._reload_locations(select_first=True)
        self._loading = False
        if self._combo.count() > 1:
            # La señal `currentIndexChanged` se encarga de rellenar y emitir.
            self._combo.setCurrentIndex(1)

    # -- API ----------------------------------------------------------------
    def latitude(self) -> float:
        return self._latitude.value()

    def longitude(self) -> float:
        return self._longitude.value()

    def utc_offset_hours(self) -> float | None:
        """Desfase horario a usar en los cálculos.

        «Auto» → la hora del reloj del sistema (lo que pide el usuario sin
        tocar nada); «Solar (longitud)» → ``None``, para que los planos
        calculen la hora solar desde la longitud; un valor fijo → ese
        desfase de reloj.
        """
        value = self._offset.currentData()
        if value is None:                       # «Auto»
            return _system_offset_hours()
        if value == "solar":                    # «Solar (longitud)»
            return None
        return value

    def has_saved_location(self) -> bool:
        """¿Hay una ubicación de la base seleccionada (no el modo manual)?"""
        return isinstance(self._combo.currentData(), dict)

    def reemit(self) -> None:
        """Vuelve a emitir el estado actual.

        Útil quien crea la barra y sus destinos a la vez: la primera emisión
        ocurre dentro del constructor, cuando aún no hay nadie conectado.
        """
        self._emit()

    def reload(self) -> None:
        """Vuelve a leer las ubicaciones guardadas (tras crear una nueva)."""
        current = self._combo.currentData()
        self._loading = True
        self._reload_locations()
        if current is not None:
            index = self._combo.findData(current)
            if index >= 0:
                self._combo.setCurrentIndex(index)
        self._loading = False

    # -- Internos -----------------------------------------------------------
    def _reload_locations(self, select_first: bool = False) -> None:
        self._combo.blockSignals(True)
        self._combo.clear()
        try:
            from equipment.localizations import list_locations

            locations = list_locations()
        except Exception:  # sin tabla o base recién creada: solo manual
            locations = []
        # Sin ubicaciones guardadas, el propio combo avisa. La etiqueta es
        # corta para no desbordar la columna izquierda.
        # Sin ubicaciones guardadas el texto largo se cortaba en el combo;
        # la indicación completa está en el tooltip.
        self._combo.addItem(
            "Manual — escribe aquí" if not locations else "(Manual)", None
        )
        for location in locations:
            name = location.get("name") or f"Ubicación {location['id']}"
            self._combo.addItem(name, location)
        self._combo.blockSignals(False)
        if select_first:
            self._combo.setCurrentIndex(0)

    def _on_combo(self, index: int) -> None:
        if self._loading:
            return
        location = self._combo.itemData(index)
        if location:
            self._loading = True
            self._latitude.setValue(float(location.get("latitude") or 0.0))
            self._longitude.setValue(float(location.get("longitude") or 0.0))
            offset = location.get("utc_offset_hours")
            at = self._offset.findData(offset)
            self._offset.setCurrentIndex(at if at >= 0 else 0)
            self._loading = False
        self._emit()

    def _on_manual(self, _value: float) -> None:
        if self._loading:
            return
        self._combo.blockSignals(True)
        self._combo.setCurrentIndex(0)
        self._combo.blockSignals(False)
        self._emit()

    def _emit(self, *_args) -> None:
        if self._loading:
            return
        self.location_changed.emit(
            self._latitude.value(), self._longitude.value(), self.utc_offset_hours()
        )


# --------------------------------------------------------------------------- #
#                            T A R J E T A S                                   #
# --------------------------------------------------------------------------- #
class MetricCard(QFrame):
    """Tarjeta título + valor (clima, seeing, métricas de plan)."""

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        title_color: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setMinimumWidth(110)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setObjectName("MetricTitle")
        if title_color:
            # Color propio por tarjeta; el resto del estilo (tamaño,
            # negrita) sigue viniendo de #MetricTitle.
            title_label.setStyleSheet(f"color: {title_color};")
        layout.addWidget(title_label)

        self._value = QLabel("--")
        self._value.setObjectName("MetricValue")
        self._value.setWordWrap(True)
        self._value.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self._value)

        self.set_value("--")

    def set_value(
        self, text: str, unavailable: bool = False, color: str | None = None
    ) -> None:
        """Pon el valor; ``unavailable`` lo muestra atenuado y sin borde vivo.

        ``color`` tiñe el texto (tarjetas de clima al estilo del original:
        seeing verde, rocío naranja…); sin color o sin datos se mantiene el
        gris del tema.
        """
        if color and not unavailable:
            self._value.setText(f'<span style="color:{color}">{text}</span>')
        else:
            self._value.setText(text)
        self.setProperty("unavailable", str(unavailable).lower())
        self._value.setProperty("unavailable", str(unavailable).lower())
        # La hoja de estilos usa [unavailable="true"]: hay que reevaluarla.
        for widget in (self, self._value):
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)


def _first(values: list[float]) -> float | None:
    """Primera muestra útil de una serie (vacía → None, nunca un 0 inventado)."""
    return float(values[0]) if values else None


def _transparency(cloud_pct: float | None) -> str:
    """Transparencia del cielo a partir de la nubosidad (cualitativa)."""
    if cloud_pct is None:
        return "--"
    if cloud_pct <= 10:
        return "Excelente"
    if cloud_pct <= 30:
        return "Buena"
    if cloud_pct <= 60:
        return "Regular"
    return "Mala"


def _metric_text(value: float | None, template: str) -> tuple[str, bool]:
    """``(texto, sin_datos)`` de una métrica opcional; nunca formatea ``None``."""
    if value is None:
        return "Sin datos", True
    return template.format(value), False


class WeatherCards(QWidget):
    """Las 6 tarjetas de clima/seeing (títulos y colores del original).

    Combina Clear Outside (clima) y Meteoblue (seeing). Sin API key los
    proveedores devuelven ``available=False`` y aquí se muestra "Sin datos".
    """

    #: (título, fuente, color del valor, color del título)
    #: Títulos cortos: en una tarjeta estrecha las frases largas se cortaban.
    #: Cada título con su color para distinguir las tarjetas de un vistazo.
    CARDS = (
        ("Seeing", "seeing", "#22c55e", "#22c55e"),          # verde
        ("Nubosidad", "cloud", "#60a5fa", "#60a5fa"),        # azul
        ("Humedad", "humidity", "#60a5fa", "#22d3ee"),       # cian
        ("Rocío", "dew", "#f59e0b", "#f59e0b"),              # ámbar
        ("Viento", "wind", "#60a5fa", "#a78bfa"),            # violeta
        ("Transparencia", "transparency", "#22c55e", "#2dd4bf"),  # turquesa
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._cards: dict[str, MetricCard] = {}
        for title, key, _color, title_color in self.CARDS:
            card = MetricCard(title, title_color=title_color)
            self._cards[key] = card
            layout.addWidget(card)

        # Nota de proveedores sin API key: NO va en este layout (estiraba
        # las tarjetas y les cortaba el título); la coloca quien ensambla
        # el panel, en la fila del título.
        self.note_label = QLabel("")
        self.note_label.setObjectName("HintLabel")
        self.note_label.hide()

    def refresh(self, latitude: float, longitude: float, date_iso: str) -> None:
        """Rellena las tarjetas para ``date_iso`` en la ubicación dada."""
        clear = ClearOutside().forecast(latitude, longitude, date_iso)
        meteo = Meteoblue().forecast(latitude, longitude, date_iso)

        seeing = _first(meteo.seeing_arcsec)
        clouds = _first(clear.cloud_cover_pct)
        humidity = _first(clear.humidity_pct)
        wind = _first(clear.wind_kmh)

        values: dict[str, tuple[str, bool]] = {
            "seeing": _metric_text(seeing, '{value:.1f}"'),
            "cloud": _metric_text(clouds, "{value:.0f} %"),
            "humidity": _metric_text(humidity, "{value:.0f} %"),
            "dew": ("Sin datos", True),        # sin temperatura no se calcula
            "wind": _metric_text(wind, "{value:.0f} km/h"),
            "transparency": ("Sin datos", True)
            if clouds is None
            else (_transparency(clouds), False),
        }
        colors = {key: color for _title, key, color, _tc in self.CARDS}
        # La transparencia cambia de color con su cualitativa.
        if not values["transparency"][1]:
            colors["transparency"] = {
                "Excelente": "#22c55e",
                "Buena": "#22c55e",
                "Regular": "#f59e0b",
                "Mala": "#ef4444",
            }.get(values["transparency"][0], colors["transparency"])
        for key, (text, unavailable) in values.items():
            self._cards[key].set_value(text, unavailable, colors[key])

        # Aviso genérico: el detalle de keys no se enseña en la sección
        # (viven en Configuración general); solo un «falta conectar» o,
        # si ya hay key pero la llamada real sigue en el horno, un
        # «integración pendiente».
        notes = [p.note for p in (clear, meteo) if not p.available and p.note]
        if notes:
            if any(note.startswith("Falta") for note in notes):
                self.note_label.setText("Falta conectar la API del clima")
            else:
                self.note_label.setText("API guardada: integración pendiente")
            self.note_label.setToolTip(
                "Las API keys se guardan en Configuración general.\n"
                + " · ".join(notes)
            )
            self.note_label.show()
        else:
            self.note_label.hide()


# --------------------------------------------------------------------------- #
#                       F A S E   L U N A R   /   B A R R A                    #
# --------------------------------------------------------------------------- #
def _rect_path(rect: QRectF) -> QPainterPath:
    """``QRectF`` convertido a ``QPainterPath``.

    PyQt6 solo acepta paths en ``intersected``/``united``, no rects.
    """
    path = QPainterPath()
    path.addRect(rect)
    return path


def _lit_path(
    center_x: float, center_y: float, radius: float, illumination: float, waxing: bool
) -> QPainterPath:
    """Silueta iluminada de la luna (disco ∩ forma creciente/gibosa)."""
    path = QPainterPath()
    if illumination <= 0.0:
        return path
    if illumination >= 1.0:
        path.addEllipse(QPointF(center_x, center_y), radius, radius)
        return path

    # Mitad iluminada: el creciente mira al oeste (derecha) en el hemisferio norte.
    if waxing:
        lit_half = QRectF(center_x, center_y - radius, radius, 2 * radius)
        dark_half = QRectF(center_x - radius, center_y - radius, radius, 2 * radius)
    else:
        lit_half = QRectF(center_x - radius, center_y - radius, radius, 2 * radius)
        dark_half = QRectF(center_x, center_y - radius, radius, 2 * radius)

    disc = QPainterPath()
    disc.addEllipse(QPointF(center_x, center_y), radius, radius)
    lit = disc.intersected(_rect_path(lit_half))

    terminator_rx = radius * abs(1.0 - 2.0 * illumination)
    if terminator_rx > 0.5:
        terminator = QPainterPath()
        terminator.addEllipse(QPointF(center_x, center_y), terminator_rx, radius)
        if illumination > 0.5:
            # Gibosa: la curva terminadora se mete en la mitad oscura.
            lit = lit.united(terminator.intersected(_rect_path(dark_half)))
        else:
            # Creciente: la curva terminadora recorta la mitad iluminada.
            lit = lit.subtracted(terminator.intersected(_rect_path(lit_half)))
    return lit


class MoonPhaseWidget(QWidget):
    """Disco lunar con su fase (iluminación 0-1 y sentido de crecimiento)."""

    def __init__(self, size: int = 56, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._illumination = 0.5
        self._waxing = True
        self.setFixedSize(size, size)

    def set_phase(self, illumination: float, waxing: bool) -> None:
        self._illumination = max(0.0, min(1.0, float(illumination)))
        self._waxing = bool(waxing)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (API de Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        radius = min(self.width(), self.height()) / 2.0 - 2
        center = QPointF(self.width() / 2.0, self.height() / 2.0)

        painter.setPen(QPen(QColor(PALETTE["border"]), 1))
        painter.setBrush(QColor("#0b0f16"))
        painter.drawEllipse(center, radius, radius)

        lit = _lit_path(center.x(), center.y(), radius, self._illumination, self._waxing)
        if not lit.isEmpty():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#e8e2c8"))   # blanco roto tipo luna
            painter.drawPath(lit)

        painter.setPen(QPen(QColor(PALETTE["border"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius, radius)
        painter.end()


class DayNightBar(QWidget):
    """Barra de 24 h con día, crepúsculo y noche astronómica.

    Los cinco hitos (puesta, ocaso, amanecer, salida) vienen ya convertidos a
    hora local decimal; esta clase solo clasifica cada píxel y pinta.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._marks: dict[str, float | None] = {
            "sunset": None, "dusk": None, "dawn": None, "sunrise": None,
        }

    def set_marks(
        self,
        sunset: float | None,
        dusk: float | None,
        dawn: float | None,
        sunrise: float | None,
    ) -> None:
        self._marks = {"sunset": sunset, "dusk": dusk, "dawn": dawn, "sunrise": sunrise}
        self.update()

    @staticmethod
    def _in_interval(hour: float, start: float, end: float) -> bool:
        """¿``hour`` dentro de [start, end)? Soporta intervalo que cruza 0."""
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    def _kind(self, hour: float) -> str:
        marks = self._marks
        night = None
        if marks["dusk"] is not None and marks["dawn"] is not None:
            night = (marks["dusk"], marks["dawn"])
        elif marks["sunset"] is not None and marks["sunrise"] is not None:
            night = (marks["sunset"], marks["sunrise"])

        if night and self._in_interval(hour, *night):
            return "night"
        if (
            marks["sunset"] is not None
            and marks["dusk"] is not None
            and self._in_interval(hour, marks["sunset"], marks["dusk"])
        ):
            return "twilight"
        if (
            marks["dawn"] is not None
            and marks["sunrise"] is not None
            and self._in_interval(hour, marks["dawn"], marks["sunrise"])
        ):
            return "twilight"
        if night is None:
            return "unknown"
        return "day"

    def paintEvent(self, event) -> None:  # noqa: N802 (API de Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(0, 4, self.width(), 14)
        painter.setPen(Qt.PenStyle.NoPen)

        for x in range(int(rect.width())):
            hour = (x + 0.5) / max(rect.width(), 1) * 24.0
            kind = self._kind(hour)
            color = {
                "day": COLOR_DAY,
                "twilight": COLOR_TWILIGHT,
                "night": COLOR_NIGHT_BAR,
                "unknown": PALETTE["surface"],
            }[kind]
            painter.setBrush(QColor(color))
            painter.drawRect(QRectF(rect.left() + x, rect.top(), 1, rect.height()))

        painter.setPen(QPen(QColor(PALETTE["border"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        # Marcas de 6 h
        painter.setPen(QColor(PALETTE["textDim"]))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        for tick in (0, 6, 12, 18, 24):
            x = rect.left() + tick / 24.0 * rect.width()
            painter.drawLine(QPointF(x, rect.bottom()), QPointF(x, rect.bottom() + 2))
            label = f"{tick % 24:02d}h"
            painter.drawText(
                QRectF(x - 16, rect.bottom() + 3, 32, 13),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

        # Hitos de la noche
        for key, color in (
            ("sunset", "#f59e0b"), ("dusk", "#818cf8"),
            ("dawn", "#818cf8"), ("sunrise", "#f59e0b"),
        ):
            value = self._marks.get(key)
            if value is None:
                continue
            x = rect.left() + value / 24.0 * rect.width()
            painter.setPen(QPen(QColor(color), 1.6))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        painter.end()


# --------------------------------------------------------------------------- #
#                           E F E M É R I D E S                                #
# --------------------------------------------------------------------------- #
#: Nombres de la fase por fracción iluminada, separados por sentido:
#: la iluminación da la FORMA (creciente → cuarto → gibosa → llena) y el
#: sentido da si crece o mengua. No se puede deducir una de la otra.
_PHASE_TABLES: dict[bool, tuple[tuple[float, str], ...]] = {
    True: (   # creciente (de luna nueva a llena)
        (0.02, "Luna nueva"),
        (0.48, "Creciente"),
        (0.52, "Cuarto creciente"),
        (0.98, "Gibosa creciente"),
        (1.01, "Luna llena"),
    ),
    False: (  # menguante (de llena a luna nueva)
        (0.02, "Luna nueva"),
        (0.48, "Menguante"),
        (0.52, "Cuarto menguante"),
        (0.98, "Gibosa menguante"),
        (1.01, "Luna llena"),
    ),
}


def phase_name(illumination: float, waxing: bool) -> str:
    """Nombre de la fase a partir de la fracción iluminada y su sentido."""
    for limit, name in _PHASE_TABLES[bool(waxing)]:
        if illumination <= limit:
            return name
    return "Luna llena"


class EphemerisPanel(QFrame):
    """Panel "Efemérides Sol y Luna": fecha, fase, barra día/noche y horarios.

    Emite ``date_changed(date_iso)`` para que quien lo usa recalcule su curva
    de tránsito. El lugar (lat/long) lo aporta quien llama a :meth:`refresh`.
    """

    date_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GroupFrame")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(4)

        title = QLabel("Efemérides Sol y Luna")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        # --- Fecha: ◀/▶ día a día y botón "Hoy"
        date_row = QHBoxLayout()
        date_row.setSpacing(6)

        prev_day = QPushButton("◀")
        prev_day.setFixedWidth(34)
        prev_day.setToolTip("Un día atrás")
        prev_day.clicked.connect(lambda: self._step_day(-1))
        date_row.addWidget(prev_day)

        self._date = QDateEdit()
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("dd/MM/yyyy")
        self._date.setDate(QDate.currentDate())
        self._date.dateChanged.connect(self._emit_date)
        date_row.addWidget(self._date)

        next_day = QPushButton("▶")
        next_day.setFixedWidth(34)
        next_day.setToolTip("Un día adelante")
        next_day.clicked.connect(lambda: self._step_day(1))
        date_row.addWidget(next_day)

        today = QPushButton("Hoy")
        today.setFixedWidth(64)
        today.clicked.connect(self._go_today)
        date_row.addWidget(today)
        date_row.addStretch(1)
        layout.addLayout(date_row)

        # --- Fase lunar (rótulos del original: «LUNA», fase e iluminación)
        luna_label = QLabel("LUNA")
        luna_label.setObjectName("MetricTitle")
        layout.addWidget(luna_label)

        moon_row = QHBoxLayout()
        moon_row.setSpacing(8)
        self._moon_icon = MoonPhaseWidget(44)
        moon_row.addWidget(self._moon_icon)

        moon_text = QVBoxLayout()
        moon_text.setSpacing(0)
        self._phase_label = QLabel("--")
        self._phase_label.setObjectName("MoonPhase")
        moon_text.addWidget(self._phase_label)
        self._illum_label = QLabel("--")
        self._illum_label.setObjectName("HintLabel")
        moon_text.addWidget(self._illum_label)
        moon_row.addLayout(moon_text, 1)
        moon_row.addStretch(1)
        layout.addLayout(moon_row)

        # --- Luz del día y noche
        day_label = QLabel("LUZ DEL DÍA Y NOCHE ASTRONÓMICA")
        day_label.setObjectName("MetricTitle")
        layout.addWidget(day_label)

        self._bar = DayNightBar()
        layout.addWidget(self._bar)

        # --- Horas (los valores van en color, como en el original)
        self._sunset_label = QLabel("Puesta de Sol: --:-- – --:--")
        self._sunset_label.setObjectName("HintLabel")
        layout.addWidget(self._sunset_label)

        self._night_label = QLabel("Noche astronómica: --:-- – --:--")
        self._night_label.setObjectName("HintLabel")
        layout.addWidget(self._night_label)

        # Estado actual (para poder refrescar tras mover la ubicación)
        self._latitude = 0.0
        self._longitude = 0.0
        self._utc_offset_hours: float | None = None

    # -- API ----------------------------------------------------------------
    def set_date(self, date_iso: str) -> None:
        """Pon la fecha sin disparar ``date_changed`` (evita bucles)."""
        moment = QDate.fromString(date_iso, "yyyy-MM-dd")
        if moment.isValid():
            self._date.blockSignals(True)
            self._date.setDate(moment)
            self._date.blockSignals(False)

    def refresh(
        self,
        latitude: float,
        longitude: float,
        date_iso: str,
        utc_offset_hours: float | None = None,
    ) -> None:
        """Recalcula todo el panel para ``date_iso`` y la ubicación dada.

        ``utc_offset_hours`` es el desfase horario guardado de la ubicación
        (``None`` → se usa la longitud como hora solar).
        """
        self._latitude = latitude
        self._longitude = longitude
        self._utc_offset_hours = utc_offset_hours
        self.set_date(date_iso)

        info: NightInfo = night_info(latitude, longitude, date_iso)
        illumination = info.moon_illumination

        self._moon_icon.set_phase(illumination, info.waxing)
        self._phase_label.setText(phase_name(illumination, info.waxing))
        self._illum_label.setText(
            f"{illumination * 100:.0f} % iluminada · Edad {info.moon_age_days:.1f} d"
        )

        def _local(iso: str | None) -> float | None:
            return iso_to_local_hours(iso, longitude, utc_offset_hours)

        self._bar.set_marks(
            _local(info.sunset),
            _local(info.astronomical_dusk),
            _local(info.astronomical_dawn),
            _local(info.sunrise),
        )

        sunset = _local(info.sunset)
        sunrise = _local(info.sunrise)
        # Como el original: puesta → salida en naranja.
        self._sunset_label.setText(
            "Puesta de Sol: "
            f'<span style="color:#f59e0b">{_local_label(sunset)} – '
            f"{_local_label(sunrise)}</span>"
        )

        dusk = _local(info.astronomical_dusk)
        dawn = _local(info.astronomical_dawn)
        if dusk is None or dawn is None:
            self._night_label.setText("Noche astronómica: sin noche ese día")
        else:
            # Y la noche astronómica en azul.
            self._night_label.setText(
                "Noche astronómica: "
                f'<span style="color:#60a5fa">{_local_label(dusk)} – '
                f"{_local_label(dawn)}</span>"
            )

    def current_date_iso(self) -> str:
        """Fecha visible como ``yyyy-MM-dd``."""
        return self._date.date().toString("yyyy-MM-dd")

    # -- Señales ------------------------------------------------------------
    def _emit_date(self, _date: QDate) -> None:
        self.date_changed.emit(self.current_date_iso())

    def _step_day(self, days: int) -> None:
        """Mueve la fecha±1 día; ``dateChanged`` se encarga de emitir."""
        self._date.setDate(self._date.date().addDays(days))

    def _go_today(self) -> None:
        self._date.setDate(QDate.currentDate())
        self.date_changed.emit(self.current_date_iso())


# --------------------------------------------------------------------------- #
#                         C U R V A   D E   T R Á N S I T O                    #
# --------------------------------------------------------------------------- #
class TransitCurve(QWidget):
    """Curva de tránsito con PyQtGraph: altitud del objeto y de la Luna.

    Un solo eje (izquierdo, 0-90°) para dos curvas: la **altitud del
    objeto** (azul) y la de la **Luna** (gris) — esta última muestra a
    qué hora sale y se oculta la Luna y qué altura alcanza. Debajo se
    pintan las bandas de noche astronómica, las ventanas de captura
    Ideal/Possible y la **zona ±2°** (amarilla): tramos en los que el
    objeto está a ±2° del umbral de separación mínima o de los 45° de
    altitud. La separación objeto-Luna se lee como **texto** en el
    subtítulo («Separación» y «Mínimo»), junto con las líneas de
    Captura Ideal y Captura Posible (rangos horarios y duración).

    No hay eje derecho: la gráfica aprovecha todo el ancho (petición
    del usuario; antes ahí vivían la curva de separación y el umbral,
    ya retirados).

    Es una gráfica **fija** (petición del usuario): no hace zoom con la
    rueda, no se desplaza por el eje horario y no tiene menú contextual;
    solo cambia cuando cambian los datos (objeto, fecha, filtros,
    ubicación).

    El eje horario es **dinámico**: muestra desde 1 h antes del inicio
    de la noche astronómica hasta 1 h después de su fin (si no hay
    noche astronómica, la muestra completa).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GroupFrame")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # --- Cabecera
        header = QVBoxLayout()
        header.setSpacing(1)

        self._title = QLabel(CURVE_TITLE)
        self._title.setObjectName("CurveTitle")
        header.addWidget(self._title)

        self._subtitle = QLabel(CURVE_EMPTY_SUBTITLE)
        self._subtitle.setObjectName("CurveSubtitle")
        header.addWidget(self._subtitle)

        # Rangos de Captura Ideal / Posible (aparecen solo con datos).
        self._windows_label = QLabel()
        self._windows_label.setObjectName("CurveSubtitle")
        self._windows_label.setWordWrap(True)
        header.addWidget(self._windows_label)

        self._legend = QLabel(self._legend_text(full=False))
        self._legend.setObjectName("CurveLegend")
        header.addWidget(self._legend)

        layout.addLayout(header)

        # --- Gráfico (solo eje izquierdo: el derecho se retiró para que
        # la gráfica ocupe todo el ancho)
        self._axis_bottom = pg.AxisItem(orientation="bottom")
        self._axis_bottom.tickStrings = self._tick_strings  # type: ignore[method-assign]
        self._plot = pg.PlotWidget(
            axisItems={"bottom": self._axis_bottom},
            enableMenu=False,
        )
        # Mínimo holgado: la curva se expande con el espacio libre, pero si
        # la columna se queda sin sitio Qt la comprime por debajo de su
        # mínimo y el eje inferior (20 px) sale recortado.
        self._plot.setMinimumHeight(150)
        # Gráfica fija: sin zoom de rueda ni desplazamiento por arrastre.
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("left", "Altitud", units="°")

        item = self._plot.getPlotItem()

        # Ejes y etiquetas en gris secundario (los dos, idénticos al tema)
        for axis in (item.getAxis("left"), self._axis_bottom):
            axis.setTextPen(QColor(PALETTE["textDim"]))

        layout.addWidget(self._plot, 1)

        # --- Curvas y bandas
        # Una banda = una pool de tramos: pyqtgraph 0.14 solo pinta un
        # tramo por LinearRegionItem (ver _BandPool).
        self._night_band = _BandPool(
            item,
            brush=pg.mkBrush(*COLOR_NIGHT),
            pen=pg.mkPen(QColor(148, 163, 184, 110), width=1),
            z_value=-10,
        )
        self._possible_band = _BandPool(
            item,
            brush=pg.mkBrush(*COLOR_POSSIBLE),
            pen=pg.mkPen(QColor(245, 158, 11, 170), width=1),
            z_value=-10,
        )
        self._ideal_band = _BandPool(
            item,
            brush=pg.mkBrush(*COLOR_IDEAL),
            pen=pg.mkPen(QColor(34, 197, 94, 180), width=1),
            z_value=-10,
        )
        # Zona ±2° (umbral lunar / 45° de altitud): por encima de las
        # bandas (-9) para que se vea incluso sobre Ideal/Posible.
        self._zone_band = _BandPool(
            item,
            brush=pg.mkBrush(*COLOR_ZONE),
            pen=pg.mkPen(QColor(251, 191, 36, 170), width=1),
            z_value=-9,
        )

        self._limit_line = item.addLine(
            y=30, pen=pg.mkPen(COLOR_LIMIT, width=1.5, style=Qt.PenStyle.DashLine)
        )
        self._limit_line.setZValue(5)

        self._altitude_curve = item.plot(
            pen=pg.mkPen(COLOR_ALTITUDE, width=2.2)
        )
        # Altitud de la Luna sobre el mismo eje 0-90°: sale y se oculta
        # al cruzar el borde inferior y su techo marca la altura máxima.
        self._moon_curve = item.plot(
            pen=pg.mkPen(COLOR_MOON, width=1.8)
        )

        self.clear()

    # -- Leyenda ------------------------------------------------------------
    @staticmethod
    def _legend_text(full: bool) -> str:
        """Leyenda HTML: minimal (estado vacío) o completa con las bandas.

        Solo describe lo que se pinta en el gráfico: altitud del objeto,
        límite de 30°, curva de la Luna, la zona ±2° y las dos ventanas
        de captura. La separación y los rangos horarios viven en el
        subtítulo.
        """
        alt = f'<span style="color:{COLOR_ALTITUDE}">━━</span> Altitud'
        if not full:
            return alt
        return (
            f'{alt} &nbsp; '
            f'<span style="color:{COLOR_LIMIT}">- -</span> 30° &nbsp; '
            f'<span style="color:{COLOR_MOON}">━━</span> Luna &nbsp; '
            f'<span style="color:#fbbf24">■</span> Zona ±2° &nbsp; '
            f'<span style="color:#22c55e">■</span> Ideal &nbsp; '
            f'<span style="color:#f59e0b">■</span> Posible'
        )

    # -- Formato del eje ----------------------------------------------------
    @staticmethod
    def _tick_strings(values, scale, spacing) -> list[str]:
        """Etiquetas del eje inferior en ``HH:MM`` (horas desenvueltas)."""
        return [fmt_hhmm(value) for value in values]

    # -- API ----------------------------------------------------------------
    def clear(self, message: str = CURVE_EMPTY_SUBTITLE) -> None:
        """Vacía el gráfico y lo deja en el estado inicial.

        ``message`` explica **por qué** está vacío: que no hay objeto
        seleccionado no es lo mismo que tenerlo elegido y faltar la
        ubicación para poder calcular su altitud.

        Sin datos **no se dibuja nada**: las bandas con región degenerada
        quedan como dos líneas sueltas flotando en el panel y la línea de
        30° fijaba el eje vertical alrededor de ese valor.
        """
        self._title.setText(CURVE_TITLE)
        self._subtitle.setText(message)
        self._windows_label.clear()
        self._windows_label.hide()
        self._legend.setText(self._legend_text(full=False))
        self._altitude_curve.setData([], [])
        self._moon_curve.setData([], [])
        for band in (
            self._night_band,
            self._possible_band,
            self._ideal_band,
            self._zone_band,
        ):
            band.hide()
        self._limit_line.hide()

        # Rangos del estado inicial: la noche local de 16:00 a 08:00 y el
        # eje completo, para que no quede un auto-rango absurdo.
        item = self._plot.getPlotItem()
        item.setXRange(*NIGHT_X_RANGE, padding=0)
        item.setYRange(0, 90, padding=0)

    def show_curve(
        self,
        curve: NightCurve,
        target_label: str = "",
    ) -> dict[str, dict]:
        """Pinta la noche y devuelve el resumen de ventanas.

        ``curve`` viene de ``planners.transit.night_curve``; si al construirla
        se le pasó el ``utc_offset_hours`` de la ubicación, el eje horario ya
        es hora de reloj.
        """
        illumination_pct = curve.moon_illumination * 100.0
        min_dist = min_moon_distance(illumination_pct)

        hours = unwrap_hours(curve.hours_local)
        windows = capture_windows(
            curve.altitudes,
            curve.moon_separations,
            curve.moon_altitudes,
            curve.astro_night,
            illumination_pct,
        )
        summary = capture_window_summary(windows, hours)

        # --- Cabecera (título fijo; el subtítulo resume el tránsito)
        transit = curve.hours_local[curve.transit_index]
        peak = curve.altitudes[curve.transit_index]
        worst_sep = min(curve.moon_separations)
        self._subtitle.setText(
            f"Tránsito: {target_label} · Máx {peak:.1f}° · "
            f"Culm. {fmt_hhmm(transit)} · Luna {illumination_pct:.0f} % · "
            f"Separación {worst_sep:.0f}° · Mínimo {min_dist:.0f}°"
        )
        # Rangos de captura: Ideal y Posible (no ideal) con horas y duración.
        ideal_line, possible_line = window_lines(summary)
        self._windows_label.setText(f"{ideal_line} · {possible_line}")
        self._windows_label.show()
        self._legend.setText(self._legend_text(full=True))

        # --- Curvas
        self._altitude_curve.setData(hours, curve.altitudes)
        self._moon_curve.setData(hours, curve.moon_altitudes)

        # --- Bandas
        self._night_band.set_spans(_contiguous_spans(hours, curve.astro_night))
        self._possible_band.set_spans(
            _contiguous_spans(hours, [w == WINDOW_POSSIBLE for w in windows])
        )
        self._ideal_band.set_spans(
            _contiguous_spans(hours, [w == WINDOW_IDEAL for w in windows])
        )
        # Zona ±2°: el objeto a tiro del umbral lunar o de los 45° de
        # altitud (ambas condiciones comparten la misma banda amarilla).
        # Con la Luna bajo el horizonte no hay umbral lunar que vigilar
        # (igual que en las ventanas): solo cuenta la transición de altitud.
        zone_mask = [
            (
                moon_alt > 0.0 and abs(separation - min_dist) <= 2.0
            )
            or abs(altitude - 45.0) <= 2.0
            for separation, altitude, moon_alt in zip(
                curve.moon_separations, curve.altitudes, curve.moon_altitudes,
                strict=False,
            )
        ]
        self._zone_band.set_spans(_contiguous_spans(hours, zone_mask))
        self._limit_line.show()          # límite de 30° (oculto en clear())

        # --- Eje
        item = self._plot.getPlotItem()
        item.setYRange(0, 90, padding=0)
        # Eje horario dinámico: de 1 h antes a 1 h después de la noche
        # astronómica (petición del usuario). Si la noche no existe
        # (objeto que no sale, latitudes extremas) se muestra la muestra
        # completa, como hasta ahora.
        night_hours = [
            hour
            for hour, night in zip(hours, curve.astro_night, strict=False)
            if night
        ]
        if night_hours:
            item.setXRange(night_hours[0] - 1.0, night_hours[-1] + 1.0, padding=0)
        else:
            item.setXRange(hours[0], hours[-1], padding=0.02)
        return summary


class _BandPool:
    """Una banda de fondo con uno o varios tramos (varios `LinearRegionItem`).

    pyqtgraph 0.14 pinta **un solo tramo** por ``LinearRegionItem``:
    ``setRegion`` solo lee ``rgn[0]`` y ``rgn[1]`` e ignora el resto, así
    que las bandas con huecos (ventanas Ideal/Posible partidas, zonas ±2°
    en subida y bajada del objeto) se quedaban solo con el primer tramo.
    Esta pool crea un item por par, actualiza su región y oculta los
    sobrantes.

    El ``pen`` de LinearRegionItem pinta los BORDES de la banda: sin él
    hereda el color por defecto de pyqtgraph y las marcas salían en un
    tono que no era el de su banda.
    """

    def __init__(self, plot_item, brush, pen, z_value: int) -> None:
        self._plot_item = plot_item
        self._brush = brush
        self._pen = pen
        self._z_value = z_value
        self._regions: list[pg.LinearRegionItem] = []

    def set_spans(self, spans: list[float]) -> None:
        """Pinta los tramos dados como pares planos (inicio, fin, ...).

        ``[0, 0]`` (lo que devuelve `_contiguous_spans` sin tramos) o una
        lista vacía significan «nada que pintar»: se oculta todo.
        """
        pairs = [
            (spans[index], spans[index + 1])
            for index in range(0, len(spans) - 1, 2)
        ]
        if not pairs or pairs == [(0, 0)]:
            pairs = []
        while len(self._regions) < len(pairs):
            region = pg.LinearRegionItem(
                brush=self._brush, pen=self._pen, movable=False
            )
            region.setZValue(self._z_value)
            self._plot_item.addItem(region)
            self._regions.append(region)
        for index, region in enumerate(self._regions):
            if index < len(pairs):
                region.setRegion(pairs[index])
                region.show()
            else:
                region.hide()

    def hide(self) -> None:
        """Oculta todos los tramos (estado vacío, sin datos)."""
        for region in self._regions:
            region.hide()


def _contiguous_spans(hours: list[float], mask: list[bool]) -> list[float]:
    """Pares (inicio, fin) de los tramos continuos en ``True`` de ``mask``.

    Un tramo de una sola muestra se ensancha al paso de muestreo para que la
    banda sea visible. Devuelve ``[0, 0]`` si no hay tramos (banda oculta).
    """
    spans: list[float] = []
    start: float | None = None
    step = _step_of(hours)
    for index, active in enumerate(mask + [False]):
        if active and start is None:
            start = hours[index]
        elif not active and start is not None:
            spans.extend((start, hours[index - 1] + step))
            start = None
    return spans if spans else [0, 0]


def _step_of(hours: list[float]) -> float:
    """Paso de muestreo entre horas consecutivas (0 si hay menos de dos)."""
    if len(hours) < 2:
        return 0.0
    # zip sin strict: hours y hours[1:] difieren en longitud por diseño.
    deltas = [b - a for a, b in zip(hours, hours[1:], strict=False) if b > a]
    return min(deltas) if deltas else 0.0
