"""Rango de planificación explícito, sin extrapolar ni corregir fechas guardadas del usuario."""

import sqlite3
from datetime import UTC, date, datetime

import pytest

from planners.planning_dates import planning_date, planning_interval


@pytest.mark.parametrize("value", ["1950-01-01", "2100-12-31", "2000-02-29", date(2026, 10, 20)])
def test_fechas_nominales_dentro_del_rango_son_inclusivas(value):
    """Las noches extremas están incluidas; la malla puede cruzar medianoche sin ampliar el rango de selección."""
    result = planning_date(value)
    assert date(1950, 1, 1) <= result <= date(2100, 12, 31)


@pytest.mark.parametrize("value", ["1949-12-31", "2101-01-01", "1800-01-01", "9999-12-31"])
def test_fuera_del_rango_avisa_sin_recortar_fecha(value):
    """No sustituye una fecha no admitida por el extremo más cercano."""
    with pytest.raises(ValueError, match="1950.*2100"):
        planning_date(value)


@pytest.mark.parametrize("value", [None, "", "2026-02-30", "2026-10-20T12:00:00", "20261020",
                                  datetime(2026, 10, 20, 12, tzinfo=UTC), True])
def test_no_trunca_instantes_ni_inventa_fechas(value):
    """Una fecha ilegible no se transforma en hoy ni en medianoche."""
    with pytest.raises(ValueError, match="Fecha"):
        planning_date(value)


def test_intervalo_completo_se_valida_antes_de_calcular(monkeypatch):
    """Ni la ausencia de visibilidad ni una puntuación evitan avisar que el rango solicitado excede 2100."""
    from planners import capture_plan

    calls = []
    monkeypatch.setattr(capture_plan, "max_altitude", lambda *args: calls.append(args))
    with pytest.raises(ValueError, match="1950.*2100"):
        capture_plan.best_dates(1, 20, 40, 0, start_date="2100-12-20", date_range_days=30)
    assert calls == []
    assert planning_interval("2100-12-20", 12) == date(2100, 12, 20)
    assert planning_interval("2100-12-31", 1) == date(2100, 12, 31)


@pytest.mark.parametrize("nights", [0, -1, True, 1.5, 2 ** 80])
def test_intervalo_invalido_o_enorme_no_desborda(nights):
    """Rechazo temprano sin construir mallas de memoria arbitrarias o fechas fuera del rango."""
    with pytest.raises(ValueError):
        planning_interval("2026-10-20", nights)


@pytest.mark.parametrize("operation", ["night_info", "night_curve", "transit_info"])
def test_calculos_publicos_no_llaman_efemerides_fuera_del_rango(monkeypatch, operation):
    """La validación no se limita al selector visual ni puede saltarse llamando el backend directamente."""
    from planners import transit

    def forbidden(*args, **kwargs):
        """Detecta cualquier intento de construir el modelo temporal con fecha no admitida."""
        pytest.fail("No debe construir efemérides fuera del rango")

    monkeypatch.setattr(transit, "Time", forbidden)
    args = (40, 0, "2101-01-01") if operation == "night_info" else (1, 20, 40, 0, "2101-01-01")
    with pytest.raises(ValueError, match="1950.*2100"):
        getattr(transit, operation)(*args)


def test_extremos_solo_validan_malla_no_prometen_precision_uniforme():
    """Aceptación de calendario y disponibilidad/precisión de los modelos son comprobaciones distintas."""
    from erfa import ErfaWarning

    from planners.transit import _night_times

    for day in ("1950-01-01", "2100-12-31"):
        with pytest.warns(ErfaWarning, match="dubious year"):
            instants = _night_times(day, 0, sample_min=60).iso
        assert len(instants) > 1
        assert str(instants[0]).startswith(day)


def test_busqueda_con_calculo_temporal_rechaza_fecha_fuera_de_rango(memory_db):
    """El tránsito de la tabla también respeta el alcance; buscar sin fecha no necesita efemérides."""
    from planners.celestial_search import SearchFilters, search

    with pytest.raises(ValueError, match="1950.*2100"):
        search(SearchFilters(latitude=40, date_iso="2101-01-01"))
    assert search(SearchFilters(date_iso=None)) == []


