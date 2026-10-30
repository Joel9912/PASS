"""Ventanas y reparto multinoches explícito: restricciones simultáneas, exposiciones enteras y déficit sin ranking ficticio."""

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
from astropy import units as u
from astropy.coordinates import EarthLocation, SkyCoord, angular_separation
from astropy.time import Time

from equipment.models import DIRECTIONS

from .astronomy_status import astronomy_status
from .ephemeris import EphemerisModel, model_scope
from .moon_distance import (
    POSSIBLE_LOW_MOON_ALTITUDE,
    POSSIBLE_MOON_MARGIN,
    min_moon_distance,
)
from .planning_dates import planning_date
from .sky_state import civil_to_utc
from .timezones import rules_label
from .transit import (
    ASTRO_TWILIGHT_DEG,
    _lunar_illumination,
    _moon_sun_series,
    _target_arrays,
)


@dataclass(frozen=True)
class Demand:
    """Horas solicitadas para un filtro y duración de cada toma; no se añaden overheads desconocidos."""

    filter_name: str
    hours: float
    exposure_s: int


@dataclass(frozen=True)
class Objective:
    """Objeto con identidad local explícita y encuadre elegido, sin imponer precedencia región/equipo."""

    key: str
    name: str
    ra_hours: float
    dec_deg: float
    demands: tuple[Demand, ...]
    tiles_x: int = 1
    tiles_y: int = 1
    fov_width: float | None = None
    fov_height: float | None = None
    integration_mode: str = "per_tile"


@dataclass(frozen=True)
class Request:
    """Entradas por valor para un calendario único: la fecha identifica el inicio civil de la franja."""

    start: str
    end: str
    latitude: float
    longitude: float
    clock: str | float | None
    start_minute: int
    end_minute: int
    weekdays: tuple[int, ...]
    minimum_altitude: float
    objectives: tuple[Objective, ...]
    policy: str
    obstacles: tuple[float, ...] | None = None
    horizon_policy: str | None = None


@dataclass(frozen=True)
class Opportunity:
    """Intervalo UTC semiabierto admisible para el centro de una tesela, con límites de muestreo declarados."""

    objective: str
    tile: int
    night: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Allocation:
    """Bloque de tomas enteras de un objeto/filtro/tesela; comparte un solo recurso temporal con el resto."""

    objective: str
    tile: int
    filter_name: str
    night: str
    start: datetime
    end: datetime
    frames: int
    exposure_s: int


@dataclass(frozen=True)
class Balance:
    """Objetivo y reparto por categoría: un exceso en otro filtro no compensa lo que falta aquí."""

    objective: str
    tile: int
    filter_name: str
    requested_s: float
    assigned_s: int


@dataclass(frozen=True)
class Result:
    """Propuesta reproducible de reparto, no plan confirmado ni promesa de clima o tiempo instrumental real."""

    opportunities: tuple[Opportunity, ...]
    allocations: tuple[Allocation, ...]
    balances: tuple[Balance, ...]
    accuracy: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class Preview:
    """Curvas de la franja efectiva y máscara conjunta de restricciones, no bandas del ranking antiguo."""

    times: tuple[str, ...]
    altitude: tuple[float, ...]
    moon_altitude: tuple[float, ...]
    horizon: tuple[float, ...]
    allowed: tuple[bool, ...]
    accuracy: str


def objective_from_data(data, exposure):
    """Restaura un objetivo de borrador usando la exposición vigente de los Valores del plan."""
    if not isinstance(data, dict) or set(data) != {
        "key", "name", "ra_hours", "dec_deg", "demands", "tiles_x", "tiles_y", "fov_width", "fov_height", "integration_mode",
    }:
        raise ValueError("Objetivo de borrador incompatible.")
    item = dict(data)
    if not isinstance(item["demands"], (list, tuple)):
        raise TypeError("Filtros de borrador inválidos.")
    for value in item["demands"]:
        if not isinstance(value, dict) or set(value) != {"filter_name", "hours", "exposure_s"}:
            raise ValueError("Filtro de borrador incompatible.")
        if type(value["exposure_s"]) is not int or not 1 <= value["exposure_s"] <= 7200:
            raise ValueError("Exposición de borrador inválida.")
    item["demands"] = tuple(Demand(value["filter_name"], value["hours"], exposure) for value in item["demands"])
    return Objective(**item)


