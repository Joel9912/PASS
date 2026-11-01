"""Simulación del recurso único: exposiciones completas y maniobras explícitas con estado nocturno."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .multinight import Allocation
from .planning_models import Operation


@dataclass(frozen=True)
class EquipmentState:
    """Estado tras una toma; su reloj y contadores no se reinician al cambiar de objeto."""

    end: datetime
    focus_end: datetime
    frames: int = 0
    objective: str | None = None
    tile: int = 0
    filter_name: str | None = None


def initial_state(start):
    """El reloj de un enfoque periódico sin enfoque inicial arranca al abrir disponibilidad."""
    return EquipmentState(start, start)


def next_exposure(profile, state, opportunity, filter_name, exposure_s, *, earliest=None, track=None):
    """Intenta una toma y sus eventos previos sin atravesar el final de ventana ni cortar la exposición.

    Devuelve None cuando no cabe. Los eventos solo se adoptan junto a una toma
    válida; no deja enfoques o cambios huérfanos al explorar candidatos.
    """
    cursor = max(state.end, earliest or state.end)
    events = []
    focus_end, frames = state.focus_end, state.frames
    first = state.objective is None
    changed_filter = state.filter_name != filter_name and (not first or filter_name != "Sin filtro")
    moved = (state.objective, state.tile) != (opportunity.objective, opportunity.tile)

    def operation(kind, seconds):
        """Consume tiempo consecutivo y registra su causa en la noche del apuntado activo."""
        nonlocal cursor
        if seconds:
            end = cursor+timedelta(seconds=seconds)
            events.append(Operation(kind, opportunity.night, cursor, end, opportunity.objective, opportunity.tile, filter_name))
            cursor = end

    if moved:
        operation("movement", profile.slew_s or 0)
    if changed_filter:
        operation("filter", profile.filter_s or 0)
    cursor = max(cursor, opportunity.start)
    pause_end = state.end+timedelta(seconds=profile.pause_s or 0) if not first else state.end
    if cursor < pause_end:
        operation("pause", (pause_end-cursor).total_seconds())
    flipped = False
    if profile.meridian_flip and track is not None:
        for transit in track.transits:
            a, b = transit-timedelta(seconds=profile.meridian_s/2), transit+timedelta(seconds=profile.meridian_s/2)
            if cursor < b and cursor+timedelta(seconds=exposure_s) > a:
                if cursor <= a:
                    cursor = a
                    operation("meridian", profile.meridian_s)
                    flipped = True
                else:
                    if state.end <= a and not moved and not changed_filter and all(event.kind == "pause" for event in events):
                        # El veto absorbe el descanso que había avanzado unos segundos.
                        events.clear()
                        cursor = a
                        operation("meridian", profile.meridian_s)
                        flipped = True
                    else:
                        return None
            elif not first and not moved and state.end <= a and cursor >= b:
                # Si se retoma el mismo apuntado, la maniobra debe existir también
                # cuando su ventana central quedó dentro de un hueco sin capturas.
                events.append(Operation("meridian", opportunity.night, a, b, opportunity.objective, opportunity.tile, filter_name))
                flipped = True
    due = ((profile.focus_interval_s is not None and (cursor-focus_end).total_seconds() >= profile.focus_interval_s)
           or (profile.focus_frames is not None and frames >= profile.focus_frames)
           or (first and profile.focus_start) or (changed_filter and profile.focus_filter)
           or (flipped and profile.focus_flip))
    if due:
        if events and events[-1].kind == "pause":
            cursor = events.pop().start
        operation("focus", profile.focus_s or 0)
        focus_end, frames = cursor, 0
        if cursor < pause_end:
            operation("pause", (pause_end-cursor).total_seconds())
    end = cursor+timedelta(seconds=exposure_s)
    if end > opportunity.end:
        return None
    if profile.meridian_flip and track is not None and any(
        cursor < transit+timedelta(seconds=profile.meridian_s/2)
        and end > transit-timedelta(seconds=profile.meridian_s/2) for transit in track.transits
    ):
        return None
    frame = Allocation(opportunity.objective, opportunity.tile, filter_name, opportunity.night, cursor, end, 1, exposure_s)
    updated = replace(state, end=end, focus_end=focus_end, frames=frames+1, objective=opportunity.objective,
                      tile=opportunity.tile, filter_name=filter_name)
    return updated, frame, tuple(sorted(events, key=lambda event: event.start))
