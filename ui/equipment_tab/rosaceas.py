"""Rosáceas de la ficha de Ubicación: los 3 discos de entrada y la salida.

Todo QPainter y dueño único de la paleta de CL (R2): los colores
muestreados de las capturas de referencia (barra 19,6–21,8 mag/arcsec²),
la correspondencia Bortle→SQM y el modelo de campana viven aquí porque
solo los consume este módulo.

Convención de mirada (como en las capturas de referencia): se mira HACIA
ARRIBA — N arriba, E a la izquierda y O a la derecha; el azimut crece de
N→E→S→O. Regla UX global (D-5): nada se persiste hasta «Guardar
ubicación»; los discos solo mantienen el estado en memoria.
"""

import math

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QActionGroup,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from equipment.models import DIRECTIONS, LP_SOURCES, OBSTRUCTION_ALTITUDES

#: Azimut de cada dirección (grados, desde N hacia E al mirar el cielo).
_AZIMUT: dict[str, int] = {
    "N": 0,
    "NE": 45,
    "E": 90,
    "SE": 135,
    "S": 180,
    "SO": 225,
    "O": 270,
    "NO": 315,
}
_AZ_POR_GRADOS = {grados: direccion for direccion, grados in _AZIMUT.items()}

#: Paleta de CL muestreada de la captura de referencia: de cielo
#: brillante (t = 0, mag 19,6) a cielo oscuro (t = 1, mag 21,8).
_PALETA: tuple[tuple[float, str], ...] = (
    (0.000, "#e171eb"),  # magenta
    (0.182, "#ee260d"),  # rojo
    (0.409, "#ff750d"),  # naranja
    (0.636, "#f4f40d"),  # amarillo
    (0.864, "#6e9d0d"),  # verde
    (1.000, "#1090bf"),  # azul
)
_PARADAS: tuple[tuple[float, QColor], ...] = tuple(
    (t, QColor(hex)) for t, hex in _PALETA
)

_NEGRO = QColor("#000000")      # fondo del disco sin datos (las capturas)
_ARO = QColor("#8f8f8f")        # aro del horizonte
_REJILLA = QColor("#565d66")    # rejilla punteada de altitud/azimut
_LETRAS = QColor("#e6edf3")     # letras de dirección y valores
_DIM = QColor("#8b949e")        # etiquetas secundarias (altitud, km)
_ROJO = QColor(226, 63, 55, 170)  # obstrucciones: rojo translúcido

#: Escala de caída con la distancia (km) de la campana: glow ∝ R/(R+km).
_R_KM = 10.0
#: Ancho del eje de color en mag/arcsec² (el de la captura: 19,6–21,8).
_ANCHO_ESCALA = 2.2
#: SQM de cielo medio cuando solo hay fuentes sin Bortle/SQM informado.
_SQM_BASE = 21.0
#: Campana por fuente: (intensidad, altura h en grados, anchura σ en
#: grados). h y σ dentro de los rangos delegados (h≈12-25°, σ≈30-45°):
#: cuanto más grande la fuente, domo más alto y más ancho en acimut.
_CAMPANAS: dict[str, tuple[float, float, float]] = {
    "pueblo": (1.0, 12.0, 30.0),
    "pueblo_grande": (2.0, 16.0, 35.0),
    "ciudad": (4.0, 20.0, 40.0),
    "gran_ciudad": (7.0, 25.0, 45.0),
}
#: Nombre corto para las etiquetas pequeñas del disco de entrada (el
#: nombre completo vive en ``LP_SOURCES`` y en el panel de edición).
_CORTAS: dict[str, str] = {
    "pueblo": "Pueblo",
    "pueblo_grande": "P. Grande",
    "ciudad": "Ciudad",
    "gran_ciudad": "G. Ciudad",
}
#: Descripciones delegadas en el plan: tooltips de las fuentes.
_TOOLTIPS_CL: dict[str, str] = {
    "pueblo": "Núcleo pequeño, domo estrecho y bajo que cae rápido.",
    "pueblo_grande": "Domo más ancho que ya marca su cuadrante.",
    "ciudad": "Domo amplio y brillante que domina su horizonte.",
    "gran_ciudad": "Domo muy amplio que levanta el brillo de medio cielo "
    "cercano al horizonte.",
}
#: Resolución del campo de color cacheado (px); se escala con suavizado.
_CAMPO_RES = 168
#: Margen del widget para las letras de dirección (fuera del aro).
_MARGEN_LETRAS = 22
#: Ancho reservado a la derecha del disco para la barra de mag/arcsec².
_ANCHO_BARRA = 84
#: Lo que ocupa la barra tras el borde del disco: hueco 32 + barra 12 +
#: hueco 4 + etiquetas 44; el conjunto se centra con este ancho total.
_DESPUES_DISCO = 92


