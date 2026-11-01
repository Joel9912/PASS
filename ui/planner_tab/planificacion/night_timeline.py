"""Calendario nocturno nativo: bloques del recurso común con color, texto y maniobras tramadas."""

from collections import defaultdict
from datetime import timedelta
from hashlib import sha256

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate

from planners.multinight import availability
from planners.timezones import local_moment
from ui.style import PALETTE

OPERATION_LABELS = {"pause":"Pausa", "movement":"Movimiento", "filter":"Filtro", "focus":"Autoenfoque", "meridian":"Meridiano"}


def object_color(key):
    """Color estable por identidad del objeto, independiente del orden de filas o de la selección."""
    index = int(sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 6+1
    return PALETTE[f"planObject{index}"]


class NightDelegate(QStyledItemDelegate):
    """Tarjetas de noche virtualizadas para no construir un widget por intervalo de captura."""

    def sizeHint(self, option, index):
        """Reserva espacio según la fuente del sistema para títulos, eje y línea temporal."""
        return QSize(450, max(130, option.fontMetrics.height()*6))

    def paint(self, painter, option, index):
        """Pinta tiempo real continuo; las horas civiles son etiquetas y nunca posiciones del eje."""
        data = index.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(4, 4, -4, -4)
        painter.setPen(QPen(QColor(PALETTE["accentLight"] if option.state & QStyle.StateFlag.State_HasFocus else PALETTE["border"])))
        painter.setBrush(QColor(PALETTE["panel"]))
        painter.drawRoundedRect(rect, 10, 10)
        line = option.fontMetrics.height()
        painter.setPen(QColor(PALETTE["text"]))
        painter.drawText(rect.adjusted(12, 4, -12, -4), Qt.AlignmentFlag.AlignTop, data["title"])
        painter.setPen(QColor(PALETTE["textDim"]))
        painter.drawText(rect.adjusted(12, line+6, -12, -4), Qt.AlignmentFlag.AlignTop, data["summary"])
        axis = QRectF(rect.left()+12, rect.top()+line*3, rect.width()-24, line*1.6)
        painter.fillRect(axis, QColor(PALETTE["bg"]))
        duration = (data["end"]-data["start"]).total_seconds()
        for visit in data["visits"]:
            left = (visit.start-data["start"]).total_seconds()/duration
            width = (visit.end-visit.start).total_seconds()/duration
            block = QRectF(axis.left()+axis.width()*left, axis.top(), max(2., axis.width()*width), axis.height())
            color = QColor(object_color(visit.objective))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(block, 5, 5)
            painter.setPen(QColor(PALETTE["bg"]))
            text = option.fontMetrics.elidedText(data["names"][visit.objective], Qt.TextElideMode.ElideRight, max(0, int(block.width()-8)))
            painter.drawText(block.adjusted(4, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, text)
        for event in data["operations"]:
            if event.kind == "pause":
                continue
            left = (event.start-data["start"]).total_seconds()/duration
            width = (event.end-event.start).total_seconds()/duration
            block = QRectF(axis.left()+axis.width()*left, axis.bottom()-7, max(2., axis.width()*width), 7)
            painter.setBrush(Qt.BrushStyle.BDiagPattern)
            painter.setPen(QColor(PALETTE["text"]))
            painter.drawRect(block)
        painter.setPen(QColor(PALETTE["textDim"]))
        for tick in range(4):
            time = data["start"]+timedelta(seconds=duration*tick/3)
            clock = local_moment(time, data["longitude"], data["clock"]).strftime("%H:%M %z")
            x = axis.left()+(axis.width()-110)*tick/3
            painter.drawText(QRectF(x, axis.bottom()+4, 120, line+4), clock)
        painter.restore()


class NightTimeline(QListWidget):
    """Calendario accesible con selección de visitas por ratón y flechas izquierda/derecha."""

    visit_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        """El foco y las etiquetas complementan colores; las noches largas tienen scroll local."""
        super().__init__(parent)
        self.setItemDelegate(NightDelegate(self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAccessibleName("Calendario de noches; izquierda y derecha recorren los bloques de la noche")
        self.currentItemChanged.connect(self._selected)
        self._visit_index = 0

    def set_plan(self, request, result):
        """Sustituye tarjetas y alternativas conjuntamente, sin conservar una selección de otra propuesta."""
        self.blockSignals(True)
        self.clear()
        names = {obj.key:obj.name for obj in request.objectives}
        groups, events = defaultdict(list), defaultdict(list)
        for visit in result.visits:
            groups[visit.night].append(visit)
        for event in result.operations:
            events[event.night].append(event)
        for night, start, end in availability(request):
            visits = sorted(groups[night], key=lambda value:value.start)
            if not visits:
                continue
            net = sum(visit.integration_s for visit in visits)
            overhead = sum((event.end-event.start).total_seconds() for event in events[night])
            title = f"{night}   ·   {len({v.objective for v in visits})} objetos"
            summary = f"{net/3600:.2f} h integración  ·  {overhead/60:.1f} min operación  ·  {(net+overhead)/3600:.2f} h ocupadas"
            item = QListWidgetItem(title+". "+summary)
            item.setData(Qt.ItemDataRole.UserRole, dict(title=title, summary=summary, start=start, end=end, visits=visits,
                                                       operations=events[night], names=names, longitude=request.longitude, clock=request.clock))
            description = "\n".join(f"{names[v.objective]}: {v.reason}" for v in visits)
            item.setToolTip(description)
            item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, description)
            self.addItem(item)
        self.blockSignals(False)
        self._visit_index = 0

    def _selected(self, item, _previous=None):
        """Una noche seleccionada ofrece el primer bloque sin exigir hover."""
        self._visit_index = 0
        self._emit_visit(item)

    def _emit_visit(self, item):
        """Emite datos backend inmutables; el controlador decide qué curva inspeccionar."""
        if item:
            visits = item.data(Qt.ItemDataRole.UserRole)["visits"]
            if visits:
                self.visit_selected.emit(visits[self._visit_index % len(visits)])

    def mousePressEvent(self, event):
        """Permite seleccionar el bloque bajo el cursor además de navegar con teclado."""
        super().mousePressEvent(event)
        item = self.itemAt(event.pos())
        if item:
            data = item.data(Qt.ItemDataRole.UserRole)
            rect = self.visualItemRect(item)
            fraction = (event.position().x()-rect.left()-16)/max(1, rect.width()-32)
            time = data["start"]+(data["end"]-data["start"])*fraction
            for index, visit in enumerate(data["visits"]):
                if visit.start <= time <= visit.end:
                    self._visit_index = index
                    break
            self._emit_visit(item)

    def keyPressEvent(self, event):
        """Izquierda/derecha recorren visitas; arriba/abajo conservan la navegación normal por noches."""
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._visit_index += 1 if event.key() == Qt.Key.Key_Right else -1
            self._emit_visit(self.currentItem())
            return
        super().keyPressEvent(event)
