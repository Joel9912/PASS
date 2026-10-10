"""Cinco paneles del asistente de apilado: sesiones, calibrar, auditar, apilar y final.

Cada panel es solo presentación: sus botones emiten señales y la página
(``ui.stacker_tab``) decide qué tarea lanza en el hilo de trabajo. Así la
lógica de orquestación vive en un sitio y los widgets son probables por
separado.
"""
import math
import shlex
import subprocess
from html import escape
from pathlib import Path
from shutil import which

import numpy as np
import pyqtgraph as pg
from astropy.io import fits
from PyQt6.QtCore import QEvent, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QImage,
    QPixmap,
    QResizeEvent,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stacks.frame_metrics import Evaluacion, FrameMetrics, Pesos, evaluar
from stacks.registration import Registro
from stacks.session_parser import FichaFITS, Session
from stacks.siril_finder import find_siril
from stacks.stacker import (
    INTEGRACIONES,
    NORMS,
    PONDERACIONES,
    RECHAZOS,
    StackOptions,
)
from ui.style import FONT_FAMILY, PALETTE

from .visor_sesiones import CieloCapturado, VisorSesiones

#: Fondos de la gráfica de auditoría (mismo ajuste que el Planificador).
pg.setConfigOptions(antialias=True, background=PALETTE["bg"])

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


