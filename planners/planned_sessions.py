"""Sesiones planificadas: las que el usuario concreta en el Planificador.

El Planificador las escribe; la pestaña Resumen las lee para saber en qué
sesión está el usuario (requisito del programa).

Además de la fecha y el equipo, cada sesión guarda los parámetros del
encuadre (centro RA/Dec, FOV, teselas) y las notas, para que la sesión sea
reproducible sin volver a calcularla.
"""
from db.connection import get_connection

#: Columnas que :func:`update_session` permite modificar.
_UPDATABLE = (
    "target_name", "setup_id", "session_date", "planned_exposure_s",
    "target_kind", "ra_hours", "dec_deg", "fov_major_arcmin", "fov_minor_arcmin",
    "tiles_x", "tiles_y", "notes", "status",
)


def add(
    object_id: str,
    target_name: str,
    session_date: str,
    setup_id: int | None = None,
    planned_exposure_s: int | None = None,
    target_kind: str = "catalog",
    ra_hours: float | None = None,
    dec_deg: float | None = None,
    fov_major_arcmin: float | None = None,
    fov_minor_arcmin: float | None = None,
    tiles_x: int | None = None,
    tiles_y: int | None = None,
    notes: str = "",
) -> int:
    """Crea una sesión planificada y devuelve su id.

    ``object_id``/``target_kind`` identifican el destino ('catalog' con la
    designación, o 'region' con el nombre de la región). Las coordenadas y
    el encuadre son los del momento de guardar.
    """
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO planned_sessions (object_id, target_name, setup_id,"
        " session_date, planned_exposure_s, target_kind, ra_hours, dec_deg,"
        " fov_major_arcmin, fov_minor_arcmin, tiles_x, tiles_y, notes)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (object_id, target_name, setup_id, session_date, planned_exposure_s,
         target_kind, ra_hours, dec_deg, fov_major_arcmin, fov_minor_arcmin,
         tiles_x, tiles_y, notes),
    )
    conn.commit()
    return cur.lastrowid


def update_session(session_id: int, **params) -> None:
    """Actualiza los parámetros dados de una sesión.

    Solo se aceptan columnas conocidas (``target_name``, ``session_date``,
    ``notes``...); el resto se ignora para no escribir en la base lo que no
    corresponde.
    """
    fields = {key: value for key, value in params.items() if key in _UPDATABLE}
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn = get_connection()
    conn.execute(
        f"UPDATE planned_sessions SET {assignments} WHERE id = ?",
        (*fields.values(), session_id),
    )
    conn.commit()


def mark_completed(session_id: int) -> None:
    """Marca una sesión como completada (la usa el flujo del Apilador)."""
    conn = get_connection()
    conn.execute(
        "UPDATE planned_sessions SET status = 'completada' WHERE id = ?",
        (session_id,),
    )
    conn.commit()


def delete_session(session_id: int) -> None:
    """Elimina una sesión planificada."""
    conn = get_connection()
    conn.execute("DELETE FROM planned_sessions WHERE id = ?", (session_id,))
    conn.commit()


def list_sessions(status: str | None = None) -> list[dict]:
    """Lista sesiones; opcionalmente filtradas por estado."""
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM planned_sessions WHERE status = ? ORDER BY session_date",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM planned_sessions ORDER BY session_date").fetchall()
    return [dict(row) for row in rows]