def validate_editor(data):
    """Rechaza formatos futuros, claves desconocidas y valores truncables, sin exigir un plan completo."""
    keys = {"version", "start", "end", "start_minute", "end_minute", "weekdays", "minimum_altitude", "policy",
            "location_id", "setup_id", "use_obstacles", "horizon_policy", "exposure", "notes", "name", "objectives"}
    if not isinstance(data, dict) or set(data) != keys or type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("Borrador multinoches incompatible.")
    for key in ("start", "end"):
        if not isinstance(data[key], str) or date.fromisoformat(data[key]).isoformat() != data[key]:
            raise ValueError("Fecha de borrador inválida.")
        if date.fromisoformat(data[key]) < date(1752, 9, 14):
            raise ValueError("Fecha fuera del rango del editor.")
    for key, low, high in (("start_minute", 0, 1439), ("end_minute", 0, 1439), ("exposure", 1, 7200)):
        if type(data[key]) is not int or not low <= data[key] <= high:
            raise ValueError("Valor fuera de rango en el borrador.")
    _number(data["minimum_altitude"], 0, 90)
    if round(data["minimum_altitude"], 2) != data["minimum_altitude"]:
        raise ValueError("La altura del borrador supera la resolución del editor.")
    if not isinstance(data["weekdays"], list) or any(type(day) is not int or day not in range(7) for day in data["weekdays"]):
        raise ValueError("Días de borrador inválidos.")
    if data["policy"] not in (None, "windows_only", "chronological_order") or data["horizon_policy"] not in (None, "sectors", "linear"):
        raise ValueError("Política de borrador desconocida.")
    for key in ("location_id", "setup_id"):
        if data[key] is not None and (type(data[key]) is not int or data[key] <= 0):
            raise ValueError("Referencia inválida en el borrador.")
    if type(data["use_obstacles"]) is not bool or any(not isinstance(data[key], str) for key in ("name", "notes")):
        raise ValueError("Datos de borrador inválidos.")
    if any(len(data[key]) > 32767 for key in ("name", "notes")):
        raise ValueError("El texto del borrador excede el tamaño admitido por el editor.")
    if not isinstance(data["objectives"], list):
        raise TypeError("Objetivos de borrador inválidos.")
    identities = []
    for item in data["objectives"]:
        if not isinstance(item, dict) or set(item) != {"object_id", "catalog", "source", "region_fov_mode", "objective"}:
            raise ValueError("Objetivo de borrador incompatible.")
        if item["source"] not in ("none", "setup", "region") or any(not isinstance(item[key], str) or not item[key] for key in ("object_id", "catalog")):
            raise ValueError("Fuente o identidad del encuadre desconocida.")
        if item["region_fov_mode"] not in (None, "per_tile", "whole_frame"):
            raise ValueError("Interpretación del FOV regional desconocida.")
        if item["source"] == "region" and item["region_fov_mode"] is None:
            raise ValueError("El FOV regional requiere una interpretación explícita.")
        obj = objective_from_data(item["objective"], data["exposure"])
        if obj.key != json.dumps([item["catalog"], item["object_id"]], ensure_ascii=False):
            raise ValueError("Identidad del objetivo incoherente.")
        identities.append(obj.key)
        validate(Request("2026-01-01", "2026-01-01", 0, 0, 0, 0, 60, (0,), 30, (obj,), "windows_only"))
    if len(set(identities)) != len(identities):
        raise ValueError("Objetivos de borrador repetidos.")


def _number(value, low, high):
    """Rechaza ausencias, booleanos y no finitos antes de calcular o truncar datos."""
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Número fuera del intervalo admitido.")


