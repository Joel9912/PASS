"""Solapes y muestras de captura: geometría celeste, cabeceras intactas y clasificación explicable."""

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from stacks.session_fov import (
    CaptureField,
    SessionField,
    compare_fields,
    read_field,
    shared_fraction,
    survey_sessions,
)
from stacks.session_parser import Session, parse_session


def _capture(path, ra=10, dec=20, scale=.02, rotation=0):
    """FITS TAN sintético con orientación explícita, sin catálogos ni red."""
    celestial = WCS(naxis=2)
    celestial.wcs.crpix = [50.5, 50.5]
    celestial.wcs.crval = [ra, dec]
    celestial.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    angle = np.radians(rotation)
    celestial.wcs.cd = scale * np.array([[-np.cos(angle), -np.sin(angle)],
                                        [-np.sin(angle), np.cos(angle)]])
    path.parent.mkdir(parents=True, exist_ok=True)
    fits.writeto(path, np.zeros((100, 100), dtype=np.uint16), celestial.to_header())
    return path


@pytest.mark.parametrize("ra,dec", [(10, 20), (359.9, 0), (0.1, 89), (180, -89)])
def test_huella_identica_y_campo_interior_cuentan_como_uno(tmp_path, ra, dec):
    """El denominador es el FOV menor incluso en RA=0 y cerca de polos."""
    first = read_field(_capture(tmp_path / "a.fit", ra, dec))
    smaller = read_field(_capture(tmp_path / "b.fit", ra, dec, scale=.01))
    assert shared_fraction(first, first) == pytest.approx(1)
    assert shared_fraction(first, smaller) == pytest.approx(1, abs=1e-8)
    assert shared_fraction(smaller, first) == pytest.approx(1, abs=1e-8)


@pytest.mark.parametrize("rotation", [0, 30, 90])
def test_solape_simetrico_y_campos_lejanos(tmp_path, rotation):
    """La rotación afecta la huella; no compara solo centros ni rectángulos en RA/Dec."""
    a = read_field(_capture(tmp_path / "a.fit", dec=0))
    b = read_field(_capture(tmp_path / "b.fit", ra=10.9, dec=0, rotation=rotation))
    far = read_field(_capture(tmp_path / "c.fit", ra=30))
    assert 0 < shared_fraction(a, b) < .8
    assert shared_fraction(a, b) == pytest.approx(shared_fraction(b, a), abs=1e-8)
    assert shared_fraction(a, far) == 0


def test_rotacion_distingue_rectangulos_no_cuadrados(tmp_path):
    """Una captura girada no se toma por idéntica solo porque su centro coincide."""
    a = CaptureField(tmp_path / "a.fit", ((9., -.2), (11., -.2), (11., .2), (9., .2)), "Sintético")
    b = CaptureField(tmp_path / "b.fit", ((9.8, -1.), (10.2, -1.), (10.2, 1.), (9.8, 1.)), "Sintético girado")
    assert shared_fraction(a, b) == pytest.approx(.2, abs=.001)


def test_sin_rotacion_ni_wcs_no_inventa_encuadre(tmp_path):
    """Centro y tamaño sin orientación no bastan para certificar el porcentaje de solape."""
    path = tmp_path / "a.fit"
    fits.writeto(path, np.zeros((10, 10)), fits.Header({"RA": 10, "DEC": 20, "SCALE": 5}))
    assert read_field(path) is None
    assert read_field(tmp_path / "ausente.fit") is None


def test_rectangulo_cabecera_y_fits_original_intacto(tmp_path):
    """SCALE/RA/DEC/CROTA2 permiten solo una huella estimada; leerla no modifica el FITS."""
    path = tmp_path / "a.fit"
    fits.writeto(path, np.zeros((20, 30)), fits.Header({"RA": 10, "DEC": 20, "SCALE": 5, "CROTA2": 30}))
    before = path.read_bytes()
    field = read_field(path)
    assert field is not None and "estimado" in field.method
    assert field.center == pytest.approx((10, 20), abs=1e-6)
    assert path.read_bytes() == before


def test_wcs_con_ejes_dec_ra_no_intercambia_coordenadas(tmp_path):
    """El orden de ejes WCS no siempre es RA/Dec; la huella se transforma al marco común correctamente."""
    celestial = WCS(naxis=2)
    celestial.wcs.ctype = ["DEC--TAN", "RA---TAN"]
    celestial.wcs.crval = [20, 10]
    celestial.wcs.crpix = [50.5, 50.5]
    celestial.wcs.cdelt = [.02, -.02]
    path = tmp_path / "swapped.fit"
    fits.writeto(path, np.zeros((100, 100)), celestial.to_header())
    assert read_field(path).center == pytest.approx((10, 20), abs=1e-6)


