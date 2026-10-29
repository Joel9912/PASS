"""Elementos de portada dibujados en Qt: progreso e ilustración originales, sin texturas ni servicios externos."""

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QWidget

from ui.planner_tab.widgets import _lit_path
from ui.style import PALETTE


def _mix(a, b, amount):
    """Interpola colores de ilustración, no magnitudes ni umbrales astronómicos."""
    left, right = QColor(a), QColor(b)
    return QColor(*(round(x+(y-x)*amount) for x, y in zip(left.getRgb()[:3], right.getRgb()[:3], strict=True)))


class ProgressDial(QWidget):
    """Arco protagonista de integración con horas reales separadas del porcentaje acotado."""

    def __init__(self, parent=None):
        """Mantiene un tamaño flexible y texto accesible equivalente a lo pintado."""
        super().__init__(parent)
        self.progress = None
        self.setMinimumSize(175, 175)

    def set_progress(self, progress):
        """Acepta un modelo ya calculado; no consulta archivos ni deduce horas."""
        self.progress = progress
        self.setAccessibleName("Integración del objeto")
        self.setAccessibleDescription("Sin integración vinculada" if progress is None else
                                      f"{progress.total_hours:g} de {progress.goal_hours:g} horas; "
                                      f"{progress.pending_hours:g} pendientes de auditoría")
        self.update()

    def paintEvent(self, event):
        """Dibuja un anillo sencillo, sin animaciones continuas ni reemplazar la información textual."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 22
        rect = QRectF((self.width()-side)/2, (self.height()-side)/2, side, side)
        pen = QPen(QColor(PALETTE["surface"]), 12)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360*16)
        if self.progress is None:
            return
        pen.setColor(QColor(PALETTE["accentLight"]))
        painter.setPen(pen)
        painter.drawArc(rect, 90*16, -round(self.progress.fraction*360*16))
        font = QFont(self.font())
        font.setPointSize(30)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(PALETTE["text"]))
        painter.drawText(rect.adjusted(0, -15, 0, -15), Qt.AlignmentFlag.AlignCenter, f"{self.progress.fraction:.0%}")
        font.setPointSize(12)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(PALETTE["textDim"]))
        painter.drawText(rect.adjusted(0, 55, 0, 0), Qt.AlignmentFlag.AlignCenter, "del objetivo")


class SkyScene(QWidget):
    """Paisaje estático con luz solar y fase real; posiciones de sus elementos explícitamente decorativas."""

    def __init__(self, parent=None):
        """Genera geometría propia y transiciones breves; no carga imágenes ni anima estrellas."""
        super().__init__(parent)
        self.setMinimumSize(280, 245)
        self._state = None
        self._light = 0.15
        rng = random.Random(1936)
        self._stars = [(rng.uniform(.05, .95), rng.uniform(.05, .66), rng.uniform(.55, 1.4), rng.randint(100, 220))
                       for _ in range(52)]
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(280)
        self._animation.valueChanged.connect(self._light_changed)
        self.setAccessibleName("Ilustración del cielo y paisaje, no carta astronómica")

    def set_state(self, state, *, animate=True):
        """Recolorea por luz real; sin datos no representa una fase lunar o una posición supuesta."""
        self._animation.stop()
        self._state = state
        # Rango puramente gráfico para mezclar paletas, no clasificación científica de crepúsculos.
        target = max(0., min(1., (state.sun_altitude + 18.) / 40.)) if state else 0.15
        if animate and self.isVisible():
            self._animation.setStartValue(self._light)
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._light_changed(target)
        self.setAccessibleDescription("Sin datos solares: elige ubicación" if state is None else
                                      f"{state.title}. Luna {state.illumination:.0%} iluminada; posición decorativa.")

    def _light_changed(self, value):
        """Actualiza solo el color interpolado y solicita repintado bajo demanda."""
        self._light = float(value)
        self.update()

    def paintEvent(self, event):
        """Compone cielo, puntos de estrellas y siluetas sin simular terreno ni clima del lugar."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, light = self.width(), self.height(), self._light
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()), 16, 16)
        p.setClipPath(shape)
        gradient = QLinearGradient(0, 0, 0, h)
        gradient.setColorAt(0, _mix("#081126", "#19528b", light))
        gradient.setColorAt(.62, _mix("#223057", "#74b5d5", light))
        dusk = max(0., 1-abs(light-.4)/.4)
        horizon = _mix("#313750", "#dce8dc", light)
        gradient.setColorAt(1, _mix(horizon, "#f2ad83", dusk*.7))
        p.fillRect(self.rect(), gradient)
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, radius, alpha in self._stars:
            color = QColor("#e4edff")
            color.setAlpha(round((1-light)**3 * alpha))
            p.setBrush(color)
            p.drawEllipse(QPointF(x*w, y*h), radius, radius)
        if self._state is not None:
            cx, cy, radius = w*.72, h*.25, min(w, h)*.085
            if self._state.sun_altitude >= 0:
                glow = QRadialGradient(QPointF(cx, cy), radius*3.5)
                glow.setColorAt(0, QColor(255, 232, 162, 110))
                glow.setColorAt(1, QColor(255, 232, 162, 0))
                p.setBrush(glow)
                p.drawEllipse(QPointF(cx, cy), radius*3.5, radius*3.5)
                p.setBrush(QColor("#fff0be"))
                p.drawEllipse(QPointF(cx, cy), radius, radius)
            else:
                p.setBrush(QColor("#26324b"))
                p.drawEllipse(QPointF(cx, cy), radius, radius)
                p.fillPath(_lit_path(cx, cy, radius, self._state.illumination, self._state.waxing), QColor("#f0ead5"))
        for layer, color in enumerate(("#293e54", "#1c2e40", "#122332")):
            path = QPainterPath(QPointF(-10, h))
            for i in range(13):
                x = w*i/12
                y = h*(.75+layer*.065) + math.sin(i*.82+layer)*h*.065 + math.cos(i*1.7+layer)*h*.025
                path.lineTo(x, y)
            path.lineTo(w+10, h)
            path.closeSubpath()
            p.fillPath(path, _mix(color, "#416374", light*.4))


class IdleIllustration(QWidget):
    """Motivo gráfico de portada sin datos: no es una constelación real ni un indicador de progreso vacío."""

    def __init__(self, parent=None):
        """Reserva aire visual moderado sin recursos externos o movimiento permanente."""
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setMaximumHeight(210)
        self.setAccessibleName("Motivo decorativo para una nueva observación")

    def paintEvent(self, event):
        """Dibuja órbitas abstractas, puntos y una estrella central como composición original."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width()/2, self.height()/2
        p.setPen(QPen(QColor("#283c55"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for radius in (40, 62, 83):
            p.drawEllipse(QPointF(cx, cy), radius*1.65, radius*.72)
        for dx, dy, radius in ((-112, 28, 4), (78, -30, 5), (25, 43, 3)):
            p.setBrush(QColor("#7fa6cf"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx+dx, cy+dy), radius, radius)
        path = QPainterPath(QPointF(cx, cy-24))
        for dx, dy in ((6,-6), (24,0), (6,6), (0,24), (-6,6), (-24,0), (-6,-6)):
            path.lineTo(cx+dx, cy+dy)
        path.closeSubpath()
        p.fillPath(path, QColor("#9dbfe5"))
