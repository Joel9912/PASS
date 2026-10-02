"""Registro de los lights calibrados con SirIL.

Registra los lights del pool global (por referencias, sin copias) y obtiene de
SirIL las métricas de cada frame para la auditoría.
"""
from .global_pool import GlobalPool


def register_pool(pool: GlobalPool) -> None:
    """Registra todos los lights del pool con SirIL (usa los hilos disponibles)."""
    raise NotImplementedError
