"""Subpestañas del Planificador de PAS.S.

Orden de las subpestañas (decisión del usuario) — **cada una en su propia
carpeta con su propio `README.md`**:

1. **Búsqueda** (`busqueda/`): filtros, tabla de resultados, efemérides
   Sol/Luna, curva de tránsito (PyQtGraph) y tarjetas de clima/seeing.
2. **Catálogo Personal** (`catalogo_personal/`): objetos y regiones guardados.
3. **Planificación** (`planificacion/`): planetario visual, encuadre, ventana
   nocturna, plan de captura y parámetros de la sesión a guardar.
4. **Sesiones Planificadas** (`sesiones/`): sesiones concretadas con parámetros.

El módulo de cada subpestaña es `tab.py` dentro de su carpeta; este
`__init__.py` re-exporta las clases para que los consumidores sigan
importando `ui.planner_tab` igual que antes.

`widgets.py` (raíz) reúne lo compartido (barra de ubicación, tarjetas,
efemérides, curva de tránsito y el formato de catálogo). El cableado entre
subpestañas vive en `PlannerPage` (`ui/main_window.py`), no aquí, para que
ninguna importe a otra.
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
