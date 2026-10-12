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
    # La excepción hasta menos de 5° solo permite Posible, no Ideal.
    assert classify_instant(60.0, 10.0, 50.0, 1.0) == WINDOW_POSSIBLE


@pytest.mark.parametrize("luna, esperado", [(0.001, WINDOW_POSSIBLE), (4.999, WINDOW_POSSIBLE),
                                            (5.0, WINDOW_NO_POSSIBLE), (5.001, WINDOW_NO_POSSIBLE)])
def test_margen_lunar_bajo_cinco_grados(luna, esperado):
    """El margen bajo de la Luna no convierte una separación insuficiente en Ideal."""
    assert classify_instant(60, 10, 50, luna) == esperado
    assert classify_instant(29, 10, 50, luna) == WINDOW_NO_POSSIBLE


@pytest.mark.parametrize("lunas, esperado", [([4.8, 5.2], (22.0, 22 + 0.5 / 60)),
                                            ([5.2, 4.8], (22 + 0.5 / 60, 22 + 1 / 60))])
def test_corte_lunar_fraccionario_en_cinco_grados(lunas, esperado):
    """Subida y bajada lunar cortan el intervalo, sin adjudicar un minuto entero."""
    from planners.moon_distance import capture_summary_from_samples

    resumen = capture_summary_from_samples([60, 60], [10, 10], lunas, [True, True], 50,
                                          [22.0, 22 + 1 / 60])
    assert resumen[WINDOW_POSSIBLE]["ranges"][0] == pytest.approx(esperado)
    assert resumen[WINDOW_POSSIBLE]["hours"] == pytest.approx(0.5 / 60)


def test_salida_lunar_reparte_ideal_y_posible_sin_exceso():
    """Al salir la Luna, Ideal acaba en su cruce y el resto sigue como Posible."""
    from planners.moon_distance import capture_summary_from_samples

    resumen = capture_summary_from_samples([60, 60], [10, 10], [-1, 1], [True, True], 50,
                                          [22.0, 22 + 11 / 60])
    assert resumen[WINDOW_IDEAL]["hours"] == pytest.approx(5 / 60)
    assert resumen[WINDOW_POSSIBLE]["ranges"] == [(22 + 5 / 60, 22 + 11 / 60)]
    assert sum(s["hours"] for s in resumen.values()) == pytest.approx(11 / 60)


@pytest.mark.parametrize("inicio", [20.0, 23.75])
def test_margen_ideal_interno_y_corte_solar(inicio):
    """Los cinco minutos interiores son Posible, sin contar crepúsculo ni día."""
    from planners.moon_distance import capture_summary_from_samples

    resumen = capture_summary_from_samples(
        [60] * 4, [100] * 4, [-5] * 4, [False, True, True, False], 50,
        [(inicio + m / 60) % 24 for m in (0, 10, 30, 40)],
        sun_altitudes=[-17, -19, -19, -17],
    )
    assert resumen[WINDOW_IDEAL]["ranges"][0] == pytest.approx((inicio + 10 / 60, inicio + 30 / 60))
    assert resumen[WINDOW_POSSIBLE]["ranges"][0] == pytest.approx((inicio + 5 / 60, inicio + 10 / 60))
    assert resumen[WINDOW_POSSIBLE]["ranges"][1] == pytest.approx((inicio + 30 / 60, inicio + 35 / 60))
    assert resumen[WINDOW_IDEAL]["hours"] == pytest.approx(20 / 60)
    assert resumen[WINDOW_POSSIBLE]["hours"] == pytest.approx(10 / 60)


@pytest.mark.parametrize("altitud", [29, 60])
def test_margen_no_inventa_captura_en_noche_corta(altitud):
    """Una noche de diez minutos no tiene Ideal; objeto bajo no tiene Posible."""
    from planners.moon_distance import capture_summary_from_samples

    resumen = capture_summary_from_samples(
        [altitud] * 3, [100] * 3, [-5] * 3, [False, True, False], 50,
        [20, 20 + 10 / 60, 20 + 20 / 60], sun_altitudes=[-17, -19, -17],
    )
    assert resumen.get(WINDOW_IDEAL, {}).get("hours", 0) == 0
    assert resumen.get(WINDOW_POSSIBLE, {}).get("hours", 0) == pytest.approx(10 / 60 if altitud == 60 else 0)


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


def test_ideal_redondeado_cede_restos_a_posible_sin_huecos():
    """Los cortes ideales se ajustan hacia dentro y Posible recoge los restos."""
    summary = capture_window_summary(
        [WINDOW_POSSIBLE, WINDOW_IDEAL, WINDOW_POSSIBLE, WINDOW_NO_POSSIBLE],
        [19 + 5 / 60, 20 + 47 / 60, 21 + 8 / 60, 22.0],
    )
    assert summary[WINDOW_IDEAL]["ranges"] == [(20 + 50 / 60, 21 + 5 / 60)]
    assert summary[WINDOW_IDEAL]["hours"] == pytest.approx(15 / 60)
    assert summary[WINDOW_POSSIBLE]["ranges"] == [
        (19 + 5 / 60, 20 + 50 / 60), (21 + 5 / 60, 22.0),
    ]
    assert sum(v["hours"] for v in summary.values()) == pytest.approx(22 - (19 + 5 / 60))


