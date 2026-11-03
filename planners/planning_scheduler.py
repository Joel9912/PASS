"""Reparto conjunto por visitas: alternativas comparables y simulación operativa sin ranking científico oculto."""

import itertools
import math
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from .multinight import Balance, Result, _check_cancel, availability, validate
from .planning_candidates import altitude_at
from .planning_models import Alternative, Visit
from .planning_operations import initial_state, next_exposure


def goals_for(request):
    """Segundos por categoría, con el denominador explícito del mosaico elegido."""
    return {(obj.key, tile, demand.filter_name): Decimal(str(demand.hours))*3600/
            (obj.tiles_x*obj.tiles_y if obj.integration_mode == "total_equal" else 1)
            for obj in request.objectives for tile in range(1, obj.tiles_x*obj.tiles_y+1) for demand in obj.demands}


def _integrations(allocations):
    """Agrupa únicamente exposición neta, sin usar duración de visitas como integración."""
    values = defaultdict(int)
    for item in allocations:
        values[item.objective, item.tile, item.filter_name] += item.frames*item.exposure_s
    return values


def _balances(goals, frames):
    """Conserva cada déficit independiente aunque otra categoría tenga más capacidad."""
    assigned = _integrations(frames)
    return tuple(Balance(key, tile, name, float(goal), assigned[key, tile, name]) for (key, tile, name), goal in goals.items())


def _filter_order(request):
    """Solo el orden declarado da prioridad; identidades sin prioridad empatan sin inferir banda espectral."""
    names = {d.filter_name for obj in request.objectives for d in obj.demands}
    return tuple(request.filter_order)+tuple(sorted(names-set(request.filter_order)))


