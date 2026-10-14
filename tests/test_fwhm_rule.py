"""Corte FWHM del usuario, separado del ranking y sin mezclar sesiones o filtros."""

import pytest

from stacks.frame_metrics import FrameMetrics, Pesos, evaluar


def _frames(values, session="noche", filtro=None):
    """Fabrica mediciones estelares comparables sin archivos ni SirIL."""
    return [FrameMetrics(f"{session}-{filtro}-{i}", session, value, 0.95, 1, 1, 0, filtro=filtro)
            for i, value in enumerate(values)]


def _evaluate(frames):
    """Aísla el corte FWHM de puntuación y otras métricas."""
    return evaluar(frames, Pesos(100, 0, 0, 0), umbral=0, criterio_fwhm="media_minimo")


def test_formula_exacta_y_igualdad_permitida():
    """El corte es media+(media−mínimo)/6; la igualdad no recomienda descartar."""
    results = _evaluate(_frames([3, 4.4, 5.2]))
    assert [r.corte_fwhm for r in results] == pytest.approx([4.4]*3)
    assert [r.descartada for r in results] == [False, False, True]
    assert results[2].motivo == "FWHM"


@pytest.mark.parametrize("other_session,other_filter", [("D:/B/noche", None), ("D:/A/noche", "Ha")])
def test_otro_grupo_no_mueve_el_corte(other_session, other_filter):
    """Una sesión homónima por ruta o un filtro distinto no contamina el límite del grupo."""
    first = _frames([3, 4.4, 5.2], "D:/A/noche")
    other = _frames([9, 9.5, 10], other_session, other_filter)
    alone = _evaluate(first)
    together = _evaluate(first+other)
    assert [r.corte_fwhm for r in together[:3]] == [r.corte_fwhm for r in alone]
    assert [r.descartada for r in together] == [False, False, True, False, False, True]


@pytest.mark.parametrize("values", [[4], [4, 4, 4]])
def test_igualdad_o_grupo_unico_no_fabrica_extremos(values):
    """Un límite relativo sin dispersión no acredita calidad ni inventa descartes."""
    results = _evaluate(_frames(values))
    assert all(r.corte_fwhm == 4 and not r.descartada for r in results)


def test_peso_fwhm_cero_desactiva_tambien_la_formula():
    """Peso cero mantiene el contrato existente de no puntuar ni cortar esa métrica."""
    results = evaluar(_frames([3, 4.4, 5.2]), Pesos(0, 100, 0, 0),
                       umbral=0, criterio_fwhm="media_minimo")
    assert all(not r.descartada and r.corte_fwhm is None for r in results)


def test_criterio_desconocido_falla_sin_asumir_otro():
    """Un perfil inválido nunca cae silenciosamente a un corte distinto."""
    with pytest.raises(ValueError, match="criterio"):
        evaluar(_frames([3, 4, 5]), criterio_fwhm="desconocido")


def test_ui_formula_sin_puntuacion_conserva_casillas(qt_app, tmp_path):
    """Configura la regla y desactiva el mínimo sin registrar ni tocar elecciones manuales."""
    from pathlib import Path

    from stacks.global_pool import LightRef
    from stacks.registration import Registro
    from ui.stacker_tab.paneles.auditar import PanelAuditar

    frames = _frames([3, 4.4, 5.2])
    registry = Registro(tmp_path, "probe_", [LightRef(Path(f.path), f.session, None, 60) for f in frames])
    panel = PanelAuditar()
    try:
        panel._criterio_fwhm.setCurrentIndex(panel._criterio_fwhm.findData("media_minimo"))
        panel._usar_puntuacion.setChecked(False)
        for name, control in panel._pesos.items():
            control.setValue(100 if name == "fwhm" else 0)
        panel.mostrar(registry, frames)
        assert panel.umbral() == 0 and not panel._umbral.isEnabled()
        assert sum(e.descartada for e in panel._evaluaciones.values()) == 1
        known = {str(Path(frames[0].path).absolute())}
        panel.restaurar_aceptados(known)
        before = panel.aceptados()
        panel._boton_actualizar.click()
        assert panel.aceptados() == before
        assert "sesión y filtro" in panel._resumen.text()
        assert "4.4" in panel._tabla.item(0, 3).toolTip()
    finally:
        panel.deleteLater()


def test_seleccionar_todo_respeta_siril_y_no_cambia_criterios(qt_app, tmp_path):
    """Marca utilizables en lote, incluso sugeridas, sin habilitar frames sin métricas."""
    from pathlib import Path

    from stacks.global_pool import LightRef
    from stacks.registration import Registro
    from ui.stacker_tab.paneles.auditar import PanelAuditar

    frames = _frames([3, 4.4, 5.2])
    refs = [LightRef(Path(f.path), f.session, None, 60) for f in frames]
    refs.append(LightRef(Path("rechazada.fit"), "noche", None, 60))
    panel = PanelAuditar()
    events = []
    try:
        assert not panel._boton_seleccionar_todo.isEnabled()
        panel.mostrar(Registro(tmp_path, "probe_", refs), frames)
        panel.resize(1309, 735)
        panel.show()
        qt_app.processEvents()
        assert panel._boton_seleccionar_todo.isVisible()
        assert panel._boton_seleccionar_todo.geometry().right() <= panel.width()
        assert not panel._boton_seleccionar_todo.geometry().intersects(panel._usar_puntuacion.geometry())
        panel.restaurar_aceptados(set())
        before = [(e.motivo, e.metricas.weighted) for e in panel._evaluaciones.values()]
        panel.seleccion_cambiada.connect(lambda: events.append(True))
        panel._boton_seleccionar_todo.click()
        assert sorted(panel.aceptados()) == [1, 2, 3]
        assert events == [True]
        assert [(e.motivo, e.metricas.weighted) for e in panel._evaluaciones.values()] == before
        panel._boton_seleccionar_todo.click()
        assert events == [True]
        panel.limpiar()
        assert not panel._boton_seleccionar_todo.isEnabled()
    finally:
        panel.deleteLater()


def test_seleccionar_todo_bloqueado_no_cambia_casillas(qt_app, tmp_path):
    """No altera la selección utilizada por una operación en curso."""
    from pathlib import Path

    from stacks.global_pool import LightRef
    from stacks.registration import Registro
    from ui.stacker_tab.paneles.auditar import PanelAuditar

    frames = _frames([3, 4, 5])
    panel = PanelAuditar()
    try:
        refs = [LightRef(Path(f.path), f.session, None, 60) for f in frames]
        panel.mostrar(Registro(tmp_path, "probe_", refs), frames)
        panel.restaurar_aceptados(set())
        panel.bloquear(True)
        assert not panel._boton_seleccionar_todo.isEnabled()
        assert panel.seleccionar_todos() == 0
        assert panel.aceptados() == []
        panel.bloquear(False)
        assert panel._boton_seleccionar_todo.isEnabled()
    finally:
        panel.deleteLater()
