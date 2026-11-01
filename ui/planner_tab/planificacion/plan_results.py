"""Tarjetas de cobertura del plan: progreso calculado, no progreso de capturas realizadas."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .night_timeline import object_color


class CoverageCards(QScrollArea):
    """Resumen por objeto con barras y desglose legible sin depender solo del color."""

    def __init__(self, parent=None):
        """Permite scroll local de objetos manteniendo siempre visibles las acciones de planificación."""
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAccessibleName("Cobertura propuesta por objeto y filtro")
        self.set_message("Calcula para ver la cobertura propuesta.")

    def set_message(self, text):
        """Retira tarjetas anteriores cuando las entradas ya no corresponden a la propuesta."""
        container = QWidget()
        layout = QVBoxLayout(container)
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch(1)
        old = self.takeWidget()
        self.setWidget(container)
        if old:
            old.deleteLater()

    def set_plan(self, request, result):
        """Usa únicamente balances del calendario seleccionado, no números ilustrativos."""
        container = QWidget()
        layout = QVBoxLayout(container)
        for obj in request.objectives:
            values = [balance for balance in result.balances if balance.objective == obj.key]
            assigned = sum(value.assigned_s for value in values)
            wanted = sum(value.requested_s for value in values)
            card = QFrame()
            card.setObjectName("GroupFrame")
            content = QVBoxLayout(card)
            title = QLabel(f"{obj.name}    {assigned/3600:.2f} / {wanted/3600:.2f} h propuestas")
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setWordWrap(True)
            title.setStyleSheet("background: transparent;")
            content.addWidget(title)
            progress = QProgressBar()
            progress.setRange(0, 1000)
            progress.setValue(round(1000*assigned/wanted) if wanted else 0)
            progress.setTextVisible(False)
            progress.setFixedHeight(12)
            progress.setAccessibleName(f"{100*assigned/wanted:.1f} % previsto" if wanted else "Sin objetivo")
            progress.setStyleSheet(f"QProgressBar::chunk {{ background-color: {object_color(obj.key)}; }}")
            content.addWidget(progress)
            for value in values:
                line = QLabel(f"{value.filter_name} · tesela {value.tile}    {value.assigned_s/3600:.2f} h / "
                              f"{value.requested_s/3600:.2f} h · faltan {(value.requested_s-value.assigned_s)/3600:.2f} h")
                line.setTextFormat(Qt.TextFormat.PlainText)
                line.setWordWrap(True)
                line.setStyleSheet("background: transparent;")
                content.addWidget(line)
            layout.addWidget(card)
        layout.addStretch(1)
        old = self.takeWidget()
        self.setWidget(container)
        if old:
            old.deleteLater()
