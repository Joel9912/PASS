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

import math
import sqlite3

import pyqtgraph as pg
from PyQt6.QtCore import (
    QDate,
    QObject,
    QPointF,
    QRectF,
    QRunnable,
    Qt,
    QThreadPool,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from planners.moon_distance import (
    WINDOW_IDEAL,
    WINDOW_POSSIBLE,
    astronomical_night_spans,
    capture_summary_from_samples,
    format_hour_range,
    min_moon_distance,
    unwrap_hours,
)
from planners.planning_dates import planning_date
from planners.timefmt import format_hhmm
from planners.transit import NightCurve, NightInfo, night_info, phase_name
from planners.weather import (
    ClearOutside,
    Meteoblue,
    WeatherForecast,
    load_api_key,
    transparency,
)

from ..style import PALETTE

pg.setConfigOptions(antialias=True, background=PALETTE["bg"])

#: Colores de la curva de tránsito (coherentes con el resto del tema).
COLOR_ALTITUDE = PALETTE["accent"]        # azul: altitud del objeto
COLOR_MOON = PALETTE["gray"]                   # gris: altitud de la Luna
COLOR_LIMIT = PALETTE["error"]                 # rojo: línea de 30°
COLOR_IDEAL = (34, 197, 94, 55)           # verde: ventana ideal
COLOR_POSSIBLE = (245, 158, 11, 45)       # ámbar: ventana posible
COLOR_NIGHT = (255, 255, 255, 26)         # gris: noche astronómica

COLOR_DAY = PALETTE["gray"]                    # barra: día
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
    """Decimal de horas (0-24) a ``HH:MM`` local, envuelto en 24 h.

    Delega en el formateador único `planners.timefmt.format_hhmm` (A-34).
    """
    return format_hhmm(hour_decimal)


def iso_to_local_hours(
    iso_utc: str | None,
    longitude: float,
    utc_offset_hours: float | str | None = None,
) -> float | None:
    """Instante ISO en UTC a horas decimales locales (``None`` si falta).

    Acepta zona IANA según instante, desfase fijo o aproximación heredada
    por longitud; nunca consulta el huso del ordenador.
    """
    if not iso_utc:
        return None
    from planners.timezones import local_hours

    return local_hours(iso_utc, longitude, utc_offset_hours)


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
    # La ★ va envuelta en span: sin él toma el color del texto (azul) y
    # se perdía sobre la interfaz. Verde, igual que la banda y la leyenda
    # de Ideal; el ⚠ de Posible sí se distingue por su glifo ámbar.
    return (
        _window_text(summary, WINDOW_IDEAL, '<span style="color:#22c55e">★</span> Captura Ideal'),
        _window_text(summary, WINDOW_POSSIBLE, "⚠ Captura Posible"),
    )


def _window_text(summary: dict[str, dict], key: str, prefix: str) -> str:
    """Leyenda de una ventana del resumen: «prefijo: rangos (duración)».

    Sin tramos devuelve «prefijo: sin ventana» para no dejar la línea vacía.
    """
    entry = summary.get(key) or {}
    ranges = entry.get("ranges") or []
    if not ranges:
        return f"{prefix}: sin ventana"
    text = " y ".join(entry.get("display_ranges") or [format_hour_range(start, end) for start, end in ranges])
    return f"{prefix}: {text} ({format_duration(entry.get('hours', 0.0))})"


def _local_label(local_hours: float | None) -> str:
    """Horas locales a ``HH:MM`` (o ``--:--`` si no hay dato)."""
    return fmt_hhmm(local_hours) if local_hours is not None else "--:--"


# --------------------------------------------------------------------------- #
#             F O R M A T O   D E L   C A T Á L O G O   (s h a r e d)         #
# --------------------------------------------------------------------------- #
#: Códigos OpenNGC → etiqueta corta que ve el usuario. Compartida por Búsqueda
#: y Catálogo Personal: vive aquí para que ninguna subpestaña importe de otra.
TYPE_LABELS: dict[str, str] = {
    "G": "Galaxia", "GPair": "Galaxia", "GTrpl": "Galaxia", "GGroup": "Galaxia",
    "OCl": "Cúmulo abierto", "GCl": "Cúmulo globular", "*Ass": "Asociación",
    "Cl+N": "Cúmulo y nebulosa", "Cl*": "Cúmulo",
    "Neb": "Nebulosa", "PN": "Nebulosa planetaria", "HII": "Región HII",
    "EmN": "Nebulosa de emisión", "RfN": "Nebulosa de reflexión",
    "SNR": "Resto de supernova", "DrkN": "Nebulosa oscura",
    "*": "Estrella", "**": "Estrella doble", "Nova": "Nova",
}

#: Catálogo → etiqueta legible. Compartida por Búsqueda (opción del combo
#: «Catálogo») y Catálogo Personal (celda de la tabla), como TYPE_LABELS.
#: Estaba duplicada en ambos con valores ya divergidos («LDN (nebulosas
#: oscuras)»/«LDN», «Otros»/«Otro» — M-12 de la auditoría). Los canónicos
#: son los cortos: en la tabla del Personal el tipo («Nebulosa oscura»)
#: ya va en su propia columna.
CATALOG_LABELS: dict[str, str] = {
    "region": "Región",
    "messier": "Messier", "ngc": "NGC", "ic": "IC",
    "barnard": "Barnard", "caldwell": "Caldwell",
    "ldn": "LDN",
    "other": "Otros",
}


def format_ra(ra_hours: float | None) -> str:
    """RA decimal en horas a sexagesimal: ``00h42m44s`` (``--`` si falta)."""
    if ra_hours is None:
        return "--"
    total = round(ra_hours * 3600.0) % 86400
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}h{minutes:02d}m{seconds:02d}s"


