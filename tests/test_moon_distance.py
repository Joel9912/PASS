"""Tests de la función de distancia lunar y las ventanas de captura.

El polinomio de grado 3 está ajustado a datos reales del usuario, así que
se comprueban sus valores de referencia y su comportamiento en los extremos.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planners.moon_distance import (
    WINDOW_IDEAL,
    WINDOW_NO_POSSIBLE,
    WINDOW_POSSIBLE,
    capture_window_summary,
    capture_windows,
    classify_instant,
    format_hour_range,
    min_moon_distance,
    unwrap_hours,
)


# ------------------------------------------------------------------ polinomio
def test_min_moon_distance_reference_values():
    """Valores clave del ajuste: luna nueva ~40°, llena ~120°."""
    assert min_moon_distance(0) == pytest.approx(40.5, abs=0.5)
    assert min_moon_distance(25) == pytest.approx(60.2, abs=1.0)
    assert min_moon_distance(50) == pytest.approx(77.4, abs=1.0)
    assert min_moon_distance(75) == pytest.approx(95.9, abs=1.5)
    assert min_moon_distance(100) == pytest.approx(119.6, abs=1.0)


def test_min_moon_distance_is_monotonic_and_clamped():
    """Más luna → más distancia exigida; fuera de [0,100] se recorta."""
    values = [min_moon_distance(p) for p in range(101)]
    assert all(b > a for a, b in zip(values, values[1:], strict=False))
    assert min_moon_distance(-20) == min_moon_distance(0)
    assert min_moon_distance(150) == min_moon_distance(100)


def test_min_moon_distance_fits_user_data_within_rmse():
    """Los datos originales del usuario se reproducen con RMSE < 1.5°."""
    data = [  # (iluminación %, distancia mínima °)
        (1, 39.8), (2, 41.9), (6, 46.2), (12, 51.6), (21, 57.1),
        (31, 63.8), (42, 71.3), (54, 80.2), (66, 88.8), (82, 102.5),
        (89, 108.8), (95, 114.5), (98, 118.3), (100, 119.8), (97, 114.6),
    ]
    errors = [min_moon_distance(illum) - expected for illum, expected in data]
    rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5
    assert rmse < 1.5


# ------------------------------------------------------------ clasificación
def test_classify_instant_ideal_possible_and_no_possible():
    """Ideal exige alt>45 y sep>umbral; Possible alt>=30 y sep>=umbral-10."""
    # 50 % de luna → umbral ~77°; la luna arriba (30°) exige distancia
    moon_up = 30.0
    assert classify_instant(60.0, 100.0, 50.0, moon_up) == WINDOW_IDEAL
    assert classify_instant(40.0, 75.0, 50.0, moon_up) == WINDOW_POSSIBLE   # 77-10=67
    assert classify_instant(44.0, 120.0, 50.0, moon_up) == WINDOW_POSSIBLE  # alt < 45
    assert classify_instant(35.0, 60.0, 50.0, moon_up) == WINDOW_NO_POSSIBLE  # sep < 67
    assert classify_instant(20.0, 120.0, 50.0, moon_up) == WINDOW_NO_POSSIBLE  # alt < 30


def test_classify_instant_stricter_with_full_moon():
    """Con llena (umbral ~120°) casi nada es Ideal, aunque la luna esté lejos."""
    moon_up = 30.0
    assert classify_instant(70.0, 110.0, 100.0, moon_up) == WINDOW_POSSIBLE
    assert classify_instant(70.0, 125.0, 100.0, moon_up) == WINDOW_IDEAL


def test_classify_instant_moon_below_horizon_skips_separation():
    """Luna bajo el horizonte: no contamina, solo manda la altitud.

    Regresión del caso M31 del 02/10/2026: con la luna hundida la
    separación angular bloqueaba ventanas legítimas (el usuario vio la
    Posible cortada hasta las 22:20 en vez de empezar a las 19:40).
    """
    moon_down = -5.0
    assert classify_instant(60.0, 10.0, 50.0, moon_down) == WINDOW_IDEAL
    assert classify_instant(40.0, 10.0, 50.0, moon_down) == WINDOW_POSSIBLE
    # La altitud sigue mandando con la luna hundida
    assert classify_instant(20.0, 10.0, 50.0, moon_down) == WINDOW_NO_POSSIBLE
    # En el horizonte exacto cuenta como hundida (arriba = > 0°)
    assert classify_instant(60.0, 10.0, 50.0, 0.0) == WINDOW_IDEAL
    # Un pelo sobre el horizonte vuelve a exigir la distancia
    assert classify_instant(60.0, 10.0, 50.0, 1.0) == WINDOW_NO_POSSIBLE


def test_capture_windows_only_classifies_astro_night():
    """Fuera de la noche astronómica todo queda en no_possible."""
    windows = capture_windows(
        altitudes=[60.0, 60.0, 10.0],
        moon_separations=[120.0, 10.0, 120.0],
        moon_altitudes=[30.0, 30.0, -10.0],
        astro_night_mask=[True, True, False],
        illumination_pct=20.0,  # umbral ~54°
    )
    assert windows == [WINDOW_IDEAL, WINDOW_NO_POSSIBLE, WINDOW_NO_POSSIBLE]


def test_capture_windows_ignores_separation_while_moon_is_down():
    """La serie lunar entera manda: hundida ignora sep, arriba la exige."""
    windows = capture_windows(
        altitudes=[60.0, 60.0, 60.0],
        moon_separations=[10.0, 10.0, 10.0],
        moon_altitudes=[-5.0, 5.0, -5.0],
        astro_night_mask=[True, True, True],
        illumination_pct=50.0,  # umbral ~77°
    )
    assert windows == [WINDOW_IDEAL, WINDOW_NO_POSSIBLE, WINDOW_IDEAL]


def test_capture_windows_rejects_mismatched_lengths():
    """Las cuatro series deben tener la misma longitud."""
    with pytest.raises(ValueError):
        capture_windows([1.0], [1.0, 2.0], [1.0], [True], 50.0)


def test_capture_window_summary_groups_ranges_and_hours():
    """Agrupa instantes consecutivos; cada muestra cubre hasta la siguiente.

    Con paso 0.5 h: Ideal en 18.0-18.5 ⇒ [18.0, 19.0); Possible en 19.0 ⇒
    [19.0, 19.5); Ideal de nuevo en 19.5 ⇒ [19.5, 20.0). Los rangos casillan
    la línea del tiempo sin huecos ni solapes.
    """
    summary = capture_window_summary(
        windows=[WINDOW_IDEAL, WINDOW_IDEAL, WINDOW_POSSIBLE, WINDOW_IDEAL],
        hours=[18.0, 18.5, 19.0, 19.5],
    )
    assert summary[WINDOW_IDEAL]["hours"] == pytest.approx(1.5)  # 1.0 + 0.5
    assert summary[WINDOW_POSSIBLE]["hours"] == pytest.approx(0.5)
    assert summary[WINDOW_IDEAL]["ranges"] == [(18.0, 19.0), (19.5, 20.0)]
    assert summary[WINDOW_POSSIBLE]["ranges"] == [(19.0, 19.5)]


def test_capture_window_summary_single_sample_lasts_one_step():
    """Una ventana de una sola muestra dura un paso de muestreo, no cero."""
    summary = capture_window_summary(
        windows=[WINDOW_POSSIBLE],
        hours=[21.0],
    )
    # Sin deltas no hay paso conocido: se queda en 0 (límite del cálculo)
    assert summary[WINDOW_POSSIBLE]["hours"] == 0.0

    summary = capture_window_summary(
        windows=[WINDOW_IDEAL, WINDOW_IDEAL, WINDOW_POSSIBLE],
        hours=[20.0, 20.1667, 20.3333],   # paso de 10 min
    )
    assert summary[WINDOW_POSSIBLE]["hours"] == pytest.approx(0.1667, abs=0.01)


def test_format_hour_range():
    """18.6 → '18:36'; el módulo de 24 rodea el día."""
    assert format_hour_range(18.6, 21.87) == "18:36–21:52"
    assert format_hour_range(23.5, 0.25) == "23:30–00:15"
    # Rango desenvuelto (>24) también sale como reloj
    assert format_hour_range(21.5, 26.5) == "21:30–02:30"


# ------------------------------------------------------------------ medianoche
def test_unwrap_hours_removes_midnight_jump():
    """23.5 → 0.5 se vuelve 24.5; lo que ya va de subida no se toca."""
    assert unwrap_hours([16.0, 20.0, 23.5, 0.5, 4.0]) == [16.0, 20.0, 23.5, 24.5, 28.0]
    assert unwrap_hours([21.0, 22.0, 23.0]) == [21.0, 22.0, 23.0]
    assert unwrap_hours([1.0, 2.0]) == [1.0, 2.0]      # noche que no cruza medianoche
    assert unwrap_hours([]) == []


def test_capture_window_summary_keeps_range_across_midnight():
    """Regresión: la ventana Ideal que cruza las 00:00 no se pierde.

    Antes de desenvolver las horas, ``end < start`` descartaba el rango y la
    noche se resumía como "sin ventana" aunque hubo 5 h de captura ideal.
    """
    hours = [21.5, 22.0, 23.5, 0.5, 1.0, 2.0]
    summary = capture_window_summary(
        windows=[WINDOW_IDEAL] * len(hours),
        hours=hours,
    )
    assert summary[WINDOW_IDEAL]["ranges"] == [(21.5, 26.5)]
    assert summary[WINDOW_IDEAL]["hours"] == pytest.approx(5.0)
    assert format_hour_range(*summary[WINDOW_IDEAL]["ranges"][0]) == "21:30–02:30"


def test_capture_window_summary_wraps_windows_around_midnight():
    """Ideal entre dos tramos de Possible repartidos a ambos lados de 00:00.

    Malla de 30 min en una noche de 21:30 a 01:30: Possible 21:30-22:00,
    Ideal 22:00-01:30 y Possible 01:30-02:00. Los tres rangos son crecientes
    (25.5 > 22.0), no se parten en dos al cruzar la medianoche.
    """
    hours = [21.5, 22.0, 23.5, 0.5, 1.0, 1.5]
    windows = [
        WINDOW_POSSIBLE, WINDOW_IDEAL, WINDOW_IDEAL,
        WINDOW_IDEAL, WINDOW_IDEAL, WINDOW_POSSIBLE,
    ]
    summary = capture_window_summary(windows, hours)
    assert summary[WINDOW_IDEAL]["ranges"] == [(22.0, 25.5)]
    assert summary[WINDOW_IDEAL]["hours"] == pytest.approx(3.5)
    assert summary[WINDOW_POSSIBLE]["ranges"] == [(21.5, 22.0), (25.5, 26.0)]
    assert format_hour_range(22.0, 25.5) == "22:00–01:30"