def test_ui_efemerides_conserva_fecha_y_quita_datos_anteriores(qt_app, memory_db):
    """Una fecha no admitida no deja Sol/Luna anteriores ni se recorta silenciosamente a 2100."""
    from ui.planner_tab.widgets import EphemerisPanel

    panel = EphemerisPanel()
    try:
        panel._phase_label.setText("Resultado anterior")
        panel.refresh(40, 0, "2101-01-01")
        assert panel.current_date_iso() == "2101-01-01"
        assert panel._phase_label.text() == "Fecha no admitida"
        assert panel._moon_icon.isHidden()
        assert "1950" in panel._date.accessibleDescription()
        assert panel._sunset_label.text() == "Puesta de Sol: —"
        panel.refresh(40, 0, "2026-10-20")
        assert not panel._moon_icon.isHidden()
        assert panel._date.accessibleDescription() == ""
        assert panel._phase_label.text() != "Fecha no admitida"
    finally:
        panel.deleteLater()


def test_hoy_tras_fecha_fuera_de_rango_recupera_efemerides_sin_resultados_obsoletos(qt_app, memory_db, monkeypatch):
    """El botón real sale de 2101, recalcula la fecha válida y limpia el aviso sin tocar sesiones personales."""
    from PyQt6.QtCore import QDate
    from PyQt6.QtWidgets import QPushButton

    from ui.planner_tab import widgets

    class FixedDate(QDate):
        """Reloj explícito de prueba para no depender del día de ejecución o de tablas futuras."""

        @staticmethod
        def currentDate():
            """Devuelve la fecha válida acordada para este escenario, no la del equipo del usuario."""
            return QDate(2026, 10, 22)

    monkeypatch.setattr(widgets, "QDate", FixedDate)
    panel = widgets.EphemerisPanel()
    changes = []
    panel.date_changed.connect(changes.append)
    panel.date_changed.connect(lambda day: panel.refresh(40, -3, day))
    try:
        panel.refresh(40, -3, "2101-01-01")
        assert panel.current_date_iso() == "2101-01-01"
        assert panel._phase_label.text() == "Fecha no admitida" and panel._moon_icon.isHidden()
        today = next(button for button in panel.findChildren(QPushButton) if button.text() == "Hoy")
        today.click()
        assert changes == ["2026-10-22"]
        assert panel.current_date_iso() == "2026-10-22"
        assert panel._phase_label.text() != "Fecha no admitida"
        assert not panel._moon_icon.isHidden() and panel._date.accessibleDescription() == ""
        assert panel._sunset_label.text() != "Puesta de Sol: —"
    finally:
        panel.deleteLater()


@pytest.mark.parametrize("error_type", [ValueError, OSError, sqlite3.Error])
def test_ui_recurso_astronomico_roto_no_se_atribuye_a_fecha_invalida(qt_app, memory_db, monkeypatch, error_type):
    """Una fecha válida no pasa a estar fuera de rango por perder un kernel; tampoco conserva efemérides antiguas."""
    from ui.planner_tab import widgets

    original = widgets.night_info

    def unavailable(*args, **kwargs):
        """Simula un recurso/modelo ilegible, no una fecha prohibida."""
        raise error_type("Kernel de prueba no disponible")

    panel = widgets.EphemerisPanel()
    try:
        panel._phase_label.setText("Resultado anterior")
        monkeypatch.setattr(widgets, "night_info", unavailable)
        panel.refresh(40, -3, "2026-10-22")
        assert panel.current_date_iso() == "2026-10-22"
        assert panel._phase_label.text() == "Efemérides no disponibles"
        assert panel._moon_icon.isHidden() and panel._sunset_label.text() == "Puesta de Sol: —"
        assert "Kernel de prueba" in panel._date.accessibleDescription()
        monkeypatch.setattr(widgets, "night_info", original)
        panel.refresh(40, -3, "2026-10-22")
        assert panel._phase_label.text() != "Efemérides no disponibles"
        assert not panel._moon_icon.isHidden() and panel._date.accessibleDescription() == ""
    finally:
        panel.deleteLater()


