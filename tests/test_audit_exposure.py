"""Fondos comparables, datos ausentes y revisión conservadora sin inventar exposición."""

import pytest

from stacks.frame_metrics import Pesos, evaluar, extract_metrics
from stacks.global_pool import LightRef
from stacks.registration import Registro


def _registry(tmp_path, exposures):
    """Secuencia sintética completa, sin imágenes originales ni SirIL."""
    count = len(exposures)
    registry = Registro(tmp_path, "probe_", [
        LightRef(tmp_path/f"frame{i}.fit", "noche", None, exposure)
        for i, exposure in enumerate(exposures)
    ], False)
    text = f"S 'probe_' 1 {count} {count} 5 0 6 0 0 0\nL 1\n"
    text += "".join(f"I {i} 1\n" for i in range(1,count+1))
    text += "".join(f"R0 {4+i/10} {5+i/10} 0.9 0 {0.001*(i+1)} 100 H 1 0 0 0 1 0 0 0 1\n"
                    for i in range(count))
    registry.ruta_seq.write_text(text, encoding="utf-8")
    return registry


@pytest.mark.parametrize("unknown", [None, 0.0])
def test_exposicion_ausente_no_se_mezcla_con_fondo_por_segundo(tmp_path, unknown):
    """S-0027: el fondo sin tasa queda desconocido, no bruto ni cero."""
    registry = _registry(tmp_path, [60,unknown,60])
    metrics = extract_metrics(registry)
    assert metrics[0].background == pytest.approx(0.001*65535/60)
    assert metrics[1].background is None
    assert metrics[1].transparency is None
    assert metrics[1].weighted is None
    assert metrics[1].background_normalized == pytest.approx(0.002)
    assert metrics[1].fwhm == 4.1 and metrics[1].stars == 100


def test_desconocido_no_altera_el_proxy_de_fondos_conocidos(tmp_path):
    """La normalización del fondo solo usa tasas disponibles; no crea una falsa escala."""
    metrics = extract_metrics(_registry(tmp_path, [60,None,60]), Pesos(0,0,0,100))
    assert metrics[0].transparency == 1
    assert metrics[2].transparency == pytest.approx(1/3)
    assert [m.weighted for m in metrics] == [100,None,0]


def test_todas_sin_exposicion_conservan_estrellas_y_se_revisan(tmp_path):
    """Un grupo incompleto no se convierte en un grupo perfecto ni pierde sus métricas estelares."""
    metrics = extract_metrics(_registry(tmp_path, [None,None,None]))
    assert len(metrics) == 3
    results = evaluar(metrics)
    assert all(m.weighted is None and m.fwhm > 0 for m in metrics)
    assert all(e.revisar and e.descartada and "Datos insuficientes" in e.motivo for e in results)


def test_ranking_sin_corte_no_exige_proxy_inactivo(tmp_path):
    """Sin mínimo ni corte de fondo, la falta del proxy no veta los cortes estelares disponibles."""
    metrics = extract_metrics(_registry(tmp_path, [None,None,None]))
    results = evaluar(metrics, Pesos(100,0,20,0), umbral=0)
    assert all(not e.revisar and not e.descartada for e in results)
    assert all(m.weighted is None for m in metrics)


def test_minimo_cero_aun_revisa_fondo_activo(tmp_path):
    """Quitar el mínimo no inventa los datos que necesita el corte por fondo."""
    metrics = extract_metrics(_registry(tmp_path, [None,None,None]))
    results = evaluar(metrics, Pesos(0,0,0,100), umbral=0)
    assert all(e.revisar and e.descartada for e in results)


def test_ui_datos_ausentes_sin_ceros_ni_falso_rechazo_siril(qt_app, tmp_path):
    """La toma incompleta es revisable; gráficas y repuntuación no inventan una tasa."""
    import numpy as np
    from PyQt6.QtCore import Qt

    from ui.stacker_tab.paneles.auditar import PanelAuditar

    registry = _registry(tmp_path, [60,None,60])
    panel = PanelAuditar()
    try:
        panel.mostrar(registry, extract_metrics(registry))
        row = next(i for i in range(panel._tabla.rowCount())
                   if panel._tabla.item(i,1).data(Qt.ItemDataRole.UserRole) == str(registry.frames[1].ruta))
        assert [panel._tabla.item(row,c).text() for c in (5,6,7)] == ["—"]*3
        assert panel._tabla.item(row,8).text() == "Revisar"
        assert panel._tabla.item(row,0).flags() & Qt.ItemFlag.ItemIsUserCheckable
        panel._tabla.setCurrentCell(row,1)
        assert "sin puntuación" in panel._preview_pie.toolTip().lower()
        panel._metrica.setCurrentIndex(panel._metrica.findData("background"))
        assert np.isfinite(panel._curva.getData()[1]).all()
        panel._usar_puntuacion.setChecked(False)
        for name,control in panel._pesos.items():
            control.setValue(100 if name == "fwhm" else 0)
        panel._boton_actualizar.click()
        assert all(e.metricas.weighted is not None and not e.revisar for e in panel._evaluaciones.values())
    finally:
        panel.deleteLater()