def format_dec(dec_deg: float | None) -> str:
    """Declinación en grados a sexagesimal: ``+41°16′09″`` (``--`` si falta)."""
    if dec_deg is None:
        return "--"
    sign = "-" if dec_deg < 0 else "+"
    total = round(abs(dec_deg) * 3600.0)
    degrees, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{sign}{degrees:02d}°{minutes:02d}′{seconds:02d}″"


def format_size(major_arcmin: float | None, minor_arcmin: float | None) -> str:
    """Muestra ejes independientes en grados/minutos; una ausencia nunca se sustituye por el eje conocido."""
    if major_arcmin is None and minor_arcmin is None:
        return "--"
    degrees = max(value for value in (major_arcmin, minor_arcmin) if value is not None) >= 60

    def axis(value):
        """Conserva el hueco de cada eje sin perder la unidad del otro."""
        if value is None:
            return "—"
        return f"{value / 60.0:.2f}°" if degrees else f"{value:.0f}′"

    return f"{axis(major_arcmin)}×{axis(minor_arcmin)}"


def _type_label(type_code: str | None) -> str:
    """Código de tipo → etiqueta (``--`` si falta o se desconoce)."""
    if not type_code:
        return "--"
    return TYPE_LABELS.get(type_code, type_code)


#: Husos horarios ofrecidos en el selector (frente a UTC, horas).
UTC_OFFSETS: tuple[float, ...] = tuple(
    step * 0.25 for step in range(-48, 57)
)


# --------------------------------------------------------------------------- #
#                                T A B L A S                                   #
# --------------------------------------------------------------------------- #
def crear_tabla_filas(
    etiquetas: list[str],
    *,
    altura_min: int,
    alto_fila: int | None = None,
    stretch_ultima: bool = True,
    word_wrap: bool = True,
) -> QTableWidget:
    """Tabla de solo lectura con selección de fila entera (A-16).

    El patrón que las cuatro subpestañas del Planificador repetían: filas
    enteras seleccionables de una en una, sin edición, header sin números
    de fila y columnas a ancho de contenido.

    - ``alto_fila``: alto de fila por defecto (solo donde la vista lo pide).
    - ``stretch_ultima=False``: en Búsqueda el sobrante lo reparte
      ``_spread_surplus`` a partir de los anchos de contenido.
    """
    # Ojo: QTableWidget(filas, 0) + setHorizontalHeaderLabels NO crea
    # columnas (solo etiqueta las existentes); hay que pasarlas aquí.
    tabla = QTableWidget(0, len(etiquetas))
    tabla.setHorizontalHeaderLabels(etiquetas)
    tabla.verticalHeader().setVisible(False)
    if alto_fila is not None:
        tabla.verticalHeader().setDefaultSectionSize(alto_fila)
    tabla.setAlternatingRowColors(True)
    tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tabla.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tabla.setWordWrap(word_wrap)
    tabla.setMinimumHeight(altura_min)
    header = tabla.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setStretchLastSection(stretch_ultima)
    return tabla


def fila_seleccionada(tabla: QTableWidget, filas: list) -> dict | None:
    """Dict de la fila seleccionada en ``tabla``; ``None`` si no la hay (A-16).

    ``filas`` es la lista que alimenta la tabla (``_rows``, ``_plan``…).
    El índice fuera de rango se descarta a mano (defensa contra una
    selección huérfana tras recargar la tabla).
    """
    seleccion = tabla.selectionModel()
    indices = seleccion.selectedRows() if seleccion else []
    if not indices:
        return None
    indice = indices[0].row()
    return filas[indice] if 0 <= indice < len(filas) else None


