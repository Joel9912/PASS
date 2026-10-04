"""Tests del plan de captura (mejores fechas para un target).

Los tests de puntuación son offline; el de ``best_dates`` usa astropy con
pocas noches para mantener el tiempo de ejecución bajo.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planners.capture_plan import (  # noqa: E402
    CaptureWeights,
    best_dates,
    _moon_score,
    _score_date,
)
from planners.moon_distance import min_moon_distance  # noqa: E402

M42_RA, M42_DEC = 5.588139, -5.391111
MADRID_LAT, MADRID_LON = 40.4, -3.7


# ------------------------------------------------------------------ puntuación
def test_moon_score_uses_phase_threshold():
    """1.0 sobre el umbral, 0.5 en el margen de 10°, 0.0 por debajo."""
    threshold = min_moon_distance(50.0)  # ~77°
    assert _moon_score(threshold + 5, threshold) == 1.0
    assert _moon_score(threshold - 5, threshold) == 0.5
    assert _moon_score(threshold - 20, threshold) == 0.0


def test_score_date_ranks_better_conditions_higher():
    """Más altura, más separación lunar y más noche ⇒ puntuación más alta."""
    base = _score_date(40.0, 50.0, 70.0, 6.0, 10.0, CaptureWeights())
    better_alt = _score_date(80.0, 50.0, 70.0, 6.0, 10.0, CaptureWeights())
    better_moon = _score_date(40.0, 90.0, 70.0, 6.0, 10.0, CaptureWeights())
    better_night = _score_date(40.0, 50.0, 70.0, 10.0, 10.0, CaptureWeights())

    assert 0.0 < base < 100.0
    assert better_alt > base
    assert better_moon > base
    assert better_night > base


def test_score_date_weights_are_configurable():
    """Los pesos los pone el usuario: cambiarlos cambia el resultado."""
    alt_heavy = CaptureWeights(altitude=100, moon_separation=0, night=0)
    moon_heavy = CaptureWeights(altitude=0, moon_separation=100, night=0)

    high_alt_low_moon = _score_date(85.0, 10.0, 70.0, 6.0, 10.0, alt_heavy)
    low_alt_high_moon = _score_date(30.0, 100.0, 70.0, 6.0, 10.0, alt_heavy)
    # Con la luna ponderada al máximo, la buena en luna gana
    high_alt_low_moon_m = _score_date(85.0, 10.0, 70.0, 6.0, 10.0, moon_heavy)
    low_alt_high_moon_m = _score_date(30.0, 100.0, 70.0, 6.0, 10.0, moon_heavy)

    assert high_alt_low_moon > low_alt_high_moon
    assert low_alt_high_moon_m > high_alt_low_moon_m


def test_score_date_never_exceeds_100():
    """Con lo mejores condiciones posibles la puntuación no pasa de 100."""
    perfect = _score_date(90.0, 180.0, 40.0, 12.0, 10.0, CaptureWeights())
    assert 0.0 <= perfect <= 100.0


# ----------------------------------------------------------------- best_dates
def test_best_dates_returns_sorted_plan_with_windows():
    """Plan para M42 en Madrid: fechas ordenadas por puntuación y con ventanas."""
    plan = best_dates(
        M42_RA, M42_DEC, MADRID_LAT, MADRID_LON,
        start_date="2026-10-02", date_range_days=6, top_n=3,
    )
    assert 1 <= len(plan) <= 3
    scores = [item["score"] for item in plan]
    assert scores == sorted(scores, reverse=True)

    required = {"date", "transit_local", "max_altitude_deg", "moon_illumination",
                "moon_separation_deg", "min_moon_distance_deg",
                "astronomical_hours", "hours_above_30", "score", "windows"}
    for item in plan:
        assert required <= item.keys()
        assert 0.0 <= item["score"] <= 100.0
        # El umbral debe corresponder a la iluminación de esa noche
        assert item["min_moon_distance_deg"] == pytest.approx(
            min_moon_distance(item["moon_illumination"]), abs=0.1
        )
        # Las ventanas solo se calculan para las mejores fechas
        assert isinstance(item["windows"], dict)


def test_best_dates_empty_without_astronomical_night():
    """En el ártico en verano no hay noche astronómica ⇒ sin candidatas."""
    plan = best_dates(
        5.0, 60.0, 70.0, 25.0,
        start_date="2026-06-15", date_range_days=5, top_n=5,
    )
    assert plan == []


def test_best_dates_empty_when_object_never_rises():
    """Un objeto bajo el horizonte para esa latitud no se puede planificar."""
    plan = best_dates(
        5.0, -85.0, MADRID_LAT, MADRID_LON,
        start_date="2026-10-02", date_range_days=5, top_n=5,
    )
    assert plan == []


def test_best_dates_transit_local_uses_the_saved_offset():
    """La culminación del plan pasa a hora de reloj con ``utc_offset_hours``.

    El desfase no cambia la puntuación ni las fechas (la física es la misma):
    solo cambia cómo se lee la hora. Con +2 guardado, la diferencia frente al
    huso inferido de la longitud es ``2 − round(longitud/15)`` (con el
    redondeo a minutos del texto).
    """
    window = dict(start_date="2026-10-02", date_range_days=4, top_n=2)
    clock = best_dates(
        M42_RA, M42_DEC, MADRID_LAT, MADRID_LON, utc_offset_hours=2.0, **window
    )
    solar = best_dates(M42_RA, M42_DEC, MADRID_LAT, MADRID_LON, **window)

    assert clock and solar
    assert [item["date"] for item in clock] == [item["date"] for item in solar]
    assert [item["score"] for item in clock] == [item["score"] for item in solar]

    expected_delta = (2.0 - round(MADRID_LON / 15.0)) % 24.0
    for clock_item, solar_item in zip(clock, solar, strict=True):
        delta = (_hhmm(clock_item["transit_local"])
                 - _hhmm(solar_item["transit_local"])) % 24.0
        # Cada hora se redondea a minutos: hasta 1 min de tolerancia
        assert delta == pytest.approx(expected_delta, abs=0.02)


def test_best_dates_pasa_el_huso_a_night_info(monkeypatch):
    """M-07: el huso guardado centra la ventana de cada noche del plan.

    Antes ``night_info`` no recibía el huso: la ventana se abría con el
    huso inferido de la longitud y, con >3 h de desfase, el plan salía
    vacío mientras la curva miraba otra noche.
    """
    import planners.capture_plan as capture_plan

    husos: list = []
    original = capture_plan.night_info

    def espia(latitude, longitude, date_iso, **kwargs):
        husos.append(kwargs.get("utc_offset_hours"))
        return original(latitude, longitude, date_iso, **kwargs)

    monkeypatch.setattr(capture_plan, "night_info", espia)
    best_dates(
        M42_RA, M42_DEC, MADRID_LAT, MADRID_LON,
        start_date="2026-10-02", date_range_days=2, top_n=1,
        utc_offset_hours=2.0,
    )

    assert husos == [2.0, 2.0]


def _hhmm(text: str) -> float:
    """'23:45' → 23.75 horas decimales."""
    hours, minutes = text.split(":")
    return int(hours) + int(minutes) / 60.0
