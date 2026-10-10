"""Helpers compartidos de los cinco paneles del asistente de apilado.

Formato de fichas FITS y regiones, banners, tablas, estilos QSS, miniaturas
de auditoría y la configuración de pyqtgraph que los paneles de
``ui/stacker_tab/paneles/`` reutilizan. Sin widgets de panel ni orquestación:
eso vive en ``paneles/`` y en ``ui/stacker_tab/__init__.py``.
"""

import math
from html import escape
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from astropy.io import fits
from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QImage,
)
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QHeaderView,
    QLabel,
    QSpinBox,
    QTableWidget,
)

from stacks.session_parser import FichaFITS, Session
from ui.style import PALETTE


def configurar_pyqtgraph() -> None:
    """Fondo y antialias de las gráficas de auditoría, aplicados a pyqtgraph.

    pyqtgraph configura el proceso entero, así que esto no puede vivir en
    nivel módulo (un import no debe cambiar estado global): lo llama la
    página al construirse (regla A-13 de la auditoría).
    """
    pg.setConfigOptions(antialias=True, background=PALETTE["bg"])


#: Fondos de la gráfica de auditoría (mismo ajuste que el Planificador).

#: Nombres de carpeta de material por sesión (clave dentro de ``Session.frames``).
MATERIAL = (
    ("bias", "bias"),
    ("darks", "dark"),
    ("flats", "flat"),
    ("dark_flats", "dflat"),
)

#: Rojo del veredicto «descartada» (fila y puntos de la gráfica).
COLOR_DESCARTE = "#ef4444"

#: Posiciones (fila, columna) de R y B dentro del mosaico Bayer 2×2.
_BAYER: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {
    "RGGB": ((0, 0), (1, 1)),
    "GRBG": ((0, 1), (1, 1)),
    "GBRG": ((1, 0), (0, 1)),
    "BGGR": ((1, 1), (0, 0)),
}

#: Lado máximo (px) de la miniatura de la auditoría.
_ANCHO_PREVIEW = 900