class PanelSesiones(QWidget):
    """Paso 1: sesiones a la izquierda y cielo capturado por FITS a la derecha."""

    escanear = pyqtSignal()  # «Escanear» (el Siguiente de la página también)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta ruta, resumen+tabla, carta con controles flotantes y dos fichas."""
        super().__init__(parent)
        self._ficha_actual: FichaFITS | None = None
        self._escala_cabecera: float | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        # 1. Ruta de sesiones: «Enter» en el campo lanza el escaneo.
        fila = QHBoxLayout()
        fila.setContentsMargins(2, 2, 2, 2)
        fila.setSpacing(8)
        etiqueta_dir = QLabel("Directorio Sesión:")
        etiqueta_dir.setStyleSheet(
            "font-weight: bold; color: #60a5fa; font-size: 12px;"
        )
        fila.addWidget(etiqueta_dir)
        self._raiz = QLineEdit()
        self._raiz.setPlaceholderText("Selecciona la carpeta con tus sesiones…")
        self._raiz.returnPressed.connect(self.escanear)
        self._boton_examinar = QPushButton("📁 Examinar…")
        self._boton_examinar.clicked.connect(self._examinar)
        self._boton_escanear = QPushButton("🔄 Re-escanear")
        self._boton_escanear.setObjectName("PrimaryButton")
        self._boton_escanear.clicked.connect(self.escanear)
        fila.addWidget(self._raiz, 8)
        fila.addWidget(self._boton_examinar, 2)
        fila.addWidget(self._boton_escanear, 1)
        layout.addLayout(fila)

        # 2. Desglose (izquierda) y carta del cielo (derecha).
        centro = QHBoxLayout()
        centro.setSpacing(10)

        grupo_ses = QGroupBox("Desglose de Sesiones e Integración")
        grupo_ses.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        grupo_ses.setStyleSheet(_ESTILO_GRUPO)
        lista_layout = QVBoxLayout(grupo_ses)
        lista_layout.setContentsMargins(10, 10, 10, 10)
        lista_layout.setSpacing(8)

        self._resumen = QLabel(_RESUMEN_INICIAL)
        self._resumen.setStyleSheet(_ESTILO_BANNER)
        lista_layout.addWidget(self._resumen)

        self._tabla = QTableWidget(0, 4)
        self._tabla.setHorizontalHeaderLabels(
            ["ID", "Tomas", "Exposición", "Tiempo"]
        )
        self._tabla.verticalHeader().setVisible(False)
        self._tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tabla.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tabla.setStyleSheet(_ESTILO_TABLA)
        cabecera = self._tabla.horizontalHeader()
        cabecera.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        cabecera.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tabla.installEventFilter(self)  # anchos al cambiar la anchura
        self._tabla.itemSelectionChanged.connect(self._al_elegir_sesion)
        lista_layout.addWidget(self._tabla, 1)
        centro.addWidget(grupo_ses, 5)

        grupo_fov = QGroupBox("Campo de Visión (FOV) y Planetario Interactivo")
        grupo_fov.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        grupo_fov.setStyleSheet(_ESTILO_GRUPO)
        visor_layout = QVBoxLayout(grupo_fov)
        visor_layout.setContentsMargins(6, 6, 6, 6)
        visor_layout.setSpacing(6)
        self._vistas = QStackedWidget()
        self._cielo = CieloCapturado()
        self._visor = VisorSesiones(_preview_fits)
        self._vistas.addWidget(self._cielo)
        self._vistas.addWidget(self._visor)
        visor_layout.addWidget(self._vistas, 1)
        centro.addWidget(grupo_fov, 6)
        layout.addLayout(centro, 1)

        # Controles flotantes: van encima de la carta, no en una fila aparte.
        self._telescopius = QPushButton("🌐 Telescopius", self._cielo)
        self._telescopius.setStyleSheet(_ESTILO_TELESCOPIUS)
        self._telescopius.setToolTip("Próximamente: integración con Telescopius.")
        self._telescopius.setEnabled(False)

        self._panel_rot = QWidget(self._cielo)
        self._panel_rot.setObjectName("PanelRotacion")
        self._panel_rot.setStyleSheet(_ESTILO_ROTACION)
        lay_rot = QHBoxLayout(self._panel_rot)
        lay_rot.setContentsMargins(8, 2, 8, 2)
        lay_rot.setSpacing(8)
        lay_rot.addWidget(QLabel("Rot:"))
        self._rotacion = QSlider(Qt.Orientation.Horizontal)
        self._rotacion.setRange(-180, 180)
        self._rotacion.setFixedWidth(180)
        lay_rot.addWidget(self._rotacion)
        self._rotacion_spin = QSpinBox()
        self._rotacion_spin.setRange(-180, 180)
        self._rotacion_spin.setSuffix("°")
        self._rotacion_spin.setFixedWidth(56)
        lay_rot.addWidget(self._rotacion_spin)
        self._rotacion.valueChanged.connect(self._al_rotar)
        self._rotacion_spin.valueChanged.connect(self._rotacion.setValue)
        self._panel_rot.hide()

        self._alternar_vista = QPushButton("Ver FITS", self._vistas)
        self._alternar_vista.setStyleSheet(_ESTILO_FLOTANTE)
        self._reiniciar = QPushButton("Reset Vista", self._vistas)
        self._reiniciar.setStyleSheet(_ESTILO_FLOTANTE)
        self._alternar_vista.clicked.connect(self._alternar)
        self._reiniciar.clicked.connect(self._reiniciar_vista)

        self._cielo.installEventFilter(self)
        self._vistas.installEventFilter(self)

        # 3. Las dos fichas inferiores: rejilla 2×2 con altura fija de 115 px.
        tarjetas = QHBoxLayout()
        tarjetas.setSpacing(10)

        self._grupo_opt = QGroupBox("Tren Óptico y Muestreo")
        self._grupo_opt.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._grupo_opt.setFixedHeight(115)
        self._grupo_opt.setStyleSheet(_ESTILO_GRUPO + _ESTILO_CAMPOS)
        grid_opt = QGridLayout(self._grupo_opt)
        grid_opt.setContentsMargins(14, 12, 14, 10)
        grid_opt.setVerticalSpacing(8)
        grid_opt.setHorizontalSpacing(12)
        grid_opt.setColumnMinimumWidth(0, 130)
        grid_opt.setColumnStretch(1, 1)
        grid_opt.setColumnMinimumWidth(2, 130)
        grid_opt.setColumnStretch(3, 1)

        # Todos los datos provienen del primer FITS y son solo lectura.
        self._optica_campos_0 = _spin_dato(0.0, 5000.0, decimales=2, paso=10.0)
        self._optica_campos_0.setToolTip(
            "Distancia focal (mm) del primer light (FOCALLEN)."
        )
        self._optica_campos_1 = _spin_dato(0.0, 25.0, decimales=2, paso=0.1)
        self._optica_campos_1.setToolTip(
            "Tamaño del píxel (µm) del primer light (PIXSIZE1/XPIXSZ)."
        )
        self._optica_campos_2 = QLabel("Pendiente FITS")
        self._optica_campos_2.setStyleSheet(_estilo_dato("#8092af"))
        self._optica_campos_3 = QLabel("Pendiente FITS")
        self._optica_campos_3.setStyleSheet(_estilo_dato("#8092af"))

        grid_opt.addWidget(_campo("Distancia Focal (mm):"), 0, 0)
        grid_opt.addWidget(self._optica_campos_0, 0, 1)
        grid_opt.addWidget(_campo("Tamaño Píxel (µm):"), 0, 2)
        grid_opt.addWidget(self._optica_campos_1, 0, 3)
        grid_opt.addWidget(_campo("Escala de Placa:"), 1, 0)
        grid_opt.addWidget(self._optica_campos_2, 1, 1)
        grid_opt.addWidget(_campo("Rotación Sensor:"), 1, 2)
        grid_opt.addWidget(self._optica_campos_3, 1, 3)
        # Texto completo (oculto): lo que no cabe en los campos sigue accesible
        # en el tooltip del grupo, no en una lista de cuatro filas más.
        self._detalle_optico = QLabel(self._grupo_opt)
        self._detalle_optico.hide()
        tarjetas.addWidget(self._grupo_opt, 5)

        self._grupo_sitio = QGroupBox(
            "Ubicación del Observatorio y Región Apuntada"
        )
        self._grupo_sitio.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._grupo_sitio.setFixedHeight(115)
        self._grupo_sitio.setStyleSheet(_ESTILO_GRUPO + _ESTILO_CAMPOS)
        grid_sitio = QGridLayout(self._grupo_sitio)
        grid_sitio.setContentsMargins(14, 12, 14, 10)
        grid_sitio.setVerticalSpacing(8)
        grid_sitio.setHorizontalSpacing(12)
        grid_sitio.setColumnMinimumWidth(0, 110)
        grid_sitio.setColumnStretch(1, 1)
        grid_sitio.setColumnMinimumWidth(2, 110)
        grid_sitio.setColumnStretch(3, 2)

        self._sitio_campos_0 = _spin_dato(
            -90.0, 90.0, decimales=5, paso=0.01, solo_lectura=True
        )
        self._sitio_campos_1 = _spin_dato(
            -180.0, 180.0, decimales=5, paso=0.01, solo_lectura=True
        )
        self._sitio_campos_2 = _spin_dato(
            -90.0, 90.0, decimales=1, paso=1.0, solo_lectura=True
        )
        self._sitio_campos_2.setToolTip(
            "Altura del objeto sobre el horizonte (OBJCTALT del primer light)."
        )
        self._sitio_campos_3 = QLineEdit()
        self._sitio_campos_3.setReadOnly(True)
        self._sitio_campos_3.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sitio_campos_3.setText("Pendiente FITS")
        self._sitio_campos_3.setStyleSheet(_estilo_region("#8092af"))

        grid_sitio.addWidget(_campo("Latitud (°):"), 0, 0)
        grid_sitio.addWidget(self._sitio_campos_0, 0, 1)
        grid_sitio.addWidget(_campo("Longitud (°):"), 0, 2)
        grid_sitio.addWidget(self._sitio_campos_1, 0, 3)
        grid_sitio.addWidget(_campo("Alt. objeto (°):"), 1, 0)
        grid_sitio.addWidget(self._sitio_campos_2, 1, 1)
        grid_sitio.addWidget(_campo("Coords:"), 1, 2)
        grid_sitio.addWidget(self._sitio_campos_3, 1, 3)
        self._detalle_sitio = QLabel(self._grupo_sitio)
        self._detalle_sitio.hide()
        tarjetas.addWidget(self._grupo_sitio, 5)
        layout.addLayout(tarjetas)

        self._sesiones_actuales: list[Session] = []
        self._fichas_actuales: dict[str, FichaFITS] = {}

    def raiz(self) -> str:
        """Carpeta raíz escrita por el usuario (vacío si aún no hay)."""
        return self._raiz.text().strip()

    def poner_raiz(self, raiz: str) -> None:
        """Fija la raíz (Configuración al abrir; la pestaña puede cambiarla)."""
        self._raiz.setText(raiz)

    def bloquear(self, bloqueado: bool) -> None:
        """Deshabilita sus botones mientras una tarea corre en el hilo."""
        self._boton_examinar.setEnabled(not bloqueado)
        self._boton_escanear.setEnabled(not bloqueado)
        self._raiz.setEnabled(not bloqueado)

    def mostrar(
        self,
        sesiones: list[Session],
        calibradas: set[str],
        exposiciones: dict[str, list[float]],
        fichas: dict[str, FichaFITS] | None = None,
    ) -> None:
        """Rellena la tabla y sincroniza el visor/fichas con la sesión elegida.

        ``exposiciones`` da la exposición por frame de cada sesión (segundos;
        lista vacía si no hay dato): de ahí salen «Exposición» (por frame) y
        «Tiempo» (acumulado). ``fichas`` son las cabeceras FITS del primer
        light de cada sesión (región apuntada y ficha del equipo); sin ella
        la región no sale y la ficha avisa de que no hay cabeceras.
        """
        fichas = fichas or {}
        self._sesiones_actuales = list(sesiones)
        self._fichas_actuales = fichas
        self._tabla.setRowCount(0)
        total_lights = 0
        total_segundos = 0.0
        negrita = QFont(FONT_FAMILY, 10)
        negrita.setBold(True)
        normal = QFont(FONT_FAMILY, 10)
        for sesion in sesiones:
            fila = self._tabla.rowCount()
            self._tabla.insertRow(fila)
            lights = sesion.n_lights
            duraciones = exposiciones.get(sesion.path.name, [])
            total = sum(duraciones)
            total_lights += lights
            total_segundos += total
            calibrada = sesion.path.name in calibradas
            ficha = fichas.get(sesion.path.name)
            # ID en azul y en negrita, tomas en blanco, exposición en azul
            # claro y tiempo en verde: el color codifica la columna.
            celdas = (
                (sesion.path.name, "#58a6ff", negrita),
                (str(lights), "#f0f6fc", normal),
                (_formato_duracion(duraciones), "#79c0ff", normal),
                (_formato_total(total), "#7ee787", negrita),
            )
            for columna, (texto, color, fuente) in enumerate(celdas):
                item = QTableWidgetItem(texto)
                item.setForeground(QColor(color))
                item.setFont(fuente)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if columna == 0:
                    item.setToolTip(_ayuda_fila(sesion, calibrada, ficha))
                self._tabla.setItem(fila, columna, item)
            self._tabla.setRowHeight(fila, 30)
        self._repertir_anchos()
        if sesiones:
            self._resumen.setText(
                _banner(len(sesiones), total_lights, _formato_total(total_segundos))
            )
            self._tabla.selectRow(0)
        else:
            self._resumen.setText(_banner(None))
            self._visor.mostrar(None, None)
            self._cielo.mostrar(None)
            self._poner_conmutador(False)
            self._poner_detalles("Sin escanear todavía.", "Sin escanear todavía.")
            self._rellenar_campos(None)

    def _al_elegir_sesion(self) -> None:
        """Muestra solo el FITS de la fila seleccionada; no modifica el origen."""
        indice = self._tabla.currentRow()
        if not 0 <= indice < len(self._sesiones_actuales):
            return
        sesion = self._sesiones_actuales[indice]
        ficha = self._fichas_actuales.get(sesion.path.name)
        lights = sesion.frames.get("lights", [])
        primer_fits = next(
            (f for f in lights if f.suffix.lower() in (".fit", ".fits", ".fts")),
            None,
        )
        self._visor.mostrar(primer_fits, ficha)
        self._cielo.mostrar(ficha)
        self._poner_conmutador(primer_fits is not None)
        self._rellenar_campos(ficha)
        self._actualizar_detalles(ficha)

    def _poner_conmutador(self, hay_fits: bool) -> None:
        """«Ver FITS» solo existe cuando hay imagen que enseñar.

        Sin FITS legible (RAW u otro formato que la cabecera no abre) no se
        deja un botón muerto: se oculta y la vista se queda en la carta.
        """
        self._alternar_vista.setVisible(hay_fits)
        if hay_fits:
            return
        self._alternar_vista.setText("Ver FITS")
        if self._vistas.currentWidget() is not self._cielo:
            self._vistas.setCurrentWidget(self._cielo)
            self._reiniciar.raise_()

    def _rellenar_campos(self, ficha: FichaFITS | None) -> None:
        """Rellena las dos fichas sin fabricar medidas ausentes del FITS.

        Todos los valores proceden del primer light y son de solo lectura.
        Lo que el FITS no trae se muestra como
        «--» o «Pendiente FITS», nunca con un valor por defecto.
        """
        self._ficha_actual = ficha
        self._escala_cabecera = ficha.escala_as_px if ficha else None
        _poner_dato(
            self._optica_campos_0,
            ficha.focal_mm if ficha else None, 0.0, 5000.0,
        )
        _poner_dato(
            self._optica_campos_1,
            ficha.pix_um if ficha else None, 0.0, 25.0,
        )
        _poner_dato(
            self._sitio_campos_0, ficha.lat if ficha else None, -90.0, 90.0
        )
        _poner_dato(
            self._sitio_campos_1, ficha.lon if ficha else None, -180.0, 180.0
        )
        _poner_dato(
            self._sitio_campos_2,
            ficha.altura_obj_deg if ficha else None, -90.0, 90.0,
        )

        rotacion = ficha.rotacion_deg if ficha and ficha.rotacion_deg is not None else None
        self._optica_campos_3.setText(
            f"{_numero(rotacion, 1)}°"
            if rotacion is not None else "Pendiente FITS"
        )
        self._optica_campos_3.setToolTip("Rotación de la cabecera (CROTA2).")
        self._optica_campos_3.setStyleSheet(
            _estilo_dato("#d2a8ff" if rotacion is not None else "#8092af")
        )

        region = _texto_region(ficha)
        self._sitio_campos_3.setText(region or "Pendiente FITS")
        self._sitio_campos_3.setToolTip(region or "Sin región en FITS")
        self._sitio_campos_3.setStyleSheet(
            _estilo_region("#f1fa8c" if region else "#8092af")
        )
        grados = ficha.rotacion_deg if ficha and ficha.rotacion_deg is not None else None
        self._rotacion.setValue(_rotacion_slider(grados))
        self._recalcular_escala()

    def _escala_de_spins(self) -> float | None:
        """Escala derivada de focal, píxel y binning (los que traiga el FITS)."""
        focal = self._optica_campos_0.value()
        pixel = self._optica_campos_1.value()
        if focal <= 0 or pixel <= 0:
            return None
        binning = self._ficha_actual.binning if self._ficha_actual else None
        return 206.265 * pixel * (binning or 1) / focal

    def _recalcular_escala(self) -> None:
        """Etiqueta de escala de placa, reencuadre de la carta y panel de rotación.

        El ``SCALE`` de la cabecera manda; si no está, se deriva de la
        óptica del FITS con la misma fórmula de ``campo_vision``. Sin ningún
        dato la etiqueta se queda en «Pendiente FITS» y no se dibuja un FOV.
        """
        escala = self._escala_cabecera
        if escala is None:
            escala = self._escala_de_spins()
        if escala is None:
            self._optica_campos_2.setText("Pendiente FITS")
            self._optica_campos_2.setStyleSheet(_estilo_dato("#8092af"))
        else:
            self._optica_campos_2.setText(f"{_numero(escala, 3)} arcsec/px")
            self._optica_campos_2.setStyleSheet(_estilo_dato("#58a6ff"))
        self._aplicar_campo(escala)
        if self._cielo.tiene_encuadre():
            self._colocar_flotantes()
            self._panel_rot.show()
        else:
            self._panel_rot.hide()

    def _aplicar_campo(self, escala: float | None) -> None:
        """Reencuadra la carta con la escala vigente y el sensor real del FITS."""
        ficha = self._ficha_actual
        if ficha is None:
            return  # sin sesión no hay centro que reanclar
        campo = None
        if escala and ficha.px_x and ficha.px_y:
            campo = (ficha.px_x * escala / 3600.0, ficha.px_y * escala / 3600.0)
        self._cielo.actualizar_campo(campo)

    def _actualizar_detalles(self, ficha: FichaFITS | None) -> None:
        """Textos auxiliares de la sesión elegida (visibles en el tooltip)."""
        if ficha is None:
            self._poner_detalles(
                "Sin cabecera FITS legible.",
                "Región y sitio: — (sin cabecera FITS).",
            )
            return
        self._poner_detalles(
            f"Óptica: {escape(_optica(ficha) or '—')}<br>"
            f"Sensor: {escape(_sensor(ficha) or '—')}<br>"
            f"Equipo: {escape(_equipo(ficha) or '—')}",
            f"Observatorio: {escape(_sitio(ficha) or '—')}<br>"
            f"Elevación del observatorio: "
            f"{escape(f'{_numero(ficha.altitud_m, 0)} m' if ficha.altitud_m is not None else 'No consta en FITS')}<br>"
            f"Región: {escape(_formato_region(ficha))}<br>"
            f"Objetivo FITS: {escape(ficha.objeto or '—')}",
        )

    def _poner_detalles(self, optico: str, sitio: str) -> None:
        """Guarda la ficha en los textos ocultos y la expone en los tooltip.

        Los dos grupos tienen la rejilla 2×2 y no admiten más filas: el
        detalle completo (sensor, equipo, objetivo) vive en el tooltip del
        propio grupo para no romper la maquetación.
        """
        self._detalle_optico.setText(optico)
        self._detalle_sitio.setText(sitio)
        self._grupo_opt.setToolTip(optico)
        self._grupo_sitio.setToolTip(sitio)

    def _al_rotar(self, valor: int) -> None:
        """El slider manda: espeja los grados en el spin y gira el contorno FOV."""
        if self._rotacion_spin.value() != valor:
            self._rotacion_spin.blockSignals(True)
            self._rotacion_spin.setValue(valor)
            self._rotacion_spin.blockSignals(False)
        self._cielo.set_rotation(valor)

    def _alternar(self) -> None:
        """Alterna entre carta de la captura y el light FITS original."""
        es_cielo = self._vistas.currentWidget() is self._cielo
        self._vistas.setCurrentWidget(self._visor if es_cielo else self._cielo)
        self._alternar_vista.setText("Ver cielo" if es_cielo else "Ver FITS")
        # QStackedWidget sube su página al cambiar: los botones flotantes
        # son hermanos de la página y tienen que volver a la cima.
        self._alternar_vista.raise_()
        self._reiniciar.raise_()

    def _reiniciar_vista(self) -> None:
        """Vuelve al encuadre de la sesión en ambas vistas."""
        self._cielo.reset_view()
        self._visor.reiniciar_vista()

    def _colocar_flotantes(self) -> None:
        """Sitúa los controles flotantes en las esquinas de la carta y del visor.

        Las mismas posiciones de la referencia: Telescopius arriba a la
        derecha, el panel de rotación abajo (a la izquierda de «Reset Vista»)
        y los dos botones flotando sobre la pila de vistas.
        """
        ancho, alto = self._cielo.width(), self._cielo.height()
        self._telescopius.setGeometry(max(0, ancho - 147), 10, 135, 30)
        panel_ancho = max(self._panel_rot.sizeHint().width(), 1)
        self._panel_rot.setGeometry(
            max(0, ancho - 105 - panel_ancho - 12),
            max(0, alto - 37),
            panel_ancho, 28,
        )
        ancho_v, alto_v = self._vistas.width(), self._vistas.height()
        # En la misma fila que Telescopius (arriba a la derecha): la leyenda
        # de la carta arranca justo debajo y no debe quedar tapada por él.
        self._alternar_vista.adjustSize()
        ancho_alt = self._alternar_vista.width()
        self._alternar_vista.setGeometry(
            max(0, ancho_v - 147 - 8 - ancho_alt), 10, ancho_alt, 30
        )
        self._reiniciar.setGeometry(max(0, ancho_v - 105), max(0, alto_v - 36), 95, 26)

    def _repertir_anchos(self, ancho: int | None = None) -> None:
        """El ID ocupa el 44 % y el resto reparte entre las tres columnas.

        Si el panel es más estrecho que los mínimos, se conservan los mínimos
        y Qt ofrece desplazamiento horizontal: mejor barras que cabeceras
        partidas («Exposición» y «Tiempo» tienen que leerse enteras).

        Args:
            ancho: anchura de la cabecera a repartir; si falta, se lee la real.
        """
        if ancho is None:
            ancho = self._tabla.horizontalHeader().width()
        columnas = self._tabla.columnCount()
        minimos = [145, 75, 110, 105][:columnas]
        if ancho <= 0 or columnas < 3:
            return
        if ancho < sum(minimos):
            for columna, minimo in enumerate(minimos):
                self._tabla.setColumnWidth(columna, minimo)
            return
        sesion = min(max(int(ancho * 0.44), minimos[0]), ancho - sum(minimos[1:]))
        resto = ancho - sesion
        reparto, sobrantes = divmod(resto - sum(minimos[1:]), columnas - 1)
        anchos = [sesion] + [
            minimos[columna] + reparto + (columna - 1 < sobrantes)
            for columna in range(1, columnas)
        ]
        for columna, ancho_columna in enumerate(anchos):
            self._tabla.setColumnWidth(columna, ancho_columna)

    def eventFilter(self, objeto, evento):
        """Recalcula anchos y posiciones de los controles al redimensionar.

        Va por event filter (y no por ``resizeEvent`` del panel) porque la
        tabla o la carta pueden redimensionarse sin que el panel lo haga: al
        asentarse el layout la primera vez, por ejemplo. El reencaje
        diferido cubre el caso en que la cabecera aún no tiene su ancho
        final dentro del propio evento.
        """
        if evento.type() == QEvent.Type.Resize:
            if objeto is self._tabla:
                self._repertir_anchos()
                QTimer.singleShot(0, self._repertir_anchos)
            elif objeto is getattr(self, "_cielo", None):
                self._colocar_flotantes()
            elif objeto is getattr(self, "_vistas", None):
                self._colocar_flotantes()
                self._alternar_vista.raise_()
                self._reiniciar.raise_()
        return super().eventFilter(objeto, evento)

    def _examinar(self) -> None:
        """Selector de carpeta del sistema, empezando en la raíz actual."""
        carpeta = QFileDialog.getExistingDirectory(
            self, "Carpeta raíz de sesiones", self.raiz()
        )
        if carpeta:
            self._raiz.setText(carpeta)


