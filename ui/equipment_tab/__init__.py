"""Pestaña **Equipo** de PAS.S: equipos (setups) y ubicaciones.

Exporta ``EquipmentPage``, la página que monta la ventana principal en su
fila de navegación: un ``QTabWidget`` con **Equipos** (``EquiposTab``) y
**Ubicaciones** (``UbicacionesTab``).

Dos señales para el cableado exterior (ninguna pestaña importa a otra;
quien escucha es ``ui/main_window.py``):

- ``setups_changed`` — se creó/actualizó/borró un equipo, una pieza o un
  filtro (los componentes cambian el FOV que pinta Planificación).
- ``locations_changed`` — se creó/actualizó/borró una ubicación (barra de
  ubicación del Planificador y combos).

El cableado interno (una ubicación nueva refresca el combo de Ubicación
de Equipos) vive también aquí, en el constructor de la página.
"""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .equipos import EquiposTab
from .ubicaciones import UbicacionesTab


class EquipmentPage(QWidget):
    """Página de la pestaña Equipo: subpestañas Equipos y Ubicaciones."""

    locations_changed = pyqtSignal()
    setups_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta las dos subpestañas y su cableado interno y externo."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        tabs = QTabWidget()
        self.equipos = EquiposTab()
        self.ubicaciones = UbicacionesTab()
        tabs.addTab(self.equipos, "Equipos")
        tabs.addTab(self.ubicaciones, "Ubicaciones")
        layout.addWidget(tabs, 1)

        # Externo: reemitir hacia la ventana principal.
        self.equipos.setups_changed.connect(self.setups_changed)
        self.ubicaciones.locations_changed.connect(self.locations_changed)
        # Interno: una ubicación nueva/al actualizada refresca el combo de
        # Ubicación de la cabecera de Equipos.
        self.locations_changed.connect(self.equipos.reload_locations)