def test_clasificacion_no_confunde_ausencia_con_mosaico(tmp_path):
    """El 80 % estricto se aplica a huellas disponibles, no a campos inexistentes."""
    a = read_field(_capture(tmp_path / "a.fit", dec=0))
    b = read_field(_capture(tmp_path / "b.fit", ra=11, dec=0))
    assert compare_fields([SessionField("a", a), SessionField("b", a)]).classification.startswith("Mismo encuadre")
    assert compare_fields([SessionField("a", a), SessionField("b", b)]).classification.startswith("Mosaico")
    assert compare_fields([SessionField("a", a), SessionField("b", None)]).classification.startswith("Revisar")


def test_80_exacto_no_impone_un_lado_de_la_regla(tmp_path, monkeypatch):
    """El usuario definió > y <: igualdad es límite pendiente de revisión, no umbral inventado."""
    from stacks import session_fov

    a = read_field(_capture(tmp_path / "a.fit"))
    monkeypatch.setattr(session_fov, "shared_fraction", lambda *args: .8)
    assert "límite" in compare_fields([SessionField("a", a), SessionField("b", a)]).classification


@pytest.mark.parametrize("check_ra", [30, 10])
def test_sesion_aislada_lee_otro_fits_y_no_sustituye_discrepancia(tmp_path, monkeypatch, check_ra):
    """Dos campos alejados se contrastan; cabeceras incompatibles quedan visibles para revisar."""
    from stacks import session_fov

    sessions = []
    for name, center, check_center in (("A", 10, 10), ("B", 30, check_ra)):
        paths = [_capture(tmp_path / name / "first.fit", ra=center),
                 _capture(tmp_path / name / "second.fit", ra=check_center)]
        sessions.append(Session(tmp_path / name, frames={"lights": paths}))
    chosen = []

    def choose(paths):
        """Hace reproducible la selección aleatoria sin reutilizar el primer FITS."""
        chosen.append(paths)
        return paths[0]

    monkeypatch.setattr(session_fov.random, "choice", choose)
    survey = survey_sessions(sessions)
    assert len(chosen) == 2
    row = survey.sessions[1]
    assert row.primary.source.name == "first.fit" and row.check.source.name == "second.fit"
    assert row.primary.center[0] == pytest.approx(30)
    if check_ra == 10:
        assert row.state == "discrepante" and survey.classification.startswith("Revisar")
    else:
        assert row.state == "válido" and survey.classification.startswith("Mosaico")


def test_raw_y_sesiones_sin_fits_se_conservan_como_sin_datos(tmp_path):
    """El análisis no convierte RAW ni exige calibrar para rellenar metadatos ausentes."""
    raw = tmp_path / "a.nef"
    raw.write_bytes(b"raw sintetico")
    survey = survey_sessions([Session(tmp_path, frames={"lights": [raw]})])
    assert survey.sessions[0].primary is None
    assert raw.read_bytes() == b"raw sintetico"


def test_cancelacion_interrumpe_comparacion_sin_leer_todos_los_fits(tmp_path):
    """Un cierre o reescaneo detiene pronto la tarea obsoleta, sin producir un resultado parcial."""
    from concurrent.futures import CancelledError

    sessions = [Session(tmp_path / "a", frames={"lights": []})]

    def checkpoint():
        """Reproduce la cancelación cooperativa antes de la primera lectura."""
        raise CancelledError

    with pytest.raises(CancelledError):
        survey_sessions(sessions, checkpoint)


def test_carpeta_repetida_no_cuenta_como_otro_panel(tmp_path):
    """La misma referencia repetida se rechaza, no añade evidencia de solape ficticia."""
    session = Session(tmp_path)
    with pytest.raises(ValueError, match="misma carpeta"):
        survey_sessions([session, session])


