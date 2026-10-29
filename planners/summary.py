"""Lecturas y modelos de Resumen: presenta hechos disponibles, sin asociar capturas por nombres ni procesarlas."""

import math
from dataclasses import dataclass
from datetime import date

from db.connection import get_connection


@dataclass(frozen=True)
class IntegrationProgress:
    """Objetivo explícito y horas observadas; selección y datos sin auditar siguen distinguidos."""

    goal_hours: float
    selected_hours: float
    pending_hours: float = 0.0

    def __post_init__(self):
        """Rechaza cifras inventadas por valores no finitos o tiempos negativos."""
        if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
               for value in (self.goal_hours, self.selected_hours, self.pending_hours)) or self.goal_hours == 0:
            raise ValueError("La integración necesita un objetivo positivo y horas finitas no negativas.")

    @property
    def total_hours(self) -> float:
        """Suma seleccionadas y pendientes, sin recuperar descartadas de una selección previa."""
        return self.selected_hours + self.pending_hours

    @property
    def fraction(self) -> float:
        """Acota solo la representación; no recorta las horas reales."""
        return min(1.0, self.total_hours / self.goal_hours)

    @property
    def extra_hours(self) -> float:
        """Mantiene visible el exceso sin compensar automáticamente otras categorías."""
        return max(0.0, self.total_hours - self.goal_hours)


@dataclass(frozen=True)
class Activity:
    """Una actividad existente con destino de navegación; no carga ni modifica su borrador."""

    section: str
    title: str
    kind: str


@dataclass(frozen=True)
class Overview:
    """Instantánea local de sesiones guardadas y borradores, sin acceso a fotografías."""

    sessions: tuple[dict, ...]
    activities: tuple[Activity, ...]


def read_overview(today: date) -> Overview:
    """Lee datos legacy reales sin tratarlos como planes multinoches ni deducir sus horas objetivo.

    planned_exposure_s es exposición por toma, no la integración total solicitada.
    Los nuevos archivos maestro/vínculos no están implementados en esta etapa.
    """
    conn = get_connection()
    sessions = tuple(dict(row) for row in conn.execute(
        "SELECT s.*, e.name AS setup_name, l.name AS location_name FROM planned_sessions s "
        "LEFT JOIN equipment_setups e ON e.id=s.setup_id LEFT JOIN locations l ON l.id=e.location_id "
        "ORDER BY s.session_date,s.id"
    ))
    activities = []
    for row in conn.execute("SELECT workflow,updated_at FROM work_drafts ORDER BY workflow"):
        section = {"planner": "planner_tab", "stacker": "stacker_tab"}.get(row[0])
        if section:
            activities.append(Activity(section, f"Borrador guardado · {row[1]}", "continue"))
    for item in sessions:
        if item.get("status") == "completada":
            continue
        try:
            day = date.fromisoformat(item["session_date"])
        except (ValueError, TypeError):
            continue
        if day >= today:
            activities.append(Activity("planner_tab", f"{item['target_name']} · {day.strftime('%d/%m/%Y')}", "upcoming"))
    return Overview(sessions, tuple(activities))


def sessions_on_day(overview: Overview, today: date) -> tuple[dict, ...]:
    """Filtra por fecha guardada sin inventar intervalos ni resolver prioridades horarias inexistentes."""
    return tuple(item for item in overview.sessions
                 if item.get("session_date") == today.isoformat() and item.get("status") != "completada")
