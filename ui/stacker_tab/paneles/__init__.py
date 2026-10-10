"""Los cinco paneles del asistente (API: `from ui.stacker_tab.paneles import …`)."""
from .apilar import PanelApilar
from .auditar import PanelAuditar
from .calibrar import PanelCalibrar
from .final import PanelFinal
from .sesiones import PanelSesiones

__all__ = ["PanelApilar", "PanelAuditar", "PanelCalibrar", "PanelFinal", "PanelSesiones"]