@pytest.mark.parametrize("operation", ["curve", "plan"])
@pytest.mark.parametrize("error_type", [ValueError, OSError, sqlite3.Error])
def test_planificador_error_de_recurso_retira_calculos_y_restaura_controles(qt_app, memory_db, monkeypatch, operation, error_type):
    """Curva y plan presentan el motivo sin conservar resultados previos ni dejar cursor/botón bloqueados."""
    from PyQt6.QtWidgets import QApplication

    from ui.planner_tab.planificacion import tab as module

    def unavailable(*args, **kwargs):
        """Simula el fallo de archivo/registro esperado en la frontera de un cálculo astronómico."""
        raise error_type("Recurso científico de prueba no disponible")

    tab = module.PlanificacionTab()
    try:
        monkeypatch.setattr(tab, "_current_target", lambda: {"object_id": "M31", "ra_hours": 1, "dec_deg": 20})
        monkeypatch.setattr(tab, "_has_location", lambda: True)
        tab._latitude, tab._longitude = 40, -3
        if operation == "curve":
            reasons = []
            monkeypatch.setattr(module, "night_curve", unavailable)
            monkeypatch.setattr(tab._curve, "clear", reasons.append)
            tab._refresh_curve()
            assert reasons == ["Recurso científico de prueba no disponible"]
        else:
            monkeypatch.setattr(module, "best_dates", unavailable)
            tab._plan = [{"date": "2026-10-21"}]
            tab._plan_table.setRowCount(1)
            tab._calculate_plan()
            assert tab._plan == [] and tab._plan_table.rowCount() == 0
            assert "Recurso científico" in tab._window_label.text()
            assert tab._plan_button.isEnabled() and QApplication.overrideCursor() is None
    finally:
        tab.deleteLater()


def test_ui_busqueda_no_muestra_transitos_obsoletos_con_fecha_invalida(qt_app, memory_db):
    """Cambiar a una fecha fuera de alcance limpia resultados, pero conserva el valor para corregirlo."""
    from ui.planner_tab.busqueda.tab import BusquedaTab

    tab = BusquedaTab()
    try:
        tab._rows = [{"object_id": "resultado anterior"}]
        tab._table.setRowCount(1)
        tab._ephemeris.set_date("2101-01-01")
        tab.refresh()
        assert tab.current_date_iso() == "2101-01-01"
        assert tab._rows == [] and tab._table.rowCount() == 0
        assert "1950" in tab._count.text() and "2100" in tab._count.text()
        assert not tab._add_button.isEnabled()
    finally:
        tab.deleteLater()


def test_ui_plan_avisa_del_intervalo_sin_dejar_plan_anterior(qt_app, memory_db, monkeypatch):
    """Un mes que excede 2100 no se recorta ni conserva resultados de otra petición; restaura cursor/botón."""
    from PyQt6.QtCore import QDate
    from PyQt6.QtWidgets import QApplication

    from ui.planner_tab.planificacion.tab import PlanificacionTab

    tab = PlanificacionTab()
    try:
        tab._date.setDate(QDate(2100, 12, 20))
        tab._latitude, tab._longitude = 40, 0
        monkeypatch.setattr(tab, "_current_target", lambda: {"object_id": "M31", "ra_hours": 1, "dec_deg": 20})
        tab._plan = [{"date": "2026-10-20"}]
        tab._plan_table.setRowCount(1)
        tab._calculate_plan()
        assert tab._date_iso() == "2100-12-20"
        assert tab._plan == [] and tab._plan_table.rowCount() == 0
        assert "1950" in tab._window_label.text() and "2100" in tab._window_label.text()
        assert QApplication.overrideCursor() is None and tab._plan_button.isEnabled()
    finally:
        tab.deleteLater()
