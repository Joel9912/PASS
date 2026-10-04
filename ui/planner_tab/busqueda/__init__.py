"""Subpestaña **Búsqueda** del Planificador: filtros, catálogo y efemérides.

Re-exporta lo que consumen `ui.planner_tab` y los tests
(`from ui.planner_tab.busqueda import COLUMNS`): el módulo de la subpestaña
vive en `tab.py`.
"""
from .tab import COLUMNS, BusquedaTab

__all__ = ["BusquedaTab", "COLUMNS"]