def _visit(request, obj, night, state, remaining, opportunities, tracks, quota, used_filters, *, used_tiles=(), cancelled=None):
    """Explora inicios y secuencias de teselas en una visita, sin rellenar otra ventana obstructiva del mismo objeto."""
    sources = [value for value in opportunities if value.night == night and value.objective == obj.key]
    if not sources:
        return []
    order = _filter_order(request)
    demand_map = {d.filter_name:d for d in obj.demands}
    tiles = sorted({item.tile for item in sources})
    tiles.sort(key=lambda tile: next((t for t in tracks.get((obj.key, tile, night), ()).transits), state.end)
               if (obj.key, tile, night) in tracks else state.end)
    tile_orders = list(itertools.permutations(tiles)) if len(tiles) <= 4 else [
        tuple(tiles[index:]+tiles[:index]) for index in range(min(8, len(tiles)))
    ]+[tuple(reversed(tiles))]
    starts = {max(state.end, value.start) for value in sources}
    for value in sources:
        tile_goal = sum(float(amount) for (key, tile, _name), amount in remaining.items() if key == obj.key and tile == value.tile)
        starts.add(max(state.end, value.start, value.end-timedelta(seconds=min(quota, tile_goal))))
        track = tracks.get((obj.key, value.tile, night))
        center = min(track.transits, key=lambda t: abs((t-value.start).total_seconds())) if track and track.transits else value.start+(value.end-value.start)/2
        if track:
            for transit in track.transits:
                after = transit+timedelta(seconds=request.profile.meridian_s/2)
                if value.start <= after < value.end:
                    starts.add(max(state.end, after))
        for ratio in (.25, .5, .75):
            starts.add(max(state.end, value.start, min(center-timedelta(seconds=quota*ratio), value.end-timedelta(seconds=quota))))
    starts = sorted(starts)
    if len(starts) > 18:
        starts = [starts[round(index*(len(starts)-1)/17)] for index in range(18)]
    choices = []
    for tile_order in dict.fromkeys(tile_orders):
        for beginning in starts:
            _check_cancel(cancelled)
            current, frames, events = state, [], []
            pending = dict(remaining)
            selected_filters, selected_tiles = set(used_filters), set(used_tiles)
            active_sources = {}
            net = 0
            for name in order:
                if name not in demand_map or len(selected_filters | {name}) > request.max_filters:
                    continue
                for tile in tile_order:
                    if len(selected_tiles | {tile}) > obj.max_tiles:
                        continue
                    key = obj.key, tile, name
                    demand = demand_map[name]
                    limit = int(pending[key]//demand.exposure_s)
                    if limit <= 0:
                        continue
                    windows = [value for value in sources if value.tile == tile and value.end > max(current.end, beginning)]
                    if tile in active_sources:
                        windows = [value for value in windows if value == active_sources[tile]]
                    window = next((value for value in windows if value.start <= max(current.end, beginning)), None)
                    if window is None and not frames:
                        window = min(windows, key=lambda value: value.start, default=None)
                    if window is None:
                        continue
                    # No volver a una ventana posterior para esconder una obstrucción.
                    if frames and window.start > current.end:
                        continue
                    track = tracks.get((obj.key, tile, night))
                    for _index in range(limit):
                        _check_cancel(cancelled)
                        if net+demand.exposure_s > quota:
                            break
                        simulated = next_exposure(request.profile, current, window, name, demand.exposure_s,
                                                  earliest=beginning if not frames else None, track=track)
                        if simulated is None:
                            break
                        current, frame, operations = simulated
                        frames.append(frame)
                        events.extend(operations)
                        pending[key] -= demand.exposure_s
                        selected_filters.add(name)
                        selected_tiles.add(tile)
                        active_sources[tile] = window
                        net += demand.exposure_s
            if frames:
                beginning = min(frames[0].start, events[0].start if events else frames[0].start)
                track = tracks.get((obj.key, frames[0].tile, night))
                height = sum(altitude_at(tracks.get((obj.key, f.tile, night)), f.start+(f.end-f.start)/2)*f.exposure_s for f in frames)/net
                reason = f"Bloque continuo · {net/3600:.2f} h netas · altura media muestreada {height:.1f}°"
                if obj.night_mode == "desired":
                    reason += f" · solicitado {obj.night_hours:.2f} h/noche · diferencia {net/3600-obj.night_hours:+.2f} h"
                visit = Visit(obj.key, night, beginning, current.end, net, reason)
                choices.append((current, tuple(frames), tuple(events), visit, pending, selected_filters))
    choices.sort(key=lambda choice: (-choice[3].integration_s,
                                    -sum(altitude_at(tracks.get((f.objective, f.tile, night)), f.start)*f.exposure_s for f in choice[1]),
                                    choice[0].end))
    # Mantiene posiciones distintas, no solo variantes casi iguales del mejor inicio.
    unique = {}
    for choice in choices:
        unique.setdefault((choice[3].start, choice[3].end, tuple((f.tile, f.filter_name) for f in choice[1])), choice)
    return list(unique.values())[:12]


def _capacities(request, opportunities, tracks, goals, cancelled):
    """Capacidad neta aislada: la competencia con otros objetos no rebaja el mínimo aplicable."""
    result = {}
    capacity_goals = {key:Decimal(86400) for key in goals}
    for night, start, _end in availability(request):
        for obj in request.objectives:
            _check_cancel(cancelled)
            choices = _visit(request, obj, night, initial_state(start), capacity_goals, opportunities, tracks, 86400, set(), cancelled=cancelled)
            result[obj.key, night] = max((choice[3].integration_s for choice in choices), default=0)
    return result


def _minimum(capacities, key):
    """Aplica los umbrales acordados a capacidades aisladas, no a huecos residuales del reparto."""
    values = [value for (objective, _night), value in capacities.items() if objective == key and value > 0]
    if not values:
        return 1800
    if max(values) >= 3600 or min(values) >= 1800:
        return 1800
    return 601


def _score(request, frames, events, visits, goals, capacities, tracks, *, future=()):
    """Comparación lexicográfica: pérdida irrecuperable, cobertura equitativa, filtros, preferencia y altura.

    Escasez = integración pendiente que la capacidad futura aislada no puede
    cubrir. No se suman pesos de calidad, clima o supuesta precisión científica.
    """
    assigned = _integrations(frames)
    totals, completed = defaultdict(float), defaultdict(int)
    for key, goal in goals.items():
        totals[key[0]] += float(goal)
        completed[key[0]] += assigned[key]
    fractions = tuple(sorted(completed[key]/total for key, total in totals.items()))
    lost = sum(max(0., totals[key]-completed[key]-sum(capacities.get((key, night), 0) for night in future))/totals[key] for key in totals)
    filters = tuple(sum(value for (key, tile, name), value in assigned.items() if name == filt) for filt in request.filter_order)
    preference = 0.
    for obj in request.objectives:
        own = [visit for visit in visits if visit.objective == obj.key]
        if obj.night_mode == "desired":
            preference -= sum(abs(visit.integration_s-obj.night_hours*3600) for visit in own)/max(1, totals[obj.key])
        elif obj.night_mode == "maximum":
            preference -= len({visit.night for visit in own})
    quality = sum(altitude_at(tracks.get((f.objective, f.tile, f.night)), f.start+(f.end-f.start)/2)*f.exposure_s/
                  max(1, totals[f.objective]) for f in frames)
    return (-round(lost, 8), tuple(round(value, 8) for value in fractions), filters, round(preference, 8), round(quality, 5),
            -len({visit.night for visit in visits}), -len([event for event in events if event.kind != "pause"]))


def _build(request, opportunities, tracks, goals, capacities, quantum, *, extended=False, exceptional=False, cancelled=None):
    """Construye visitas con búsqueda local conjunta por noche y anticipación de capacidad futura."""
    frames, events, visits = (), (), ()
    remaining = dict(goals)
    calendar = availability(request)
    expanded = 0
    for night_index, (night, start, _end) in enumerate(calendar):
        _check_cancel(cancelled)
        future = tuple(day for day, _a, _b in calendar[night_index+1:])
        # Estado, categorías restantes, filtros usados, objetos ya visitados, deltas.
        beam = [(initial_state(start), remaining, set(), set(), (), (), ())]
        all_choices = list(beam)
        for _depth in range(len(request.objectives)*(2 if exceptional else 1)):
            proposals = []
            for state, pending, filters, seen, local_frames, local_events, local_visits in beam:
                for obj in sorted(request.objectives, key=lambda value: value.key):
                    if obj.key in seen and not exceptional:
                        continue
                    if sum(visit.objective == obj.key for visit in local_visits) >= (2 if exceptional else 1):
                        continue
                    rest = sum(float(value) for (key, _tile, _name), value in pending.items() if key == obj.key)
                    minimum = _minimum(capacities, obj.key)
                    if extended:
                        days = sum(capacities.get((obj.key, value), 0) >= minimum for value in (night,)+future)
                        quota = min(rest, max(minimum, math.ceil(rest/max(1, days))))
                    elif obj.night_mode == "maximum":
                        quota = rest
                    elif obj.night_mode == "desired":
                        quota = min(rest, max(minimum, obj.night_hours*3600*quantum/3600))
                    else:
                        quota = min(rest, quantum)
                    if quota < minimum and not exceptional:
                        continue
                    used_tiles = {frame.tile for frame in local_frames if frame.objective == obj.key}
                    choices = _visit(request, obj, night, state, pending, opportunities, tracks, quota, filters,
                                     used_tiles=used_tiles, cancelled=cancelled)
                    expanded += len(choices)
                    for current, additions, operations, visit, rest_goals, used in choices:
                        final_remainder = rest-visit.integration_s < min(d.exposure_s for d in obj.demands)
                        if visit.integration_s < minimum and not (exceptional and final_remainder):
                            continue
                        future_capacity = sum(capacities.get((obj.key, value), 0) for value in future)
                        reason = ("Prioridad por capacidad futura escasa" if rest > future_capacity else "Coordinado con otros objetos y sus ventanas")
                        visit = replace(visit, reason=f"{visit.reason} · {reason}; capacidad futura hallada {future_capacity/3600:.2f} h")
                        proposals.append((current, rest_goals, used, seen | {obj.key}, local_frames+additions,
                                          local_events+operations, local_visits+(visit,)))
            if not proposals:
                break
            proposals.sort(key=lambda value: _score(request, frames+value[4], events+value[5], visits+value[6], goals, capacities, tracks, future=future), reverse=True)
            beam = proposals[:8]
            all_choices.extend(beam)
        best = max(all_choices, key=lambda value: _score(request, frames+value[4], events+value[5], visits+value[6], goals, capacities, tracks, future=future))
        _state, remaining, _filters, _seen, additions, operations, new_visits = best
        frames, events, visits = frames+additions, events+operations, visits+new_visits
    return frames, events, visits, expanded


def schedule(request, opportunities, tracks=(), accuracy=(), *, cancelled=None):
    """Compara cuotas y una alternativa extendida sin adoptar fragmentación o restos cortos silenciosamente."""
    validate(request)
    from .multinight import distribute

    # Reutiliza únicamente la validación de pertenencia de ventanas, sin repartir.
    distribute(replace(request, policy="windows_only"), opportunities)
    goals = goals_for(request)
    track_map = {(track.objective, track.tile, track.night):track for track in tracks}
    capacities = _capacities(request, opportunities, track_map, goals, cancelled)
    variants = [_build(request, opportunities, track_map, goals, capacities, duration, cancelled=cancelled)
                for duration in (1800, 3600, 5400, 7200, 14400)]
    extended = _build(request, opportunities, track_map, goals, capacities, 3600, extended=True, cancelled=cancelled)
    variants.append(extended)
    best = max(variants, key=lambda value: _score(request, value[0], value[1], value[2], goals, capacities, track_map))
    exceptional = _build(request, opportunities, track_map, goals, capacities, 86400, exceptional=True, cancelled=cancelled)
    unknown = [label for name, label in (("pause_s", "pausa entre tomas"), ("slew_s", "movimientos"), ("filter_s", "cambios de filtro"))
               if getattr(request.profile, name) is None]
    notes = ("Búsqueda heurística acotada por candidatos y ancho de exploración; no certifica óptimo global ni imposibilidad.",
             "Orden: oportunidades que se pierden, cobertura equilibrada, prioridad de filtros, altura/tránsito; desempate por noches y maniobras.",
             "Alturas de centros de teselas, malla de un minuto; geometría de cámara y solape nominal, sin clima previsto ni conflictos entre maestros.")
    if unknown:
        notes += ("Tiempos no informados y no contemplados: "+", ".join(unknown)+".",)
    if any(balance.assigned_s < balance.requested_s for balance in _balances(goals, best[0])):
        notes += (("Queda integración pendiente. Compara la alternativa excepcional; también puedes ampliar fechas o disponibilidad "
                   "y recalcular. No se han evaluado ni adoptado fechas externas al rango elegido."),)
    alternatives = []
    for key, label, value, consent in (("recommended", "Recomendado", best, False), ("extended", "Entre más noches", extended, False),
                                       ("exception", "Con fragmentación / resto corto", exceptional, True)):
        frames, events, visits, _count = value
        alternative = Alternative(key, label, frames, _balances(goals, frames), events, visits, notes, consent)
        if key == "extended" and frames == best[0]:
            alternative = replace(alternative, label="Extendida · coincide con recomendada")
        alternatives.append(alternative)
    chosen = alternatives[0]
    result = Result(opportunities, chosen.allocations, chosen.balances, tuple(accuracy), notes, chosen.operations,
                    chosen.visits, tuple(alternatives), chosen.key, tuple(tracks))
    validate_calendar(request, result, capacities=capacities)
    return result


def select_alternative(result, key):
    """Cambia solo la propuesta elegida, sin recalcular ni alterar las otras alternativas."""
    choice = next(value for value in result.alternatives if value.key == key)
    return replace(result, allocations=choice.allocations, balances=choice.balances, operations=choice.operations,
                   visits=choice.visits, selected=key)


def validate_calendar(request, result, *, capacities=None):
    """Comprueba calendario por invariantes y reproducción operativa, sin volver a optimizarlo."""
    from .multinight import distribute

    validate(request)
    distribute(replace(request, policy="windows_only"), result.opportunities)
    nights = {value[0] for value in availability(request)}
    if any(item.night not in nights for item in result.allocations+result.operations+result.visits):
        raise ValueError("El calendario contiene noches ajenas a la disponibilidad.")
    goals = goals_for(request)
    if result.balances != _balances(goals, result.allocations):
        raise ValueError("Balances incoherentes con las tomas del calendario.")
    if any(balance.assigned_s > balance.requested_s for balance in result.balances):
        raise ValueError("El calendario supera objetivos de integración.")
    intervals = sorted([(item.start, item.end) for item in result.allocations+result.operations])
    if any(b <= a for a, b in intervals) or any(a[1] > b[0] for a, b in zip(intervals, intervals[1:])):
        raise ValueError("El calendario tiene tiempos vacíos o solapes de recurso.")
    tracks = {(track.objective, track.tile, track.night):track for track in result.tracks}
    if len(tracks) != len(result.tracks):
        raise ValueError("Curvas de tesela repetidas.")
    for track in result.tracks:
        if not track.times or len(track.times) != len(track.altitudes) or any(
            type(value) not in (int, float) or not math.isfinite(value) or not -90 <= value <= 90 for value in track.altitudes
        ) or any(a >= b for a, b in zip(track.times, track.times[1:])) or any(t.tzinfo is None for t in track.times+track.transits):
            raise ValueError("Curva de tesela inválida.")
    demand = {(obj.key, item.filter_name):item.exposure_s for obj in request.objectives for item in obj.demands}
    objects = {obj.key:obj for obj in request.objectives}
    for night, start, end in availability(request):
        frames = sorted((item for item in result.allocations if item.night == night), key=lambda item: item.start)
        operations = [item for item in result.operations if item.night == night]
        consumed_operations = []
        if len({frame.filter_name for frame in frames}) > request.max_filters:
            raise ValueError("Se supera el máximo global de filtros de la noche.")
        state = initial_state(start)
        for frame in frames:
            if frame.frames != 1 or type(frame.frames) is not int or demand.get((frame.objective, frame.filter_name)) != frame.exposure_s:
                raise ValueError("Toma incompatible con su demanda.")
            if frame.end-frame.start != timedelta(seconds=frame.exposure_s):
                raise ValueError("Una toma no tiene su duración completa.")
            window = next((value for value in result.opportunities if value.objective == frame.objective and value.tile == frame.tile
                           and value.night == night and value.start <= frame.start < frame.end <= value.end), None)
            if window is None:
                raise ValueError("Captura fuera de su ventana admisible.")
            prior = [item for item in operations if state.end <= item.start < frame.start]
            if request.profile.meridian_flip and (frame.objective, frame.tile, night) not in tracks:
                raise ValueError("Falta el tránsito para validar el cambio de meridiano.")
            earliest = prior[0].start if prior else frame.start
            simulated = next_exposure(request.profile, state, window, frame.filter_name, frame.exposure_s,
                                      earliest=earliest, track=tracks.get((frame.objective, frame.tile, night)))
            if simulated is None or simulated[1] != frame or tuple(prior) != simulated[2]:
                raise ValueError("Maniobras o autoenfoque incoherentes con el estado del equipo.")
            state = simulated[0]
            consumed_operations.extend(prior)
        if tuple(consumed_operations) != tuple(operations):
            raise ValueError("El calendario contiene maniobras sin captura asociada.")
        if any(not start <= item.start < item.end <= end for item in frames+operations):
            raise ValueError("Tiempo operativo fuera de disponibilidad.")
        for key, obj in objects.items():
            if len({frame.tile for frame in frames if frame.objective == key}) > obj.max_tiles:
                raise ValueError("Se supera el máximo de teselas del objeto.")
            visits = [value for value in result.visits if value.night == night and value.objective == key]
            if len(visits) > 1 and result.selected != "exception":
                raise ValueError("La propuesta normal fragmenta el objeto en una noche.")
            for visit in visits:
                own = [f for f in frames if f.objective == key and visit.start <= f.start < f.end <= visit.end]
                if sum(f.exposure_s for f in own) != visit.integration_s:
                    raise ValueError("Visita incoherente con su integración.")
        covered = Counter()
        for visit in [value for value in result.visits if value.night == night]:
            if visit.objective not in objects or not start <= visit.start < visit.end <= end:
                raise ValueError("Visita ajena a objetivos o disponibilidad.")
            for frame in frames:
                if frame.objective == visit.objective and visit.start <= frame.start < frame.end <= visit.end:
                    covered[frame] += 1
        if covered != Counter(frames):
            raise ValueError("Las visitas no cubren cada toma exactamente una vez.")
    if capacities is None:
        capacities = _capacities(request, result.opportunities, tracks, goals, None)
    for visit in result.visits:
        if visit.integration_s < _minimum(capacities, visit.objective):
            last = max((v.end for v in result.visits if v.objective == visit.objective), default=visit.end)
            rest = sum(balance.requested_s-balance.assigned_s for balance in result.balances if balance.objective == visit.objective)
            quantum = min(d.exposure_s for d in objects[visit.objective].demands)
            if result.selected != "exception" or visit.end != last or rest >= quantum:
                raise ValueError("Bloque corto fuera de la excepción final seleccionada.")
    return capacities