class LocationBar(QFrame):
    """Selector de ubicación de las subpestañas del Planificador.

    Un único control para latitud, longitud y desfase horario: así Búsqueda
    (efemérides, curva, clima) y Planificación (curva, ranking) no pueden
    divergir. Emite ``location_changed(lat, lon, utc_offset|None)``.

    Vive en la **tercera fila de la izquierda de Búsqueda** (a la izquierda
    de las condiciones meteorológicas), compactado en tres filas para caber
    en la columna izquierda; el resto de subpestañas lo consumen por señal.

    Transmite zona IANA o desfase fijo. La aproximación heredada por longitud
    queda explícitamente rotulada y no se presenta como zona legal.
    """

    location_changed = pyqtSignal(float, float, object)  # lat, lon, offset|None

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta las tres filas (ubicación, lat/long, huso) y carga el estado inicial.

        Prioriza la ubicación guardada; sin ninguna se espera a que el
        usuario escriba lat/long (nunca se inventa el punto 0,0).
        """
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

        # Fila 2: latitud y longitud, con ◀/▶ como los botones de
        # Efemérides: un clic = 1°, botones grandes de 34 px. Las
        # flechitas nativas del spinbox eran minúsculas y el clic a
        # veces no acertaba. El valor sigue editable a mano (3 decimales);
        # el spinbox va sin botones nativos para que quepa en la columna.
        coords = QHBoxLayout()
        coords.setSpacing(6)

        self._latitude = QDoubleSpinBox()
        self._latitude.setRange(-90.0, 90.0)
        self._latitude.setDecimals(3)
        self._latitude.setSingleStep(1.0)
        self._latitude.setSuffix("°")
        self._latitude.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._latitude.setMinimumWidth(88)     # «-90,000°» sin botones
        self._latitude.valueChanged.connect(self._on_manual)

        coords.addWidget(QLabel("Lat"))
        coords.addLayout(self._stepper(self._latitude))

        self._longitude = QDoubleSpinBox()
        self._longitude.setRange(-180.0, 180.0)
        self._longitude.setDecimals(3)
        self._longitude.setSingleStep(1.0)
        self._longitude.setSuffix("°")
        self._longitude.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._longitude.setMinimumWidth(96)    # «-180,000°» sin botones
        self._longitude.valueChanged.connect(self._on_manual)

        coords.addWidget(QLabel("Lon"))
        coords.addLayout(self._stepper(self._longitude))
        layout.addLayout(coords)

        # Fila 3: huso horario.
        offset_row = QHBoxLayout()
        offset_row.setSpacing(6)
        offset_row.addWidget(QLabel("Huso"))
        self._offset = QComboBox()
        # «Auto» (None) se infiere de la longitud de la ubicación en
        # local_utc_offset (round(lon/15)); nunca la hora del sistema.
        self._offset.addItem("Aprox. longitud", None)
        for value in UTC_OFFSETS:
            self._offset.addItem(f"{value:+g} h", value)
        from planners.timezones import zone_names

        for key in zone_names():
            self._offset.addItem(key, key)
        # 170 px: «Solar (longitud)» + desplegable pedían 158; margen de sobra.
        self._offset.setMinimumWidth(170)
        self._offset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._offset.setMinimumContentsLength(14)
        self._offset.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._offset.setToolTip(
            "Zona IANA: ajusta según fecha, incluido verano, sin red.\n"
            "Número: desfase fijo manual. Aprox. longitud: heredada, no hora legal."
        )
        self._offset.currentIndexChanged.connect(self._emit)
        offset_row.addWidget(self._offset, 1)
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
        """Latitud visible, en grados (-90 … 90)."""
        return self._latitude.value()

    def longitude(self) -> float:
        """Longitud visible, en grados (-180 … 180)."""
        return self._longitude.value()

    def utc_offset_hours(self) -> float | str | None:
        """Desfase horario a usar en los cálculos.

        Texto: identificador IANA; número: fijo; None: aproximación heredada.
        Se transmite la zona, no el desfase de hoy, para calcular cada fecha.
        """
        return self._offset.currentData()

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
        """Vuelve a leer las ubicaciones guardadas (tras crear o editar una).

        La reselección es **por id**, no por dict completo (C-4): al editar
        una ubicación su dict cambia y `findData` no la encontraba, el combo
        caía a «(Manual)» y los campos conservaban lat/long vieja. En modo
        manual no se toca nada de lo escrito a mano.
        """
        actual = self._combo.currentData()
        actual_id = actual.get("id") if isinstance(actual, dict) else None
        self._loading = True
        self._reload_locations()
        indice = 0  # por defecto, Manual
        if actual_id is not None:
            for index in range(1, self._combo.count()):
                location = self._combo.itemData(index)
                if isinstance(location, dict) and location.get("id") == actual_id:
                    indice = index
                    break
        self._combo.setCurrentIndex(indice)
        self._loading = False
        if indice:
            # Ubicación guardada: aplicar (posiblemente editados) lat/long/
            # huso y avisar a quien escuche. Manual: sin cambios, sin aviso.
            self._on_combo(indice)

    # -- Internos -----------------------------------------------------------
    def _reload_locations(self, select_first: bool = False) -> None:
        """Vuelve a leer las ubicaciones de la base y repuebla el combo.

        Con señales bloqueadas para no emitir a mitad de recarga; sin
        ubicaciones guardadas «Manual» es la única opción.
        """
        self._combo.blockSignals(True)
        self._combo.clear()
        try:
            from equipment.localizations import list_locations

            locations = list_locations()
        except sqlite3.Error:  # sin tabla o base recién creada: solo manual
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
        """Entrada del combo elegida: vierte sus datos y emite la ubicación.

        En «Manual» (entrada sin dict) no hay datos que volcar y solo se
        emite el estado actual de los campos.
        """
        if self._loading:
            return
        location = self._combo.itemData(index)
        if location:
            self._loading = True
            self._latitude.setValue(float(location.get("latitude") or 0.0))
            self._longitude.setValue(float(location.get("longitude") or 0.0))
            offset = location.get("timezone_id") if location.get("timezone_id") is not None else location.get("utc_offset_hours")
            at = self._offset.findData(offset)
            if at < 0:
                self._offset.addItem(str(offset), offset)
                at = self._offset.count() - 1
            self._offset.setCurrentIndex(max(at, 0))
            self._loading = False
        self._emit()

    @staticmethod
    def _stepper(spin: QDoubleSpinBox) -> QHBoxLayout:
        """``◀ [valor] ▶`` alrededor de un spinbox: un clic, un paso.

        Igual que los botones ◀/▶ de Efemérides Sol y Luna (mismo ancho,
        sin repetición al mantener pulsado), pero moviendo el paso del
        propio spinbox. Así el paso vive en un solo sitio.
        """
        row = QHBoxLayout()
        row.setSpacing(2)

        back = QPushButton("◀")
        back.setFixedWidth(34)
        back.setToolTip("Un grado atrás")
        back.clicked.connect(lambda: spin.setValue(spin.value() - spin.singleStep()))
        row.addWidget(back)
        row.addWidget(spin)

        forward = QPushButton("▶")
        forward.setFixedWidth(34)
        forward.setToolTip("Un grado adelante")
        forward.clicked.connect(lambda: spin.setValue(spin.value() + spin.singleStep()))
        row.addWidget(forward)
        return row

    def _on_manual(self, _value: float) -> None:
        """Se editó lat/long a mano: el combo vuelve a «Manual» y se emite.

        Las señales del combo se bloquean para no reentrar en ``_on_combo``.
        """
        if self._loading:
            return
        self._combo.blockSignals(True)
        self._combo.setCurrentIndex(0)
        self._combo.blockSignals(False)
        self._emit()

    def _emit(self, *_args) -> None:
        """Emite ``location_changed(lat, lon, offset)`` salvo durante una recarga.

        ``_args`` absorbe los argumentos de las señales de Qt (valueChanged,
        currentIndexChanged) para poder conectar la misma función a cualquiera.
        """
        if self._loading:
            return
        self.location_changed.emit(
            self._latitude.value(), self._longitude.value(), self.utc_offset_hours()
        )


# --------------------------------------------------------------------------- #
#                            T A R J E T A S                                   #
# --------------------------------------------------------------------------- #
class MetricCard(QFrame):
    """Tarjeta «título + valor» para métricas compactas (clima, seeing, plan).

    El valor arranca en ``--``; :meth:`set_value` sabe atenuar lo no
    disponible y teñir el texto cuando la tarjeta trae color propio.
    """

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        title_color: str | None = None,
    ) -> None:
        """Tarjeta «título + valor»: valor inicial ``--`` y estilo ``#MetricCard``."""
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


