"""Estado de precisión informativo: procedencia IERS real, offline y sin promesas de precisión uniforme."""

import warnings

import numpy as np
import pytest
from astropy import units as u
from astropy.time import Time
from astropy.utils import iers

from planners import transit
from planners.astronomy_status import AstronomyStatus, astronomy_status


class LocalTable:
    """Tabla controlada para separar códigos de procedencia y valores, sin descargar recursos astronómicos."""

    def __init__(self, ut1_codes, pole_codes, *, finite=True):
        """Guarda códigos explícitos y permite simular un valor inválido dentro de una tabla aparentemente cubierta."""
        self.ut1_codes = np.asarray(ut1_codes)
        self.pole_codes = np.asarray(pole_codes)
        self.finite = finite

    def ut1_utc(self, times, *, return_status):
        """Devuelve cantidades de tiempo y sus códigos como lo hace la interfaz IERS."""
        return np.full(len(self.ut1_codes), 0.1 if self.finite else np.nan) * u.s, self.ut1_codes

    def pm_xy(self, times, *, return_status):
        """Movimiento polar independiente: un UT1 cubierto no acredita por sí solo sus dos ejes."""
        return np.zeros(len(self.pole_codes)) * u.arcsec, np.zeros(len(self.pole_codes)) * u.arcsec, self.pole_codes


@pytest.mark.parametrize("expected,ut1,pole", [
    ("local", [0, 1], [1, 0]), ("prediction", [0, 2], [0, 0]),
    ("outside", [0, -1], [0, 0]), ("outside", [0, 0], [0, -2]),
    ("unknown", [0, 97], [0, 0]), ("unknown", [], []),
])
def test_estado_respeta_procedencia_de_toda_la_malla(expected, ut1, pole):
    """Se conserva el estado menos verificable presente, sin contar una predicción o extrapolación como dato observado."""
    result = astronomy_status(Time("2020-01-01"), table=LocalTable(ut1, pole))
    assert result.orientation == expected
    assert "≈" in result.summary
    assert "No se ha certificado precisión uniforme" in result.details


def test_valor_no_finito_no_se_declara_cubierto():
    """Un código local no transforma un dato inválido en precisión conocida."""
    result = astronomy_status(Time("2020-01-01"), table=LocalTable([0], [0], finite=False))
    assert result.orientation == "unknown"


def test_consulta_ires_fuerza_offline_y_restaura_configuracion(monkeypatch):
    """Incluso llamada fuera de transit, la consulta de estado no activa descargas ni deja cambios globales."""
    seen = []

    def local_only():
        """Comprueba la configuración en el punto donde Astropy abriría sus datos locales."""
        seen.append(iers.conf.auto_download)
        return LocalTable([0], [0])

    monkeypatch.setattr(iers.earth_orientation_table, "get", local_only)
    with iers.conf.set_temp("auto_download", True):
        assert astronomy_status(Time("2020-01-01")).orientation == "local"
        assert iers.conf.auto_download
    assert seen == [False]


@pytest.mark.parametrize("date,expected", [("2020-01-01", "local"), ("1950-01-01", "outside"), ("2100-01-01", "outside")])
def test_tabla_real_local_sin_certificar_extremos(date, expected):
    """La tabla instalada acredita cobertura solo donde la tiene, no por admitir el calendario completo."""
    with warnings.catch_warnings(record=True):
        result = astronomy_status(Time(date))
    assert result.orientation == expected


def test_error_de_lectura_de_estado_es_desconocido_no_precision_fingida(monkeypatch):
    """El diagnóstico no cambia el cálculo ni inventa precisión si no logra leer sus datos auxiliares."""
    def unavailable():
        """Simula un recurso local de diagnóstico no disponible."""
        raise OSError("No disponible")

    monkeypatch.setattr(iers.earth_orientation_table, "get", unavailable)
    assert astronomy_status(Time("2020-01-01")).orientation == "unknown"


def test_curva_y_efemerides_transportan_el_estado_sin_cambiar_resultados(monkeypatch):
    """El aviso se adjunta a ambas APIs, no se deduce después de la fecha desde la interfaz."""
    status = AstronomyStatus("outside", "builtin", "Tabla de prueba")
    monkeypatch.setattr(transit, "astronomy_status", lambda times: status)
    curve = transit.night_curve(4, 40, 40, -3, "2020-01-01")
    info = transit.night_info(40, -3, "2020-01-01")
    assert curve.accuracy is status and info.accuracy is status
    assert len(curve.altitudes) == len(curve.hours_local)
    assert np.all(np.isfinite(curve.altitudes))


def test_curva_muestra_aviso_accesible_y_limpia_estado_anterior(qt_app):
    """Fuera de tabla es visible y legible por teclado/ayuda; limpiar no conserva avisos de otra fecha."""
    from PyQt6.QtCore import Qt

    from ui.planner_tab.widgets import TransitCurve

    status = AstronomyStatus("outside", "builtin", "Tabla sintética")
    curve = transit.NightCurve(["2020-01-01"] * 3, [18, 19, 20], [30, 40, 30], [-10, -10, -10],
                               [90, 90, 90], [True, True, True], .1, 1, accuracy=status)
    widget = TransitCurve()
    try:
        widget.show_curve(curve)
        assert "IERS fuera de tabla" in widget._accuracy_label.text()
        assert "No se ha certificado" in widget._accuracy_label.whatsThis()
        assert widget._accuracy_label.accessibleDescription() == status.details
        assert widget._accuracy_label.focusPolicy() == Qt.FocusPolicy.StrongFocus
        curve.accuracy = AstronomyStatus("local", "builtin", "Tabla sintética")
        widget.show_curve(curve)
        assert "fuera de tabla" not in widget._accuracy_label.text()
        widget.clear("Fecha no válida")
        assert widget._accuracy_label.text().strip() == ""
        assert not widget._accuracy_label.toolTip()
        assert not widget._accuracy_label.accessibleDescription()
    finally:
        widget.deleteLater()
