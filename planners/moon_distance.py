"""Distancia mínima a la Luna según su fase y ventanas de captura.

El usuario definió una función polinómica de grado 3 ajustada a sus propios
datos reales de fase lunar vs distancia mínima aceptable (R² = 0.9994,
RMSE = 0.75°). El umbral NO se impone: se calcula de la iluminación de esa
noche y la UI lo muestra para que se pueda revisar.

Con ese umbral se clasifica cada instante de la noche en tres ventanas:
- ``ideal``:    altitud > 45° y separación lunar > umbral (mejor captura).
- ``possible``: altitud >= 30° y separación >= umbral - 10° (aceptable).
- ``no_possible``: todo lo demás dentro de la noche astronómica.

Solo se clasifica dentro de la noche astronómica; el día y el crepúsculo
quedan fuera (la UI los pinta aparte).

La separación lunar solo se exige cuando la Luna está sobre el horizonte
(``moon_altitude > 0°``): con la Luna hundida no contamina, así que la
condición de separación se da por cumplida y manda únicamente la altitud
del objeto. Sin esa regla, un objeto a tiro de umbral quedaba bloqueado
por una separación angular calculada contra una Luna invisible.
"""
from __future__ import annotations

#: Etiquetas de ventana (constantes para que UI y tests no las escriban a mano).
WINDOW_IDEAL = "ideal"
WINDOW_POSSIBLE = "possible"
WINDOW_NO_POSSIBLE = "no_possible"

#: Umbrales de altitud (grados) de las ventanas de captura.
IDEAL_MIN_ALTITUDE = 45.0
POSSIBLE_MIN_ALTITUDE = 30.0

#: Margen de tolerancia (grados) respecto al umbral lunar para "possible".
POSSIBLE_MOON_MARGIN = 10.0

#: Coeficientes del polinomio de grado 3 (de mayor a menor potencia).
#: Ajustados por mínimos cuadrados a los datos del usuario.
_POLY_COEFFS = (4.061e-05, -5.012e-03, 0.8861, 40.53)


def min_moon_distance(illumination_pct: float) -> float:
    """Distancia mínima aceptable a la Luna según su iluminación (0-100 %).

    ``dist = a·x³ + b·x² + c·x + d`` con ``x`` en % de iluminación.

    Valores de referencia:
    - Luna nueva (0 %)  → ~40°
    - Cuarto (50 %)     → ~77°
    - Luna llena (100 %) → ~120°

    La iluminación se recorta al rango [0, 100] para no salir del ajuste.
    """
    x = max(0.0, min(100.0, float(illumination_pct)))
    a, b, c, d = _POLY_COEFFS
    return a * x**3 + b * x**2 + c * x + d


def classify_instant(
    altitude_deg: float,
    separation_moon_deg: float,
    illumination_pct: float,
    moon_altitude_deg: float,
) -> str:
    """Clasifica un instante de la noche en una ventana de captura.

    - ``ideal``:    altitud > 45° y separación > umbral.
    - ``possible``: altitud >= 30° y separación >= umbral - 10° (y no ideal).
    - ``no_possible``: el resto.

    Si ``moon_altitude_deg`` no supera los 0° la Luna está bajo el
    horizonte: no contamina, la separación se da por cumplida y solo
    manda la altitud. En cuanto la Luna asoma, la distancia exige el
    umbral de vuelta.

    Esta función NO mira si es de noche: el filtro de noche astronómica lo
    aplica quien tenga la máscara (ver :func:`capture_windows`).
    """
    min_dist = min_moon_distance(illumination_pct)
    moon_up = moon_altitude_deg > 0.0
    sep_ok_ideal = not moon_up or separation_moon_deg > min_dist
    sep_ok_possible = (
        not moon_up or separation_moon_deg >= min_dist - POSSIBLE_MOON_MARGIN
    )
    if altitude_deg > IDEAL_MIN_ALTITUDE and sep_ok_ideal:
        return WINDOW_IDEAL
    if altitude_deg >= POSSIBLE_MIN_ALTITUDE and sep_ok_possible:
        return WINDOW_POSSIBLE
    return WINDOW_NO_POSSIBLE