def _metric_text(value: float | None, template: str) -> tuple[str, bool]:
    """``(texto, sin_datos)`` de una métrica opcional; nunca formatea ``None``."""
    if value is None:
        return "Sin datos", True
    return template.format(value=value), False


class _PronosticoSignal(QObject):
    """Señal por la que el hilo del pool devuelve el pronóstico (A-32)."""

    listo = pyqtSignal(int, object, object)  # (petición, clear outside, meteoblue)


class _PronosticoRunnable(QRunnable):
    """Trae Clear Outside y Meteoblue fuera del hilo de UI (A-32).

    Hoy los proveedores son mocks sin red, pero el camino queda listo para
    cuando se activen las API keys: la UI no se congela esperando.

    Las API keys **no se leen aquí**: este código corre en un hilo del pool
    y SQLite rechazaría la conexión creada en el hilo principal
    (``ProgrammingError``, la causa del crashe de v0.2-rc). Las lee
    ``WeatherCards.refresh`` en su hilo y las pasa por parámetro.
    """

    def __init__(
        self,
        senal: _PronosticoSignal,
        peticion: int,
        latitude: float,
        longitude: float,
        date_iso: str,
        clave_clear: str | None,
        clave_meteo: str | None,
    ) -> None:
        """Guarda la petición, las API keys ya leídas y la señal de vuelta."""
        super().__init__()
        self._senal = senal
        self._peticion = peticion
        self._latitude = latitude
        self._longitude = longitude
        self._date_iso = date_iso
        self._clave_clear = clave_clear
        self._clave_meteo = clave_meteo

    def run(self) -> None:
        """Ejecuta los dos pronósticos y emite el resultado (hilo del pool).

        Ninguna excepción escapa: un error aquí mataría el worker sin
        avisar y las tarjetas se quedarían colgadas; en su lugar el
        pronóstico degrada a ``available=False`` con el motivo.
        """
        try:
            clear = ClearOutside().forecast(
                self._latitude, self._longitude, self._date_iso,
                api_key=self._clave_clear,
            )
            meteo = Meteoblue().forecast(
                self._latitude, self._longitude, self._date_iso,
                api_key=self._clave_meteo,
            )
        except Exception as exc:  # el worker nunca muere callado: el motivo
            # viaja en la nota y las tarjetas se pintan como "sin datos".
            nota = f"Error al consultar el clima: {exc}"
            vacio = dict(date_iso=self._date_iso, available=False, note=nota)
            clear = WeatherForecast(provider="clear_outside", **vacio)
            meteo = WeatherForecast(provider="meteoblue", **vacio)
        self._senal.listo.emit(self._peticion, clear, meteo)


