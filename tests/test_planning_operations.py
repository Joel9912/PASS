"""Tiempos operativos sintéticos: integración separada, foco deduplicado y recurso común."""

from datetime import UTC, datetime, timedelta

from equipment.planning_profile import PlanningProfile
from planners.multinight import Opportunity
from planners.planning_models import SkyTrack
from planners.planning_operations import initial_state, next_exposure

START = datetime(2026, 11, 1, 20, tzinfo=UTC)


def window():
    """Ventana controlada que no afirma visibilidad de un objeto astronómico real."""
    return Opportunity("a", 1, "2026-11-01", START, START+timedelta(hours=4))


def test_pausa_entre_tomas_no_se_cobra_al_final():
    """Sesenta tomas suman una hora neta y solo cincuenta y nueve descansos."""
    profile = PlanningProfile(pause_s=2)
    state = initial_state(START)
    frames, events = [], []
    for _ in range(60):
        state, frame, operations = next_exposure(profile, state, window(), "L", 60)
        frames.append(frame)
        events.extend(operations)
    assert sum(f.exposure_s for f in frames) == 3600
    assert (state.end-START).total_seconds() == 3718
    assert len(events) == 59


def test_foco_inicial_contadores_y_descanso_absorbido():
    """El enfoque consume disponibilidad y varios disparadores solo realizan una rutina."""
    profile = PlanningProfile(pause_s=2, filter_s=5, focus_s=30, focus_start=True, focus_filter=True, focus_frames=1)
    state, first, events = next_exposure(profile, initial_state(START), window(), "L", 60)
    assert first.start == START+timedelta(seconds=35)
    assert [event.kind for event in events] == ["filter", "focus"]
    state, second, events = next_exposure(profile, state, window(), "R", 60)
    assert [event.kind for event in events] == ["filter", "focus"]
    assert (second.start-first.end).total_seconds() == 35
    assert state.frames == 1
    assert state.focus_end == second.start


def test_periodico_vence_durante_exposicion_no_la_corta():
    """Termina la toma completa y enfoca antes de la siguiente."""
    profile = PlanningProfile(focus_s=20, focus_interval_s=30)
    state, first, _events = next_exposure(profile, initial_state(START), window(), "L", 60)
    _state, second, events = next_exposure(profile, state, window(), "L", 60)
    assert first.end-first.start == timedelta(seconds=60)
    assert second.start == first.end+timedelta(seconds=20)
    assert [event.kind for event in events] == ["focus"]


def test_enfoque_absorbe_pausa_respetando_minimo():
    """El enfoque periódico sustituye el descanso, sin sumarlo ni acortarlo."""
    for pause, focus in ((2, 20), (30, 20)):
        profile = PlanningProfile(pause_s=pause, focus_s=focus, focus_frames=1)
        state, first, _ = next_exposure(profile, initial_state(START), window(), "L", 60)
        _, second, events = next_exposure(profile, state, window(), "L", 60)
        assert (second.start-first.end).total_seconds() == max(pause, focus)
        assert next(event for event in events if event.kind == "focus").start == first.end


def test_meridiano_reserva_ventana_total_y_enfoque_posterior():
    """No atraviesa la ventana central ni cobra dos veces la maniobra."""
    transit = START+timedelta(minutes=30)
    track = SkyTrack("a", 1, "2026-11-01", (START,), (60,), (transit,))
    profile = PlanningProfile(meridian_flip=True, focus_s=30, focus_flip=True)
    state = initial_state(START)
    state, frame, events = next_exposure(profile, state, window(), "L", 1800, track=track)
    assert frame.start == transit+timedelta(seconds=180)
    assert [event.kind for event in events] == ["meridian", "focus"]
    assert (events[0].end-events[0].start).total_seconds() == 300