def test_ideal_menor_de_cinco_minutos_pasa_a_posible():
    """Sin bloques completos ideales el tramo sigue siendo captura posible."""
    summary = capture_window_summary([WINDOW_IDEAL, WINDOW_NO_POSSIBLE], [20.02, 20.06])
    assert summary[WINDOW_IDEAL]["hours"] == 0
    assert summary[WINDOW_POSSIBLE]["ranges"] == [(20.02, 20.06)]


def test_resumen_no_rellena_huecos_reales():
    """La captura imposible no puede desaparecer por el redondeo ideal."""
    summary = capture_window_summary(
        [WINDOW_IDEAL, WINDOW_NO_POSSIBLE, WINDOW_IDEAL, WINDOW_NO_POSSIBLE],
        [20.02, 20.2, 20.3, 20.49],
    )
    assert summary[WINDOW_NO_POSSIBLE]["ranges"] == [(20.2, 20.3)]
    assert all(not (a < 20.3 and b > 20.2) for a, b in summary[WINDOW_POSSIBLE]["ranges"])


def test_capture_window_summary_groups_ranges_and_hours():
    """Agrupa instantes consecutivos; cada muestra cubre hasta la siguiente.

    Con paso 0.5 h: Ideal en 18.0-18.5 ⇒ [18.0, 19.0); Possible en 19.0 ⇒
    [19.0, 19.5); la muestra final de 19.5 solo cierra la malla.
    """
    summary = capture_window_summary(
        windows=[WINDOW_IDEAL, WINDOW_IDEAL, WINDOW_POSSIBLE, WINDOW_IDEAL],
        hours=[18.0, 18.5, 19.0, 19.5],
    )
    assert summary[WINDOW_IDEAL]["hours"] == pytest.approx(1.0)
    assert summary[WINDOW_POSSIBLE]["hours"] == pytest.approx(0.5)
    assert summary[WINDOW_IDEAL]["ranges"] == [(18.0, 19.0)]
    assert summary[WINDOW_POSSIBLE]["ranges"] == [(19.0, 19.5)]


def test_capture_window_summary_ultima_muestra_no_extiende_malla():
    """La muestra final no aporta tiempo fuera de la gráfica."""
    summary = capture_window_summary(
        windows=[WINDOW_POSSIBLE],
        hours=[21.0],
    )
    # Sin deltas no hay paso conocido: se queda en 0 (límite del cálculo)
    assert summary[WINDOW_POSSIBLE]["hours"] == 0.0

    summary = capture_window_summary(
        windows=[WINDOW_IDEAL, WINDOW_IDEAL, WINDOW_POSSIBLE],
        hours=[20.0, 20 + 1 / 6, 20 + 1 / 3],
    )
    assert summary[WINDOW_POSSIBLE]["hours"] == 0.0


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
    noche se resumía como "sin ventana" aunque hubo captura ideal.
    """
    hours = [21.5, 22.0, 23.5, 0.5, 1.0, 2.0]
    summary = capture_window_summary(
        windows=[WINDOW_IDEAL] * len(hours),
        hours=hours,
    )
    assert summary[WINDOW_IDEAL]["ranges"] == [(21.5, 26.0)]
    assert summary[WINDOW_IDEAL]["hours"] == pytest.approx(4.5)
    assert format_hour_range(*summary[WINDOW_IDEAL]["ranges"][0]) == "21:30–02:00"


def test_capture_window_summary_wraps_windows_around_midnight():
    """Ideal entre dos tramos de Possible repartidos a ambos lados de 00:00.

    Malla de 30 min en una noche de 21:30 a 01:30: Possible 21:30-22:00,
    Ideal 22:00-01:30; el punto de 01:30 solo cierra la malla. Los rangos son crecientes
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
    assert summary[WINDOW_POSSIBLE]["ranges"] == [(21.5, 22.0)]
    assert format_hour_range(22.0, 25.5) == "22:00–01:30"


def test_redondeo_ideal_cinco_minutos_cruza_medianoche():
    """Los bloques ideales y sus restos se mantienen unidos tras medianoche."""
    summary = capture_window_summary(
        [WINDOW_IDEAL, WINDOW_POSSIBLE, WINDOW_NO_POSSIBLE],
        [23 + 57 / 60, 13 / 60, 19 / 60],
    )
    assert summary[WINDOW_IDEAL]["ranges"] == [(24.0, 24 + 10 / 60)]
    assert summary[WINDOW_POSSIBLE]["ranges"] == [
        (23 + 57 / 60, 24.0), (24 + 10 / 60, 24 + 19 / 60),
    ]
    assert sum(s["hours"] for s in summary.values()) == pytest.approx(22 / 60)