def _sqm_de_bortle(bortle: int) -> float:
    """SQM aproximado de un nivel Bortle (22,0 en el 1 … 18,0 en el 9).

    Correspondecia lineal de referencia: el programa prefiere el SQM
    cenital si el usuario lo informa; el Bortle es el respaldo.
    """
    return 22.0 - 0.5 * (bortle - 1)


def _color_para(t: float) -> QColor:
    """Color de la paleta para ``t`` interpolando entre paradas.

    Args:
        t: 0 = cielo más brillante (magenta), 1 = más oscuro (azul); se
            recorta al rango.
    """
    t = min(1.0, max(0.0, t))
    for i in range(len(_PARADAS) - 1):
        t0, c0 = _PARADAS[i]
        t1, c1 = _PARADAS[i + 1]
        if t <= t1:
            if t1 == t0:
                return c1
            f = (t - t0) / (t1 - t0)
            return QColor(
                round(c0.red() + f * (c1.red() - c0.red())),
                round(c0.green() + f * (c1.green() - c0.green())),
                round(c0.blue() + f * (c1.blue() - c0.blue())),
            )
    return _PARADAS[-1][1]


def _punto(cx: float, cy: float, r: float, azimut: float) -> QPointF:
    """Punto del disco para un azimut (N arriba, E a la izquierda)."""
    rad = math.radians(azimut)
    return QPointF(cx - r * math.sin(rad), cy - r * math.cos(rad))


def _anillo(
    cx: float,
    cy: float,
    r_ext: float,
    r_int: float,
    az1: float,
    az2: float,
    muestras: int = 8,
) -> QPolygonF:
    """Polígono anular entre dos azimutes (para las obstrucciones)."""
    puntos = []
    for i in range(muestras + 1):
        puntos.append(_punto(cx, cy, r_ext, az1 + (az2 - az1) * i / muestras))
    for i in range(muestras + 1):
        puntos.append(_punto(cx, cy, r_int, az2 + (az1 - az2) * i / muestras))
    return QPolygonF(puntos)


def _r_altitud(r: float, grados: float) -> float:
    """Radio del anillo de ``grados`` de elevación (0° = borde, 90° = centro)."""
    return r * (90.0 - grados) / 90.0


def _direccion_en(cx: float, cy: float, r: float, pos: QPointF) -> str | None:
    """Dirección cuyo sector contiene el punto; el centro se ignora.

    Returns:
        La clave de ``DIRECTIONS`` o ``None`` si el clic fue en el centro
        (o demasiado lejos del disco).
    """
    dx = pos.x() - cx
    dy = pos.y() - cy
    dist = math.hypot(dx, dy)
    if dist > r * 1.15 or dist < r * 0.14:
        return None
    az = math.degrees(math.atan2(-dx, -dy)) % 360.0
    return _AZ_POR_GRADOS[round(az / 45.0) % 8 * 45]


def _grados_sitio(valor: dict) -> dict[str, int]:
    """Grados por dirección con las 8 claves; lo raro → 0° (defecto)."""
    origen = valor if isinstance(valor, dict) else {}
    salida: dict[str, int] = {}
    for direccion in DIRECTIONS:
        bruto = origen.get(direccion, 0)
        if not isinstance(bruto, int) or bruto not in OBSTRUCTION_ALTITUDES:
            salida[direccion] = 0
        else:
            salida[direccion] = bruto
    return salida


def _fuentes_de(valor: dict) -> list[tuple[float, float, float, float, float]]:
    """Fuentes útiles de ``lp`` como (intensidad, km, h, σ, azimut).

    Solo direcciones con fuente del catálogo y km > 0; lo raro se omite.
    """
    lista: list[tuple[float, float, float, float, float]] = []
    if not isinstance(valor, dict):
        return lista
    for direccion in DIRECTIONS:
        entrada = valor.get(direccion)
        if not isinstance(entrada, dict):
            continue
        clave = entrada.get("fuente")
        km = entrada.get("km")
        if clave not in _CAMPANAS or not isinstance(km, (int, float)) or km <= 0:
            continue
        intensidad, altura, sig = _CAMPANAS[clave]
        lista.append((intensidad, float(km), altura, sig, float(_AZIMUT[direccion])))
    return lista


