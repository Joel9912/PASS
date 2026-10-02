"""Tests del tránsito analítico rápido (sin astropy) de la tabla de Búsqueda.

Incluye una comprobación de consistencia contra el cálculo exacto con
astropy: la aproximación debe quedar a menos de 10 minutos.
"""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planners.analytical_transit import (  # noqa: E402
    format_transit_hours,
    hours_above_altitude,
    is_circumpolar,
    local_utc_offset,
    max_altitude,
    never_rises,
    transit_local_hours,
    transit_utc_hours,
)

MADRID_LAT, MADRID_LON = 40.4, -3.7
M42_RA, M42_DEC = 5.588139, -5.391111


def test_max_altitude_is_ninety_minus_latitude_offset():
    """Culminación: 90 − |lat − dec|; un objeto en el cenit da 90°."""
    assert max_altitude(40.4, 40.4) == pytest.approx(90.0)
    assert max_altitude(MADRID_LAT, M42_DEC) == pytest.approx(44.2, abs=0.1)
    assert max_altitude(0.0, 0.0) == pytest.approx(90.0)
    assert max_altitude(40.0, -50.0) == pytest.approx(0.0)          # justo sale
    assert max_altitude(40.0, -80.0) == pytest.approx(-30.0)        # nunca sale


def test_circumpolar_and_never_rises():
    """Polaris circumpolar en Madrid; un objeto en el polo sur, invisible."""
    assert is_circumpolar(MADRID_LAT, 89.0) is True
    assert is_circumpolar(MADRID_LAT, M42_DEC) is False
    assert never_rises(MADRID_LAT, -89.0) is True
    assert never_rises(MADRID_LAT, M42_DEC) is False
    # Hemisferio sur: en 40°S, dec −89° es circumpolar y +89° nunca sale
    assert is_circumpolar(-40.0, -89.0) is True
    assert never_rises(-40.0, 89.0) is True


def test_hours_above_altitude_known_cases():
    """Circumpolar sobre 30° → 24 h; objeto bajo el horizonte → 0 h."""
    # En 70°N, dec 70° nunca baja de 30° sobre el horizonte
    assert hours_above_altitude(70.0, 70.0, 30.0) == 24.0
    assert hours_above_altitude(40.4, -89.0, 30.0) == 0.0
    # M42 en Madrid sobre 30°: coherente con la fórmula del arco horario
    hours = hours_above_altitude(MADRID_LAT, M42_DEC, 30.0)
    cos_h = ((math.sin(math.radians(30)) - math.sin(math.radians(MADRID_LAT))
              * math.sin(math.radians(M42_DEC)))
             / (math.cos(math.radians(MADRID_LAT)) * math.cos(math.radians(M42_DEC))))
    expected = 2.0 * math.degrees(math.acos(cos_h)) / 15.0
    assert hours == pytest.approx(expected, abs=0.01)
    assert 4.0 < hours < 8.0


def test_hours_above_altitude_decreases_with_stricter_threshold():
    """Subir el umbral nunca aumenta las horas sobre él."""
    low = hours_above_altitude(MADRID_LAT, M42_DEC, 20.0)
    high = hours_above_altitude(MADRID_LAT, M42_DEC, 60.0)
    assert low > high


def test_transit_time_is_a_valid_hour():
    """La hora de tránsito cae en [0, 24) y cambia poco de un día a otro."""
    first = transit_local_hours(M42_RA, "2026-10-01", MADRID_LON)
    second = transit_local_hours(M42_RA, "2026-10-02", MADRID_LON)
    assert 0.0 <= first < 24.0
    # El tránsito adelanta ~4 min al día; envuelto en el módulo 24
    delta = (second - first) % 24.0
    assert delta < 0.2 or delta > 23.8


def test_transit_time_matches_astropy_within_ten_minutes():
    """La aproximación analítica coincide con astropy a <10 min (M42, Madrid).

    ``transit_info`` devuelve el pico de una malla de 10 min, así que el
    propio valor exacto tiene hasta ±5 min de cuantización.
    """
    astropy = pytest.importorskip("planners.transit")
    info = astropy.transit_info(M42_RA, M42_DEC, MADRID_LAT, MADRID_LON, "2026-01-01")
    assert info.transit_time is not None

    exact_hours = _iso_to_utc_hours(info.transit_time)
    approx_hours = transit_utc_hours(M42_RA, "2026-01-01", MADRID_LON)
    diff = min(abs(exact_hours - approx_hours), 24.0 - abs(exact_hours - approx_hours))
    assert diff * 60.0 < 10.0, f"Diferencia de {diff * 60:.1f} min"


def _iso_to_utc_hours(iso: str) -> float:
    """'2026-01-01 22:15:30.000' → 22.255 horas UTC."""
    time_part = iso.split(" ")[1]
    hh, mm, ss = (float(part) for part in time_part.split(":"))
    return hh + mm / 60.0 + ss / 3600.0


def test_format_transit_hours():
    assert format_transit_hours(23.999) == "00:00"
    assert format_transit_hours(4.5) == "04:30"
    assert format_transit_hours(28.25) == "04:15"   # módulo 24


# -------------------------------------------------------- hora local (offset)
def test_local_utc_offset_prefers_the_saved_offset():
    """Con desfase guardado (hora de reloj) manda él, no la longitud.

    Es la única fuente de verdad para pasar de UTC a hora local: España en
    verano es +2 aunque la longitud de Madrid dé ~-0.25 (hora solar).
    """
    assert local_utc_offset(MADRID_LON, 2.0) == pytest.approx(2.0)
    assert local_utc_offset(MADRID_LON, -6.0) == pytest.approx(-6.0)
    assert local_utc_offset(0.0, 5.5) == pytest.approx(5.5)


def test_local_utc_offset_falls_back_to_longitude():
    """Sin desfase guardado se usa la longitud (hora solar, aproximación)."""
    assert local_utc_offset(MADRID_LON) == pytest.approx(MADRID_LON / 15.0)
    assert local_utc_offset(-15.0, None) == pytest.approx(-1.0)
    assert local_utc_offset(75.0, None) == pytest.approx(5.0)
    # 0 guardado SÍ es un valor (UTC+0, p. ej. Greenwich en invierno),
    # no se confunde con "sin guardar": solo None cae a la longitud.
    assert local_utc_offset(MADRID_LON, 0) == 0.0
    assert local_utc_offset(0.0, None) == 0.0


def test_transit_local_hours_accepts_an_explicit_offset():
    """Con offset +2 la culminación local es 2 h más que con hora solar."""
    solar = transit_local_hours(M42_RA, "2026-01-01", MADRID_LON)
    clock = transit_local_hours(M42_RA, "2026-01-01", MADRID_LON, utc_offset_hours=2.0)
    assert 0.0 <= clock < 24.0
    assert (clock - solar) % 24.0 == pytest.approx(2.0 - MADRID_LON / 15.0, abs=1e-6)