class PanelCalibrar(QWidget):
    """Paso 2: opciones de calibración (SirIL) y estado por sesión."""

    calibrar = pyqtSignal()  # «Calibrar todas»

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta opciones, botón de calibrado y tabla de material/estado/avisos."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(_titulo("Calibración"))
        layout.addWidget(_pista(
            "SirIL calibra cada sesión SIN debayerizar (crudo), con sus "
            "másters (o los de la carpeta global de calibrado) y escribe "
            "SOLO en data/working/calibrados/<sesión>/. Si faltan flats se "
            "usa bias+dark y se avisa. El debayer lo decides al apilar."
        ))

        fila = QHBoxLayout()
        self._opt = QCheckBox("-opt=exp")
        self._opt.setToolTip(
            "Optimiza la sustracción de dark por exposición (solo con bias+dark)."
        )
        self._cc = QCheckBox("-cc=dark")
        self._cc.setToolTip("Corrección cosmética con el dark.")
        fila.addWidget(self._opt)
        fila.addWidget(self._cc)
        fila.addStretch(1)
        self._boton = QPushButton("Calibrar todas")
        self._boton.setObjectName("PrimaryButton")
        self._boton.clicked.connect(self.calibrar)
        fila.addWidget(self._boton)
        layout.addLayout(fila)

        self._tabla = _tabla(["Sesión", "Material", "Másters", "Estado", "Avisos"])
        layout.addWidget(self._tabla, 1)

    def bloquear(self, bloqueado: bool) -> None:
        """Deshabilita el botón mientras corre una tarea en el hilo."""
        self._boton.setEnabled(not bloqueado)
        self._opt.setEnabled(not bloqueado)
        self._cc.setEnabled(not bloqueado)

    def opciones(self) -> dict:
        """Opciones elegidas (``opt``/``cc``) para ``calibrate_session``."""
        return {
            "opt": self._opt.isChecked(),
            "cc": self._cc.isChecked(),
        }

    def mostrar_pendientes(self, sesiones: list[Session], calibradas: set[str]) -> None:
        """Estado inicial: material, másters y qué sesiones ya están en la BD."""
        self._tabla.setRowCount(0)
        for sesion in sesiones:
            self._poner_fila(
                sesion.path.name,
                _material(sesion),
                ", ".join(sorted(sesion.masters)) or "—",
                "Calibrada ✓" if sesion.path.name in calibradas else "Pendiente",
                "",
            )

    def mostrar_resultados(self, resultados: list, avisos: dict[str, list[str]]) -> None:
        """Estado tras la corrida: hecha/error por sesión y sus avisos."""
        self._tabla.setRowCount(0)
        for resultado in resultados:
            sesion = resultado.session
            texto_avisos = " · ".join(avisos.get(sesion.path.name, [])) or "—"
            self._poner_fila(
                sesion.path.name,
                _material(sesion),
                ", ".join(sorted(sesion.masters)) or "—",
                "Calibrada ✓",
                texto_avisos,
            )

    def _poner_fila(self, *celdas: str) -> None:
        """Añade una fila de estado (usada por los dos pintados)."""
        fila = self._tabla.rowCount()
        self._tabla.insertRow(fila)
        for columna, texto in enumerate(celdas):
            self._tabla.setItem(fila, columna, QTableWidgetItem(texto))