def _reducir_bloques(arr: np.ndarray, k: int) -> np.ndarray:
    """Media por bloques k×k: reduce sin perder el flujo de las estrellas.

    Un muestreo a saltos dejaría invisible una estrella de 4 px; la media
    por bloques conserva su brillo y la hace visible en la miniatura.
    """
    if k <= 1:
        return arr
    alto, ancho = arr.shape
    alto2, ancho2 = (alto // k) * k, (ancho // k) * k
    return arr[:alto2, :ancho2].reshape(alto2 // k, k, ancho2 // k, k).mean(axis=(1, 3))


def _estirar(canales: list[np.ndarray]) -> list[np.ndarray]:
    """Autoestirado asinh enlazado para mostrar nebulosidad sin alterar el FITS.

    Si hay tres capas (CFA desempaquetado) primero se iguala la mediana de
    cada canal —balance de blancos simple, como el «link channels» de
    SirIL— y luego las tres comparten el mismo tramo de percentiles:
    estirarlas por separado da colores arbitrarios (cielo rosa según el
    ruido de cada canal). Un solo canal (mono) se estira tal cual. El
    tramo se calcula sobre una muestra rala: va rápido y da lo mismo.
    """
    if len(canales) == 3:
        # Los FITS float32 de SirIL suelen tener fondos ~0,001: un suelo
        # de 1 anularía por completo el balance de canales.
        medianas = [float(np.median(c)) for c in canales]
        referencia = medianas[1]  # el verde como balance
        trabajados = [
            c * (referencia / med) if med > 0 and referencia > 0 else c
            for c, med in zip(canales, medianas)
        ]
    else:
        trabajados = list(canales)
    muestra = np.concatenate([c[::8, ::8].ravel() for c in trabajados])
    muestra = muestra[np.isfinite(muestra)]
    if not muestra.size:
        return [np.zeros(c.shape, dtype=np.uint8) for c in trabajados]
    mediana = np.median(muestra)
    dispersion = 1.4826 * np.median(np.abs(muestra - mediana))
    # Se deja más margen bajo la mediana para levantar el fondo sin ocultar
    # gradientes, nubes o cables: la auditoría debe seguir revelándolos.
    bajo = mediana - 3.0 * dispersion
    alto = np.percentile(muestra, 99.7)
    if alto <= bajo:
        alto = bajo + 1.0
    factor = 1.0 / (alto - bajo)
    return [
        (255 * np.arcsinh(16 * np.clip(
            np.nan_to_num((c - bajo) * factor, nan=0.0), 0, 1
        )) / np.arcsinh(16)).astype(np.uint8)
        for c in trabajados
    ]


def _preview_fits(ruta: Path) -> QImage | None:
    """Miniatura con estirado por percentiles de un light o apilado RGB.

    El FITS se reduce por bloques hasta ~900 px por lado y, si trae
    ``BAYERPAT``, se desempaqueta el mosaico a RGB (vecino más cercano:
    para mirar el frame, no para medir). None si el fichero no es un FITS
    2-D legible.
    """
    try:
        # memmap=False: con lights uint16 (BZERO) astropy aborta el memmap
        # y, además, la miniatura lee el fichero entero de todas formas.
        with fits.open(ruta, memmap=False) as hdul:
            datos = hdul[0].data
            if datos is None or datos.ndim not in (2, 3):
                return None
            if datos.ndim == 3:
                if datos.shape[0] != 3:
                    return None
                k = max(1, math.ceil(max(datos.shape[1:]) / _ANCHO_PREVIEW))
                planos = _estirar([
                    _reducir_bloques(np.asarray(canal, dtype=np.float32), k)
                    for canal in datos
                ])
                rgb = np.ascontiguousarray(np.stack(planos, axis=-1))
                return QImage(
                    rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0],
                    QImage.Format.Format_RGB888,
                ).copy()
            patron = _BAYER.get(
                str(hdul[0].header.get("BAYERPAT", "")).strip().upper()
            )
            arr = np.asarray(datos, dtype=np.float32)
    except (OSError, ValueError):
        return None
    lado = max(arr.shape)
    if patron:
        # Cada canal es la mitad del mosaico: el bloque va por canal.
        r_pos, b_pos = patron
        g_pos = next(
            pos
            for pos in ((0, 0), (0, 1), (1, 0), (1, 1))
            if pos not in (r_pos, b_pos)
        )
        canales = [arr[o::2, f::2] for o, f in (r_pos, g_pos, b_pos)]
        k = max(1, math.ceil(lado / (2 * _ANCHO_PREVIEW)))
    else:
        canales = [arr]
        k = max(1, math.ceil(lado / _ANCHO_PREVIEW))
    planos = _estirar([_reducir_bloques(canal, k) for canal in canales])
    if len(planos) == 3:
        rgb = np.ascontiguousarray(np.stack(planos, axis=-1))
        return QImage(
            rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0],
            QImage.Format.Format_RGB888,
        ).copy()
    gris = np.ascontiguousarray(planos[0])
    return QImage(
        gris.data, gris.shape[1], gris.shape[0], gris.strides[0],
        QImage.Format.Format_Grayscale8,
    ).copy()


def _titulo(texto: str) -> QLabel:
    """Etiqueta de cabecera de paso (mismo estilo que los títulos de panel)."""
    etiqueta = QLabel(texto)
    etiqueta.setObjectName("PanelTitle")
    return etiqueta


def _pista(texto: str) -> QLabel:
    """Texto auxiliar gris y con ajuste de línea (ayuda del paso)."""
    etiqueta = QLabel(texto)
    etiqueta.setObjectName("HintLabel")
    etiqueta.setWordWrap(True)
    return etiqueta


def _campo(texto: str) -> QLabel:
    """Rótulo de campo de las fichas inferiores: gris, alineado a la derecha."""
    etiqueta = QLabel(texto)
    etiqueta.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
    etiqueta.setStyleSheet(
        "color: #8b949e; font-size: 11pt; background: transparent;"
    )
    return etiqueta


