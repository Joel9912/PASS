"""Lectura y escritura de la tabla ``settings`` (clave-valor).

Único punto de verdad para la configuración persistente del programa:
API keys del clima, ruta de SirIL, carpeta base de proyectos, etc.
Los valores son TEXT y **nunca** se guardan en código ni en el
repositorio (solo en la base local ``data/pass.db``).
"""
from __future__ import annotations

from db.connection import get_connection

#: Clave de ``settings`` de la carpeta base de proyectos (raíz de sesiones).
#: Vive aquí, no en la UI: la comparten Configuración y el Apilador (A-23).
PROJECT_ROOT_KEY = "project_root"


def get_setting(key: str, default: str | None = None) -> str | None:
    """Valor de ``key``; ``default`` (por defecto ``None``) si no existe."""
    row = get_connection().execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def get_float(key: str, default: float) -> float:
    """Valor numérico de ``key``; ``default`` si falta o no se puede leer.

    La tabla ``settings`` guarda TEXT: esta lectura defensiva (clave
    ausente o texto corrupto → default) es la que usan los umbrales de
    muestreo y el diálogo de Configuración.
    """
    texto = get_setting(key, str(default))
    try:
        return float(texto)
    except (TypeError, ValueError):
        return default


def set_setting(key: str, value: str) -> None:
    """Guarda ``value`` para ``key`` (insert o update) y hace commit."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def set_settings(values: dict[str, str]) -> None:
    """Guarda un conjunto de ajustes todo o nada para evitar estados parciales."""
    conn = get_connection()
    with conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            values.items(),
        )