class PanelAuditar(QWidget):
    """Paso 3: registro rápido, puntuación dinámica y descarte de frames.

    La auditoría NO repite el registro para cambiar de criterio: las
    métricas crudas ya están en el ``.seq`` y «Actualizar» repuntúa con
    los pesos/umbral/σ del momento, reordena la tabla (de mayor a menor
    puntuación) y repinta los motivos de descarte. La decisión final son
    las casillas: nadie descarta nada sin el usuario. Aquí NO se decide
    drizzle ni debayer: eso es del paso Apilar.
    """

    auditar = pyqtSignal()    # «Registrar y auditar»
    descartar = pyqtSignal()  # «Descartar recomendados»

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta registro, pesos, tabla+miniatura, gráfica y resumen."""
        super().__init__(parent)
        self._cargando = False
        self._registro: Registro | None = None
        self._metricas: list[FrameMetrics] = []
        self._evaluaciones: dict[str, Evaluacion] = {}  # ruta → veredicto
        self._previews: dict[str, QImage] = {}          # caché de miniaturas
        self._preview_img: QImage | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(_titulo("Auditoría"))
        intro_fila = QHBoxLayout()
        intro_fila.addWidget(_pista(
            "Mide con SirIL y revisa los frames. Ajusta pesos y pulsa "
            "«Actualizar» para repuntuar; tú decides qué casillas desmarcar."
        ), 1)
        self._boton = QPushButton("Registrar y auditar")
        self._boton.setObjectName("PrimaryButton")
        self._boton.clicked.connect(self.auditar)
        intro_fila.addWidget(self._boton)
        layout.addLayout(intro_fila)

        controles_fila = QHBoxLayout()
        controles_fila.setSpacing(4)
        controles_fila.addWidget(QLabel("Pesos:"))
        self._pesos: dict[str, QSpinBox] = {}
        valores = Pesos()
        for etiqueta, atributo in (
            ("FWHM", "fwhm"),
            ("Redondez", "redondez"),
            ("Transparencia", "transparencia"),
            ("Fondo", "fondo"),
        ):
            spin = _spin_entero(0, 100, int(getattr(valores, atributo)))
            spin.setFixedWidth(96)
            spin.setToolTip(
                f"Peso de {etiqueta.lower()} en la puntuación 0–100 "
                "(0 = no puntúa ni corta). "
                + (
                    "Transparencia es un indicador relativo derivado del fondo, "
                    "no una medición directa de transmisión atmosférica."
                    if atributo == "transparencia" else ""
                )
            )
            self._pesos[atributo] = spin
            controles_fila.addWidget(QLabel(etiqueta))
            controles_fila.addWidget(spin)
        controles_fila.addStretch(1)
        self._umbral = _spin(0.0, 100.0, 80.0, paso=5.0, decimales=0)
        self._umbral.setFixedWidth(96)
        self._umbral.setToolTip(
            "Puntuación mínima: por debajo, el frame se recomienda "
            "descartar (motivo «Puntuación»)."
        )
        controles_fila.addWidget(QLabel("Mín.:"))
        controles_fila.addWidget(self._umbral)
        self._sigma = _spin(0.5, 10.0, 3.0, paso=0.5, decimales=1)
        self._sigma.setFixedWidth(96)
        self._sigma.setToolTip(
            "Sigma de los cortes por métrica (mediana + σ×MAD, lado malo)."
        )
        controles_fila.addWidget(QLabel("σ:"))
        controles_fila.addWidget(self._sigma)
        self._boton_actualizar = QPushButton("Actualizar")
        self._boton_actualizar.setToolTip(
            "Repuntúa y reordena con los pesos/umbral/σ actuales, sin "
            "volver a registrar."
        )
        self._boton_actualizar.clicked.connect(self._al_actualizar)
        controles_fila.addWidget(self._boton_actualizar)
        self._boton_descartar = QPushButton("Descartar sugeridos")
        self._boton_descartar.setToolTip("Desmarca los frames recomendados para descartar.")
        self._boton_descartar.clicked.connect(self.descartar)
        controles_fila.addWidget(self._boton_descartar)
        layout.addLayout(controles_fila)

        self._tabla = _tabla([
            "Usar", "Frame", "Sesión", "FWHM", "Redondez", "Fondo",
            "Transparencia", "Puntuación", "Descartada",
        ], columna_ancha=1)
        # Frame tiene un ancho fijo suficiente para los nombres habituales;
        # el nombre completo permanece en el tooltip.
        cabecera = self._tabla.horizontalHeader()
        cabecera.setMinimumSectionSize(42)
        for columna, ancho in {
            0: 46, 1: 145, 2: 100, 3: 62, 4: 84, 5: 78,
            6: 112, 7: 88, 8: 100,
        }.items():
            cabecera.setSectionResizeMode(columna, QHeaderView.ResizeMode.Fixed)
            self._tabla.setColumnWidth(columna, ancho)
        # 815 px de columnas + scrollbar vertical (12) + marco (2): no
        # reservar un margen vacío que le quite anchura al visor FITS.
        self._tabla.setMinimumWidth(831)
        self._tabla.setMaximumWidth(831)
        self._tabla.verticalHeader().setDefaultSectionSize(31)
        self._tabla.horizontalHeaderItem(5).setToolTip(
            "Fondo en ADU equivalentes de 16 bits/s: el .seq de SirIL lo "
            "guarda normalizado (0–1). Se convierte con 65535 y se divide "
            "por la exposición para comparar sesiones de distintas duraciones."
        )
        self._tabla.itemChanged.connect(self._alCambiarItem)
        self._tabla.itemSelectionChanged.connect(self._alSeleccionar)

        preview = QWidget()
        preview.setMinimumWidth(300)
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_label = QLabel("Selecciona un frame para verlo.")
        # La miniatura llena el hueco entero (no su sizeHint): por eso
        # Explanding y el filtro de Resize, que la reescala cuando el
        # layout le da más o menos sitio.
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preview_label.setMinimumSize(200, 120)
        self._preview_label.installEventFilter(self)
        preview_layout.addWidget(self._preview_label, 1)
        self._preview_pie = QLabel("")
        self._preview_pie.setObjectName("HintLabel")
        self._preview_pie.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self._preview_pie)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._tabla)
        splitter.addWidget(preview)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([831, 719])
        splitter.setMinimumHeight(320)
        self._splitter = splitter
        layout.addWidget(splitter, 1)

        grafica_fila = QHBoxLayout()
        grafica_fila.addWidget(QLabel("Gráfica:"))
        self._metrica = QComboBox()
        for texto, atributo in (
            ("Puntuado", "weighted"),
            ("FWHM (px)", "fwhm"),
            ("Redondez", "roundness"),
            ("Transparencia", "transparency"),
            ("Fondo (ADU/s)", "background"),
        ):
            self._metrica.addItem(texto, atributo)
        self._metrica.currentIndexChanged.connect(self._pintar_grafica)
        grafica_fila.addWidget(self._metrica)
        grafica_fila.addStretch(1)
        layout.addLayout(grafica_fila)

        self._plot = pg.PlotWidget(enableMenu=False)
        # Conserva la gráfica alta cuando sobra sitio, pero cede altura a
        # la tabla/terminal en ventanas de 800 px con barra de título.
        self._plot.setMinimumHeight(110)
        self._plot.setMaximumHeight(130)
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        for eje in (self._plot.getPlotItem().getAxis("left"),
                    self._plot.getPlotItem().getAxis("bottom")):
            eje.setTextPen(QColor(PALETTE["textDim"]))
        self._curva = self._plot.plot(
            pen=pg.mkPen(QColor(PALETTE["accentLight"]), width=1.5),
            symbol="o",
            symbolSize=5,
            symbolBrush=pg.mkBrush(QColor(PALETTE["accentLight"])),
            symbolPen=pg.mkPen("transparent"),
        )
        self._descartados_plot = pg.ScatterPlotItem(
            pen=pg.mkPen(COLOR_DESCARTE),
            brush=pg.mkBrush(239, 68, 68, 140),
            size=9,
        )
        self._plot.addItem(self._descartados_plot)
        self._umbral_linea = pg.InfiniteLine(
            movable=False,
            pen=pg.mkPen(QColor(PALETTE["textDim"]), style=Qt.PenStyle.DashLine),
        )
        self._plot.addItem(self._umbral_linea)
        self._umbral_linea.hide()
        self._seleccion_plot = pg.ScatterPlotItem(
            size=13,
            pen=pg.mkPen(QColor("#ffffff"), width=2),
            brush=pg.mkBrush(0, 0, 0, 0),
        )
        self._plot.addItem(self._seleccion_plot)
        layout.addWidget(self._plot)

        self._resumen = _pista("Todavía no hay métricas: pulsa «Registrar y auditar».")
        layout.addWidget(self._resumen)

    def bloquear(self, bloqueado: bool) -> None:
        """Deshabilita sus botones y spins mientras corre una tarea en el hilo."""
        self._boton.setEnabled(not bloqueado)
        self._boton_actualizar.setEnabled(not bloqueado)
        self._boton_descartar.setEnabled(not bloqueado)
        for spin in self._pesos.values():
            spin.setEnabled(not bloqueado)
        self._umbral.setEnabled(not bloqueado)
        self._sigma.setEnabled(not bloqueado)

    def limpiar(self) -> None:
        """Borra métricas, veredictos, casillas, gráfica y miniatura."""
        self._cargando = True
        self._tabla.setRowCount(0)
        self._cargando = False
        self._registro = None
        self._metricas = []
        self._evaluaciones = {}
        self._previews.clear()
        self._limpiar_seleccion()
        self._curva.setData([], [])
        self._descartados_plot.setData([], [])
        self._umbral_linea.hide()
        self._resumen.setText(
            "Todavía no hay métricas: pulsa «Registrar y auditar»."
        )

    def pesos(self) -> Pesos:
        """Pesos del usuario para la puntuación; si suman 0, error claro."""
        pesos = Pesos(
            fwhm=float(self._pesos["fwhm"].value()),
            redondez=float(self._pesos["redondez"].value()),
            transparencia=float(self._pesos["transparencia"].value()),
            fondo=float(self._pesos["fondo"].value()),
        )
        if pesos.fwhm + pesos.redondez + pesos.transparencia + pesos.fondo <= 0:
            raise ValueError("Los pesos no pueden ser todos cero.")
        return pesos

    def sigma(self) -> float:
        """Sigma elegido para los cortes por métrica."""
        return self._sigma.value()

    def umbral(self) -> float:
        """Puntuación mínima para recomendar el descarte de un frame."""
        return self._umbral.value()

    def mostrar(self, registro: Registro, metricas: list[FrameMetrics]) -> None:
        """Guarda el registro y pinta la primera evaluación (una fila por frame)."""
        self._registro = registro
        self._metricas = list(metricas)
        self.actualizar()

    def actualizar(self) -> None:
        """Repuntúa con los pesos/umbral/σ actuales, ordena y repinta.

        Es el recálculo «barato»: no registra nada, solo relee las
        métricas que SirIL dejó en el ``.seq``. Conserva las casillas que
        el usuario hubiera desmarcado (van por índice de secuencia, no
        por fila). Falla claro si los pesos suman cero.
        """
        if self._registro is None:
            return
        evaluaciones = evaluar(
            self._metricas, self.pesos(), umbral=self.umbral(), sigma=self.sigma()
        )
        self._evaluaciones = {e.metricas.path: e for e in evaluaciones}
        # Filas de mayor a menor puntuación; lo que SirIL descartó (sin
        # métricas) va al final: no hay puntuación que darle.
        filas = sorted(
            (
                (
                    self._evaluaciones[str(ref.ruta)].metricas.weighted
                    if str(ref.ruta) in self._evaluaciones
                    else -1.0,
                    indice,
                    ref,
                )
                for indice, ref in enumerate(self._registro.frames, start=1)
            ),
            key=lambda fila: (-fila[0], fila[1]),
        )
        previos = set(self.aceptados()) if self._tabla.rowCount() else None
        self._cargando = True
        self._tabla.setRowCount(0)
        for _puntuacion, indice, ref in filas:
            ev = self._evaluaciones.get(str(ref.ruta))
            self._insertar_fila(indice, ref, ev, previos)
        self._cargando = False
        self._limpiar_seleccion()
        self._pintar_grafica()
        self._pintar_resumen()

    def _insertar_fila(
        self,
        indice: int,
        ref,
        ev: Evaluacion | None,
        previos: set[int] | None,
    ) -> None:
        """Una fila: casilla (con su índice de secuencia), métricas y motivo."""
        fila = self._tabla.rowCount()
        self._tabla.insertRow(fila)
        casilla = QTableWidgetItem()
        if ev is None:
            casilla.setFlags(casilla.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            casilla.setToolTip(
                "SirIL descartó este frame al registrar: no se puede apilar."
            )
        else:
            casilla.setFlags(casilla.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            marcada = previos is None or indice in previos
            casilla.setCheckState(
                Qt.CheckState.Checked if marcada else Qt.CheckState.Unchecked
            )
        # El índice de secuencia viaja en la propia fila: la tabla está
        # ordenada por puntuación, no por orden de registro.
        casilla.setData(Qt.ItemDataRole.UserRole, indice)
        casilla.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tabla.setItem(fila, 0, casilla)
        nombre = QTableWidgetItem(ref.ruta.name)
        nombre.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        nombre.setToolTip(str(ref.ruta))
        nombre.setData(Qt.ItemDataRole.UserRole, str(ref.ruta))
        self._tabla.setItem(fila, 1, nombre)
        sesion = QTableWidgetItem(ref.sesion)
        sesion.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        sesion.setToolTip(ref.sesion)
        self._tabla.setItem(fila, 2, sesion)
        celdas = (
            ["—"] * 5
            if ev is None
            else [
                f"{ev.metricas.fwhm:.2f}",
                f"{ev.metricas.roundness:.2f}",
                f"{ev.metricas.background:.1f}",
                f"{ev.metricas.transparency:.2f}",
                f"{ev.metricas.weighted:.1f}",
            ]
        )
        for columna, texto in enumerate(celdas, start=3):
            celda = QTableWidgetItem(texto)
            celda.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tabla.setItem(fila, columna, celda)
        if ev is None:
            motivo, color = "SirIL", QColor(COLOR_DESCARTE)
            ayuda = "SirIL descartó este frame al registrar: sin métricas."
        elif ev.descartada:
            motivo, color = f"Sí · {ev.motivo}", QColor(COLOR_DESCARTE)
            ayuda = f"Recomendado descartar por: {ev.motivo}. Tú decides (casilla)."
        else:
            motivo, color = "No", QColor(PALETTE["textDim"])
            ayuda = ""
        celda_motivo = QTableWidgetItem(motivo)
        celda_motivo.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        celda_motivo.setForeground(color)
        if ayuda:
            celda_motivo.setToolTip(ayuda)
        self._tabla.setItem(fila, 8, celda_motivo)

    def aceptados(self) -> list[int]:
        """Índices 1-based de la secuencia de los frames marcados (no de fila)."""
        indices = []
        for fila in range(self._tabla.rowCount()):
            item = self._tabla.item(fila, 0)
            if item is None or not item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                continue
            if item.checkState() == Qt.CheckState.Checked:
                indices.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return indices

    def descartar_recomendados(self) -> int:
        """Desmarca las casillas de los frames con veredicto «descartada»."""
        cambiados = 0
        self._cargando = True
        for fila in range(self._tabla.rowCount()):
            casilla = self._tabla.item(fila, 0)
            nombre = self._tabla.item(fila, 1)
            if casilla is None or nombre is None:
                continue
            ev = self._evaluaciones.get(nombre.data(Qt.ItemDataRole.UserRole))
            if (
                ev is not None
                and ev.descartada
                and casilla.flags() & Qt.ItemFlag.ItemIsUserCheckable
                and casilla.checkState() == Qt.CheckState.Checked
            ):
                casilla.setCheckState(Qt.CheckState.Unchecked)
                cambiados += 1
        self._cargando = False
        self._pintar_grafica()
        return cambiados

    def _al_actualizar(self) -> None:
        """Botón «Actualizar»: repuntúa al instante (sin registrar nada)."""
        try:
            self.actualizar()
        except ValueError as exc:
            self._resumen.setText(str(exc))

    def _alCambiarItem(self, _item: QTableWidgetItem) -> None:
        """Cambiaron casillas → repinta la gráfica (los rojos dependen de ellas)."""
        if not self._cargando:
            self._pintar_grafica()

    def _alSeleccionar(self) -> None:
        """Frame seleccionado → anillo en la gráfica + miniatura a la derecha."""
        if self._cargando:
            return
        fila = self._tabla.currentRow()
        casilla = self._tabla.item(fila, 0) if fila >= 0 else None
        nombre = self._tabla.item(fila, 1) if fila >= 0 else None
        if casilla is None or nombre is None:
            return
        ruta = nombre.data(Qt.ItemDataRole.UserRole)
        ev = self._evaluaciones.get(ruta)
        indice = int(casilla.data(Qt.ItemDataRole.UserRole))
        if ev is None:
            self._seleccion_plot.setData([], [])
            pie = f"{nombre.text()} · descartado por SirIL al registrar"
        else:
            atributo = self._metrica.currentData()
            self._seleccion_plot.setData(
                [indice], [float(getattr(ev.metricas, atributo))]
            )
            pie = f"{nombre.text()} · {ev.metricas.weighted:.1f} puntos"
            if ev.descartada:
                pie += f" · descartar: {ev.motivo}"
        self._mostrar_preview(Path(ruta), pie)

    def _mostrar_preview(self, ruta: Path, pie: str) -> None:
        """Carga (con caché de 3) y escala la miniatura del frame elegido."""
        qimg = self._previews.get(str(ruta))
        if qimg is None:
            qimg = _preview_fits(ruta)
            if qimg is not None:
                if len(self._previews) >= 3:
                    self._previews.clear()
                self._previews[str(ruta)] = qimg
        self._preview_img = qimg
        self._preview_pie.setText(pie)
        if qimg is None:
            self._preview_label.setText("Sin vista previa: ¿FITS ilegible?")
            return
        self._preview_label.setText("")
        self._escalar_preview()

    def _escalar_preview(self) -> None:
        """Escala la miniatura al hueco (se repite en cada resize del panel)."""
        if self._preview_img is None:
            return
        tam = self._preview_label.size()
        if tam.width() < 40 or tam.height() < 40:
            tam = self.size()
        self._preview_label.setPixmap(
            QPixmap.fromImage(self._preview_img).scaled(
                tam,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, evento: QResizeEvent) -> None:
        """Al cambiar el tamaño del panel, la miniatura se reescala."""
        super().resizeEvent(evento)
        self._escalar_preview()

    def eventFilter(self, objeto, evento) -> bool:
        """El label de la miniatura cambia de tamaño con el layout: reescalar ahí.

        Sin esto la imagen solo se reescalaba al redimensionar la ventana
        y se quedaba pequeña en el primer pintado (el sizeHint del label
        es el de la miniatura anterior).
        """
        if objeto is self._preview_label and evento.type() == QEvent.Type.Resize:
            self._escalar_preview()
        return super().eventFilter(objeto, evento)

    def _limpiar_seleccion(self) -> None:
        """Tras reordenar: sin anillo y la miniatura vuelve al texto inicial."""
        self._seleccion_plot.setData([], [])
        self._preview_img = None
        self._preview_label.setText("Selecciona un frame para verlo.")
        self._preview_pie.setText("")

    def _pintar_grafica(self) -> None:
        """Curva de la métrica elegida por frame; fuera de las casillas, en rojo.

        El eje x es el orden de registro (no el de la tabla ordenada):
        así se ve la evolución a lo largo de la noche.
        """
        atributo = self._metrica.currentData()
        self._plot.setLabel("left", self._metrica.currentText())
        puntos: list[tuple[int, float, bool]] = []
        for fila in range(self._tabla.rowCount()):
            casilla = self._tabla.item(fila, 0)
            nombre = self._tabla.item(fila, 1)
            if casilla is None or nombre is None:
                continue
            ev = self._evaluaciones.get(nombre.data(Qt.ItemDataRole.UserRole))
            if ev is None:
                continue
            indice = int(casilla.data(Qt.ItemDataRole.UserRole))
            marcada = casilla.checkState() == Qt.CheckState.Checked
            puntos.append(
                (indice, float(getattr(ev.metricas, atributo)), marcada)
            )
        # La tabla va ordenada por puntuación: la curva se reordena por
        # índice de registro para que la línea avance por la noche y no
        # zigzaguee saltando de un frame a otro.
        puntos.sort()
        xs = [indice for indice, valor, marcada in puntos if marcada]
        ys = [valor for indice, valor, marcada in puntos if marcada]
        xd = [indice for indice, valor, marcada in puntos if not marcada]
        yd = [valor for indice, valor, marcada in puntos if not marcada]
        self._curva.setData(xs, ys)
        self._descartados_plot.setData(xd, yd)
        if atributo == "weighted" and self._evaluaciones:
            self._umbral_linea.setValue(self.umbral())
            self._umbral_linea.show()
        else:
            self._umbral_linea.hide()
        if not self._cargando:
            self._alSeleccionar()  # recoloca el anillo del frame seleccionado

    def _pintar_resumen(self) -> None:
        """Resumen: con métricas, cuántos descartó SirIL y cuántos recomienda."""
        if self._registro is None:
            return
        descartados_siril = len(self._registro.frames) - len(self._metricas)
        recomendados = sum(1 for e in self._evaluaciones.values() if e.descartada)
        sigma = self.sigma()
        aviso = ""
        if self._metricas and recomendados == len(self._metricas):
            aviso = (
                " ⚠ El mínimo se lleva TODOS los frames: la puntuación es "
                "relativa al pool, baja «Mín.» o revisa los pesos."
            )
        self._resumen.setText(
            f"{len(self._metricas)} frames con métricas de "
            f"{len(self._registro.frames)}"
            + (
                f" · {descartados_siril} los descartó SirIL al registrar"
                if descartados_siril
                else ""
            )
            + f" · {recomendados} descartes recomendados (mínimo {self.umbral():g}, "
            f"σ={sigma:g}). El motivo está en la tabla; las casillas son tuyas."
            + aviso
        )


class PanelApilar(QWidget):
    """Paso 4: registro final (drizzle/debayer), opciones de ``stack`` y salidas."""

    apilar = pyqtSignal()  # «Apilar»

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta nombre, registro final, opciones de stack, botón y salidas."""
        super().__init__(parent)
        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        exterior.addWidget(self._scroll)
        contenido = QWidget()
        self._scroll.setWidget(contenido)
        layout = QVBoxLayout(contenido)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        cabecera = QHBoxLayout()
        cabecera.addWidget(_titulo("Apilado"))
        cabecera.addStretch(1)
        self._boton = QPushButton("Apilar")
        self._boton.setObjectName("PrimaryButton")
        self._boton.clicked.connect(self.apilar)
        cabecera.addWidget(self._boton)
        layout.addLayout(cabecera)
        layout.addWidget(_pista(
            "Configura el registro final y el apilado en SirIL. Solo se usan "
            "los frames aceptados; los originales no se modifican."
        ))

        nombre_fila = QHBoxLayout()
        nombre_fila.addWidget(QLabel("Nombre:"))
        self._nombre = QLineEdit()
        self._nombre.setPlaceholderText("Vacío: result_<tiempo de integración>s")
        nombre_fila.addWidget(self._nombre, 1)
        layout.addLayout(nombre_fila)

        def bloque(titulo: str, alto: int = 90) -> tuple[QGroupBox, QVBoxLayout]:
            """Agrupa controles como la referencia sin cambiar sus opciones."""
            caja = QGroupBox(titulo)
            caja.setMinimumHeight(alto)
            caja.setStyleSheet(
                "QGroupBox { border: 1px solid #26374f; border-radius: 6px; "
                "margin-top: 14px; background: #0e1625; } "
                "QGroupBox::title { color: #58a6ff; subcontrol-origin: margin; "
                "left: 12px; padding: 0 4px; }"
            )
            contenido = QVBoxLayout(caja)
            contenido.setContentsMargins(14, 10, 14, 10)
            contenido.setSpacing(8)
            layout.addWidget(caja)
            return caja, contenido

        _, metodo = bloque("1. Método de integración y ponderación", 100)
        fila_metodo = QHBoxLayout()
        fila_metodo.addWidget(QLabel("Método de apilado:"))
        self._integracion = QComboBox()
        nombres_metodo = {
            "mean": "Promedio con rechazo (mean)", "med": "Mediana (med)",
            "sum": "Suma (sum)", "min": "Mínimo (min)", "max": "Máximo (max)",
        }
        for modo in INTEGRACIONES:
            self._integracion.addItem(nombres_metodo[modo], modo)
        self._integracion.setCurrentIndex(INTEGRACIONES.index("mean"))
        fila_metodo.addWidget(self._integracion, 1)
        fila_metodo.addWidget(QLabel("Ponderación de tomas:"))
        self._ponderacion = QComboBox()
        self._ponderacion.addItem("(ninguna)", None)
        nombres_peso = {
            "noise": "Ruido de fondo (noise)", "wfwhm": "FWHM ponderado (wfwhm)",
            "nbstars": "Número de estrellas (nbstars)",
            "nbstack": "Número de integraciones (nbstack)",
        }
        for modo in PONDERACIONES:
            self._ponderacion.addItem(nombres_peso[modo], modo)
        fila_metodo.addWidget(self._ponderacion, 1)
        metodo.addLayout(fila_metodo)
        fila_norm = QHBoxLayout()
        fila_norm.addWidget(QLabel("Normalización de entrada:"))
        self._norm = QComboBox()
        self._norm.addItem("(la de SirIL)", None)
        nombres_norm = {
            "add": "Aditiva (add)", "addscale": "Aditiva + escala (addscale)",
            "mul": "Multiplicativa (mul)",
            "mulscale": "Multiplicativa + escala (mulscale)",
            "nonorm": "Ninguna (nonorm)",
        }
        for modo in (*NORMS, "nonorm"):
            self._norm.addItem(nombres_norm[modo], modo)
        fila_norm.addWidget(self._norm, 1)
        fila_norm.addWidget(QLabel("Modo de encuadre:"))
        self._framing = QComboBox()
        for texto, modo in (
            ("current — referencia", "current"),
            ("min — área común", "min"),
            ("max — área completa", "max"),
            ("cog — centro de gravedad", "cog"),
        ):
            self._framing.addItem(texto, modo)
        self._framing.setCurrentIndex(1)
        fila_norm.addWidget(self._framing, 1)
        metodo.addLayout(fila_norm)

        _, rechazo_bloque = bloque("2. Rechazo de píxeles", 90)
        fila_rechazo = QHBoxLayout()
        fila_rechazo.addWidget(QLabel("Algoritmo:"))
        self._rechazo = QComboBox()
        nombres_rechazo = {
            "none": "Sin rechazo", "percentile": "Percentile clipping",
            "sigma": "Sigma clipping", "median": "Median clipping",
            "winsorized": "Winsorized sigma clipping",
            "linear": "Linear fit clipping", "generalized": "Generalized ESD",
            "mad": "MAD clipping",
        }
        for modo in RECHAZOS:
            self._rechazo.addItem(nombres_rechazo[modo], modo)
        self._rechazo.setCurrentIndex(RECHAZOS.index("winsorized"))
        fila_rechazo.addWidget(self._rechazo, 1)
        fila_rechazo.addWidget(QLabel("Sigma bajo:"))
        self._sigma_low = _spin(0.1, 20.0, 3.0, paso=0.5, decimales=1)
        fila_rechazo.addWidget(self._sigma_low, 1)
        fila_rechazo.addWidget(QLabel("Sigma alto:"))
        self._sigma_high = _spin(0.1, 20.0, 3.0, paso=0.5, decimales=1)
        fila_rechazo.addWidget(self._sigma_high, 1)
        rechazo_bloque.addLayout(fila_rechazo)
        fila_mapas = QHBoxLayout()
        self._rejmaps = QCheckBox("Generar mapas de rechazo FITS")
        self._rejmaps.setToolTip("SirIL: -rejmaps genera dos mapas; -rejmap uno fusionado.")
        fila_mapas.addWidget(self._rejmaps)
        self._merge_rejmaps = QCheckBox("Fusionar alto y bajo")
        self._merge_rejmaps.setChecked(True)
        fila_mapas.addWidget(self._merge_rejmaps)
        fila_mapas.addStretch(1)
        rechazo_bloque.addLayout(fila_mapas)

        _, drizzle_bloque = bloque("3. Registro final y Bayer Drizzle", 90)

        registro_fila = QHBoxLayout()
        self._drizzle = QCheckBox("Bayer Drizzle")
        self._drizzle.setToolTip(
            "seqapplyreg -drizzle con la escala elegida. "
            "SirIL debayeriza solo al drizzlezar: sin drizzle, los CFA se "
            "debayerizan antes de registrar."
        )
        self._scale = QComboBox()
        for escala in (1.0, 1.4, 1.6, 2.0):
            self._scale.addItem(f"{escala:.1f}×", escala)
        self._pixfrac = _spin(0.1, 1.2, 1.0, paso=0.05, decimales=2)
        self._pixfrac.setToolTip("Pixfrac de drizzle (fracción del píxel de salida).")
        self._kernel = QComboBox()
        # Núcleos que documenta `help seqapplyreg` de SirIL 1.4.4.
        for nucleo in ("square", "gaussian", "point", "turbo", "lanczos2", "lanczos3"):
            self._kernel.addItem(nucleo)
        registro_fila.addWidget(self._drizzle)
        registro_fila.addWidget(QLabel("Escala:"))
        registro_fila.addWidget(self._scale, 1)
        registro_fila.addWidget(QLabel("Pixfrac:"))
        registro_fila.addWidget(self._pixfrac, 1)
        registro_fila.addWidget(QLabel("Kernel:"))
        registro_fila.addWidget(self._kernel, 1)
        drizzle_bloque.addLayout(registro_fila)
        flat_fila = QHBoxLayout()
        self._flat_drizzle = QCheckBox("Ponderar gotas por máster flat (-flat)")
        self._flat_drizzle.setToolTip(
            "Selecciona explícitamente un máster flat aplicable a todas las "
            "tomas; SirIL lo usa para ponderar gotas, no para recalibrar."
        )
        flat_fila.addWidget(self._flat_drizzle)
        self._ruta_flat = QLineEdit()
        self._ruta_flat.setPlaceholderText("Elige un máster flat FITS común a las tomas")
        flat_fila.addWidget(self._ruta_flat, 1)
        buscar_flat = QPushButton("Elegir…")
        buscar_flat.clicked.connect(self._elegir_flat)
        flat_fila.addWidget(buscar_flat)
        drizzle_bloque.addLayout(flat_fila)

        _, salida_bloque = bloque("4. Opciones de guardado del máster", 78)
        salida_fila = QHBoxLayout()
        self._bit32 = QCheckBox("FITS de 32 bits (-32b)")
        self._bit32.setChecked(True)
        salida_fila.addWidget(self._bit32)
        self._output_norm = QCheckBox("Normalizar salida [0, 1] (-output_norm)")
        salida_fila.addWidget(self._output_norm)
        self._rgb_equal = QCheckBox("Igualar fondo RGB (-rgb_equal)")
        salida_fila.addWidget(self._rgb_equal)
        salida_fila.addStretch(1)
        salida_bloque.addLayout(salida_fila)
        salida_fila = QHBoxLayout()
        self._fastnorm = QCheckBox("Normalización rápida de entrada (-fastnorm)")
        self._fastnorm.setToolTip("Solo con mean/med; no normaliza la salida.")
        salida_fila.addWidget(self._fastnorm)
        salida_fila.addStretch(1)
        salida_bloque.addLayout(salida_fila)
        salida_bloque.addWidget(_pista("Salida: data/working/apilados/<nombre>/."))

        extra_fila = QHBoxLayout()
        extra_fila.addWidget(QLabel("Argumentos extra:"))
        self._extra = QLineEdit()
        self._extra.setPlaceholderText("otros argumentos de stack, separados por espacios")
        self._extra.setToolTip("Avanzado: consulta help stack de tu versión de SirIL.")
        extra_fila.addWidget(self._extra, 1)
        layout.addLayout(extra_fila)

        _, guia_bloque = bloque("Guía de parámetros", 62)
        self._guia = _pista("")
        self._conteo_aceptados = 0
        guia_bloque.addWidget(self._guia)
        self._integracion.currentIndexChanged.connect(self._actualizar_guia)
        self._rechazo.currentIndexChanged.connect(self._actualizar_guia)
        self._drizzle.toggled.connect(self._actualizar_guia)
        self._scale.currentIndexChanged.connect(self._actualizar_guia)
        self._rejmaps.toggled.connect(self._merge_rejmaps.setEnabled)
        self._merge_rejmaps.setEnabled(False)
        self._drizzle.toggled.connect(self._scale.setEnabled)
        self._drizzle.toggled.connect(self._pixfrac.setEnabled)
        self._drizzle.toggled.connect(self._kernel.setEnabled)
        self._drizzle.toggled.connect(self._flat_drizzle.setEnabled)
        self._drizzle.toggled.connect(self._ruta_flat.setEnabled)
        self._drizzle.toggled.connect(buscar_flat.setEnabled)
        for control in (self._scale, self._pixfrac, self._kernel,
                        self._flat_drizzle, self._ruta_flat, buscar_flat):
            control.setEnabled(False)
        self._actualizar_guia()

        self._salidas_titulo = QLabel("Salidas:")
        self._salidas_titulo.hide()
        layout.addWidget(self._salidas_titulo)
        self._salidas = QListWidget()
        self._salidas.setMaximumHeight(60)
        self._salidas.hide()
        layout.addWidget(self._salidas)

        self._siril_aviso = _pista("")
        layout.addWidget(self._siril_aviso)
        layout.addStretch(1)

    def _actualizar_guia(self) -> None:
        """Explica las dependencias del guion de SirIL sin imponer valores."""
        promedio = self._integracion.currentData() == "mean"
        self._guia.setText(
            f"{self._conteo_aceptados} tomas seleccionadas en Auditoría. "
            + ("Mean admite rechazo y ponderación. " if promedio else
             "Esta integración no aplica rechazo ni ponderación. ")
            + (f"Drizzle ×{self._scale.currentData():g} se aplica en el registro final. "
               if self._drizzle.isChecked() else
               "Sin drizzle se mantiene la escala del registro. ")
            + ("Con pocas tomas, revisa el rechazo antes de ejecutar. "
               if 0 < self._conteo_aceptados < 8 and promedio else "")
            + "Comprueba el log antes de apilar."
        )

    def actualizar_conteo(self, n: int) -> None:
        """Refleja el número real de casillas marcadas, nunca uno ficticio."""
        self._conteo_aceptados = n
        self._actualizar_guia()

    def _elegir_flat(self) -> None:
        """Permite elegir explícitamente el flat de drizzle, sin tocar los originales."""
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Máster flat para drizzle", "", "FITS (*.fit *.fits *.fts)"
        )
        if ruta:
            self._ruta_flat.setText(ruta)

    def bloquear(self, bloqueado: bool) -> None:
        """Deshabilita el botón mientras corre una tarea en el hilo."""
        self._boton.setEnabled(not bloqueado)

    def limpiar(self) -> None:
        """Vacía las salidas de la corrida anterior (reinicio del asistente)."""
        self._salidas.clear()
        self._salidas.hide()
        self._salidas_titulo.hide()

    def nombre(self) -> str:
        """Nombre escrito por el usuario, o vacío para generar uno con la exposición."""
        nombre = self._nombre.text().strip()
        if "/" in nombre or "\\" in nombre or nombre in (".", ".."):
            raise ValueError("El nombre del apilado no puede tener barras ni ser «.»/«..».")
        return nombre

    def opciones_registro(self) -> dict:
        """Opciones del registro final (drizzle y sus parámetros) para ``register_pool``."""
        flat = None
        if self._flat_drizzle.isChecked():
            flat = Path(self._ruta_flat.text().strip())
            if not self._drizzle.isChecked() or not flat.is_file():
                raise ValueError("El flat de drizzle requiere drizzle y un FITS existente.")
        return {
            "drizzle": self._drizzle.isChecked(),
            "scale": self._scale.currentData(),
            "framing": self._framing.currentData(),
            "pixfrac": self._pixfrac.value(),
            "kernel": self._kernel.currentText(),
            "flat": flat,
        }

    def opciones(self) -> StackOptions:
        """Opciones del formulario; valida ya mismo la combinación contra SirIL."""
        try:
            extra = shlex.split(self._extra.text())
        except ValueError as exc:
            raise ValueError(f"Argumentos extra: {exc}") from exc
        opciones = StackOptions(
            integration=self._integracion.currentData(),
            rejection=self._rechazo.currentData(),
            sigma_low=self._sigma_low.value(),
            sigma_high=self._sigma_high.value(),
            weighting=self._ponderacion.currentData(),
            norm=self._norm.currentData(),
            fastnorm=self._fastnorm.isChecked(),
            bit32=self._bit32.isChecked(),
            rejmaps=self._rejmaps.isChecked(),
            merge_rejmaps=self._merge_rejmaps.isChecked(),
            output_norm=self._output_norm.isChecked(),
            rgb_equal=self._rgb_equal.isChecked(),
            extra_args=extra,
        )
        opciones.to_siril_args()  # falla aquí, no a mitad de la corrida
        return opciones

    def mostrar_salidas(self, salidas: list[Path]) -> None:
        """Lista los FITS generados (la ruta completa va en la pista del ratón)."""
        self._salidas.clear()
        self._salidas.setVisible(bool(salidas))
        self._salidas_titulo.setVisible(bool(salidas))
        for ruta in salidas:
            item = QListWidgetItem(ruta.name)
            item.setToolTip(str(ruta))
            self._salidas.addItem(item)

    def avisar_siril(self, falta: bool) -> None:
        """Aviso persistente de que SirIL no está localizado (si no lo está)."""
        self._siril_aviso.setText(
            "SirIL no está en el PATH: al ejecutar te pediré que elijas su ruta."
            if falta
            else ""
        )