def validate(request: Request):
    """Valida el intervalo completo y las decisiones explícitas; no corrige entradas silenciosamente."""
    first, last = planning_date(request.start), planning_date(request.end)
    if last < first:
        raise ValueError("La fecha final es anterior a la inicial.")
    _number(request.latitude, -90, 90)
    _number(request.longitude, -180, 180)
    _number(request.minimum_altitude, 0, 90)
    for value in (request.start_minute, request.end_minute):
        if type(value) is not int or not 0 <= value < 1440:
            raise ValueError("La disponibilidad debe expresarse en minutos civiles de 00:00 a 23:59.")
    if not request.weekdays or any(type(day) is not int or day not in range(7) for day in request.weekdays):
        raise ValueError("Selecciona al menos un día de disponibilidad.")
    if request.policy not in ("windows_only", "chronological_order"):
        raise ValueError("Elige una política de reparto; no se impone una prioridad de objetos.")
    if request.obstacles is not None:
        if len(request.obstacles) != len(DIRECTIONS) or request.horizon_policy not in ("sectors", "linear"):
            raise ValueError("Elige cómo interpretar las ocho direcciones del horizonte.")
        for altitude in request.obstacles:
            _number(altitude, 0, 90)
    if not request.objectives:
        raise ValueError("Añade al menos un objetivo al plan.")
    if not isinstance(request.objectives, tuple) or not isinstance(request.weekdays, tuple):
        raise TypeError("La petición debe contener colecciones inmutables.")
    keys = [objective.key for objective in request.objectives]
    if len(set(keys)) != len(keys) or any(not isinstance(key, str) or not key for key in keys):
        raise ValueError("Los objetivos deben tener identidades distintas.")
    for objective in request.objectives:
        _number(objective.ra_hours, 0, 24)
        _number(objective.dec_deg, -90, 90)
        if not isinstance(objective.name, str) or not objective.name.strip() or not objective.demands:
            raise ValueError("Cada objeto necesita nombre y objetivos de integración.")
        if not isinstance(objective.demands, tuple):
            raise TypeError("Los filtros de una petición deben ser inmutables.")
        if objective.integration_mode not in ("per_tile", "total_equal"):
            raise ValueError("Elige integración por tesela o total con reparto equitativo explícito.")
        for tiles in (objective.tiles_x, objective.tiles_y):
            if type(tiles) is not int or not 1 <= tiles <= 20:
                raise ValueError("Teselas fuera de rango.")
        if (objective.fov_width is None) != (objective.fov_height is None):
            raise ValueError("El FOV necesita los dos ejes o ninguno.")
        if objective.fov_width is not None:
            _number(objective.fov_width, .000001, 90)
            _number(objective.fov_height, .000001, 90)
        elif objective.tiles_x * objective.tiles_y > 1:
            raise ValueError("No se calculan centros de teselas sin un FOV explícito.")
        names = [demand.filter_name for demand in objective.demands]
        if len(set(names)) != len(names):
            raise ValueError("Un filtro no puede repetirse dentro del mismo objeto.")
        for demand in objective.demands:
            if not isinstance(demand.filter_name, str) or not demand.filter_name.strip():
                raise ValueError("Identifica el filtro o usa «Sin filtro».")
            _number(demand.hours, .000001, 1_000_000)
            if type(demand.exposure_s) is not int or not 1 <= demand.exposure_s <= 7200:
                raise ValueError("La exposición por toma debe estar entre 1 y 7200 segundos.")
    return first, last


def availability(request: Request) -> tuple[tuple[str, datetime, datetime], ...]:
    """Construye franjas por fechas/días civiles; al cruzar medianoche conserva la fecha de inicio.

    Inicio igual a fin significa 24 horas civiles. DST puede producir 23/25 horas
    físicas; los límites civiles ambiguos o inexistentes se rechazan, sin elegir fold.
    """
    first, last = validate(request)
    location = {"longitude": request.longitude, "timezone_id": request.clock if isinstance(request.clock, str) else None,
                "utc_offset_hours": request.clock if not isinstance(request.clock, str) else None}
    windows = []
    for offset in range((last-first).days+1):
        day = first + timedelta(days=offset)
        if day.weekday() not in request.weekdays:
            continue
        base = datetime.combine(day, datetime.min.time())
        start = base + timedelta(minutes=request.start_minute)
        end = base + timedelta(minutes=request.end_minute)
        if end <= start:
            end += timedelta(days=1)
        planning_date(end.date().isoformat())
        windows.append((day.isoformat(), civil_to_utc(start, location), civil_to_utc(end, location)))
    return tuple(windows)