def test_ui_superpone_huellas_sin_filas_nuevas_y_conserva_seleccion(qt_app, tmp_path):
    """La carta usa muestras por sesión; el resultado no recarga tabla ni ocupa más altura."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    from stacks.session_parser import ficha_de_luz
    from ui.stacker_tab.paneles.sesiones import PanelSesiones

    sessions = [Session(tmp_path / name, frames={"lights": [_capture(tmp_path / name / "a.fit", ra=ra, dec=0)]})
                for name, ra in (("A", 10), ("B", 11))]
    survey = survey_sessions(sessions)
    panel = PanelSesiones()
    try:
        fichas = {str(s.path.resolve()): ficha_de_luz(s.frames["lights"][0]) for s in sessions}
        panel.mostrar(sessions, set(), {}, fichas)
        panel.resize(1500, 760)
        panel.show()
        panel._tabla.selectRow(1)
        qt_app.processEvents()
        before = (panel._tabla.currentRow(), panel._tabla.rowCount(), panel._cielo.height())
        panel._visor._zoom = 2.5
        revision = panel._visor._revision
        panel.poner_campos(survey)
        qt_app.processEvents()
        assert before == (panel._tabla.currentRow(), panel._tabla.rowCount(), panel._cielo.height())
        assert panel._visor._zoom == 2.5 and panel._visor._revision == revision
        assert panel._cielo._survey is survey
        assert len(panel._cielo._survey.sessions) == 2
        assert "Mosaico" in panel._cielo.toolTip()
        assert "a.fit" in panel._tabla.item(1, 0).toolTip()
        assert "Solape" in panel._tabla.item(1, 0).data(Qt.ItemDataRole.AccessibleDescriptionRole)
        assert panel._cielo.accessibleDescription() == panel._cielo.toolTip()
        assert not panel._panel_rot.isEnabled()
        assert not panel._cielo.grab().isNull()
        panel._tabla.setFocus()
        QTest.keyClick(panel._tabla, Qt.Key.Key_Up)
        assert panel._tabla.currentRow() == 0
        assert panel._cielo._selected_session == str(sessions[0].path.resolve())
        panel.mostrar([], set(), {})
        assert panel._campos is None and panel._cielo._survey is None
    finally:
        panel.close()
        panel.deleteLater()


def _wait(qt_app, condition):
    """Procesa señales Qt de una tarea real sin entrar en diálogos ni ejecutar SirIL."""
    import time

    end = time.monotonic() + 5
    while time.monotonic() < end:
        qt_app.processEvents()
        if condition():
            return True
        time.sleep(.005)
    return False


def test_recuperacion_compara_fov_en_otro_hilo_sin_siril(qt_app, memory_db, tmp_path, monkeypatch):
    """Recuperar deriva las huellas sin procesar imágenes, cambiar permisos ni bloquear el hilo Qt."""
    from threading import get_ident

    from stacks import work_recovery
    from ui import stacker_tab

    path = _capture(tmp_path / "sesion" / "lights" / "a.fit")
    source = stacker_tab.StackerPage()
    restored = stacker_tab.StackerPage()
    threads = []
    survey = stacker_tab.survey_sessions

    def compare(sessions, checkpoint):
        """Conserva lector real y registra el hilo para comprobar separación de Qt."""
        threads.append(get_ident())
        return survey(sessions, checkpoint)

    monkeypatch.setattr(stacker_tab, "survey_sessions", compare)
    try:
        source.sesiones = [parse_session(path.parent.parent)]
        source._input_stamps = work_recovery.input_signature(source.sesiones)
        source._inputs_verified = True
        restored._restore_draft(source._draft_snapshot())
        assert restored._inputs_verified
        assert _wait(qt_app, lambda: restored._campos is not None)
        assert threads and all(thread != get_ident() for thread in threads)
        assert restored._worker is None and restored.registro is None
        assert not restored._auditado and not restored._apilado
        generation = restored._fov_generation
        old = restored._campos
        restored.reiniciar()
        restored._recibir_campos(generation, old)
        assert restored._campos is None
        assert restored.panel_sesiones._cielo._survey is None
    finally:
        for page in (source, restored):
            page._cancelar_revision_campos()
            page.deleteLater()


def test_recuperacion_con_entradas_cambiadas_no_lee_muestras_nuevas(qt_app, memory_db, tmp_path, monkeypatch):
    """Una referencia que perdió su sello requiere reescaneo, no dispara lecturas de FOV en segundo plano."""
    from stacks import work_recovery
    from ui import stacker_tab

    path = _capture(tmp_path / "sesion" / "lights" / "a.fit")
    source, restored = stacker_tab.StackerPage(), stacker_tab.StackerPage()
    calls = []
    monkeypatch.setattr(stacker_tab, "survey_sessions", lambda *args: calls.append(args))
    try:
        source.sesiones = [parse_session(path.parent.parent)]
        source._input_stamps = work_recovery.input_signature(source.sesiones)
        source._inputs_verified = True
        assert work_recovery.verify_inputs(source.sesiones, source._input_stamps)
        data = source._draft_snapshot()
        path.write_bytes(b"FITS cambiado")
        restored._restore_draft(data)
        qt_app.processEvents()
        assert not restored._inputs_verified
        assert restored._fov_future is None and restored._campos is None
        assert calls == []
    finally:
        for page in (source, restored):
            page._cancelar_revision_campos()
            page.deleteLater()