def _km_texto(km: float) -> str:
    """Distancia en castellano (coma decimal): ``5 km``, ``2,5 km``."""
    return f"{km:g}".replace(".", ",") + " km"


def _pintar_letras(pintor: QPainter, cx: float, cy: float, r: float) -> None:
    """Pinta las 8 letras de dirección fuera del aro (N arriba y grande)."""
    for direccion, az in _AZIMUT.items():
        pos = _punto(cx, cy, r + _MARGEN_LETRAS - 10, az)
        fuente = QFont(pintor.font())
        es_cardinal = direccion in ("N", "E", "S", "O")
        fuente.setBold(es_cardinal)
        fuente.setPointSizeF(10.5 if direccion == "N" else 9.0 if es_cardinal else 8.5)
        pintor.setFont(fuente)
        pintor.setPen(_LETRAS)
        pintor.drawText(
            QRectF(pos.x() - 16, pos.y() - 9, 32, 18),
            Qt.AlignmentFlag.AlignCenter,
            direccion,
        )


class RosaDirecciones(QWidget):
    """Rosa de los vientos: solo orientación (letras, ticks, cenit).

    Es el primer disco de la rosácea y la única referencia de rumbo: los
    otros dos discos no llevan letras a propósito — comparten su
    orientación con esta rosa (N siempre arriba).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Tamaño fijo colectivo con el resto de discos de la rosácea."""
        super().__init__(parent)
        self.setMinimumSize(140, 140)

    def sizeHint(self) -> QSize:
        """Tamaño natural: mismo cuadrado que los discos de entrada."""
        return QSize(176, 176)

    def hasHeightForWidth(self) -> bool:
        """El ancho manda: la fila reparte todo el ancho entre los discos."""
        return True

    def heightForWidth(self, ancho: int) -> int:
        """Alto = ancho: disco cuadrado a tamaño de su celda."""
        return max(ancho, self.minimumHeight())

    def paintEvent(self, event) -> None:
        """Pinta el aro, los ticks de azimut, las letras y el cenit."""
        del event
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx = self.width() / 2
        cy = self.height() / 2
        r = min(self.width(), self.height()) / 2 - _MARGEN_LETRAS
        pintor.setPen(QPen(_ARO, 1.2))
        pintor.setBrush(_NEGRO)
        pintor.drawEllipse(QPointF(cx, cy), r, r)
        for az in range(0, 360, 15):
            largo = az % 45 == 0
            pintor.setPen(QPen(_LETRAS if largo else _REJILLA, 1.2 if largo else 1))
            pintor.drawLine(
                _punto(cx, cy, r - (8 if largo else 4), az),
                _punto(cx, cy, r, az),
            )
        _pintar_letras(pintor, cx, cy, r)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(_LETRAS)
        pintor.drawEllipse(QPointF(cx, cy), 2.5, 2.5)
        pintor.setPen(_DIM)
        fuente = QFont(pintor.font())
        fuente.setPointSizeF(7)
        pintor.setFont(fuente)
        pintor.drawText(
            QRectF(cx - 30, cy + 6, 60, 14),
            Qt.AlignmentFlag.AlignCenter,
            "cenit",
        )