def tile_centers(objective: Objective) -> tuple[tuple[float, float], ...]:
    """Centros nominales gnomónicos norte-arriba sin solape/rotación inventados; misma geometría que la carta."""
    if objective.tiles_x * objective.tiles_y == 1:
        return ((objective.ra_hours, objective.dec_deg),)
    ra0, dec0 = math.radians(objective.ra_hours*15), math.radians(objective.dec_deg)
    width, height = 2*math.tan(math.radians(objective.fov_width)/2), 2*math.tan(math.radians(objective.fov_height)/2)
    result = []
    for y in range(objective.tiles_y):
        for x in range(objective.tiles_x):
            xi = ((objective.tiles_x-1)/2-x)*width
            eta = ((objective.tiles_y-1)/2-y)*height
            rho = math.hypot(xi, eta)
            if rho == 0:
                result.append((objective.ra_hours, objective.dec_deg))
                continue
            c = math.atan(rho)
            dec = math.asin(math.cos(c)*math.sin(dec0)+eta*math.sin(c)*math.cos(dec0)/rho)
            ra = ra0 + math.atan2(xi*math.sin(c), rho*math.cos(dec0)*math.cos(c)-eta*math.sin(dec0)*math.sin(c))
            result.append((math.degrees(ra) % 360 / 15, math.degrees(dec)))
    return tuple(result)


def mosaic_fov(width, height, tiles_x, tiles_y, *, inverse=False):
    """Convierte FOV por tesela ↔ campo total sobre el mismo plano tangente, sin sumar ángulos linealmente."""
    operation = (lambda angle, count: math.tan(math.radians(angle)/2)/count) if inverse else (
        lambda angle, count: math.tan(math.radians(angle)/2)*count)
    return (math.degrees(2*math.atan(operation(width, tiles_x))), math.degrees(2*math.atan(operation(height, tiles_y))))


def horizon_at(azimuth, profile, policy):
    """Evalúa el perfil con la interpretación seleccionada, circular también entre NO y N."""
    if profile is None:
        return np.zeros_like(azimuth, dtype=float)
    position = np.asarray(azimuth) % 360 / 45
    if policy == "sectors":
        return np.asarray(profile)[np.floor(position+.5).astype(int) % 8]
    if policy != "linear":
        raise ValueError("Interpretación del horizonte no elegida.")
    lower = np.floor(position).astype(int)
    fraction = position-lower
    values = np.asarray(profile)
    return values[lower % 8]*(1-fraction)+values[(lower+1) % 8]*fraction


def sampled_windows(seconds, valid) -> tuple[tuple[float, float], ...]:
    """Conserva solo segmentos cuyos dos extremos cumplen todas las condiciones; no rellena huecos.

    Resolución nominal de un minuto, conservadora en sus bordes; no certifica
    continuidad submuestra ni exactitud instrumental. No extrapola al último punto.
    """
    if len(seconds) != len(valid) or len(seconds) < 2:
        raise ValueError("La malla necesita tiempos y condiciones correspondientes.")
    if any(not math.isfinite(float(value)) for value in seconds) or any(b <= a for a, b in zip(seconds, seconds[1:])):
        raise ValueError("El tiempo debe ser finito y estrictamente creciente.")
    spans = []
    for index in range(len(seconds)-1):
        if not valid[index] or not valid[index+1]:
            continue
        a, b = float(seconds[index]), float(seconds[index+1])
        if spans and spans[-1][1] == a:
            spans[-1] = (spans[-1][0], b)
        else:
            spans.append((a, b))
    return tuple(spans)


def _sample_times(start, end):
    """Malla de paso máximo un minuto, sin duplicar el borde por residuos flotantes de Time.

    La representación civil datetime alcanza microsegundos; el intervalo físico
    se obtiene con Time antes de generar muestras, incluidos segundos intercalares.
    """
    start_time, end_time = Time(start), Time(end)
    duration = round(float((end_time-start_time).to_value(u.s)), 6)
    seconds = np.linspace(0., duration, max(1, math.ceil(duration/60))+1)
    times = start_time+seconds*u.s
    times.precision = 6
    return start_time, seconds, times


