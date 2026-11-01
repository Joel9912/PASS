"""Formulario del perfil operativo por equipo, guardado junto a su ficha y no al editar."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QWidget,
)

from equipment.planning_profile import PlanningProfile, profile_from_data


class PlanningProfileForm(QWidget):
    """Editor de duraciones opcionales y disparadores, sin control de hardware."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        """Expone desconocido como ausencia y 5 min solo como duración inicial de meridiano."""
        super().__init__(parent)
        form = QFormLayout(self)
        self.flip = QComboBox()
        self.flip.addItem("No requiere cambio de meridiano", False)
        self.flip.addItem("Requiere cambio de meridiano", True)
        self.flip.currentIndexChanged.connect(self.changed.emit)
        form.addRow("Montura", self.flip)
        self.controls = {}
        for key, text in (("meridian_s", "Ventana total de meridiano"), ("pause_s", "Pausa entre tomas"),
                          ("filter_s", "Cambio de filtro"), ("slew_s", "Movimiento y recentrado"),
                          ("focus_s", "Duración del autoenfoque"), ("focus_interval_s", "Enfocar cada intervalo")):
            spin = QDoubleSpinBox()
            spin.setRange(-1, 86400)
            spin.setDecimals(2)
            spin.setSpecialValueText("No informado / desactivado")
            spin.setSuffix(" s")
            spin.valueChanged.connect(self.changed.emit)
            self.controls[key] = spin
            form.addRow(text, spin)
        self.frames = QSpinBox()
        self.frames.setRange(0, 1_000_000)
        self.frames.setSpecialValueText("Desactivado")
        self.frames.valueChanged.connect(self.changed.emit)
        form.addRow("Enfocar cada N tomas", self.frames)
        self.triggers = {}
        for key, text in (("focus_start", "Enfocar al iniciar la noche"), ("focus_filter", "Enfocar tras cambiar filtro"),
                          ("focus_flip", "Enfocar tras cambio de meridiano")):
            check = QCheckBox(text)
            check.toggled.connect(self.changed.emit)
            self.triggers[key] = check
            form.addRow(check)
        self.restore(None)

    def data(self):
        """Recoge incluso la edición incompleta; el backend valida al confirmar Guardar equipo."""
        values = {key:spin.value() if spin.value() >= 0 else None for key, spin in self.controls.items()}
        return dict(version=1, meridian_flip=self.flip.currentData(), focus_frames=self.frames.value() or None,
                    **values, **{key:check.isChecked() for key, check in self.triggers.items()})

    def restore(self, data):
        """Restaura sin inferir tiempos desconocidos del nombre o del tipo de montura."""
        profile = profile_from_data(data) if data is not None else PlanningProfile()
        values = profile.data()
        self.flip.setCurrentIndex(int(profile.meridian_flip))
        for key, spin in self.controls.items():
            spin.setValue(values[key] if values[key] is not None else -1)
        self.frames.setValue(profile.focus_frames or 0)
        for key, check in self.triggers.items():
            check.setChecked(values[key])