def _formato_duracion(duraciones: list[float]) -> str:
    """Duración por frame en segundos: «60 s»; «—» sin dato; «varia» si hay varias."""
    reales = [d for d in duraciones if d]
    if not reales:
        return "—"
    if len(set(reales)) > 1:
        return "varia"
    valor = reales[0]
    if float(valor).is_integer():
        return f"{int(valor)} s"
    return f"{valor:.1f}".replace(".", ",") + " s"


def _formato_total(segundos: float) -> str:
    """Tiempo acumulado sin perder segundos: 3975 s → «1 h 06 min 15 s»."""
    total = int(round(segundos))
    if total <= 0:
        return "—"
    if total < 60:
        return f"{total} s"
    horas, resto = divmod(total, 3600)
    minutos, segundos_restantes = divmod(resto, 60)
    if not horas:
        return f"{minutos} min" + (f" {segundos_restantes} s" if segundos_restantes else "")
    partes = [f"{horas} h"]
    if minutos or segundos_restantes:
        partes.append(f"{minutos:02d} min")
    if segundos_restantes:
        partes.append(f"{segundos_restantes:02d} s")
    return " ".join(partes)


def _banner(sesiones: int | None, frames: int | None = None,
            integracion: str | None = None) -> str:
    """Resumen de cabecera en una sola línea HTML (colores de la referencia).

    Los tres datos van juntos y coloreados: verde el nº de sesiones, azul el
    de tomas y amarillo la integración acumulada. Sin sesiones se devuelve el
    aviso en gris; nunca cifras «—» sueltas, que parecerían un dato real.
    """
    if sesiones is None:
        return (
            "<span style='color: #8092af;'>"
            "No se detectaron carpetas con tomas en la ruta actual.</span>"
        )
    return (
        f"<span style='color: #7ee787; font-weight: bold;'>Sesiones: {sesiones}</span>"
        " &nbsp;|&nbsp; "
        f"<span style='color: #79c0ff; font-weight: bold;'>Frames: {frames}</span>"
        " &nbsp;|&nbsp; "
        f"<span style='color: #f1fa8c; font-weight: bold;'>Integración: {integracion}</span>"
    )


def _numero(valor: float, decimales: int = 1) -> str:
    """Número en formato español sin ceros sobrantes: 6.0 → «6», 1.9156 → «1,92»."""
    texto = f"{valor:.{decimales}f}"
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def _formato_region(ficha: FichaFITS | None) -> str:
    """Encuadre legible de la sesión: «0h47m, +41,3°» («—» sin FITS)."""
    if ficha is None or ficha.ra_deg is None or ficha.dec_deg is None:
        return "—"
    horas = (ficha.ra_deg % 360.0) / 15.0
    hora = int(horas)
    minutos = int(round((horas - hora) * 60.0))
    if minutos == 60:  # el redondeo da 60 justo en el borde: sube la hora
        hora, minutos = (hora + 1) % 24, 0
    dec = f"{ficha.dec_deg:+.1f}".replace(".", ",")
    return f"{hora}h{minutos:02d}m, {dec}°"


def _texto_region(ficha: FichaFITS | None) -> str | None:
    """«M31 | 0h47m, +41,3°» para el campo Región; None si el FITS no trae nada.

    Junta el ``OBJECT`` con las coordenadas calculadas de la cabecera: si no
    hay ninguna de las dos, no se rellena el campo con una región inventada.
    """
    if ficha is None:
        return None
    region = _formato_region(ficha)
    partes = [v for v in (ficha.objeto, region if region != "—" else None) if v]
    return " | ".join(partes) or None


def _comun(valores: list[str | None]) -> str | None:
    """Valores distintos entre sesiones (« / »), o ``None`` si ninguno hay."""
    distintos: list[str] = []
    for valor in valores:
        if valor and valor not in distintos:
            distintos.append(valor)
    return " / ".join(distintos) or None