def inspect_night(request: Request, key: str, tile: int, night: str, *, model: EphemerisModel | None = None) -> Preview:
    """Inspecciona la disponibilidad elegida con exactamente las condiciones del cálculo del plan."""
    windows = availability(request)
    objective = next(item for item in request.objectives if item.key == key)
    center = tile_centers(objective)[tile-1]
    _day, start, end = next(item for item in windows if item[0] == night)
    with model_scope(model):
        _start_time, _seconds, times = _sample_times(start, end)
        location = EarthLocation(lat=request.latitude*u.deg, lon=request.longitude*u.deg)
        moon_az, moon_alt, sun_alt = _moon_sun_series(times, location)
        az, alt = _target_arrays(times, location, SkyCoord(ra=center[0]*u.hourangle, dec=center[1]*u.deg, frame="icrs"))
        separation = angular_separation(az*u.deg, alt*u.deg, moon_az*u.deg, moon_alt*u.deg).to_value(u.deg)
        horizon = horizon_at(az, request.obstacles, request.horizon_policy)
        valid = eligibility(alt, separation, moon_alt, sun_alt, horizon, request.minimum_altitude,
                            _lunar_illumination(times, location)*100)
        return Preview(tuple(str(value) for value in times.isot), tuple(map(float, alt)), tuple(map(float, moon_alt)),
                       tuple(map(float, horizon)), tuple(map(bool, valid)), astronomy_status(times).details)


def eligibility(alt, separation, moon_alt, sun_alt, horizon, minimum_altitude, illumination_pct):
    """Interseca oscuridad, altura, horizonte y la regla lunar Posible vigente, sin alterar su polinomio."""
    values = [np.asarray(value) for value in (alt, separation, moon_alt, sun_alt, horizon)]
    if len({value.shape for value in values}) != 1 or not all(np.all(np.isfinite(value)) for value in values):
        raise ValueError("La malla astronómica debe ser finita y tener dimensiones correspondientes.")
    alt, separation, moon_alt, sun_alt, horizon = values
    threshold = min_moon_distance(illumination_pct)-POSSIBLE_MOON_MARGIN
    return ((sun_alt < ASTRO_TWILIGHT_DEG) & (alt >= minimum_altitude) & (alt > horizon)
            & ((moon_alt < POSSIBLE_LOW_MOON_ALTITUDE) | (separation >= threshold)))


def _check_cancel(cancelled):
    """La cancelación retira todo el resultado, nunca entrega un plan parcial como completo."""
    if cancelled and cancelled():
        raise InterruptedError("Cálculo cancelado; no se han creado sesiones.")


def calculate(request: Request, *, model: EphemerisModel | None = None,
              cancelled: Callable[[], bool] | None = None, progress: Callable[[int, int], None] | None = None) -> Result:
    """Calcula fuera de Qt con un modelo fijo y conexión propia readonly; no escribe ni ejecuta SirIL."""
    windows = availability(request)
    opportunities, accuracy = [], set()
    total = len(windows)*sum(obj.tiles_x*obj.tiles_y for obj in request.objectives)
    done = 0
    location = EarthLocation(lat=request.latitude*u.deg, lon=request.longitude*u.deg)
    with model_scope(model):
        for night, start, end in windows:
            _check_cancel(cancelled)
            start_time, seconds, times = _sample_times(start, end)
            moon_az, moon_alt, sun_alt = _moon_sun_series(times, location)
            illumination = _lunar_illumination(times, location)*100
            accuracy.add(astronomy_status(times).details)
            for objective in request.objectives:
                for tile, (ra, dec) in enumerate(tile_centers(objective), 1):
                    _check_cancel(cancelled)
                    az, alt = _target_arrays(times, location, SkyCoord(ra=ra*u.hourangle, dec=dec*u.deg, frame="icrs"))
                    separation = angular_separation(az*u.deg, alt*u.deg, moon_az*u.deg, moon_alt*u.deg).to_value(u.deg)
                    horizon = horizon_at(az, request.obstacles, request.horizon_policy)
                    if not all(np.all(np.isfinite(values)) for values in (az, alt, separation, moon_alt, sun_alt)):
                        raise ValueError("La malla astronómica contiene valores no finitos.")
                    valid = eligibility(alt, separation, moon_alt, sun_alt, horizon, request.minimum_altitude, illumination)
                    for a, b in sampled_windows(seconds, valid):
                        # Los límites civiles se presentan con datetime; el cálculo de duración conserva Time.
                        begin = (start_time+a*u.s).to_datetime(timezone=UTC, leap_second_strict="warn")
                        finish = (start_time+b*u.s).to_datetime(timezone=UTC, leap_second_strict="warn")
                        opportunities.append(Opportunity(objective.key, tile, night, begin, finish))
                    done += 1
                    if progress:
                        progress(done, total)
    _check_cancel(cancelled)
    return distribute(request, tuple(opportunities), tuple(sorted(accuracy)), cancelled=cancelled)


