"""Planetario visual simple dibujado con QPainter (sin dependencias extra).

Es el banco de pruebas de la conexión bidireccional **Planificador ↔
Planetario** antes de construir el planetario completo:

- Seleccionar un objeto en el Planificador → el planetario lo centra.
- Hacer clic en un objeto del planetario → el Planificador lo muestra.
- Hacer clic en el cielo vacío → emite ``region_clicked`` (para crear una
  región de interés, que a su vez NO se pinta aquí: solo va a planificación).

Proyección **gnomónica** (tangente al centro de la vista): los campos
pequeños se ven sin deformación y las rectas de RA/Dec se pueden muestrear.
Orientación de carta celeste estándar: **norte arriba, este a la izquierda**
(RA creciente hacia la izquierda).

Los datos salen de las tablas ``stars`` (HYG, mag ≤ 8) y ``catalog``
a través de :mod:`planners.sky_loader` (esta UI no hace SQL); las
regiones del catálogo personal no se cargan (requisito: no ensuciar la vista).
"""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from planners.sky_loader import load_objects, load_stars

#: Nº máximo de estrellas pintadas por refresco (más allá se ven las más brillantes).
MAX_STARS_DRAWN = 6000
#: Separación mínima (px) para que un clic seleccione un objeto.
CLICK_RADIUS_PX = 10
#: Campo vertical inicial de la vista (grados).
DEFAULT_VIEW_FOV_DEG = 40.0
#: Pasos de la rejilla RA/Dec candidatos (grados), de más fino a más grueso.
GRID_STEPS_DEG = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 45.0)

#: Color de marcador por catálogo.
CATALOG_COLORS: dict[str, QColor] = {
    "messier": QColor("#ffd700"),   # dorado
    "ngc": QColor("#87ceeb"),       # celeste
    "ic": QColor("#22c55e"),        # verde
    "ldn": QColor("#b91c1c"),       # rojo oscuro
}
DEFAULT_MARKER_COLOR = QColor("#9ca3af")  # gris

#: Color de estrella por clase espectral (1ª letra del tipo).
SPECTRAL_COLORS: dict[str, QColor] = {
    "O": QColor("#9db4ff"), "B": QColor("#aabfff"), "A": QColor("#cad7ff"),
    "F": QColor("#f8f7ff"), "G": QColor("#fff4ea"), "K": QColor("#ffd2a1"),
    "M": QColor("#ffcc6f"),
}
STAR_COLOR = QColor("#e6edf3")