def _optica(ficha: FichaFITS) -> str | None:
    """Distancia focal, ratio f/ y escala angular («420 mm · f/6 · 1,916 ″/px»)."""
    partes = []
    if ficha.focal_mm:
        partes.append(f"{_numero(ficha.focal_mm)} mm")
        if ficha.diametro_mm:
            partes.append(f"f/{_numero(ficha.focal_mm / ficha.diametro_mm)}")
    if ficha.escala_as_px:
        partes.append(f"{_numero(ficha.escala_as_px, 3)} ″/px")
    return " · ".join(partes) or None


def _sensor(ficha: FichaFITS) -> str | None:
    """Sensor en píxel y en mm, píxel físico y binning («6000×4000 px · …»)."""
    if not (ficha.px_x and ficha.px_y):
        return None
    partes = [f"{ficha.px_x}×{ficha.px_y} px"]
    if ficha.pix_um:
        partes.append(f"{_numero(ficha.pix_um)} µm")
        partes.append(
            f"{_numero(ficha.px_x * ficha.pix_um / 1000)}×"
            f"{_numero(ficha.px_y * ficha.pix_um / 1000)} mm"
        )
    if ficha.binning:
        partes.append(f"bin {ficha.binning}×{ficha.binning}")
    return " · ".join(partes)


def _equipo(ficha: FichaFITS) -> str | None:
    """Cámara y montura tal y como las escribe el programa de captura."""
    return " · ".join(v for v in (ficha.camara, ficha.montura) if v) or None


def _sitio(ficha: FichaFITS) -> str | None:
    """Latitud y longitud del observatorio («+10,019°, -84,281°»)."""
    if ficha.lat is None or ficha.lon is None:
        return None
    return f"{ficha.lat:+.3f}°, {ficha.lon:+.3f}°".replace(".", ",")


def _formato_ficha(fichas: dict[str, FichaFITS]) -> str:
    """Línea de ficha FITS (óptica · sensor · equipo · sitio) de las sesiones.

    Lo común se muestra una vez; si dos sesiones traen valores distintos
    (dos cámaras, dos sitios) van separados « / ». Lo que no esté en
    ninguna cabecera no aparece.
    """
    validas = [f for f in fichas.values() if f is not None]
    campos = (
        ("Óptica", [_optica(f) for f in validas]),
        ("Sensor", [_sensor(f) for f in validas]),
        ("Equipo", [_equipo(f) for f in validas]),
        ("Sitio", [_sitio(f) for f in validas]),
    )
    partes = []
    for nombre, valores in campos:
        valor = _comun(valores)
        if valor:
            partes.append(f"<b>{nombre}:</b> {escape(valor)}")
    return " · ".join(partes) or "Sin cabeceras FITS legibles en las sesiones."


def _ayuda_fila(sesion: Session, calibrada: bool, ficha: FichaFITS | None) -> str:
    """Tooltip de la fila: ruta, estado del calibrado, región y ficha FITS.

    Va en HTML (los ``<br>`` separan líneas) y todo lo que viene de disco va
    escapado: una carpeta llamada ``<datos>`` no puede romper el texto.
    """
    lineas = [
        escape(str(sesion.path)),
        f"{escape(sesion.kind)} · {'Calibrada ✓' if calibrada else 'Pendiente'}",
    ]
    if ficha is not None:
        region = _formato_region(ficha)
        if region != "—":
            lineas.append(f"Región: {escape(region)}")
        lineas.append(_formato_ficha({sesion.path.name: ficha}))
    return "<br>".join(lineas)


def _tabla(columnas: list[str], columna_ancha: int = 0) -> QTableWidget:
    """Tabla de solo lectura con el patrón común (sin edición, filas enteras)."""
    tabla = QTableWidget(0, len(columnas))
    tabla.setHorizontalHeaderLabels(columnas)
    tabla.verticalHeader().setVisible(False)
    tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tabla.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    cabecera = tabla.horizontalHeader()
    cabecera.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    cabecera.setSectionResizeMode(columna_ancha, QHeaderView.ResizeMode.Stretch)
    return tabla


