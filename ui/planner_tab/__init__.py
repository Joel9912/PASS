"""Subpestañas del Planificador de PAS.S.

Orden de las subpestañas (decisión del usuario):

1. **Búsqueda** (`busqueda.py`): filtros, tabla de resultados, efemérides
   Sol/Luna, curva de tránsito (PyQtGraph) y tarjetas de clima/seeing.
2. **Catálogo Personal** (`catalogo_personal.py`): objetos y regiones guardados.
3. **Planificación** (`planificacion.py`): planetario visual, encuadre, ventana
   nocturna, plan de captura y parámetros de la sesión a guardar.
4. **Sesiones Planificadas** (`sesiones.py`): sesiones concretadas con parámetros.

`planetario_visual.py` es el lienzo de cielo (QPainter) que usa Planificación y
`widgets.py` reúne lo compartido (barra de ubicación, tarjetas, efemérides y
curva de tránsito). El cableado entre subpestañas vive en `PlannerPage`
(`ui/main_window.py`), no aquí, para que ninguna importe a otra.
"""
from .busqueda import BusquedaTab
from .catalogo_personal import CatalogoPersonalTab
from .planificacion import PlanificacionTab
from .sesiones import SesionesTab
from .widgets import LocationBar

__all__ = [
    "BusquedaTab",
    "CatalogoPersonalTab",
    "LocationBar",
    "PlanificacionTab",
    "SesionesTab",
]
