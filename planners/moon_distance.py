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

Ideal no exige separación con la Luna bajo el horizonte. Para Posible,
el usuario admite además una Luna a menos de 5° de altura aunque no
cumpla la distancia mínima menos 10°. A partir de 5° vuelve a exigirse
la distancia. Los cortes de 0° y 5° se interpolan entre muestras.
"""
from __future__ import annotations

import math

from planners.timefmt import format_hhmm

#: Etiquetas de ventana (constantes para que UI y tests no las escriban a mano).
WINDOW_IDEAL = "ideal"
WINDOW_POSSIBLE = "possible"
WINDOW_NO_POSSIBLE = "no_possible"

#: Umbrales de altitud (grados) de las ventanas de captura.
IDEAL_MIN_ALTITUDE = 45.0
POSSIBLE_MIN_ALTITUDE = 30.0

#: Margen de tolerancia (grados) respecto al umbral lunar para "possible".
POSSIBLE_MOON_MARGIN = 10.0

#: Margen lunar aprobado por el usuario, exclusivo de Captura Posible (<5°).
POSSIBLE_LOW_MOON_ALTITUDE = 5.0

#: Margen interno de noche astronómica aprobado por el usuario (horas).
IDEAL_NIGHT_MARGIN_HOURS = 5 / 60

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
    manda la altitud. Al asomar se exige distancia para Ideal, pero Posible
    conserva el margen lunar aprobado hasta menos de 5° de altura.

    Esta función NO mira si es de noche: el filtro de noche astronómica lo
    aplica quien tenga la máscara (ver :func:`capture_windows`).
    """
    min_dist = min_moon_distance(illumination_pct)
    moon_up = moon_altitude_deg > 0.0
    sep_ok_ideal = not moon_up or separation_moon_deg > min_dist
    sep_ok_possible = (
        moon_altitude_deg < POSSIBLE_LOW_MOON_ALTITUDE
        or separation_moon_deg >= min_dist - POSSIBLE_MOON_MARGIN
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


def capture_summary_from_samples(
    altitudes: list[float], moon_separations: list[float], moon_altitudes: list[float],
    astro_night_mask: list[bool], illumination_pct: float, hours: list[float],
    *, sun_altitudes: list[float] | None = None,
) -> dict[str, dict]:
    """Resume intervalos con cruces lunares y solares interpolados.

    Inserta los cruces de 0° y 5° y clasifica cada subintervalo en su punto
    medio. La interpolación lineal aproxima el cruce entre muestras; no es
    una efeméride exacta. Las demás magnitudes conservan la etiqueta temporal
    de la muestra inicial, como el contrato de la malla original. Con alturas
    solares limita Ideal al interior de la noche, con margen de cinco minutos
    en ambos extremos; los márgenes válidos quedan como Posible.
    """
    windows = capture_windows(altitudes, moon_separations, moon_altitudes,
                              astro_night_mask, illumination_pct)
    hours = unwrap_hours(hours)
    capture_window_summary(windows, hours)  # valida la malla antes de interpolar
    if sun_altitudes is not None and (
        len(sun_altitudes) != len(hours) or any(not math.isfinite(a) for a in sun_altitudes)
    ):
        raise ValueError("Las alturas solares deben ser finitas y corresponder a la malla.")
    noches = astronomical_night_spans(hours, astro_night_mask, sun_altitudes)
    refined_hours = []
    refined_windows = []
    for i in range(len(hours) - 1):
        luna, siguiente = moon_altitudes[i:i + 2]
        cortes = [0.0, 1.0]
        if siguiente != luna:
            for limite in (0.0, POSSIBLE_LOW_MOON_ALTITUDE):
                fraccion = (limite - luna) / (siguiente - luna)
                if 0 < fraccion < 1:
                    cortes.append(fraccion)
        for noche_inicio, noche_fin in noches:
            for borde in (noche_inicio, noche_inicio + IDEAL_NIGHT_MARGIN_HOURS,
                          noche_fin - IDEAL_NIGHT_MARGIN_HOURS, noche_fin):
                fraccion = (borde - hours[i]) / (hours[i + 1] - hours[i])
                if 0 < fraccion < 1:
                    cortes.append(fraccion)
        cortes = sorted(set(cortes))
        for inicio, fin in zip(cortes, cortes[1:]):
            refined_hours.append(hours[i] + inicio * (hours[i + 1] - hours[i]))
            lunar_alt = luna + (inicio + fin) / 2 * (siguiente - luna)
            medio = hours[i] + (inicio + fin) / 2 * (hours[i + 1] - hours[i])
            noche = next((tramo for tramo in noches if tramo[0] <= medio < tramo[1]), None)
            kind = classify_instant(altitudes[i], moon_separations[i], illumination_pct,
                                    lunar_alt) if noche else WINDOW_NO_POSSIBLE
            if kind == WINDOW_IDEAL and sun_altitudes is not None and not (
                noche[0] + IDEAL_NIGHT_MARGIN_HOURS <= medio < noche[1] - IDEAL_NIGHT_MARGIN_HOURS
            ):
                kind = WINDOW_POSSIBLE
            refined_windows.append(kind)
    if hours:
        refined_hours.append(hours[-1])
        refined_windows.append(windows[-1])
    return capture_window_summary(refined_windows, refined_hours)


def astronomical_night_spans(
    hours: list[float], mask: list[bool], sun_altitudes: list[float] | None,
) -> list[tuple[float, float]]:
    """Obtiene tramos nocturnos continuos, interpolando el cruce solar de -18°.

    Sin alturas solares mantiene la compatibilidad de las mallas antiguas,
    sin aplicar el margen ideal ni acreditar precisión en los bordes.
    """
    from planners.transit import ASTRO_TWILIGHT_DEG

    hours = unwrap_hours(hours)
    if len(mask) != len(hours) or (sun_altitudes is not None and len(sun_altitudes) != len(hours)):
        raise ValueError("La malla solar y la máscara deben corresponder a las horas.")
    tramos = []
    for i in range(len(hours) - 1):
        inicio, fin = hours[i:i + 2]
        if sun_altitudes is None:
            if not mask[i]:
                continue
        else:
            a, b = sun_altitudes[i:i + 2]
            if a >= ASTRO_TWILIGHT_DEG and b >= ASTRO_TWILIGHT_DEG:
                continue
            if (a < ASTRO_TWILIGHT_DEG) != (b < ASTRO_TWILIGHT_DEG):
                cruce = inicio + (ASTRO_TWILIGHT_DEG - a) / (b - a) * (fin - inicio)
                if a < ASTRO_TWILIGHT_DEG:
                    fin = cruce
                else:
                    inicio = cruce
        if fin <= inicio:
            continue
        if tramos and math.isclose(tramos[-1][1], inicio, rel_tol=0, abs_tol=1e-9):
            tramos[-1] = (tramos[-1][0], fin)
        else:
            tramos.append((inicio, fin))
    return tramos


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

    Cada muestra cubre hasta la siguiente; la última cierra la malla y no
    aporta duración. Ideal cuenta solo bloques completos de cinco minutos
    alineados al reloj. Sus restos pasan a Posible y se unen a sus tramos
    contiguos, con límites exactos, sin rellenar intervalos no capturables.

    Las horas se desenvuelven antes de agrupar (ver :func:`unwrap_hours`),
    así que una ventana que cruza la medianoche (21:50 → 05:50) se devuelve
    completa en vez de perderse; los rangos devueltos pueden pasar de 24 y
    ``format_hour_range`` los deja ya en HH:MM.
    """
    hours = unwrap_hours(hours)
    if len(windows) != len(hours):
        raise ValueError("Las ventanas y las horas deben tener la misma longitud.")
    if any(not math.isfinite(h) for h in hours) or any(b <= a for a, b in zip(hours, hours[1:])):
        raise ValueError("La malla horaria debe ser finita y estrictamente creciente.")
    summary = {kind: {"hours": 0.0, "ranges": []} for kind in windows}
    inicio = 0
    while inicio < len(hours) - 1:
        fin = inicio + 1
        kind = windows[inicio]
        while fin < len(hours) - 1 and windows[fin] == kind:
            fin += 1
        start, end = hours[inicio], hours[fin]
        if kind == WINDOW_IDEAL:
            ideal_start = math.ceil(round(start * 12, 9)) / 12
            ideal_end = math.floor(round(end * 12, 9)) / 12
            if ideal_end > ideal_start:
                _close_range(summary, WINDOW_POSSIBLE, start, ideal_start)
                _close_range(summary, WINDOW_IDEAL, ideal_start, ideal_end)
                _close_range(summary, WINDOW_POSSIBLE, ideal_end, end)
            else:
                _close_range(summary, WINDOW_POSSIBLE, start, end)
        else:
            _close_range(summary, kind, start, end)
        inicio = fin
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


def _close_range(
    summary: dict[str, dict], kind: str, start: float, end: float
) -> None:
    """Acumula un rango exacto, uniendo los contiguos de una misma categoría."""
    if end > start:
        entry = summary.setdefault(kind, {"hours": 0.0, "ranges": []})
        if entry["ranges"] and math.isclose(entry["ranges"][-1][1], start, rel_tol=0, abs_tol=1e-9):
            anterior, _ = entry["ranges"][-1]
            entry["ranges"][-1] = (anterior, end)
        else:
            entry["ranges"].append((start, end))
        entry["hours"] += end - start


def format_hour_range(start: float, end: float) -> str:
    """Formatea un rango de horas decimales como 'HH:MM–HH:MM'."""
    return f"{format_hhmm(start)}–{format_hhmm(end)}"
