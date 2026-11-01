"""Presentación civil de la curva y bloques elegidos, sin cambiar el eje físico ni el reparto."""

from datetime import timedelta

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor

from planners.timezones import local_moment
from ui.style import PALETTE

from .night_timeline import object_color


class LocalTimeAxis(pg.AxisItem):
    """Etiqueta horas locales sobre distancias UTC; distingue horas repetidas durante cambios de huso."""

    def __init__(self):
        """Arranca sin fechas supuestas hasta recibir la noche realmente inspeccionada."""
        super().__init__(orientation="bottom")
        self._start = None

    def set_context(self, start, end, longitude, clock):
        """Actualiza reloj y rótulo; un cambio de desfase se muestra en cada marca, no comprime el tiempo."""
        self._start, self._longitude, self._clock = start, longitude, clock
        first = local_moment(start, longitude, clock)
        last = local_moment(end, longitude, clock)
        self._offset_changes = first.utcoffset() != last.utcoffset()
        label = str(clock) if isinstance(clock, str) else "UTC"+first.strftime("%z")
        if clock is None:
            label += " · ≈ por longitud"
        self.setLabel("Hora local · "+label)
        self.picture = None
        self.update()

    def tickStrings(self, values, scale, spacing):
        """Solo convierte las etiquetas; las posiciones mantienen horas reales desde el origen UTC."""
        if self._start is None:
            return ["" for _ in values]
        moments = [local_moment(self._start+timedelta(hours=float(value)), self._longitude, self._clock) for value in values]
        return [moment.strftime("%H:%M\n%z" if self._offset_changes else "%H:%M") for moment in moments]


def draw_schedule(plot, result, key, origin, request):
    """Marca solo las tomas de la tesela inspeccionada y sus maniobras; devuelve horarios legibles."""
    if result is None or key is None:
        return ""
    objective, _tile, night = key
    frames = [frame for frame in result.allocations if (frame.objective, frame.tile, frame.night) == key]
    if not frames:
        return ""
    visits = [visit for visit in result.visits if (visit.objective, visit.night) == (objective, night)]
    if not visits:
        # Los maestros cronológicos anteriores no disponen de visitas operativas.
        intervals = [(frame.start, frame.end) for frame in sorted(frames, key=lambda item: item.start)]
        merged = []
        for start, end in intervals:
            if merged and start <= merged[-1][1]:
                merged[-1] = merged[-1][0], max(end, merged[-1][1])
            else:
                merged.append((start, end))
    else:
        merged = []
        for visit in visits:
            previous_matches = False
            for frame in sorted(result.allocations, key=lambda item: item.start):
                if frame.night != night or not visit.start <= frame.start < frame.end <= visit.end:
                    continue
                matches = (frame.objective, frame.tile, frame.night) == key
                if matches:
                    if previous_matches:
                        merged[-1] = merged[-1][0], frame.end
                    else:
                        merged.append((frame.start, frame.end))
                previous_matches = matches
    color = QColor(object_color(objective))
    fill = QColor(color)
    fill.setAlpha(55)
    labels = []
    for start, end in merged:
        for event in sorted(result.operations, key=lambda item: item.end, reverse=True):
            if (event.objective, event.tile, event.night) == key and event.end == start:
                start = event.start
        a, b = (start-origin).total_seconds()/3600, (end-origin).total_seconds()/3600
        band = pg.LinearRegionItem((a, b), movable=False, brush=pg.mkBrush(fill), pen=pg.mkPen(color, width=1))
        band.setZValue(-5)
        plot.addItem(band)
        plot.plot([a, b], [87, 87], pen=pg.mkPen(color, width=6), name="Planificado" if not labels else None)
        first, last = (local_moment(moment, request.longitude, request.clock) for moment in (start, end))
        label = first.strftime("%H:%M")+"–"+last.strftime("%H:%M")
        if first.utcoffset() != last.utcoffset():
            label = first.strftime("%H:%M %z")+"–"+last.strftime("%H:%M %z")
        labels.append(label)
    for event in result.operations:
        if (event.objective, event.tile, event.night) != key or event.kind == "pause":
            continue
        a, b = (event.start-origin).total_seconds()/3600, (event.end-origin).total_seconds()/3600
        band = pg.LinearRegionItem((a, b), span=(.85, 1), movable=False,
                                   brush=QBrush(QColor(PALETTE["text"]), Qt.BrushStyle.BDiagPattern),
                                   pen=pg.mkPen(PALETTE["textDim"]))
        band.setZValue(5)
        plot.addItem(band)
    return "; ".join(labels)
