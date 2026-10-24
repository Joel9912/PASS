"""Hora civil offline, mallas UTC y cableado de ubicación; nunca usa datos personales ni consulta servicios horarios."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from planners import transit
from planners.analytical_transit import (
    local_utc_offset,
    transit_local_hours,
    transit_utc_hours,
)
from planners.timezones import (
    clock_label,
    local_boundary,
    local_hours,
    local_moment,
    zone,
)


@pytest.mark.parametrize(("moment", "offset"), [("2026-01-15T12:00:00", 1), ("2026-07-15T12:00:00", 2)])
def test_zona_aplica_reglas_segun_instante_sin_cambiar_utc(moment, offset):
    """Madrid necesita desfases distintos según fecha; el instante permanece idéntico al convertirlo."""
    local = local_moment(moment, -3, "Europe/Madrid")
    assert local.hour == 12 + offset
    assert local.astimezone(UTC).replace(tzinfo=None).isoformat() == moment
    assert local_utc_offset(-3, "Europe/Madrid", moment) == offset


@pytest.mark.parametrize("day", ["2026-01-15", "2026-07-15"])
def test_modo_manual_no_cambia_por_verano(day):
    """El modo fijo no hereda reglas de Madrid ni de la máquina."""
    assert local_hours(day + "T12:00:00", -3, 1) == 13


@pytest.mark.parametrize(("key", "hours"), [("Asia/Kathmandu", 5.75), ("America/Costa_Rica", -6)])
def test_zonas_sin_cambio_y_fracciones(key, hours):
    """No presupone cambios de una hora ni husos enteros."""
    assert local_utc_offset(0, key, "2026-07-15T00:00:00") == hours


def test_hora_repetida_se_distingue_y_hora_inexistente_no_se_inventa():
    """Cada UTC tiene una conversión única; entradas civiles ambiguas o inexistentes exigen resolución explícita."""
    assert clock_label("2026-10-25T00:30:00", -3, "Europe/Madrid") == "02:30 UTC+02:00"
    assert clock_label("2026-10-25T01:30:00", -3, "Europe/Madrid") == "02:30 UTC+01:00"
    for value in (datetime.fromisoformat("2026-10-25T02:30:00"), datetime.fromisoformat("2026-03-29T02:30:00")):
        with pytest.raises(ValueError, match="ambiguo o inexistente"):
            local_boundary(value, "Europe/Madrid")


@pytest.mark.parametrize("key", ["../UTC", "/UTC", "Europe/NoExiste", "", "Europe\\Madrid"])
def test_zona_invalida_no_se_convierte_en_huso_del_sistema(key):
    """Un identificador inválido falla explícitamente, sin aproximación ni fallback al desfase fijo."""
    with pytest.raises(ValueError, match="Zona horaria"):
        zone(key)


@pytest.mark.parametrize(("day", "duration"), [("2026-03-28", 15), ("2026-10-24", 17), ("2026-07-15", 16)])
def test_malla_nocturna_usa_limites_civiles_y_duracion_real(day, duration):
    """De 16:00 a 08:00 civiles no siempre hay dieciséis horas transcurridas."""
    times = transit._night_times(day, -3, utc_offset_hours="Europe/Madrid")
    assert len(times) == duration * 60 + 1
    assert local_hours(str(times[0].iso), -3, "Europe/Madrid") == pytest.approx(16)
    assert local_hours(str(times[-1].iso), -3, "Europe/Madrid") == pytest.approx(8)
    assert (times[-1] - times[0]).to_value("hour") == pytest.approx(duration)
    assert np.all(np.diff(times.jd) > 0)


def test_transito_rapido_y_conversion_iso_usan_instante_no_offset_actual():
    """La tabla continúa analítica y la UI convierte el instante, no una fecha de hoy ni el huso Windows."""
    from ui.planner_tab.widgets import iso_to_local_hours

    for day in ("2026-01-15", "2026-07-15"):
        utc = datetime.fromisoformat(day) + timedelta(hours=transit_utc_hours(6, day, -3))
        expected = local_hours(utc, -3, "Europe/Madrid")
        assert transit_local_hours(6, day, -3, "Europe/Madrid") == pytest.approx(expected)
        assert iso_to_local_hours(utc.isoformat(), -3, "Europe/Madrid") == pytest.approx(expected)


def _synthetic_curve(day):
    """Construye una curva ficticia de clasificación constante sin atribuir posiciones reales a un objeto."""
    times = transit._night_times(day, -3, utc_offset_hours="Europe/Madrid")
    n = len(times)
    return transit.NightCurve(
        list(map(str, times.iso)), transit._local_hours(times, -3, "Europe/Madrid"),
        [60.] * n, [-10.] * n, [120.] * n, [True] * n, 0., n // 2,
        clock="Europe/Madrid", longitude=-3,
    )


@pytest.mark.parametrize(("day", "duration"), [("2026-03-28", 15), ("2026-10-24", 17)])
def test_resumen_no_suma_horas_inexistentes_ni_pierde_horas_repetidas(day, duration):
    """Misma categoría sintética en toda la malla: la suma debe ser exactamente su duración UTC."""
    curve = _synthetic_curve(day)
    assert all(b > a for a, b in zip(curve.axis_hours, curve.axis_hours[1:]))
    summary = curve.capture_summary()
    assert sum(entry["hours"] for entry in summary.values()) == pytest.approx(duration)
    assert all("UTC" in text for entry in summary.values() for text in entry["display_ranges"])


def test_curva_ui_usa_eje_continuo_y_rotulos_civiles(qt_app):
    """La curva y las bandas no retroceden cuando se repite una hora; el eje distingue sus desfases."""
    from ui.planner_tab.widgets import TransitCurve

    panel = TransitCurve()
    curve = _synthetic_curve("2026-10-24")
    try:
        panel.show_curve(curve)
        x, _ = panel._altitude_curve.getData()
        assert np.all(np.diff(x) > 0)
        assert panel._tick_strings([26.5, 27.5], 1, 1) == ["02:30 UTC+02:00", "02:30 UTC+01:00"]
    finally:
        panel.close()


@pytest.mark.parametrize("day", ["1950-01-01", "2100-12-31"])
def test_extremos_temporales_con_reglas_distribuidas(day):
    """Admite el rango de planificación; no acredita exactitud histórica ni leyes futuras."""
    assert len(transit._night_times(day, -3, utc_offset_hours="Europe/Madrid")) > 0


def test_persistencia_modos_excluyentes_y_conservacion_de_desfase(memory_db):
    """Guardar zona no borra otras ubicaciones; cambiar a fijo retira la zona y las opciones no se suman."""
    from equipment import localizations
    from equipment.models import DIRECTIONS, Location

    location = Location(name="Lugar sintético", utc_offset_hours=1, bortle=4,
                        obstacles=dict.fromkeys(DIRECTIONS, 0),
                        lp={d: {"fuente": None, "km": 0} for d in DIRECTIONS})
    localizations.create(location)
    assert localizations.list_locations()[0]["utc_offset_hours"] == 1
    location.timezone_id = "Europe/Madrid"
    with pytest.raises(ValueError, match="no ambos"):
        localizations.update(location)
    assert localizations.list_locations()[0]["timezone_id"] is None
    location.utc_offset_hours = None
    localizations.update(location)
    assert localizations.list_locations()[0]["timezone_id"] == "Europe/Madrid"
    location.timezone_id, location.utc_offset_hours = None, 5.75
    localizations.update(location)
    assert localizations.list_locations()[0]["utc_offset_hours"] == 5.75


def test_ui_ubicacion_guarda_zona_y_barra_reemite_la_misma(qt_app, memory_db):
    """Desde Equipo al consumidor de Planificación viaja el identificador, no el desfase de hoy."""
    from equipment import localizations
    from ui.equipment_tab.ubicaciones import UbicacionesTab
    from ui.planner_tab.widgets import LocationBar

    tab = UbicacionesTab()
    try:
        tab._nombre.setText("Ubicación sintética")
        tab._bortle.setCurrentIndex(4)
        tab._clock_mode.setCurrentIndex(tab._clock_mode.findData("zone"))
        tab._timezone.setCurrentIndex(tab._timezone.findData("Europe/Madrid"))
        assert not tab._huso.isEnabled() and tab._timezone.isEnabled()
        tab._guardar()
        row = localizations.list_locations()[0]
        assert row["timezone_id"] == "Europe/Madrid" and row["utc_offset_hours"] is None
        bar = LocationBar()
        calls = []
        bar.location_changed.connect(lambda *args: calls.append(args))
        bar.reemit()
        assert calls[-1][2] == "Europe/Madrid"
        bar.close()
    finally:
        tab.close()


def test_borrador_con_zona_preserva_reglas_y_rechaza_identificador_invalido(qt_app):
    """Recuperar un borrador no transforma su zona en el desfase de la fecha de recuperación."""
    from planners.session_draft import validate
    from ui.planner_tab.planificacion.tab import PlanificacionTab

    tab = PlanificacionTab()
    try:
        data = tab._draft_snapshot()
        data["location"] = [40., -3., "Europe/Madrid"]
        assert validate(data)["location"][2] == "Europe/Madrid"
        tab._restore_draft(data)
        assert tab._utc_offset_hours == "Europe/Madrid"
        data["location"][2] = "Europe/NoExiste"
        with pytest.raises(ValueError, match="Zona horaria"):
            validate(data)
    finally:
        tab.close()


def test_auditoria_actual_convierte_zona_sin_redisenar_descartes():
    """El consumidor de ubicaciones del Apilador conserva orden UTC y muestra la hora civil de cada captura."""
    from stacks.audit_metadata import local_capture_time

    location = dict(name="Sintética", latitude=40., longitude=-3., timezone_id="Europe/Madrid", utc_offset_hours=None)
    moment = datetime.fromisoformat("2026-07-15T12:00:00+00:00")
    local, detail = local_capture_time(moment, (40., -3.), [location], None)
    assert local.hour == 14 and local.astimezone(UTC) == moment
    assert "Europe/Madrid" in detail and "tzdata" in detail
    location["timezone_id"] = "Europe/NoExiste"
    local, detail = local_capture_time(moment, None, [], location)
    assert local == moment and "no se aplica otro desfase" in detail


def test_busqueda_y_ranking_usan_zona_en_sus_fechas_y_no_efemerides_por_fila():
    """La tabla sigue analítica; el ranking y sus ventanas detalladas presentan el mismo modo civil."""
    from planners.capture_plan import best_dates
    from planners.celestial_search import SearchFilters, search

    rows = search(SearchFilters(latitude=40, longitude=-3, date_iso="2026-07-15", utc_offset_hours="Europe/Madrid"))
    assert rows and all("UTC+02:00" in row["transit_local"] for row in rows if row["transit_local"])
    result = best_dates(.7, 41., 40, -3, start_date="2026-10-24", date_range_days=2, top_n=2,
                        utc_offset_hours="Europe/Madrid")
    assert result and all("UTC" in item["transit_local"] for item in result)
    assert all("display_ranges" in entry for item in result for entry in item["windows"].values())


def test_noche_con_segundo_intercalar_conserva_limite_y_no_falla_al_convertir():
    """Astropy mantiene el segundo real; datetime solo aproxima su representación civil al último microsegundo del minuto."""
    times = transit._night_times("2016-12-31", -3, utc_offset_hours="Europe/Madrid")
    assert str(times[-1].iso) == "2017-01-01 07:00:00.000"
    assert (times[-1] - times[0]).to_value("second") == pytest.approx(16 * 3600 + 1)
    assert len(transit._local_hours(times, -3, "Europe/Madrid")) == len(times)
    curve = _synthetic_curve("2016-12-31")
    assert np.all(np.diff(curve.axis_hours) > 0)
    assert sum(entry["hours"] for entry in curve.capture_summary().values()) == pytest.approx(16 + 1 / 3600)


def test_columna_de_zona_se_anade_sin_inferir_ni_borrar_desfase(memory_db):
    """La migración aditiva es idempotente y no transforma el número anterior en una zona supuesta."""
    from db.connection import _migrate_columns

    memory_db.execute("ALTER TABLE locations DROP COLUMN timezone_id")
    memory_db.execute("INSERT INTO locations(name,latitude,longitude,utc_offset_hours) VALUES ('Anterior',40,-3,1)")
    _migrate_columns(memory_db)
    _migrate_columns(memory_db)
    row = memory_db.execute("SELECT name,utc_offset_hours,timezone_id FROM locations").fetchone()
    assert tuple(row) == ("Anterior", 1., None)


def test_interpolacion_incluye_limite_final_y_respeta_paso_parcial(monkeypatch):
    """Las mallas con segundo intercalar o cambio histórico pueden acabar con un intervalo menor al paso normal."""
    from astropy import units as u
    from astropy.time import Time

    times = Time("2026-01-01") + np.array([0, 1, 2, 3, 4, 5, 5.5]) * u.min

    def synthetic(values, _location):
        """Serie lineal artificial, sin posiciones físicas inventadas ni garantías de precisión angular."""
        return np.zeros(len(values)), np.zeros(len(values)), (values - times[0]).to_value(u.min)

    monkeypatch.setattr(transit, "_moon_sun_arrays", synthetic)
    _, _, sun = transit._moon_sun_series(times, None)
    assert np.allclose(sun, (times - times[0]).to_value(u.min), rtol=0, atol=1e-9)


def test_zona_no_disponible_retira_tabla_sin_acusar_fecha_invalida(qt_app, monkeypatch):
    """Una zona guardada que no pueda cargarse no deja horas anteriores ni propaga excepciones desde una señal Qt."""
    from planners.timezones import zone
    from ui.planner_tab.busqueda.tab import BusquedaTab

    tab = BusquedaTab()
    try:
        tab._ephemeris.set_date("2026-10-24")
        tab._rows = [{"object_id": "Anterior"}]
        tab._table.setRowCount(1)
        monkeypatch.setattr(tab, "_run_search", lambda: zone("Europe/NoExiste"))
        tab.refresh()
        assert not tab._rows and tab._table.rowCount() == 0
        assert tab._count.text() == "Cálculo no disponible"
        assert tab.current_date_iso() == "2026-10-24"
        assert "Europe/NoExiste" in tab._ephemeris._date.toolTip()
    finally:
        tab.close()


@pytest.mark.parametrize("clock", ["Europe/Madrid", 1.])
def test_salida_solar_invernal_no_se_pierde_al_terminar_malla_a_las_ocho(clock):
    """Reproduce la captura del usuario: salida posterior a 08:00 no implica ausencia de amanecer."""
    info = transit.night_info(40.020, 1.280, "2026-01-15", utc_offset_hours=clock)
    assert info.sunset is not None and info.sunrise is not None
    assert local_moment(info.sunrise, 1.280, clock).date().isoformat() == "2026-01-16"
    assert local_hours(info.sunrise, 1.280, clock) > 8
    assert info.sunset < info.astronomical_dusk < info.astronomical_dawn < info.sunrise


def test_puesta_solar_anterior_a_las_dieciseis_no_depende_del_inicio_de_malla():
    """Invierno de Berlín: puesta antes de 16:00 y salida después de 08:00 deben tener ambos extremos."""
    info = transit.night_info(52.52, 13.405, "2026-12-15", utc_offset_hours="Europe/Berlin")
    assert info.sunset is not None and info.sunrise is not None
    assert local_hours(info.sunset, 13.405, "Europe/Berlin") < 16
    assert local_hours(info.sunrise, 13.405, "Europe/Berlin") > 8


def test_panel_no_vuelve_al_dia_completo_en_la_captura_reportada(qt_app):
    """La barra debe encuadrar la puesta y salida siguientes, no caer a 00–24 por faltar un extremo."""
    from ui.planner_tab.widgets import EphemerisPanel

    panel = EphemerisPanel()
    try:
        panel.refresh(40.020, 1.280, "2026-01-15", "Europe/Madrid")
        start, end = panel._bar.hour_range()
        assert 16 < start < 18 and 32 < end < 35
        assert panel._bar._kind(26) == "night"
        assert "--:--" not in panel._sunset_label.text()
    finally:
        panel.close()


@pytest.mark.parametrize(("day", "expected"), [("2026-01-15", "UTC+01:00"), ("2026-10-24", "UTC+02:00\n→ UTC+01:00")])
def test_panel_muestra_huso_una_vez_y_no_lo_repite_en_horas(qt_app, day, expected):
    """Zona junto a información lunar; reloj corto en rangos y eje, incluso si la noche cambia de desfase."""
    from PyQt6.QtWidgets import QLabel

    from ui.planner_tab.widgets import EphemerisPanel

    panel = EphemerisPanel()
    try:
        panel.refresh(40.020, 1.280, day, "Europe/Madrid")
        labels = [label.text() for label in panel.findChildren(QLabel) if "UTC" in label.text()]
        assert labels == [expected]
        assert "UTC" not in panel._sunset_label.text() + panel._night_label.text()
        assert all("UTC" not in panel._bar._formatter(tick) for tick in panel._bar.tick_hours(450))
        panel.show_invalid_date("Fecha inválida de prueba")
        assert all("UTC" not in label.text() for label in panel.findChildren(QLabel))
    finally:
        panel.close()


def test_selector_huso_aprovecha_el_ancho_disponible(qt_app):
    """No limita a 170 px nombres IANA largos cuando el panel dispone de espacio."""
    from ui.planner_tab.widgets import LocationBar

    bar = LocationBar()
    try:
        bar.resize(500, 160)
        bar.show()
        qt_app.processEvents()
        assert bar._offset.width() > 300
    finally:
        bar.close()


def test_cruce_solar_interpola_el_intervalo_real_no_el_paso_nominal():
    """Una pareja parcial de dos minutos no se interpola como si durase el paso nominal de cinco."""
    from astropy.time import Time

    times = Time(["2026-01-15 08:00:00", "2026-01-15 08:02:00"])
    result = transit._crossing_iso(times, np.array([1., -1.]), 0., True, 5)
    assert result == "2026-01-15 08:01:00.000"


def test_barra_no_forma_rayas_al_pintar_con_escala_125(qt_app):
    """Tramos de color continuos, sin costuras al rasterizar cada píxel lógico con DPI fraccional."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QColor, QImage, QPainter

    from ui.planner_tab.widgets import DayNightBar

    bar = DayNightBar()
    try:
        bar.resize(420, 44)
        bar.set_marks(18., 19., 29., 30., formatter=lambda hour: str(hour))
        image = QImage(525, 55, QImage.Format.Format_ARGB32)
        image.fill(QColor("black"))
        painter = QPainter(image)
        painter.scale(1.25, 1.25)
        bar.render(painter, QPoint())
        painter.end()
        assert len({image.pixelColor(x, 15).rgba() for x in range(6, 30)}) == 1
    finally:
        bar.close()