class WeatherCards(QWidget):
    """Las 6 tarjetas de clima/seeing (títulos y colores del original).

    Combina Clear Outside (clima) y Meteoblue (seeing). Sin API key los
    proveedores devuelven ``available=False`` y aquí se muestra "Sin datos".
    """

    #: (título, fuente, color del valor, color del título)
    #: Títulos cortos: en una tarjeta estrecha las frases largas se cortaban.
    #: Cada título con su color para distinguir las tarjetas de un vistazo.
    CARDS = (
        ("Seeing", "seeing", PALETTE["ok"], PALETTE["ok"]),          # verde
        ("Nubosidad", "cloud", PALETTE["accentLight"], PALETTE["accentLight"]),  # azul
        ("Humedad", "humidity", PALETTE["accentLight"], "#22d3ee"),  # cian
        ("Rocío", "dew", PALETTE["warn"], PALETTE["warn"]),          # ámbar
        ("Viento", "wind", PALETTE["accentLight"], "#a78bfa"),       # violeta
        ("Transparencia", "transparency", PALETTE["ok"], "#2dd4bf"), # turquesa
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        """Crea las 6 tarjetas de ``CARDS`` y la etiqueta de nota (oculta al inicio)."""
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

        # El pronóstico vuelve por señal desde el pool (A-32); el contador
        # invalida los resultados de peticiones anteriores.
        self._peticion = 0
        self._senal = _PronosticoSignal()
        self._senal.listo.connect(self._rellenar)

    def refresh(self, latitude: float, longitude: float, date_iso: str) -> None:
        """Rellena las tarjetas para ``date_iso`` en la ubicación dada (A-32).

        Asíncrono: la llamada a los proveedores va a un hilo del pool
        global y el resultado vuelve por señal a pintar en el hilo de UI.
        Si antes de que termine llega una petición más nueva, el resultado
        viejo se descarta (manda la última).

        Las API keys se leen **aquí, en el hilo principal**, y viajan al
        worker por parámetro: el hilo de trabajo no toca la BD en ninguna
        parte del programa (invariante del Apilador, A-03/A-32).
        """
        claves = (
            load_api_key(ClearOutside.settings_key),
            load_api_key(Meteoblue.settings_key),
        )
        self._peticion += 1
        QThreadPool.globalInstance().start(
            _PronosticoRunnable(
                self._senal, self._peticion, latitude, longitude, date_iso,
                *claves,
            )
        )

    def _rellenar(
        self, peticion: int, clear: WeatherForecast, meteo: WeatherForecast
    ) -> None:
        """Pinta las tarjetas con el pronóstico ya traído (hilo de UI)."""
        if peticion != self._peticion:
            return  # resultado de una petición antigua: la más nueva manda

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
            else (transparency(clouds), False),
        }
        colors = {key: color for _title, key, color, _tc in self.CARDS}
        # La transparencia cambia de color con su cualitativa.
        if not values["transparency"][1]:
            colors["transparency"] = {
                "Excelente": PALETTE["ok"],
                "Buena": PALETTE["ok"],
                "Regular": PALETTE["warn"],
                "Mala": PALETTE["error"],
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
        """Disco cuadrado de ``size`` px con fase inicial al 50 % creciente."""
        super().__init__(parent)
        self._illumination = 0.5
        self._waxing = True
        self.setFixedSize(size, size)

    def set_phase(self, illumination: float, waxing: bool) -> None:
        """Fija la fase (iluminación recortada a 0-1) y repinta."""
        self._illumination = max(0.0, min(1.0, float(illumination)))
        self._waxing = bool(waxing)
        self.update()

    def paintEvent(self, event) -> None:
        """Pinta fondo, porción iluminada (:func:`_lit_path`) y borde."""
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


#: Altura fija de la barra (px): 24 de franja de color + 20 para las marcas
#: y las horas de abajo. Petición del usuario: la barra **no crece** ni con
#: los datos ni con el sobrante del cuadro — ese aire se lo llevan los
#: rótulos de «Puesta de Sol» y «Noche astronómica».
DAY_NIGHT_BAR_HEIGHT = 44

#: Margen del eje dinámico: 1 h antes de la puesta y 1 h después de la
#: salida, el mismo criterio que la Curva de Tránsito.
BAR_RANGE_MARGIN_HOURS = 1.0

#: Pasos de las marcas de hora; se usa el primero que quepa en el ancho.
TICK_STEPS_HOURS = (2, 3, 4, 6)
#: Ancho mínimo (px) que se reserva a cada etiqueta de hora.
TICK_LABEL_WIDTH = 46.0


class DayNightBar(QWidget):
    """Barra de día, crepúsculo y noche sobre el rango puesta−1 h … salida+1 h.

    El eje es **dinámico**, igual que la Curva de Tránsito: empieza 1 h antes
    de la puesta del Sol y termina 1 h después de la salida, en horas locales
    **desenvueltas** para poder cruzar la medianoche. Sin puesta/salida no
    hay rango y se pinta el día completo, de 00 h a 24 h.

    Los cinco hitos (puesta, ocaso, amanecer, salida) vienen ya convertidos a
    hora local decimal; esta clase decide el rango, clasifica cada píxel y
    pinta. La altura es **fija** (44 px, ver ``DAY_NIGHT_BAR_HEIGHT``).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Barra de 44 px, con marcas y rango vacíos hasta ``set_marks``."""
        super().__init__(parent)
        # Fija: no se estira con el sobrante del panel (petición del usuario).
        self.setFixedHeight(DAY_NIGHT_BAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._marks: dict[str, float | None] = {
            "sunset": None, "dusk": None, "dawn": None, "sunrise": None,
        }
        #: (inicio, fin) en horas locales desenvueltas; None → día completo.
        self._range: tuple[float, float] | None = None
        self._formatter = None

    def set_marks(
        self,
        sunset: float | None,
        dusk: float | None,
        dawn: float | None,
        sunrise: float | None,
        formatter=None,
    ) -> None:
        """Guarda los 4 hitos (hora local) y recalcula el rango visible.

        Rango = puesta - 1 h … salida + 1 h (si la salida es al día
        siguiente se desenvuelve); sin puesta/salida no hay rango y la
        barra pinta el día completo, de 00 h a 24 h.
        """
        self._marks = {"sunset": sunset, "dusk": dusk, "dawn": dawn, "sunrise": sunrise}
        self._formatter = formatter
        # Eje dinámico: de 1 h antes de la puesta a 1 h después de la salida.
        if sunset is not None and sunrise is not None:
            start = sunset - BAR_RANGE_MARGIN_HOURS
            end = sunrise + BAR_RANGE_MARGIN_HOURS
            if end <= start:
                end += 24.0            # la salida es a la mañana siguiente
            self._range = (start, end)
        else:
            self._range = None
        self.update()

    def hour_range(self) -> tuple[float, float]:
        """Rango visible en horas locales desenvueltas (0-24 sin datos)."""
        return self._range if self._range is not None else (0.0, 24.0)

    def tick_hours(self, width: float | None = None) -> list[float]:
        """Horas redondas dentro del rango, con el paso que quepa en ``width``.

        Empieza a 2 h (como la Curva de Tránsito: «17:00», «19:00»…) y sube a
        3, 4 o 6 h si las etiquetas no caben. Las etiquetas repetidas se
        descartan (p. ej. los dos «00:00» de los extremos de un día completo).
        """
        if width is None:
            width = float(self.width()) or 1.0
        start, end = self.hour_range()
        px_per_hour = width / max(end - start, 1e-9)
        step = TICK_STEPS_HOURS[-1]
        for candidate in TICK_STEPS_HOURS:
            if candidate * px_per_hour >= TICK_LABEL_WIDTH:
                step = candidate
                break

        ticks: list[float] = []
        seen: set[str] = set()
        for hour in range(math.ceil(start), math.floor(end) + 1):
            if hour % step:
                continue
            label = self._formatter(hour) if self._formatter else fmt_hhmm(hour % 24)
            if label in seen:
                continue
            seen.add(label)
            ticks.append(float(hour))
        return ticks

    @staticmethod
    def _in_interval(hour: float, start: float, end: float) -> bool:
        """¿``hour`` dentro de [start, end)? Soporta intervalo que cruza 0."""
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    def _kind(self, hour: float) -> str:
        """Franja de esa hora: «night», «twilight», «day» o «unknown».

        La noche prefiere ocaso→amanecer astronómicos (si existen) y si no
        usa puesta→salida; «unknown» cuando faltan las marcas necesarias.
        """
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

    def paintEvent(self, event) -> None:
        """Pinta un píxel por hora del rango, las marcas de hora y los 4 hitos.

        Un hito fuera del rango no se pinta; la salida del día siguiente
        se desenvuelve +24 h para poder situarla dentro. Los colores se rellenan
        por tramos continuos para evitar costuras de antialias con DPI fraccional.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Altura: la disponible, con 20 px reservados abajo para las marcas
        # y las horas. Con la altura fija de 44 px da 24 px de franja.
        rect = QRectF(0, 4, self.width(), max(14, self.height() - 20))
        painter.setPen(Qt.PenStyle.NoPen)

        # Eje dinámico: cada píxel es una hora del rango (desenvuelta, para
        # cruzar la medianoche) y se clasifica ya envuelta en 24 h.
        start, end = self.hour_range()
        span = end - start
        width = max(rect.width(), 1)

        colors = {"day": COLOR_DAY, "twilight": COLOR_TWILIGHT, "night": COLOR_NIGHT_BAR, "unknown": PALETTE["surface"]}
        run_start, previous = 0, None
        for x in range(int(rect.width()) + 1):
            hour = start + (x + 0.5) / width * span
            kind = self._kind(hour if self._formatter else hour % 24.0) if x < int(rect.width()) else None
            if previous is not None and kind != previous:
                painter.fillRect(QRectF(rect.left() + run_start, rect.top(), x - run_start, rect.height()), QColor(colors[previous]))
                run_start = x
            previous = kind

        painter.setPen(QPen(QColor(PALETTE["border"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        # Marcas de hora dentro del rango (HH:MM cada 2 h, como la curva)
        painter.setPen(QColor(PALETTE["textDim"]))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        for hour in self.tick_hours(rect.width()):
            x = rect.left() + (hour - start) / span * rect.width()
            painter.drawLine(QPointF(x, rect.bottom()), QPointF(x, rect.bottom() + 2))
            # La etiqueta no se sale del widget en los extremos del rango.
            label_width = TICK_LABEL_WIDTH
            left = min(max(x - label_width / 2, 0.0), max(self.width() - label_width, 0.0))
            painter.drawText(
                QRectF(left, rect.bottom() + 3, label_width, 13),
                Qt.AlignmentFlag.AlignCenter,
                self._formatter(hour) if self._formatter else fmt_hhmm(hour % 24),
            )

        # Hitos de la noche: si caen fuera del rango, no se pintan
        for key, color in (
            ("sunset", "#f59e0b"), ("dusk", "#818cf8"),
            ("dawn", "#818cf8"), ("sunrise", "#f59e0b"),
        ):
            value = self._marks.get(key)
            if value is None:
                continue
            if not start <= value <= end:
                if not start <= value + 24.0 <= end:
                    continue
                value += 24.0        # la salida es a la mañana siguiente
            x = rect.left() + (value - start) / span * rect.width()
            painter.setPen(QPen(QColor(color), 1.6))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        painter.end()


# --------------------------------------------------------------------------- #
#                           E F E M É R I D E S                                #
# --------------------------------------------------------------------------- #
class EphemerisPanel(QFrame):
    """Panel "Efemérides Sol y Luna": fecha, fase, barra día/noche y horarios.

    Emite ``date_changed(date_iso)`` para que quien lo usa recalcule su curva
    de tránsito. El lugar (lat/long) lo aporta quien llama a :meth:`refresh`.

    Su fecha es la de Búsqueda: independiente de la de Planificación a
    propósito (A-33), cada pantalla se ajusta por su cuenta.
    """

    date_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta fecha (◀/▶ y «Hoy»), fase lunar, barra y rótulos de horas."""
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
        self._clock_label = QLabel("")
        self._clock_label.setObjectName("HintLabel")
        self._clock_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._clock_label.setAccessibleName("Desfase UTC de esta noche")
        moon_row.addWidget(self._clock_label)
        # Reparto del aire del cuadro: 1:3:3 entre la Luna, «Puesta de Sol»
        # y «Noche astronómica» (la Luna su par de píxeles de siempre y el
        # resto a los dos rótulos de abajo, que es lo que pidió el usuario).
        layout.addLayout(moon_row, 1)

        # --- Puesta de Sol y noche astronómica (rótulo renombrado por
        # petición del usuario: antes decía «LUZ DEL DÍA Y NOCHE ASTRONÓMICA»)
        day_label = QLabel("PUESTA DE SOL Y NOCHE ASTRONÓMICA")
        day_label.setObjectName("MetricTitle")
        layout.addWidget(day_label)

        self._bar = DayNightBar()
        # Sin stretch: la barra es de altura fija (44 px) y no crece ni con
        # los datos ni con el sobrante del cuadro; el aire se lo llevan los
        # dos rótulos de abajo.
        layout.addWidget(self._bar)

        # --- Horas (los valores van en color, como en el original)
        self._sunset_label = QLabel("Puesta de Sol: --:-- – --:--")
        self._sunset_label.setObjectName("HintLabel")
        # Centrado vertical: si el stretch le da aire, el texto no se
        # queda pegado arriba.
        self._sunset_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._sunset_label, 3)

        self._night_label = QLabel("Noche astronómica: --:-- – --:--")
        self._night_label.setObjectName("HintLabel")
        self._night_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._night_label, 3)

        # Estado actual (para poder refrescar tras mover la ubicación)
        self._latitude = 0.0
        self._longitude = 0.0
        self._utc_offset_hours: float | str | None = None

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
        utc_offset_hours: float | str | None = None,
    ) -> None:
        """Recalcula todo el panel para ``date_iso`` y la ubicación dada.

        ``utc_offset_hours`` es el desfase horario guardado de la ubicación
        (``None`` → se infiere el huso de la longitud).
        """
        self._latitude = latitude
        self._longitude = longitude
        self._utc_offset_hours = utc_offset_hours
        self.set_date(date_iso)

        try:
            planning_date(date_iso)
        except ValueError as exc:
            self.show_invalid_date(str(exc))
            return
        try:
            info: NightInfo = night_info(
                latitude, longitude, date_iso, utc_offset_hours=utc_offset_hours
            )
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.show_unavailable(str(exc))
            return
        self._moon_icon.show()
        self._date.setToolTip("")
        self._date.setAccessibleDescription("")
        illumination = info.moon_illumination

        self._moon_icon.set_phase(illumination, info.waxing)
        self._phase_label.setText(phase_name(illumination, info.waxing))
        self._illum_label.setText(
            f"{illumination * 100:.0f} % iluminada · Edad {info.moon_age_days:.1f} d"
        )

        from planners.timezones import clock_label, rules_label

        moments = [value for value in (info.sunset, info.astronomical_dusk, info.astronomical_dawn, info.sunrise) if value]
        if not moments:
            moments = [date_iso + "T12:00:00"]
        if isinstance(utc_offset_hours, str):
            offsets = list(dict.fromkeys(clock_label(value, longitude, utc_offset_hours).split(" ", 1)[1] for value in moments))
        else:
            from planners.timezones import local_moment

            offset = local_moment(moments[0], longitude, utc_offset_hours).strftime("%z")
            offsets = [f"UTC{offset[:3]}:{offset[3:5]}"]
        self._clock_label.setText(("≈ " if utc_offset_hours is None else "") + "\n→ ".join(offsets))
        self._clock_label.setToolTip(
            (str(utc_offset_hours) + "; " + rules_label()) if isinstance(utc_offset_hours, str)
            else ("Aproximación heredada por longitud, no zona legal." if utc_offset_hours is None else "Desfase fijo manual, sin ajuste estacional.")
        )

        def _local(iso: str | None) -> float | None:
            """ISO UTC → horas locales con la ubicación y el desfase vigentes."""
            return iso_to_local_hours(iso, longitude, utc_offset_hours)

        def _label(iso: str | None) -> str:
            """Reloj corto: el desfase se indica una sola vez junto a la información lunar."""
            return _local_label(_local(iso))

        if isinstance(utc_offset_hours, str):
            from datetime import datetime, timedelta

            from planners.timezones import clock_label, local_boundary, utc_moment

            start = local_boundary(datetime.fromisoformat(date_iso).replace(hour=16), utc_offset_hours)

            def _axis(iso):
                """Sitúa hitos por tiempo real transcurrido, sin saltos del reloj civil."""
                return 16 + (utc_moment(iso) - start).total_seconds() / 3600 if iso else None

            self._bar.set_marks(
                *map(_axis, (info.sunset, info.astronomical_dusk, info.astronomical_dawn, info.sunrise)),
                formatter=lambda hour: clock_label(start + timedelta(hours=hour - 16), longitude, utc_offset_hours).split(" ", 1)[0],
            )
        else:
            self._bar.set_marks(_local(info.sunset), _local(info.astronomical_dusk), _local(info.astronomical_dawn), _local(info.sunrise))

        # Como el original: puesta → salida en naranja.
        self._sunset_label.setText(
            "Puesta de Sol: "
            f'<span style="color:#f59e0b">{_label(info.sunset)} – '
            f"{_label(info.sunrise)}</span>"
        )

        dusk = _local(info.astronomical_dusk)
        dawn = _local(info.astronomical_dawn)
        if dusk is None or dawn is None:
            self._night_label.setText("Noche astronómica: sin noche ese día")
        else:
            # Y la noche astronómica en azul.
            self._night_label.setText(
                "Noche astronómica: "
                f'<span style="color:#60a5fa">{_label(info.astronomical_dusk)} – '
                f"{_label(info.astronomical_dawn)}</span>"
            )

    def show_invalid_date(self, message: str) -> None:
        """Retira resultados antiguos sin corregir la fecha elegida ni dibujar una fase lunar ficticia."""
        self._clear_results(message, "Fecha no admitida", "Planificación: 1950–2100")

    def show_unavailable(self, message: str) -> None:
        """Informa de un recurso/cálculo no disponible sin atribuir su fallo a una fecha válida."""
        self._clear_results(message, "Efemérides no disponibles", "Sin cálculo astronómico")

    def _clear_results(self, message: str, title: str, detail: str) -> None:
        """Limpia todas las magnitudes derivadas y conserva el motivo íntegro accesible, sin cambiar fecha o modelo."""
        self._moon_icon.hide()
        self._phase_label.setText(title)
        self._illum_label.setText("Sin cálculo")
        self._clock_label.clear()
        self._bar.set_marks(None, None, None, None)
        self._sunset_label.setText("Puesta de Sol: —")
        self._night_label.setText(detail)
        self._date.setToolTip(message)
        self._date.setAccessibleDescription(message)

    def current_date_iso(self) -> str:
        """Fecha visible como ``yyyy-MM-dd``."""
        return self._date.date().toString("yyyy-MM-dd")

    # -- Señales ------------------------------------------------------------
    def _emit_date(self, _date: QDate) -> None:
        """Adelanta la fecha del editor como señal ``date_changed`` al exterior."""
        self.date_changed.emit(self.current_date_iso())

    def _step_day(self, days: int) -> None:
        """Mueve la fecha±1 día; ``dateChanged`` se encarga de emitir."""
        self._date.setDate(self._date.date().addDays(days))

    def _go_today(self) -> None:
        """Vuelve a hoy.

        Si la fecha cambia, ``dateChanged`` → ``_emit_date`` ya emite:
        emitir a mano además (como se hacía) disparaba ``refresh()`` dos
        veces. Si ya estamos en hoy, no cambia nada y no se emite.
        """
        hoy = QDate.currentDate()
        if self._date.date() != hoy:
            self._date.setDate(hoy)


