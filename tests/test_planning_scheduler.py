"""Reparto conjunto en calendarios sintéticos, sin red ni datos personales."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from equipment.planning_profile import PlanningProfile
from planners.multinight import Demand, Objective, Opportunity, Request
from planners.planning_models import SkyTrack
from planners.planning_scheduler import schedule, select_alternative, validate_calendar


def scenario(days=4, hours=2):
    """Dos objetos con sendos tránsitos y ventanas amplias en un recurso único."""
    start = datetime(2026, 11, 1, 20, tzinfo=UTC)
    objects = tuple(Objective(key, key, 1, 30, (Demand("L", hours, 120),), night_mode="desired", night_hours=1) for key in ("a", "b"))
    request = Request("2026-11-01", (start+timedelta(days=days-1)).date().isoformat(), 40, 1, 0, 19*60, 6*60,
                      tuple(range(7)), 30, objects, "balanced", profile=PlanningProfile(pause_s=2, slew_s=10, filter_s=5))
    windows, tracks = [], []
    for day in range(days):
        base = start+timedelta(days=day)
        for index, obj in enumerate(objects):
            night = base.date().isoformat()
            windows.append(Opportunity(obj.key, 1, night, base, base+timedelta(hours=5)))
            times = tuple(base+timedelta(minutes=i) for i in range(301))
            peak = 60+index*60
            tracks.append(SkyTrack(obj.key, 1, night, times, tuple(70-abs(i-peak)*.1 for i in range(301)),
                                   (base+timedelta(minutes=peak),)))
    return request, tuple(windows), tuple(tracks)


def test_reparto_por_visitas_sin_arroz_con_mango():
    """Las ventanas y el periodo se coordinan sin alternar restos de un objeto en la propuesta principal."""
    request, windows, tracks = scenario()
    result = schedule(request, windows, tracks)
    assert all(balance.assigned_s == balance.requested_s for balance in result.balances)
    assert all(sum(v.objective == obj.key and v.night == night for v in result.visits) <= 1
               for obj in request.objectives for night in {w.night for w in windows})
    assert all(v.integration_s >= 1800 for v in result.visits)
    assert {a.key for a in result.alternatives} == {"recommended", "extended", "exception"}
    for alternative in result.alternatives:
        validate_calendar(request, select_alternative(result, alternative.key))


def test_limite_global_un_filtro_no_un_filtro_por_objeto():
    """Dos objetos con distintos filtros no eluden el límite nocturno común."""
    request, windows, tracks = scenario(days=2, hours=1)
    other = replace(request.objectives[1], demands=(Demand("R", 1, 120),))
    request = replace(request, objectives=(request.objectives[0], other), filter_order=("L", "R"))
    result = schedule(request, windows, tracks)
    for night in {w.night for w in windows}:
        assert len({f.filter_name for f in result.allocations if f.night == night}) <= 1
    assert sum(b.assigned_s for b in result.balances) == 7200


def test_cancelacion_interrumpe_busqueda():
    """No retorna una propuesta parcial como calendario final."""
    request, windows, tracks = scenario()
    with pytest.raises(InterruptedError):
        schedule(request, windows, tracks, cancelled=lambda: True)


def test_calendario_alterado_no_se_valida_reoptimizando():
    """La validación independiente detecta una toma desplazada sin generar otro plan."""
    request, windows, tracks = scenario(days=1, hours=1)
    result = schedule(request, windows, tracks)
    broken = replace(result.allocations[0], end=result.allocations[0].end+timedelta(seconds=1))
    with pytest.raises(ValueError):
        validate_calendar(request, replace(result, allocations=(broken,)+result.allocations[1:]))


def test_resto_corto_se_ofrece_solo_como_excepcion():
    """Un objetivo corto no rebaja el mínimo artificialmente por tener pocas horas solicitadas."""
    request, windows, tracks = scenario(days=1, hours=.25)
    result = schedule(request, windows, tracks)
    assert not result.allocations
    exceptional = select_alternative(result, "exception")
    assert sum(b.assigned_s for b in exceptional.balances) == 1680
    assert result.alternatives[-1].requires_consent


def test_ventanas_cortas_no_son_un_resto_final_por_defecto():
    """No acepta diez minutos exactos por noche para completar horas usando la excepción de resto."""
    request, windows, tracks = scenario(days=2, hours=2)
    windows = tuple(replace(w, end=w.start+timedelta(minutes=10)) for w in windows)
    result = schedule(request, windows, tracks)
    assert not result.allocations
    assert not select_alternative(result, "exception").allocations


def test_alterar_orden_de_objetos_no_cambia_minimos():
    """La capacidad aislada y el resultado no dependen del orden accidental de la lista."""
    request, windows, tracks = scenario(days=1, hours=1)
    first = schedule(request, windows, tracks)
    second = schedule(replace(request, objectives=tuple(reversed(request.objectives))), windows, tracks)
    assert first.allocations == second.allocations


def test_calculo_astronomico_real_incluye_transitos_y_margen():
    """Modelo interno explícito offline; los tránsitos no son el máximo de una curva recortada."""
    from planners.ephemeris import EphemerisModel
    from planners.multinight import calculate

    request, _windows, _tracks = scenario(days=1, hours=1)
    obj = replace(request.objectives[0], ra_hours=.712, dec_deg=41.27)
    request = replace(request, objectives=(obj,), start_minute=19*60, end_minute=23*60)
    result = calculate(request, model=EphemerisModel())
    assert result.tracks[0].transits
    assert result.allocations
    validate_calendar(request, result)


@pytest.mark.parametrize("seed", range(4))
def test_propiedades_con_maniobras_filtros_y_ventanas_partidas(seed):
    """Calendarios variados conservan recurso único, límites y estado operativo en cada alternativa."""
    import random

    rng = random.Random(seed)
    request, windows, tracks = scenario(days=2, hours=1)
    profile = PlanningProfile(pause_s=2, filter_s=5, slew_s=10, meridian_flip=True, focus_s=20,
                              focus_start=True, focus_filter=True, focus_flip=True, focus_interval_s=900, focus_frames=7)
    request = replace(request, profile=profile, max_filters=2)
    windows = tuple(replace(value, start=value.start+timedelta(minutes=rng.randrange(0, 50)),
                            end=value.end-timedelta(minutes=rng.randrange(0, 80))) for value in windows)
    result = schedule(request, windows, tracks)
    for choice in result.alternatives:
        calendar = select_alternative(result, choice.key)
        validate_calendar(request, calendar)
        intervals = sorted([(f.start, f.end) for f in calendar.allocations+calendar.operations])
        assert all(a[1] <= b[0] for a, b in zip(intervals, intervals[1:]))


def test_eventos_huerfanos_y_visitas_ausentes_se_rechazan():
    """No basta conservar balances si se eliminan visitas o se añaden tiempos sin captura asociada."""
    from planners.planning_models import Operation

    request, windows, tracks = scenario(days=1, hours=1)
    result = schedule(request, windows, tracks)
    with pytest.raises(ValueError):
        validate_calendar(request, replace(result, visits=()))
    event = Operation("focus", "2026-11-01", windows[0].end-timedelta(seconds=20), windows[0].end, "a", 1, "L")
    with pytest.raises(ValueError):
        validate_calendar(request, replace(result, operations=result.operations+(event,)))


def test_urgencia_real_precede_prioridad_de_filtro():
    """El objeto sin oportunidad mañana no se pierde por tener un filtro de prioridad inferior."""
    request, windows, tracks = scenario(days=2, hours=1)
    b = replace(request.objectives[1], demands=(Demand("R", 1, 120),))
    request = replace(request, objectives=(request.objectives[0], b), filter_order=("R", "L"),
                      profile=PlanningProfile(pause_s=0, filter_s=0, slew_s=0))
    windows = tuple(replace(value, end=value.start+timedelta(hours=1)) for value in windows
                    if value.objective != "a" or value.night == "2026-11-01")
    result = schedule(request, windows, tracks)
    assert {f.objective for f in result.allocations if f.night == "2026-11-01"} == {"a"}
    assert sum(balance.assigned_s for balance in result.balances) == 7200


@pytest.mark.parametrize("tiles", [2, 3, 4])
def test_teselas_consecutivas_se_coordinan_en_una_visita(tiles):
    """Se exploran secuencias y bordes de tesela, no solo el inicio del mosaico completo."""
    request, windows, _tracks = scenario(days=1, hours=1)
    obj = replace(request.objectives[0], tiles_x=tiles, fov_width=1, fov_height=1, max_tiles=tiles, night_mode="maximum")
    request = replace(request, objectives=(obj,), profile=PlanningProfile(pause_s=0, slew_s=0, filter_s=0))
    base = windows[0].start
    windows = tuple(Opportunity("a", index+1, "2026-11-01", base+timedelta(hours=index), base+timedelta(hours=index+1))
                    for index in range(tiles))
    result = schedule(request, windows)
    assert len(result.visits) == 1
    assert {f.tile for f in result.allocations} == set(range(1, tiles+1))
    assert sum(b.assigned_s for b in result.balances) == 3600*tiles