# ----------------------------------------------------------------- proyección
def gnomonic(
    ra_deg, dec_deg, ra0_deg: float, dec0_deg: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Proyección gnomónica de (ra, dec) hacia el centro (ra0, dec0).

    Devuelve ``(xi, eta)`` en radianes (xi este, eta norte) y una máscara de
    visibilidad: los objetos detrás del plano tangente (cos c ≤ 0) no se ven.
    Siempre devuelve arrays 1-d (también con entrada escalar).
    """
    ra = np.radians(np.atleast_1d(np.asarray(ra_deg, dtype=float)))
    dec = np.radians(np.atleast_1d(np.asarray(dec_deg, dtype=float)))
    ra0 = math.radians(ra0_deg)
    dec0 = math.radians(dec0_deg)

    cos_ra = np.cos(ra - ra0)
    sin_dec0, cos_dec0 = math.sin(dec0), math.cos(dec0)
    cos_c = sin_dec0 * np.sin(dec) + cos_dec0 * np.cos(dec) * cos_ra
    ok = cos_c > 1e-9
    denom = np.where(ok, cos_c, 1.0)

    xi = np.cos(dec) * np.sin(ra - ra0) / denom
    eta = (cos_dec0 * np.sin(dec) - sin_dec0 * np.cos(dec) * cos_ra) / denom
    return xi, eta, ok


def inverse_gnomonic(xi: float, eta: float, ra0_deg: float, dec0_deg: float) -> tuple[float, float]:
    """Inversa de :func:`gnomonic`: de (xi, eta) en radianes a (ra, dec) en grados."""
    rho = math.hypot(xi, eta)
    if rho < 1e-12:
        return ra0_deg % 360.0, dec0_deg
    c = math.atan(rho)
    ra0 = math.radians(ra0_deg)
    dec0 = math.radians(dec0_deg)
    sin_c, cos_c = math.sin(c), math.cos(c)
    dec = math.asin(cos_c * math.sin(dec0) + (eta / rho) * sin_c * math.cos(dec0))
    ra = ra0 + math.atan2(
        xi * sin_c,
        rho * math.cos(dec0) * cos_c - eta * math.sin(dec0) * sin_c,
    )
    return math.degrees(ra) % 360.0, math.degrees(dec)


def star_color(spectral: str | None) -> QColor:
    """Color de la estrella a partir de su clase espectral ('G2V' → amarillo).

    Devuelve una copia: quien la use puede cambiar el alfa sin tocar la
    paleta compartida.
    """
    if spectral:
        color = SPECTRAL_COLORS.get(spectral[0].upper())
        if color is not None:
            return QColor(color)
    return QColor(STAR_COLOR)


def marker_color(catalog: str) -> QColor:
    """Color del marcador de un objeto según su catálogo (copia)."""
    return QColor(CATALOG_COLORS.get(catalog, DEFAULT_MARKER_COLOR))


def grid_step_for(span_deg: float, target_lines: int = 6) -> float:
    """Paso de rejilla que deja ~``target_lines`` líneas en ``span_deg``."""
    ideal = span_deg / target_lines
    for step in GRID_STEPS_DEG:
        if step >= ideal:
            return step
    return GRID_STEPS_DEG[-1]


# --------------------------------------------------------------------- datos
# La consulta vive en planners/sky_loader (sin SQL en la UI).


class PlanetarioVisual(QWidget):
    """Lienzo del cielo con zoom, arrastre, rejilla y encuadre.

    Señales:

    - ``object_clicked(object_id, catalog)``: clic sobre un objeto → el
      Planificador lo muestra en la búsqueda.
    - ``region_clicked(ra_hours, dec_deg)``: clic sobre cielo vacío →
      candidato a región de interés.
    - ``view_changed(ra_hours, dec_deg, fov_deg)``: cambia la vista.
    """

    object_clicked = pyqtSignal(str, str)
    region_clicked = pyqtSignal(float, float)
    view_changed = pyqtSignal(float, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumSize(320, 240)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        # Vista
        self._ra0 = 0.0            # centro en grados (0-360)
        self._dec0 = 0.0
        self._fov_deg = DEFAULT_VIEW_FOV_DEG
        self._label = ""           # etiqueta del centro (p. ej. 'M31')

        # Estado de interacción
        self._dragging = False
        self._last_pos = QPointF()
        self._moved_pixels = 0.0    # para distinguir clic de arrastre

        # Encuadre y resaltado
        self._framing: tuple[float, float, float, float, int, int] | None = None
        self._selected: tuple[str, str] | None = None

        self._stars = load_stars()
        self._objects = load_objects()

    # ------------------------------------------------------------ API pública
    def set_center(self, ra_hours: float, dec_deg: float, label: str = "") -> None:
        """Centra la vista en (RA en horas, Dec en grados) y opcionalmente etiqueta."""
        self._ra0 = (ra_hours * 15.0) % 360.0
        self._dec0 = max(-89.9, min(89.9, dec_deg))
        self._label = label
        self._emit_view()
        self.update()

    def set_target(self, object_id: str, catalog: str | None = None) -> bool:
        """Centra la vista en ``object_id`` y lo resalta. Devuelve si existía."""
        index = self._find_object_index(object_id, catalog)
        if index is None:
            return False
        self._selected = (object_id, self._objects["catalogs"][index])
        self.set_center(
            float(self._objects["ra"][index]) / 15.0,
            float(self._objects["dec"][index]),
            object_id,
        )
        return True

    def set_framing(
        self,
        ra_hours: float,
        dec_deg: float,
        fov_major_deg: float,
        fov_minor_deg: float,
        tiles_x: int = 1,
        tiles_y: int = 1,
    ) -> None:
        """Dibuja el rectángulo de encuadre y sus teselas (None lo borra)."""
        if ra_hours is None or dec_deg is None or not fov_major_deg or not fov_minor_deg:
            self._framing = None
        else:
            self._framing = (
                (ra_hours * 15.0) % 360.0, dec_deg,
                fov_major_deg, fov_minor_deg,
                max(1, int(tiles_x or 1)), max(1, int(tiles_y or 1)),
            )
        self.update()

    def clear_framing(self) -> None:
        """Elimina el encuadre dibujado."""
        self._framing = None
        self.update()

    def reset_view(self) -> None:
        """Vuelve al centro inicial con el zoom por defecto."""
        self._ra0, self._dec0 = 0.0, 0.0
        self._fov_deg = DEFAULT_VIEW_FOV_DEG
        self._label = ""
        self._selected = None
        self._emit_view()
        self.update()

    @property
    def view(self) -> tuple[float, float, float]:
        """(ra_hours, dec_deg, fov_deg) de la vista actual."""
        return self._ra0 / 15.0, self._dec0, self._fov_deg

    def sky_at_center(self) -> tuple[float, float]:
        """(ra_hours, dec_deg) del centro de la vista (para el editor de encuadre)."""
        return self._ra0 / 15.0, self._dec0

    def _find_object_index(self, object_id: str, catalog: str | None) -> int | None:
        ids = self._objects["ids"]
        for i, oid in enumerate(ids):
            if oid == object_id and (catalog is None or self._objects["catalogs"][i] == catalog):
                return i
        return None

    def _emit_view(self) -> None:
        self.view_changed.emit(self._ra0 / 15.0, self._dec0, self._fov_deg)

    # ------------------------------------------------------------- geometría
    def _pixels_per_radian(self) -> float:
        """Escala de la proyección: píxeles por radiano según el alto y el zoom."""
        height = max(1, self.height())
        half_fov = math.radians(self._fov_deg) / 2.0
        return (height / 2.0) / max(math.tan(half_fov), 1e-9)

    def _to_screen(self, xi: np.ndarray, eta: np.ndarray, ppr: float) -> tuple[np.ndarray, np.ndarray]:
        """(xi, eta) en radianes → píxeles. Norte arriba, este a la izquierda."""
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        return cx - xi * ppr, cy - eta * ppr

    def _visible_bounds(self) -> tuple[float, float, float, float]:
        """(ra_min, ra_max, dec_min, dec_max) aproximados de lo que se ve.

        Muestrea una rejilla de píxeles, la invierte al cielo y devuelve los
        límites con la RA desenvuelta alrededor del centro (evita el corte 0/360).
        """
        w, h = self.width(), self.height()
        cols, rows_n = 8, 8
        xs = np.linspace(0, w, cols)
        ys = np.linspace(0, h, rows_n)
        grid_x, grid_y = np.meshgrid(xs, ys)
        ppr = self._pixels_per_radian()
        xi = (w / 2.0 - grid_x.ravel()) / ppr
        eta = (h / 2.0 - grid_y.ravel()) / ppr

        ras, decs = [], []
        for x, y in zip(xi, eta, strict=True):
            ra, dec = inverse_gnomonic(float(x), float(y), self._ra0, self._dec0)
            ras.append(ra)
            decs.append(dec)
        ras = np.array(ras)
        # Desenvolver alrededor del centro para que el rango no cruce 0/360
        center = self._ra0
        ras = (ras - center + 180.0) % 360.0 - 180.0 + center
        return float(ras.min()), float(ras.max()), min(decs), max(decs)

    # -------------------------------------------------------------- eventos
    def wheelEvent(self, event) -> None:
        """Rueda del ratón: acerca/aleja (logarítmico, acotado)."""
        steps = event.angleDelta().y() / 120.0
        if steps:
            factor = 0.85 ** steps
            self._fov_deg = max(1.0, min(180.0, self._fov_deg * factor))
            self._emit_view()
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_pos = event.position()
            self._moved_pixels = 0.0
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            return
        pos = event.position()
        dx = pos.x() - self._last_pos.x()
        dy = pos.y() - self._last_pos.y()
        self._last_pos = pos
        self._moved_pixels += abs(dx) + abs(dy)

        ppr = self._pixels_per_radian()
        # El contenido sigue al cursor: el centro se desplaza en sentido opuesto
        # a la posición en pantalla (este a la izquierda ⇒ RA creciente a la izq.).
        cos_dec = max(math.cos(math.radians(self._dec0)), 1e-6)
        self._ra0 = (self._ra0 + math.degrees(dx / ppr) / cos_dec) % 360.0
        self._dec0 = max(-89.9, min(89.9, self._dec0 + math.degrees(dy / ppr)))
        self._emit_view()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._moved_pixels < CLICK_RADIUS_PX:
            self._handle_click(event.position())

    def _handle_click(self, pos: QPointF) -> None:
        """Clic sin arrastre: ¿objeto cercano? si no, cielo para región."""
        ppr = self._pixels_per_radian()
        xi = (self.width() / 2.0 - pos.x()) / ppr
        eta = (self.height() / 2.0 - pos.y()) / ppr

        best_index, best_dist = None, CLICK_RADIUS_PX
        obj_xi, obj_eta, obj_ok = gnomonic(
            self._objects["ra"], self._objects["dec"], self._ra0, self._dec0
        )
        if len(obj_xi):
            sx, sy = self._to_screen(obj_xi, obj_eta, ppr)
            dist = np.hypot(sx - pos.x(), sy - pos.y())
            dist = np.where(obj_ok, dist, np.inf)
            index = int(np.argmin(dist))
            if dist[index] <= CLICK_RADIUS_PX:
                best_index, best_dist = index, float(dist[index])

        star_xi, star_eta, star_ok = gnomonic(
            self._stars["ra"], self._stars["dec"], self._ra0, self._dec0
        )
        if len(star_xi):
            sx, sy = self._to_screen(star_xi, star_eta, ppr)
            dist = np.hypot(sx - pos.x(), sy - pos.y())
            dist = np.where(star_ok, dist, np.inf)
            index = int(np.argmin(dist))
            # Solo las estrellas compiten si están tan cerca como el objeto
            if dist[index] <= best_dist:
                best_index = None   # las estrellas no emiten object_clicked

        if best_index is not None:
            self.object_clicked.emit(
                self._objects["ids"][best_index],
                self._objects["catalogs"][best_index],
            )
            return

        ra_deg, dec_deg = inverse_gnomonic(xi, eta, self._ra0, self._dec0)
        self.region_clicked.emit(ra_deg / 15.0, dec_deg)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update()

    # ---------------------------------------------------------------- pintura
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#05070d"))  # cielo casi negro

        ppr = self._pixels_per_radian()
        self._draw_grid(painter, ppr)
        self._draw_stars(painter, ppr)
        self._draw_objects(painter, ppr)
        self._draw_framing(painter, ppr)
        self._draw_selection(painter, ppr)
        self._draw_compass(painter)
        self._draw_label(painter)
        painter.end()

    def _draw_grid(self, painter: QPainter, ppr: float) -> None:
        """Rejilla de paralelos (Dec) y meridianos (RA) muestreada en pantalla."""
        ra_min, ra_max, dec_min, dec_max = self._visible_bounds()
        span_ra = max(ra_max - ra_min, 1e-6)
        span_dec = max(dec_max - dec_min, 1e-6)
        step = grid_step_for(min(span_ra * math.cos(math.radians(self._dec0)), span_dec))

        pen = QPen(QColor(70, 84, 110, 90))
        pen.setWidthF(1.0)
        painter.setPen(pen)

        # Paralelos (dec fija)
        dec_start = math.floor(dec_min / step) * step
        dec = dec_start
        while dec <= dec_max + step:
            if -90.0 <= dec <= 90.0:
                self._draw_sky_line(painter, ppr, "par", dec, ra_min, ra_max)
            dec += step

        # Meridianos (ra fija)
        ra = ra_min
        while ra <= ra_max + step:
            self._draw_sky_line(painter, ppr, "mer", ra, dec_min, dec_max)
            ra += step

    def _draw_sky_line(
        self, painter: QPainter, ppr: float, kind: str, fixed: float,
        from_deg: float, to_deg: float,
    ) -> None:
        """Pinta una línea de constante RA ('mer') o Dec ('par') muestreada."""
        samples = 40
        values = np.linspace(from_deg, to_deg, samples)
        if kind == "par":
            ras = values
            decs = np.full(samples, fixed)
        else:
            ras = np.full(samples, fixed)
            decs = values

        xi, eta, ok = gnomonic(ras, decs, self._ra0, self._dec0)
        xs, ys = self._to_screen(xi, eta, ppr)
        polyline = [
            QPointF(float(x), float(y))
            for x, y, good in zip(xs, ys, ok, strict=True)
            if good
        ]
        if len(polyline) >= 2:
            painter.drawPolyline(QPolygonF(polyline))

    # ----------------------------------------------------------- dibujos
    def _draw_stars(self, painter: QPainter, ppr: float) -> None:
        stars = self._stars
        if not len(stars["ra"]):
            return
        xi, eta, ok = gnomonic(stars["ra"], stars["dec"], self._ra0, self._dec0)
        xs, ys = self._to_screen(xi, eta, ppr)

        w, h = self.width(), self.height()
        visible = ok & (xs > -4) & (xs < w + 4) & (ys > -4) & (ys < h + 4)
        indices = np.flatnonzero(visible)
        if not len(indices):
            return
        # La carga ya viene ordenada por magnitud: recortar mantiene las brillantes
        if len(indices) > MAX_STARS_DRAWN:
            indices = indices[:MAX_STARS_DRAWN]

        mags = stars["mag"][indices]
        # Radio: brillantes más grandes (mag 0 → ~3.4 px, mag 8 → ~1 px)
        radii = np.clip(3.4 - mags * 0.3, 1.0, 3.6)
        alphas = np.clip(255 - mags * 18, 70, 255)
        spectra = stars["spect"]
        painter.setPen(Qt.PenStyle.NoPen)
        for i, radius, alpha in zip(indices, radii, alphas, strict=True):
            color = star_color(spectra[int(i)])
            color.setAlpha(int(alpha))
            painter.setBrush(color)
            painter.drawEllipse(
                QPointF(float(xs[i]), float(ys[i])), float(radius), float(radius)
            )

    def _draw_objects(self, painter: QPainter, ppr: float) -> None:
        objs = self._objects
        if not len(objs["ra"]):
            return
        xi, eta, ok = gnomonic(objs["ra"], objs["dec"], self._ra0, self._dec0)
        xs, ys = self._to_screen(xi, eta, ppr)
        w, h = self.width(), self.height()
        visible = ok & (xs > -20) & (xs < w + 20) & (ys > -20) & (ys < h + 20)

        font = QFont(self.font())
        font.setPointSizeF(8.5)
        painter.setFont(font)

        for i in np.flatnonzero(visible):
            catalog = objs["catalogs"][i]
            color = marker_color(catalog)
            mag = float(objs["mag"][i])
            radius = 5.0 if catalog == "messier" else 4.0
            if mag < 100:
                radius += max(0.0, (7.0 - mag) * 0.35)
            x, y = float(xs[i]), float(ys[i])

            painter.setPen(QPen(color, 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(x, y), radius, radius)

            # Etiqueta de los objetos suficientemente brillantes o grandes
            if mag <= 9.0 or catalog == "messier":
                painter.setPen(color)
                painter.drawText(QPointF(x + radius + 3, y + 3), str(objs["ids"][i]))

    def _draw_selection(self, painter: QPainter, ppr: float) -> None:
        """Aro alrededor del objeto seleccionado (el que centra la vista)."""
        if not self._selected:
            return
        index = self._find_object_index(*self._selected)
        if index is None:
            return
        xi, eta, ok = gnomonic(
            [self._objects["ra"][index]], [self._objects["dec"][index]],
            self._ra0, self._dec0,
        )
        if not bool(ok[0]):
            return
        x, y = self._to_screen(xi, eta, ppr)
        painter.setPen(QPen(QColor("#60a5fa"), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(float(x[0]), float(y[0])), 11.0, 11.0)

    def _draw_framing(self, painter: QPainter, ppr: float) -> None:
        """Rectángulo de encuadre y teselas del mosaico.

        El rectángulo se dibuja centrado en la proyección de su propio eje y
        con ancho/alto positivos (mitad = tan(fov/2) en radianes × escala).
        """
        if not self._framing:
            return
        ra, dec, major, minor, tiles_x, tiles_y = self._framing
        xi, eta, ok = gnomonic([ra], [dec], self._ra0, self._dec0)
        if not bool(ok[0]):
            return

        half_w = math.tan(math.radians(major / 2.0)) * ppr   # px
        half_h = math.tan(math.radians(minor / 2.0)) * ppr   # px
        center_x, center_y = self._to_screen(xi, eta, ppr)
        rect = QRectF(
            float(center_x[0]) - half_w,
            float(center_y[0]) - half_h,
            2.0 * half_w,
            2.0 * half_h,
        )

        pen = QPen(QColor("#f59e0b"), 1.8)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QColor(245, 158, 11, 26))
        painter.drawRect(rect)

        # Teselas internas
        painter.setPen(QPen(QColor(245, 158, 11, 120), 1.0))
        for k in range(1, tiles_x):
            x = rect.left() + rect.width() * k / tiles_x
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for k in range(1, tiles_y):
            y = rect.top() + rect.height() * k / tiles_y
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

    def _draw_compass(self, painter: QPainter) -> None:
        """Rosa de los vientos abajo a la izquierda (norte arriba, este a la izq.)."""
        cx, cy = 34.0, self.height() - 34.0
        radius = 18.0
        painter.setPen(QPen(QColor("#8b949e"), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        painter.setPen(QPen(QColor("#e6edf3"), 1.8))
        painter.drawLine(QPointF(cx, cy), QPointF(cx, cy - radius))       # N
        painter.drawLine(QPointF(cx, cy), QPointF(cx - radius, cy))       # E (izq.)
        painter.setPen(QColor("#60a5fa"))
        painter.drawText(QPointF(cx - 4, cy - radius - 5), "N")
        painter.setPen(QColor("#8b949e"))
        painter.drawText(QPointF(cx - radius - 14, cy + 4), "E")

    def _draw_label(self, painter: QPainter) -> None:
        """Etiqueta del centro de la vista arriba a la izquierda."""
        ra_h, dec = self._ra0 / 15.0, self._dec0
        title = self._label or "Centro"
        hours = int(ra_h)
        minutes = int(round((ra_h - hours) * 60.0))
        if minutes == 60:
            hours, minutes = (hours + 1) % 24, 0
        sign = "+" if dec >= 0 else "-"
        text = f"{title}: RA {hours:02d}h{minutes:02d}m  Dec {sign}{abs(dec):.1f}°  ·  {self._fov_deg:.1f}°"

        painter.setPen(QColor("#8b949e"))
        painter.drawText(QPointF(10.0, 20.0), text)