# --------------------------------------------------------------------------- #
#                         C U R V A   D E   T R Á N S I T O                    #
# --------------------------------------------------------------------------- #
class TransitCurve(QWidget):
    """Curva de tránsito con PyQtGraph: altitud del objeto y de la Luna.

    Un solo eje (izquierdo, 0-90°) para dos curvas: la **altitud del
    objeto** (azul) y la de la **Luna** (gris) — esta última muestra a
    qué hora sale y se oculta la Luna y qué altura alcanza. Debajo se
    pintan las bandas de noche astronómica y las ventanas de captura
    Ideal/Possible. La separación objeto-Luna se lee como **texto** en el
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
        """Monta cabecera, gráfico y bandas/curvas en estado vacío (:meth:`clear`)."""
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

        # Rangos de Captura Ideal / Posible. La línea se RESERVA desde el
        # principio (texto en blanco): si el rótulo solo apareciera con
        # datos, su mínimo crecería al seleccionar un objeto (+21 px
        # medidos), la rejilla reequilibraría sus filas y el cuadro de
        # Efemérides se hincharía — los dos rótulos de abajo cambiaban de
        # tamaño al llegar los datos (petición del usuario: los tamaños
        # tienen que estar puestos antes).
        self._windows_label = QLabel(" ")
        self._windows_label.setObjectName("CurveSubtitle")
        self._windows_label.setWordWrap(True)
        header.addWidget(self._windows_label)

        self._legend = QLabel(self._legend_text(full=False))
        self._legend.setObjectName("CurveLegend")
        header.addWidget(self._legend)
        self._accuracy_label = QLabel(" ")
        self._accuracy_label.setObjectName("HintLabel")
        self._accuracy_label.setMinimumHeight(self.fontMetrics().height())
        self._accuracy_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                                     | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self._accuracy_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        header.addWidget(self._accuracy_label)

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
        límite de 30°, curva de la Luna y las dos ventanas de captura.
        La separación y los rangos horarios viven en el subtítulo.
        """
        alt = f'<span style="color:{COLOR_ALTITUDE}">━━</span> Altitud'
        if not full:
            return alt
        return (
            f'{alt} &nbsp; '
            f'<span style="color:{COLOR_LIMIT}">- -</span> 30° &nbsp; '
            f'<span style="color:{COLOR_MOON}">━━</span> Luna &nbsp; '
            f'<span style="color:#22c55e">■</span> Ideal &nbsp; '
            f'<span style="color:#f59e0b">■</span> Posible'
        )

    # -- Formato del eje ----------------------------------------------------
    def _tick_strings(self, values, scale, spacing) -> list[str]:
        """Etiquetas del eje inferior en ``HH:MM`` (horas desenvueltas)."""
        curve = getattr(self, "_clock_curve", None)
        return [curve.axis_label(value) if curve is not None else fmt_hhmm(value) for value in values]

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
        self._clock_curve = None
        self._plot.getPlotItem().getAxis("bottom").picture = None
        self._subtitle.setText(message)
        # La línea de ventanas se reserva con texto en blanco; NO se oculta
        # (ocultarla cambiaba el mínimo del panel al llegar los datos y
        # refluía la fila entera: ver __init__).
        self._windows_label.setText(" ")
        self._windows_label.show()
        self._legend.setText(self._legend_text(full=False))
        self._accuracy_label.setText(" ")
        self._accuracy_label.setToolTip("")
        self._accuracy_label.setWhatsThis("")
        self._accuracy_label.setAccessibleDescription("")
        self._altitude_curve.setData([], [])
        self._moon_curve.setData([], [])
        for band in (
            self._night_band,
            self._possible_band,
            self._ideal_band,
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
        status = getattr(curve, "accuracy", None)
        summary = status.summary if status else "≈ Estado de precisión no informado"
        details = status.details if status else "Esta curva no informa de su modelo ni de la cobertura IERS; no implica precisión certificada."
        self._accuracy_label.setText(summary)
        self._accuracy_label.setToolTip(details)
        self._accuracy_label.setWhatsThis(details)
        self._accuracy_label.setAccessibleDescription(details)
        illumination_pct = curve.moon_illumination * 100.0
        min_dist = min_moon_distance(illumination_pct)

        self._clock_curve = curve if isinstance(getattr(curve, "clock", None), str) else None
        axis = self._plot.getPlotItem().getAxis("bottom")
        axis.picture = None
        axis.update()
        hours = curve.axis_hours if self._clock_curve is not None else unwrap_hours(curve.hours_local)
        summary = curve.capture_summary() if self._clock_curve is not None else capture_summary_from_samples(
            curve.altitudes, curve.moon_separations, curve.moon_altitudes, curve.astro_night,
            illumination_pct, hours, sun_altitudes=getattr(curve, "sun_altitudes", None),
        )

        # --- Cabecera (título fijo; el subtítulo resume el tránsito)
        transit = curve.hours_local[curve.transit_index]
        transit_label = curve.axis_label(hours[curve.transit_index]) if self._clock_curve is not None else fmt_hhmm(transit)
        peak = curve.altitudes[curve.transit_index]
        worst_sep = min(curve.moon_separations)
        self._subtitle.setText(
            f"Tránsito: {target_label} · Máx {peak:.1f}° · "
            f"Culm. {transit_label} · Luna {illumination_pct:.0f} % · "
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
        solares = getattr(curve, "sun_altitudes", None)
        self._night_band.set_spans(
            [h for tramo in astronomical_night_spans(hours, curve.astro_night, solares) for h in tramo]
            if solares is not None else _contiguous_spans(hours, curve.astro_night)
        )
        self._possible_band.set_spans(
            [h for tramo in summary.get(WINDOW_POSSIBLE, {}).get("ranges", []) for h in tramo]
        )
        self._ideal_band.set_spans(
            [h for tramo in summary.get(WINDOW_IDEAL, {}).get("ranges", []) for h in tramo]
        )
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
    que las bandas con huecos (ventanas Ideal/Posible partidas en subida
    y bajada del objeto) se quedaban solo con el primer tramo.
    Esta pool crea un item por par, actualiza su región y oculta los
    sobrantes.

    El ``pen`` de LinearRegionItem pinta los BORDES de la banda: sin él
    hereda el color por defecto de pyqtgraph y las marcas salían en un
    tono que no era el de su banda.
    """

    def __init__(self, plot_item, brush, pen, z_value: int) -> None:
        """Guarda el estilo de la banda; las regiones empiezan vacías (ver ``set_spans``)."""
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