def _free_spans(start, end, occupied):
    """Resta todos los bloques de otros objetos/filtros del único recurso temporal del plan."""
    cursor = start
    for a, b in sorted(occupied):
        if b <= cursor or a >= end:
            continue
        if a > cursor:
            yield cursor, min(a, end)
        cursor = max(cursor, b)
        if cursor >= end:
            return
    if cursor < end:
        yield cursor, end


def distribute(request: Request, opportunities: tuple[Opportunity, ...], accuracy=(), *, cancelled=None) -> Result:
    """Propuesta cronológica por el orden elegido; sin optimizador oculto ni ranking entre noches equivalentes.

    No redistribuye carencias a otras categorías, no sobrepasa objetivos y no
    presume coste cero real: el resultado expresa integración, sin overheads.
    """
    calendar = {day:(start, end) for day, start, end in availability(request)}
    known = {objective.key: objective for objective in request.objectives}
    for item in opportunities:
        if item.objective not in known or type(item.tile) is not int or not 1 <= item.tile <= known[item.objective].tiles_x*known[item.objective].tiles_y:
            raise ValueError("Ventana para objetivo o tesela desconocidos.")
        if item.start.tzinfo is None or item.end.tzinfo is None or item.end <= item.start:
            raise ValueError("Ventana sin límites UTC válidos.")
        if item.night not in calendar or not calendar[item.night][0] <= item.start < item.end <= calendar[item.night][1]:
            raise ValueError("La ventana excede la disponibilidad del usuario.")
    allocations, balances, occupied = [], [], []
    for objective in request.objectives:
        tiles = objective.tiles_x*objective.tiles_y
        for demand in objective.demands:
            for tile in range(1, tiles+1):
                _check_cancel(cancelled)
                exact_goal = Decimal(str(demand.hours))*3600/(tiles if objective.integration_mode == "total_equal" else 1)
                goal = float(exact_goal)
                assigned = 0
                if request.policy == "chronological_order":
                    candidates = sorted((item for item in opportunities if item.objective == objective.key and item.tile == tile),
                                        key=lambda item: item.start)
                    for candidate in candidates:
                        for a, b in list(_free_spans(candidate.start, candidate.end, occupied)):
                            remaining_frames = int((exact_goal-assigned)//demand.exposure_s)
                            available_frames = (b-a)//timedelta(seconds=demand.exposure_s)
                            count = min(remaining_frames, available_frames)
                            if count <= 0:
                                continue
                            finish = a+timedelta(seconds=count*demand.exposure_s)
                            allocations.append(Allocation(objective.key, tile, demand.filter_name, candidate.night,
                                                          a, finish, count, demand.exposure_s))
                            occupied.append((a, finish))
                            assigned += count*demand.exposure_s
                balances.append(Balance(objective.key, tile, demand.filter_name, goal, assigned))
    warnings = ("Muestreo de un minuto; evaluación en el centro de cada tesela, no de toda su huella.",
                "Admisibilidad lunar de Captura Posible, con el polinomio y margen vigentes; altura mínima elegida por el usuario.",
                "Integración sin tiempos de descarga, enfoque, cambios de filtro o meridiano; sin pronóstico meteorológico.",
                "Teselas nominales norte-arriba, sin rotación ni solape calculado.",
                "No detecta conflictos de horario con otros maestros ni consolida planes independientes.")
    warnings += (rules_label(),)
    if request.policy == "windows_only":
        warnings += ("Solo ventanas: no se ha elegido un reparto de capturas.",)
    else:
        warnings += ("Propuesta cronológica por orden elegido, no óptimo global ni ranking científico de noches.",)
    if not opportunities:
        warnings += ("No hay ventanas que cumplan simultáneamente la disponibilidad y todas las restricciones elegidas.",)
    elif not allocations and request.policy == "chronological_order":
        warnings += ("Ninguna toma completa cabe en la combinación de ventanas y objetivos de integración solicitados.",)
    return Result(opportunities, tuple(sorted(allocations, key=lambda item: item.start)), tuple(balances), tuple(accuracy), warnings)