def capture_windows(
    altitudes: list[float],
    moon_separations: list[float],
    moon_altitudes: list[float],
    astro_night_mask: list[bool],
    illumination_pct: float,
) -> list[str]:
    """Clasifica cada instante de la malla nocturna en su ventana.

    Devuelve una lista con la ventana de cada instante (``ideal``,
    ``possible`` o ``no_possible``). Los instantes fuera de la noche
    astronómica se etiquetan ``no_possible``: así la curva puede pintar
    todo el eje sin agujeros y la leyenda resume solo lo nocturno.

    ``moon_altitudes`` es la altitud de la Luna en cada instante: con ella
    bajo el horizonte la separación no se exige (ver
    :func:`classify_instant`).

    Las cuatro series deben tener la misma longitud.
    """
    if not (
        len(altitudes)
        == len(moon_separations)
        == len(moon_altitudes)
        == len(astro_night_mask)
    ):
        raise ValueError(
            "altitudes, moon_separations, moon_altitudes y astro_night_mask "
            "deben tener la misma longitud"
        )
    windows: list[str] = []
    for alt, sep, moon_alt, is_astro in zip(
        altitudes, moon_separations, moon_altitudes, astro_night_mask, strict=True
    ):
        if not is_astro:
            windows.append(WINDOW_NO_POSSIBLE)
        else:
            windows.append(classify_instant(alt, sep, illumination_pct, moon_alt))
    return windows


def capture_window_summary(
    windows: list[str],
    hours: list[float],
) -> dict[str, dict]:
    """Resumen por ventana: horas totales y rangos horarios continuos.

    ``windows`` son las etiquetas (:data:`WINDOW_*`) y ``hours`` la hora
    decimal de cada instante (0-24, local). Devuelve, por cada ventana
    presente::

        {
            "ideal": {"hours": 3.2, "ranges": [(18.6, 21.8), ...]},
            ...
        }

    Un rango va de la primera muestra de la ventana a la muestra posterior a
    la última (cada instante cubre el intervalo hasta el siguiente), de modo
    que los rangos de la noche casillan la línea del tiempo sin huecos ni
    solapes. Así una ventana de una sola muestra dura un paso de muestreo,
    no cero.

    Las horas se desenvuelven antes de agrupar (ver :func:`unwrap_hours`),
    así que una ventana que cruza la medianoche (21:50 → 05:50) se devuelve
    completa en vez de perderse; los rangos devueltos pueden pasar de 24 y
    ``format_hour_range`` los deja ya en HH:MM.
    """
    hours = unwrap_hours(hours)
    summary: dict[str, dict] = {}
    step = _sample_step(hours)
    current_kind: str | None = None
    range_start = 0.0

    for index, (kind, hour) in enumerate(zip(windows, hours, strict=True)):
        if kind != current_kind:
            # Cerramos el rango anterior si existía y era nocturno
            if current_kind is not None:
                _close_range(summary, current_kind, range_start, hours[index - 1], step)
            current_kind = kind
            range_start = hour

    if current_kind is not None:
        _close_range(summary, current_kind, range_start, hours[-1], step)

    return summary


def unwrap_hours(hours: list[float]) -> list[float]:
    """Horas locales sin salto de medianoche (23.9 → 0.1 se vuelve 24.1).

    La malla nocturna siempre cruza la medianoche; sin desenvolverla, un
    rango que empiece antes de las 00:00 quedaría con ``end < start`` y se
    descartaría (se perdería la ventana Ideal de casi toda la noche).

    Devuelve valores que pueden superar 24; usa ``format_hour_range`` (o
    ``% 24``) para mostrarlos como reloj.
    """
    unwrapped: list[float] = []
    offset = 0.0
    previous: float | None = None
    for hour in hours:
        current = hour + offset
        if previous is not None and current < previous - 12.0:
            offset += 24.0
            current = hour + offset
        unwrapped.append(current)
        previous = current
    return unwrapped


def _sample_step(hours: list[float]) -> float:
    """Paso de muestreo de la malla (menor delta positivo entre horas)."""
    deltas = [b - a for a, b in zip(hours, hours[1:], strict=False) if b > a]
    return min(deltas) if deltas else 0.0


def _close_range(
    summary: dict[str, dict], kind: str, start: float, last: float, step: float
) -> None:
    """Acumula el rango [start, last + step) en la ventana ``kind``."""
    entry = summary.setdefault(kind, {"hours": 0.0, "ranges": []})
    end = last + step
    if end > start:
        entry["ranges"].append((start, end))
        entry["hours"] += end - start


def format_hour_range(start: float, end: float) -> str:
    """Formatea un rango de horas decimales como 'HH:MM–HH:MM'."""
    return f"{_format_hour(start)}–{_format_hour(end)}"


def _format_hour(hour_decimal: float) -> str:
    """18.6 → '18:36'; acepta valores fuera de [0, 24] (módulo 24)."""
    hour_decimal = hour_decimal % 24.0
    hours = int(hour_decimal)
    minutes = int(round((hour_decimal - hours) * 60.0))
    if minutes == 60:  # redondeo al borde del día
        hours = (hours + 1) % 24
        minutes = 0
    return f"{hours:02d}:{minutes:02d}"