class _DiscoBase(QWidget):
    """Base de los discos de entrada: círculo, sectores y clic a menú."""

    #: Cambia cuando el usuario altera un sector (para repintar la salida).
    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Prepara el disco apuntable con el ratón."""
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(140, 140)

    def sizeHint(self) -> QSize:
        """Tamaño natural: mismo cuadrado que la rosa de orientación."""
        return QSize(176, 176)

    def hasHeightForWidth(self) -> bool:
        """El ancho manda: la fila reparte todo el ancho entre los discos."""
        return True

    def heightForWidth(self, ancho: int) -> int:
        """Alto = ancho: disco cuadrado a tamaño de su celda."""
        return max(ancho, self.minimumHeight())

    def _geometria(self) -> tuple[float, float, float]:
        """Centro y radio del disco (margen para las letras de la rosa)."""
        return (
            self.width() / 2,
            self.height() / 2,
            min(self.width(), self.height()) / 2 - _MARGEN_LETRAS,
        )

    def paintEvent(self, event) -> None:
        """Fondo negro con aro, separadores de sector y contenido propio."""
        del event
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy, r = self._geometria()
        pintor.setPen(QPen(_ARO, 1.2))
        pintor.setBrush(_NEGRO)
        pintor.drawEllipse(QPointF(cx, cy), r, r)
        pintor.setPen(QPen(_REJILLA, 1))
        for az in range(0, 360, 45):
            pintor.drawLine(QPointF(cx, cy), _punto(cx, cy, r, az))
        self._pintar_contenido(pintor, cx, cy, r)

    def _pintar_contenido(self, pintor: QPainter, cx: float, cy: float, r: float) -> None:
        """Sobrescribe: pinta los valores del sector encima de la base."""
        raise NotImplementedError

    def mousePressEvent(self, event) -> None:
        """El clic en un sector abre su menú/panel (el centro se ignora)."""
        cx, cy, r = self._geometria()
        posicion = event.position()
        direccion = _direccion_en(cx, cy, r, posicion)
        if direccion is None:
            return
        self._abrir(direccion, posicion.toPoint())

    def _abrir(self, direccion: str, posicion) -> None:
        """Sobrescribe: abre el menú (obstrucciones) o panel (CL)."""
        raise NotImplementedError


class DiscoObstrucciones(_DiscoBase):
    """Disco de entrada de obstrucciones: clic → menú radio de grados.

    Cada sector guarda a cuántos grados llega lo obstruido en esa
    dirección (catálogo ``OBSTRUCTION_ALTITUDES``); el sector lo muestra
    con un área roja desde el borde hasta su altitud, igual que la salida.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Estado inicial: 0° en las 8 direcciones."""
        super().__init__(parent)
        self._grados: dict[str, int] = {d: 0 for d in DIRECTIONS}
        self.setToolTip(
            "Clic en un sector: altura hasta la que obstruye esa dirección."
        )

    # -- estado -----------------------------------------------------------

    def obstacles(self) -> dict[str, int]:
        """Grados por dirección (copia, siempre las 8 claves)."""
        return dict(self._grados)

    def set_obstacles(self, grados: dict) -> None:
        """Carga los grados del sitio (valores raros → 0°)."""
        self._grados = _grados_sitio(grados)
        self.update()

    # -- pintura y menú ---------------------------------------------------

    def _pintar_contenido(self, pintor: QPainter, cx: float, cy: float, r: float) -> None:
        """Área roja por sector y su valor (``45°`` o «—» si es 0°)."""
        fuente_base = QFont(pintor.font())
        fuente_base.setPointSizeF(8)
        for direccion, grados in self._grados.items():
            az = _AZIMUT[direccion]
            if grados > 0:
                pintor.setPen(QPen(QColor(150, 30, 25), 0.8))
                pintor.setBrush(_ROJO)
                pintor.drawPolygon(
                    _anillo(cx, cy, r, _r_altitud(r, grados), az - 22.5, az + 22.5)
                )
            pos = _punto(cx, cy, r * 0.62, az)
            pintor.setPen(_LETRAS)
            pintor.setFont(fuente_base)
            pintor.drawText(
                QRectF(pos.x() - 24, pos.y() - 9, 48, 18),
                Qt.AlignmentFlag.AlignCenter,
                f"{grados}°" if grados else "—",
            )

    def _abrir(self, direccion: str, posicion) -> None:
        """Menú radio con las 5 alturas para la dirección del clic."""
        menu = QMenu(self)
        cabecera = menu.addAction(f"Obstrucciones en {direccion}")
        cabecera.setEnabled(False)
        grupo = QActionGroup(menu)
        for grados, etiqueta in OBSTRUCTION_ALTITUDES.items():
            accion = menu.addAction(etiqueta)
            accion.setCheckable(True)
            accion.setChecked(self._grados[direccion] == grados)
            grupo.addAction(accion)
            accion.triggered.connect(
                lambda _=False, d=direccion, g=grados: self._fijar(d, g)
            )
        menu.exec(self.mapToGlobal(posicion))

    def _fijar(self, direccion: str, grados: int) -> None:
        """Aplica la altura elegida y avisa para repintar la salida."""
        self._grados[direccion] = grados
        self.update()
        self.changed.emit()


class _PanelLumen(QFrame):
    """Panel emergente de CL de una dirección: 4 fuentes + slider de km.

    Vivo en memoria (D-5): cada cambio emite ``cambio`` y el disco lo
    vuelca a su estado; solo «Guardar ubicación» persiste. El slider va
    de 0,5 a 100 km en pasos de 0,5.
    """

    #: El valor del panel cambió (fuente elegida o km movido).
    cambio = pyqtSignal()

    def __init__(
        self, direccion: str, valor: dict, parent: QWidget | None = None
    ) -> None:
        """Monta el panel con el estado actual de la dirección."""
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup)
        self.setObjectName("GroupFrame")
        fuente = valor.get("fuente")
        self._fuente: str | None = fuente if fuente in LP_SOURCES else None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(6)

        titulo = QLabel(f"Contaminación lumínica — {direccion}")
        titulo.setObjectName("PanelTitle")
        layout.addWidget(titulo)

        self._radios: dict[str | None, QRadioButton] = {}
        sin = QRadioButton("Sin fuente")
        sin.toggled.connect(lambda on, f=None: self._elegir(f, on))
        layout.addWidget(sin)
        self._radios[None] = sin
        for clave, etiqueta in LP_SOURCES.items():
            radio = QRadioButton(etiqueta)
            radio.setToolTip(_TOOLTIPS_CL[clave])
            radio.toggled.connect(lambda on, f=clave: self._elegir(f, on))
            layout.addWidget(radio)
            self._radios[clave] = radio

        km = valor.get("km")
        km = float(km) if isinstance(km, (int, float)) and km > 0 else 0.0
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Distancia"))
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(1, 200)  # 0,5–100 km en pasos de 0,5
        self._slider.setValue(round(km * 2) if km > 0 else 10)  # 5 km por defecto
        self._slider.setFixedWidth(170)
        self._slider.valueChanged.connect(self._mostrar_km)
        fila.addWidget(self._slider, 1)
        self._valor = QLabel()
        self._valor.setMinimumWidth(52)
        fila.addWidget(self._valor)
        layout.addLayout(fila)

        pista = QLabel("Nada se guarda hasta «Guardar ubicación».")
        pista.setObjectName("HintLabel")
        pista.setWordWrap(True)
        layout.addWidget(pista)

        # Al final: el estado inicial no debe emitir cambios (sin oyentes).
        self._radios[self._fuente].setChecked(True)
        self._slider.setEnabled(self._fuente is not None)
        self._mostrar_km()

    # -- estado -----------------------------------------------------------

    def fuente(self) -> str | None:
        """Clave de ``LP_SOURCES`` elegida o ``None`` (sin fuente)."""
        return self._fuente

    def km(self) -> float:
        """Distancia de la fuente en km (0,5–100)."""
        return self._slider.value() / 2

    def _elegir(self, fuente: str | None, activo: bool) -> None:
        """Fija la fuente al marcar su radio y habilita el slider."""
        if not activo:
            return
        self._fuente = fuente
        self._slider.setEnabled(fuente is not None)
        self.cambio.emit()

    def _mostrar_km(self, valor: int | None = None) -> None:
        """Actualiza la etiqueta de km y avisa de que el valor cambió."""
        del valor
        self._valor.setText(_km_texto(self.km()))
        self.cambio.emit()


class DiscoLumen(_DiscoBase):
    """Disco de entrada de CL: clic → panel con fuentes y slider de km.

    Cada dirección guarda una única fuente (catálogo ``LP_SOURCES``) con
    su distancia; el sector muestra el nombre corto y los km.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Estado inicial: sin fuente en las 8 direcciones."""
        super().__init__(parent)
        self._lp: dict[str, dict] = {d: {"fuente": None, "km": 0.0} for d in DIRECTIONS}
        self._panel: _PanelLumen | None = None
        self.setToolTip("Clic en un sector: fuente de CL y km de esa dirección.")

    # -- estado -----------------------------------------------------------

    def lp(self) -> dict[str, dict]:
        """CL por dirección (copia, siempre las 8 claves)."""
        return {d: dict(valor) for d, valor in self._lp.items()}

    def set_lp(self, fuentes: dict) -> None:
        """Carga la CL del sitio (valores raros → sin fuente)."""
        origen = fuentes if isinstance(fuentes, dict) else {}
        for direccion in DIRECTIONS:
            entrada = origen.get(direccion)
            if not isinstance(entrada, dict):
                self._lp[direccion] = {"fuente": None, "km": 0.0}
                continue
            clave = entrada.get("fuente")
            km = entrada.get("km")
            valido = (
                isinstance(clave, str)
                and clave in LP_SOURCES
                and isinstance(km, (int, float))
                and km > 0
            )
            if valido:
                self._lp[direccion] = {"fuente": clave, "km": float(km)}
            else:
                guardado = float(km) if isinstance(km, (int, float)) and km > 0 else 0.0
                self._lp[direccion] = {"fuente": None, "km": guardado}
        self.update()

    # -- pintura y panel --------------------------------------------------

    def _pintar_contenido(self, pintor: QPainter, cx: float, cy: float, r: float) -> None:
        """Nombre corto y km en cada sector («—» si no hay fuente)."""
        fuente_nombre = QFont(pintor.font())
        fuente_nombre.setPointSizeF(7.5)
        fuente_km = QFont(pintor.font())
        fuente_km.setPointSizeF(7)
        for direccion, valor in self._lp.items():
            az = _AZIMUT[direccion]
            pos = _punto(cx, cy, r * 0.56, az)
            clave = valor.get("fuente")
            pintor.setFont(fuente_nombre)
            pintor.setPen(_LETRAS if clave in LP_SOURCES else _DIM)
            nombre = _CORTAS.get(str(clave), "—")
            pintor.drawText(
                QRectF(pos.x() - 34, pos.y() - 15, 68, 15),
                Qt.AlignmentFlag.AlignCenter,
                nombre,
            )
            if clave in LP_SOURCES:
                pintor.setFont(fuente_km)
                pintor.setPen(_DIM)
                pintor.drawText(
                    QRectF(pos.x() - 34, pos.y() + 1, 68, 14),
                    Qt.AlignmentFlag.AlignCenter,
                    _km_texto(float(valor.get("km") or 0)),
                )

    def _abrir(self, direccion: str, posicion) -> None:
        """Panel con las 4 fuentes y el slider de km de la dirección."""
        if self._panel is not None:
            self._panel.close()
        panel = _PanelLumen(direccion, self._lp[direccion], self)
        panel.cambio.connect(lambda p=panel, d=direccion: self._aplicar(p, d))
        panel.adjustSize()
        destino = self.mapToGlobal(posicion + QPointF(8, 8).toPoint())
        pantalla = QApplication.screenAt(destino)
        if pantalla is not None:
            geo = pantalla.availableGeometry()
            destino = QPointF(
                min(max(geo.left(), destino.x()), geo.right() - panel.width()),
                min(max(geo.top(), destino.y()), geo.bottom() - panel.height()),
            ).toPoint()
        panel.move(destino)
        panel.show()
        self._panel = panel

    def _aplicar(self, panel: _PanelLumen, direccion: str) -> None:
        """Vuelca el panel al sector y avisa para repintar la salida."""
        self._lp[direccion] = {"fuente": panel.fuente(), "km": panel.km()}
        self.update()
        self.changed.emit()


class DiscoEsquematico(QWidget):
    """Salida: el sitio dibujado — rejilla, campo de CL y obstrucciones.

    Sin datos de cielo (Bortle/SQM/fuentes) el disco queda negro con su
    rejilla, como la captura de referencia; con ellos se pinta el campo
    de color con la paleta ligada a mag/arcsec² y su barra, y encima van
    las obstrucciones en rojo desde el borde hasta su altitud —ocultables
    con ``set_mostrar_obstaculos``, solo pintado—. Todo es presentación:
    los valores entran por ``set_datos``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Estado vacío (disco negro) y sin campo que cachear."""
        super().__init__(parent)
        self._bortle: int | None = None
        self._sqm: float | None = None
        self._obstacles: dict[str, int] = {d: 0 for d in DIRECTIONS}
        self._lp: dict[str, dict] = {d: {"fuente": None, "km": 0.0} for d in DIRECTIONS}
        self._fuentes: list[tuple[float, float, float, float, float]] = []
        self._campo: QImage | None = None
        # Preferencia de pantalla: ¿pintar las cuñas rojas? Solo eso.
        self._mostrar_obstaculos: bool = True
        self.setMinimumSize(320, 260)

    def sizeHint(self) -> QSize:
        """Tamaño natural: disco grande + banda de la barra de color."""
        return QSize(420, 340)

    def hasHeightForWidth(self) -> bool:
        """El ancho manda: el cuadro llena su celda sin hueco a los lados."""
        return True

    def heightForWidth(self, ancho: int) -> int:
        """Alto del conjunto disco + barra para un ancho dado.

        El presupuesto es ``ancho - 60``: sobra para el disco centrado
        (margen de letras incluido), la barra a su derecha y las etiquetas.
        """
        return max(ancho - 60, self.minimumHeight())

    def set_datos(
        self,
        bortle: int | None,
        sqm: float | None,
        obstacles: dict,
        lp: dict,
    ) -> None:
        """Fija los valores del sitio y reconstruye el campo si cambian.

        El campo de color depende solo de las fuentes (la fórmula da t en
        función del glow), así que Bortle/SQM solo obligan a repintar la
        barra: tipear en el SQM no vuelve a calcular el campo.
        """
        self._bortle = bortle if isinstance(bortle, int) and 1 <= bortle <= 9 else None
        self._sqm = float(sqm) if isinstance(sqm, (int, float)) and sqm > 0 else None
        self._obstacles = _grados_sitio(obstacles)
        self._lp = (
            {d: dict(v) for d, v in lp.items()}
            if isinstance(lp, dict)
            else {d: {"fuente": None, "km": 0.0} for d in DIRECTIONS}
        )
        fuentes = _fuentes_de(self._lp)
        if fuentes != self._fuentes:
            self._fuentes = fuentes
            self._campo = self._construye_campo(fuentes) if fuentes else None
        self.update()

    def set_mostrar_obstaculos(self, mostrar: bool) -> None:
        """Muestra/oculta las cuñas rojas (el interruptor «Mostrar obstáculos»).

        Es puro pintado: los grados siguen en el widget y en la ubicación,
        y el planificador no se entera de este interruptor.
        """
        self._mostrar_obstaculos = bool(mostrar)
        self.update()

    def _base_sqm(self) -> float | None:
        """SQM de fondo: cenital, si no el del Bortle; solo fuentes → medio."""
        if self._sqm is not None:
            return self._sqm
        if self._bortle is not None:
            return _sqm_de_bortle(self._bortle)
        if self._fuentes:
            return _SQM_BASE
        return None

    def _construye_campo(
        self, fuentes: list[tuple[float, float, float, float, float]]
    ) -> QImage:
        """Campo de color (168×168) con la paleta ligado a mag/arcsec².

        Por píxel: altitud y azimut del punto, suma de las campanas de
        cada fuente (``glow``) y ``t = 1 − glow / 2,2`` — es decir, el
        fondo es el valor del sitio y la luz solo sube de brillo. Los
        pixeles fuera del disco quedan transparentes; se escala con
        suavizado al pintar.
        """
        res = _CAMPO_RES
        mitad = res / 2
        img = QImage(res, res, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        for y in range(res):
            dy = (y + 0.5) - mitad
            for x in range(res):
                dx = (x + 0.5) - mitad
                dist = math.hypot(dx, dy)
                if dist > mitad:
                    continue
                alt = 90.0 * (1.0 - dist / mitad)
                az = math.degrees(math.atan2(-dx, -dy)) % 360.0
                glow = 0.0
                for intensidad, km, altura, sig, azf in fuentes:
                    delta = abs((az - azf + 180.0) % 360.0 - 180.0)
                    glow += (
                        intensidad
                        * (_R_KM / (_R_KM + km))
                        * math.exp(-alt / altura)
                        * math.exp(-(delta * delta) / (2.0 * sig * sig))
                    )
                img.setPixelColor(x, y, _color_para(1.0 - glow / _ANCHO_ESCALA))
        return img

    def paintEvent(self, event) -> None:
        """Pinta campo, rejilla, obstrucciones (si se muestran), letras y barra."""
        del event
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        base = self._base_sqm()
        hay_barra = base is not None
        cy = self.height() / 2
        ancho_disco = self.width() - (_ANCHO_BARRA if hay_barra else 0)
        r = min(ancho_disco, self.height()) / 2 - _MARGEN_LETRAS
        if hay_barra:
            # El conjunto (disco + barra + etiquetas) centrado en todo el
            # ancho, sin pisar el margen de las letras de dirección.
            cx = self.width() / 2 - _DESPUES_DISCO / 2
            r = max(
                20.0,
                min(r, cx - _MARGEN_LETRAS, self.width() - cx - _DESPUES_DISCO),
            )
        else:
            cx = self.width() / 2

        # Disco: negro sin datos, campo con fuentes, uniforme si solo hay cielo.
        if self._campo is not None:
            pintor.setPen(QPen(_ARO, 1.2))
            pintor.setBrush(_NEGRO)
            pintor.drawEllipse(QPointF(cx, cy), r, r)
            pintor.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            pintor.drawImage(QRectF(cx - r, cy - r, 2 * r, 2 * r), self._campo)
        else:
            relleno = _color_para(1.0) if base is not None else _NEGRO
            pintor.setPen(QPen(_ARO, 1.2))
            pintor.setBrush(relleno)
            pintor.drawEllipse(QPointF(cx, cy), r, r)

        self._pintar_rejilla(pintor, cx, cy, r)

        # Obstrucciones: rojo desde el borde hasta la altitud de cada una.
        # El interruptor «Mostrar obstáculos» solo decide si se pintan: los
        # grados no se tocan.
        if self._mostrar_obstaculos:
            for direccion, grados in self._obstacles.items():
                if grados <= 0:
                    continue
                az = _AZIMUT[direccion]
                pintor.setPen(QPen(QColor(150, 30, 25), 0.8))
                pintor.setBrush(_ROJO)
                pintor.drawPolygon(
                    _anillo(cx, cy, r, _r_altitud(r, grados), az - 22.5, az + 22.5)
                )

        _pintar_letras(pintor, cx, cy, r)
        if base is not None:
            self._pintar_barra(pintor, QRectF(cx + r + 32, cy - r, 12, 2 * r), base)

    def _pintar_rejilla(self, pintor: QPainter, cx: float, cy: float, r: float) -> None:
        """Rejilla punteada: anillos de altitud cada 10° y radiales cada 15°."""
        # Sin relleno: el disco rellenado con `_NEGRO` deja el brush activo y
        # cada anillo taparía el campo de color con un círculo negro.
        pintor.setPen(QPen(_REJILLA, 1, Qt.PenStyle.DashLine))
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        for az in range(0, 360, 15):
            pintor.drawLine(QPointF(cx, cy), _punto(cx, cy, r, az))
        for grados in range(10, 90, 10):
            pintor.drawEllipse(QPointF(cx, cy), _r_altitud(r, grados), _r_altitud(r, grados))
        fuente = QFont(pintor.font())
        fuente.setPointSizeF(7)
        pintor.setFont(fuente)
        pintor.setPen(_DIM)
        for grados in (20, 40, 60, 80):
            pos = _punto(cx, cy, _r_altitud(r, grados), 0)
            pintor.drawText(
                QRectF(pos.x() + 4, pos.y() - 7, 30, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{grados}°",
            )

    def _pintar_barra(self, pintor: QPainter, rect: QRectF, base: float) -> None:
        """Barra de color con las etiquetas de mag/arcsec² del sitio.

        El extremo brillante (magenta) es ``base − 2,2`` y el oscuro
        (azul) el valor del sitio: la misma horquilla de la captura.
        """
        gradiente = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        for t, color in _PARADAS:
            gradiente.setColorAt(t, color)
        pintor.setPen(QPen(_ARO, 1))
        pintor.setBrush(gradiente)
        pintor.drawRect(rect)

        fuente = QFont(pintor.font())
        fuente.setPointSizeF(7)
        pintor.setFont(fuente)
        pintor.setPen(_LETRAS)
        for i in range(5):
            t = i / 4
            y = rect.top() + t * rect.height()
            mag = (base - _ANCHO_ESCALA) + t * _ANCHO_ESCALA
            pintor.drawLine(QPointF(rect.left() - 4, y), QPointF(rect.left(), y))
            pintor.drawText(
                QRectF(rect.right() + 4, y - 8, 44, 16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{mag:.1f}".replace(".", ","),
            )
        pintor.setPen(_DIM)
        pintor.drawText(
            QRectF(rect.left() - 4, rect.bottom() + 4, 80, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            "mag/arcsec²",
        )