def _spin(minimo: float, maximo: float, valor: float, *, paso: float,
          decimales: int) -> QDoubleSpinBox:
    """Spin de coma flotante con rangos acotados (pesos, sigmas, pixfrac)."""
    spin = QDoubleSpinBox()
    spin.setRange(minimo, maximo)
    spin.setSingleStep(paso)
    spin.setDecimals(decimales)
    spin.setValue(valor)
    return spin


def _spin_entero(minimo: int, maximo: int, valor: int) -> QSpinBox:
    """Spin entero (los pesos son números redondos 0–100)."""
    spin = QSpinBox()
    spin.setRange(minimo, maximo)
    spin.setValue(valor)
    return spin


def _poner_dato(spin: QDoubleSpinBox, valor: float | None,
                minimo: float, maximo: float) -> None:
    """Escribe en su spin un dato del FITS, o lo deja en «--» si no venía.

    El programa no inventa medidas: sin dato el spin muestra «--». Si el
    mínimo es 0 (focal, píxel) el rango real se conserva —0 ya es
    el mínimo y se lee como ausencia—; si no (latitud, longitud) el rango se
    colapsa a (0, 0), porque un 0,0 escrito a mano sí parecería una
    medida verdadera. Señales bloqueadas: cargar datos no dispara los
    manejadores de edición.
    """
    spin.blockSignals(True)
    if valor is None:
        spin.setSpecialValueText("--")
        if minimo == 0:
            spin.setRange(minimo, maximo)
            spin.setValue(0)
        else:
            spin.setRange(0.0, 0.0)
    else:
        spin.setRange(minimo, maximo)
        spin.setSpecialValueText("")
        spin.setValue(valor)
    spin.blockSignals(False)


class _DatoFITS(QDoubleSpinBox):
    """Muestra cifras FITS sin permitir cambios con rueda ni teclado."""

    def stepBy(self, steps: int) -> None:
        """Ignora incrementos: el valor lo establece únicamente el lector FITS."""

    def wheelEvent(self, event) -> None:
        """No cambia un dato astronómico al desplazarse sobre la ficha."""
        event.ignore()


def _spin_dato(minimo: float, maximo: float, *, decimales: int, paso: float,
               solo_lectura: bool = False) -> QDoubleSpinBox:
    """Spin de campo FITS que arranca en «--» (sin dato) con su rango real.

    ``solo_lectura`` marca los campos que solo informan (sitio): el usuario
    los mira pero no los edita, para que la configuración no se cambie sin
    querer desde la ficha de una sesión.
    """
    spin = _DatoFITS()
    spin.setDecimals(decimales)
    spin.setSingleStep(paso)
    spin.setReadOnly(True)
    spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    spin.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    _poner_dato(spin, None, minimo, maximo)
    return spin


#: QSS de los contenedores de la referencia: caja oscura, título azul arriba
#: a la izquierda y etiquetas sin fondo propio (el fondo del grupo se ve).
_ESTILO_GRUPO = """
QGroupBox {
    background-color: #0c1220;
    border: 1px solid #1a263d;
    border-radius: 6px;
    margin-top: 4px;
    padding-top: 24px;
    padding-bottom: 6px;
    padding-left: 6px;
    padding-right: 6px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: padding;
    subcontrol-position: top left;
    left: 12px;
    top: 6px;
    padding: 0px;
    color: #60a5fa;
    background-color: transparent;
}
QLabel { background: transparent; }
"""

#: Línea de resumen: recuadro estrecho sobre fondo casi negro.
_ESTILO_BANNER = """
QLabel {
    background-color: #090e18;
    border: 1px solid #1a263d;
    border-radius: 5px;
    padding: 8px 12px;
    font-size: 10pt;
}
"""

#: Tabla de sesiones: fondo oscuro, rejilla tenue, selección azul y cabecera azul.
_ESTILO_TABLA = """
QTableWidget {
    background-color: #090e18;
    border: 1px solid #1a263d;
    border-radius: 5px;
    gridline-color: #162033;
    font-size: 10pt;
}
QTableWidget::item:selected {
    background-color: #1e3a8a;
}
QHeaderView::section {
    background-color: #0c1220;
    color: #60a5fa;
    font-weight: bold;
    font-size: 9pt;
    padding: 6px;
    border: none;
    border-bottom: 1px solid #1a263d;
}
"""