class PanelFinal(QWidget):
    """Paso 5: resumen del flujo, salidas y acción de empezar de nuevo."""

    reiniciar = pyqtSignal()  # «Empezar de nuevo»

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta resumen, lista de salidas y los dos botones de cierre."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(_titulo("Final"))
        self._resumen = QLabel("Todavía no hay apilados.")
        self._resumen.setObjectName("PanelTitle")
        self._resumen.setWordWrap(True)
        layout.addWidget(self._resumen)

        self._salidas = QListWidget()
        self._salidas.setMaximumHeight(70)
        self._salidas.currentItemChanged.connect(self._seleccionar_salida)
        layout.addWidget(self._salidas)
        self._preview_label = QLabel("El apilado se mostrará aquí.")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumHeight(200)
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preview_label.installEventFilter(self)
        layout.addWidget(self._preview_label, 1)
        self._imagen: QImage | None = None

        fila = QHBoxLayout()
        self._abrir_boton = QPushButton("Abrir carpeta de apilados")
        self._abrir_boton.clicked.connect(self._abrir)
        self._abrir_boton.setEnabled(False)
        self._reiniciar_boton = QPushButton("Empezar de nuevo")
        self._reiniciar_boton.clicked.connect(self.reiniciar)
        fila.addWidget(self._abrir_boton)
        self._siril_boton = QPushButton("Abrir en SirIL")
        self._siril_boton.setEnabled(False)
        self._siril_boton.clicked.connect(self._abrir_siril)
        fila.addWidget(self._siril_boton)
        fila.addWidget(self._reiniciar_boton)
        fila.addStretch(1)
        layout.addLayout(fila)

        layout.addWidget(_pista(
            "Si algo salió raro, revisa el log de abajo: SirIL escribe ahí "
            "lo que hace (y lo que le falta)."
        ))
        self._carpeta: Path | None = None

    def bloquear(self, bloqueado: bool) -> None:
        """Mientras corre una tarea no se puede reiniciar el asistente."""
        self._reiniciar_boton.setEnabled(not bloqueado)

    def limpiar(self) -> None:
        """Borra resumen y salidas (reinicio del asistente)."""
        self._resumen.setText("Todavía no hay apilados.")
        self._salidas.clear()
        self._imagen = None
        self._preview_label.setText("El apilado se mostrará aquí.")
        self._carpeta = None
        self._abrir_boton.setEnabled(False)
        self._siril_boton.setEnabled(False)

    def mostrar(
        self,
        *,
        nombre: str,
        sesiones: int,
        registrados: int,
        descartados: int,
        salidas: list[Path],
    ) -> None:
        """Pinta el resumen del apilado terminado y sus imágenes."""
        self._resumen.setText(
            f"«{nombre}» listo: {sesiones} sesiones · {registrados} frames "
            f"registrados · {descartados} descartados por ti · "
            f"{len(salidas)} imagen(es) generada(s)."
        )
        self._salidas.clear()
        for ruta in salidas:
            item = QListWidgetItem(ruta.name)
            item.setToolTip(str(ruta))
            self._salidas.addItem(item)
        if salidas:
            self._salidas.setCurrentRow(len(salidas) - 1)
        else:
            self._seleccionar_salida(None)
        self._carpeta = salidas[0].parent if salidas else None
        self._abrir_boton.setEnabled(self._carpeta is not None)
        self._siril_boton.setEnabled(bool(salidas))

    def _seleccionar_salida(self, item, _anterior=None) -> None:
        """Muestra la salida elegida, sin cambiar datos ni archivos FITS."""
        self._imagen = _preview_fits(Path(item.toolTip())) if item else None
        if self._imagen is None:
            self._preview_label.setText("Vista previa no disponible; abre el FITS desde la carpeta.")
        else:
            self._mostrar_imagen()

    def eventFilter(self, objeto, evento):
        """Reescala la vista previa al cambiar el tamaño de la ventana."""
        if objeto is self._preview_label and evento.type() == QEvent.Type.Resize:
            self._mostrar_imagen()
        return super().eventFilter(objeto, evento)

    def _mostrar_imagen(self) -> None:
        """Ajusta la miniatura FITS al espacio disponible sin modificar el archivo."""
        if self._imagen is not None:
            self._preview_label.setPixmap(QPixmap.fromImage(self._imagen).scaled(
                self._preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def _abrir(self) -> None:
        """Abre la carpeta de salida en el gestor de archivos del sistema."""
        if self._carpeta is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._carpeta)))

    def _abrir_siril(self) -> None:
        """Abre el FITS seleccionado en la aplicación gráfica de SirIL."""
        item = self._salidas.currentItem() or self._salidas.item(self._salidas.count() - 1)
        if item is None:
            return
        ruta = Path(item.toolTip())
        cli = find_siril()
        candidato = Path(cli).with_name("siril.exe") if cli else None
        grafico = which("siril") or which("Siril.exe")
        ejecutable = candidato if candidato and candidato.is_file() else grafico
        if not ejecutable or not ruta.is_file():
            QMessageBox.warning(self, "SirIL", "No se encontró SirIL gráfico o el FITS ya no existe.")
            return
        try:
            subprocess.Popen([str(ejecutable), str(ruta)])
        except OSError as exc:
            QMessageBox.warning(self, "SirIL", f"No se pudo abrir el FITS: {exc}")


def _material(sesion: Session) -> str:
    """Resumen de material de calibración («bias 100 · dark 40», o «—»)."""
    partes = [
        f"{etiqueta} {len(sesion.frames.get(clave, []))}"
        for clave, etiqueta in MATERIAL
        if sesion.frames.get(clave)
    ]
    return " · ".join(partes) or "—"
