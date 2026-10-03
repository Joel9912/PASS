"""Lectura y escritura de la tabla ``settings`` (clave-valor).

Único punto de verdad para la configuración persistente del programa:
API keys del clima, ruta de SirIL, carpeta base de proyectos, etc.
Los valores son TEXT y **nunca** se guardan en código ni en el
repositorio (solo en la base local ``data/pass.db``).
"""
from __future__ import annotations

from db.connection import get_connection


def get_setting(key: str, default: str | None = None) -> str | None:
    """Valor de ``key``; ``default`` (por defecto ``None``) si no existe."""
    row = get_connection().execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    """Guarda ``value`` para ``key`` (insert o update) y hace commit."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