#: Valores FITS de las fichas inferiores: texto, sin apariencia de edición.
_ESTILO_CAMPOS = """
QDoubleSpinBox, QSpinBox {
    background: transparent;
    color: #79c0ff;
    border: none;
    padding: 0px;
    min-height: 22px;
    font-size: 12pt;
    font-weight: bold;
}
"""

#: Botón flotante «🌐 Telescopius» (visible, pero inerte hasta que exista integración).
_ESTILO_TELESCOPIUS = """
QPushButton {
    background-color: rgba(31, 111, 235, 0.85);
    color: #ffffff;
    font-weight: bold;
    font-size: 9pt;
    border: 1px solid #388bfd;
    border-radius: 5px;
    padding: 5px 12px;
}
QPushButton:hover { background-color: rgba(56, 139, 253, 0.95); }
QPushButton:disabled {
    background-color: rgba(31, 111, 235, 0.30);
    color: #93c5fd;
    border-color: #1f4b8a;
}
"""

#: Controles flotantes sobre la carta («Ver FITS» y «Reset Vista»).
_ESTILO_FLOTANTE = """
QPushButton {
    background-color: #161b22;
    border: 1px solid #30363d;
    color: #8b949e;
    border-radius: 4px;
    font-size: 8pt;
    font-weight: bold;
    padding: 2px 8px;
}
QPushButton:hover { border-color: #58a6ff; color: #58a6ff; }
"""

#: Panel flotante de rotación (etiqueta + slider + grados) sobre la carta.
_ESTILO_ROTACION = """
QWidget#PanelRotacion {
    background-color: rgba(12, 18, 32, 0.92);
    border: 1px solid #1a263d;
    border-radius: 5px;
}
QWidget#PanelRotacion QLabel {
    color: #60a5fa;
    font-weight: bold;
    font-size: 8.5pt;
    border: none;
    background: transparent;
}
QWidget#PanelRotacion QSlider::groove:horizontal {
    height: 4px;
    background: #1a263d;
    border-radius: 2px;
}
QWidget#PanelRotacion QSlider::sub-page:horizontal {
    background: #2563eb;
    border-radius: 2px;
}
QWidget#PanelRotacion QSlider::handle:horizontal {
    background: #60a5fa;
    border: 1px solid #ffffff;
    width: 14px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 7px;
}
QWidget#PanelRotacion QSpinBox {
    background-color: #090e18;
    color: #60a5fa;
    border: 1px solid #1a263d;
    border-radius: 3px;
    font-size: 8.5pt;
    font-weight: bold;
    padding: 1px 2px;
}
"""


#: Texto del resumen antes de escanear nada (todavía no hay cifras que dar).
_RESUMEN_INICIAL = (
    "Selecciona un directorio con tomas FITS o RAW para comenzar."
)


def _estilo_dato(color: str) -> str:
    """QSS inline de una etiqueta de dato de la ficha (color a medida)."""
    return f"font-weight: bold; color: {color}; font-size: 12pt; background: transparent;"


def _estilo_region(color: str) -> str:
    """QSS del campo «Coords»: amarillo con dato real, gris sin él."""
    return f"""
    QLineEdit {{
        background: transparent;
        border: none;
        padding: 0px;
        color: {color};
        font-weight: bold;
        font-size: 12pt;
    }}
    """


def _rotacion_slider(grados: float | None) -> int:
    """CROTA2 (cualquier ángulo) normalizado al rango del slider [-180, 180]."""
    if grados is None:
        return 0
    return round((grados + 180.0) % 360.0 - 180.0)


def _material(sesion: Session) -> str:
    """Resumen de material de calibración («bias 100 · dark 40», o «—»)."""
    partes = [
        f"{etiqueta} {len(sesion.frames.get(clave, []))}"
        for clave, etiqueta in MATERIAL
        if sesion.frames.get(clave)
    ]
    return " · ".join(partes) or "—"
