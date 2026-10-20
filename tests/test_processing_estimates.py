"""Previsiones informativas: originales intactos, drizzle recalculado y ninguna velocidad inventada."""

from concurrent.futures import CancelledError
from threading import get_ident
from time import monotonic, sleep

import numpy as np
import pytest
from astropy.io import fits

from stacks.estimates import (
    TimingSample,
    estimate_processing,
    format_estimate,
    read_geometry,
)
from stacks.global_pool import LightRef
from stacks.registration import Registro
from stacks.stacker import StackOptions


def _frame(tmp_path, name="a", shape=(20, 30), cfa=False, filter=None):
    """Crea una referencia calibrada ficticia con dimensiones conocidas y sin red."""
    path = tmp_path / f"{name}.fit"
    fits.writeto(path, np.zeros(shape, dtype=np.uint16), fits.Header({"BAYERPAT": "RGGB"}) if cfa else None)
    return LightRef(path, str(tmp_path), filter, 60)


@pytest.mark.parametrize("shape,cfa,channels", [((20, 30), False, 1), ((20, 30), True, 3),
                                             ((3, 20, 30), False, 3)])
def test_geometria_procede_de_cada_cabecera_sin_modificar_fits(tmp_path, shape, cfa, channels):
    """Mono, CFA y RGB conservan su identidad; lectura no escribe imágenes ni carga otra sesión."""
    frame = _frame(tmp_path, shape=shape, cfa=cfa)
    before = frame.ruta.read_bytes()
    geometry = read_geometry([frame])
    item = geometry[str(frame.ruta.absolute())]
    assert (item.width, item.height, item.channels, item.cfa) == (30, 20, channels, cfa)
    assert frame.ruta.read_bytes() == before


def test_drizzle_cuadruplica_area_no_enlaces_ni_calibrados(tmp_path):
    """Los volúmenes geométricos crecen con el cuadrado de la escala sin contar los enlaces como copias."""
    frames = [_frame(tmp_path, name=str(i)) for i in range(3)]
    geometry = read_geometry(frames)
    normal = estimate_processing(frames, geometry)
    doubled = estimate_processing(frames, geometry, drizzle=True, scale=2)
    assert normal.working_bytes == (3 * 600 + 600) * 4
    assert normal.export_bytes == 600 * 4
    assert doubled.working_bytes == normal.working_bytes * 4
    assert doubled.export_bytes == normal.export_bytes * 4
    assert normal.seconds is None and doubled.seconds is None


def test_cfa_cuenta_debayer_solo_sin_drizzle_y_siempre_salida_rgb(tmp_path):
    """Drizzle de CFA no añade el debayer intermedio de la ruta sin drizzle."""
    frame = _frame(tmp_path, cfa=True)
    geometry = read_geometry([frame])
    normal = estimate_processing([frame], geometry)
    drizzle = estimate_processing([frame], geometry, drizzle=True)
    assert normal.working_bytes == 600 * 3 * 4 * 3
    assert drizzle.working_bytes == 600 * 3 * 4 * 2
    assert drizzle.export_bytes == normal.export_bytes == 600 * 3 * 4


@pytest.mark.parametrize("merged", [False, True])
def test_mapas_bits_y_exportacion_se_cuentan_por_separado(tmp_path, merged):
    """Los mapas quedan en working; la exportación duplica solo los másters, no todo el registro."""
    frame = _frame(tmp_path)
    options = StackOptions(bit32=False, rejmaps=True, merge_rejmaps=merged)
    estimate = estimate_processing([frame], read_geometry([frame]), options=options)
    assert estimate.export_bytes == 600 * 2
    assert estimate.working_bytes == 600 * (4 + 2 + 4 * (1 if merged else 2))


def test_canales_rgb_incluyen_composicion_pero_no_triplete_arbitrario(tmp_path):
    """La previsión no promete composiciones HOO/SHO ni altera la asignación de filtros."""
    rgb = [_frame(tmp_path, name=filter, filter=filter) for filter in ("R", "G", "B")]
    estimate = estimate_processing(rgb, read_geometry(rgb))
    assert estimate.export_bytes == 600 * 4 * 6
    rgb[0].filtro = "Ha"
    other = estimate_processing(rgb, read_geometry(rgb))
    assert other.export_bytes == 600 * 4 * 3


def test_sin_tomas_no_inventa_trabajo_y_sin_datos_no_inventa_totales(tmp_path):
    """Cero es posible; datos faltantes no se sustituyen por dimensiones de otro frame."""
    zero = estimate_processing([], {})
    assert zero.selected == zero.unknown == zero.working_bytes == zero.export_bytes == 0
    assert "no se ejecutará" in format_estimate(zero)
    frame = _frame(tmp_path)
    frame.ruta.unlink()
    unknown = estimate_processing([frame], read_geometry([frame]))
    assert unknown.unknown == 1 and unknown.seconds is None
    assert "totales desconocidos" in format_estimate(unknown)


@pytest.mark.parametrize("shape", [(10,), (4, 20, 30), (2, 3, 20, 30)])
def test_dimensiones_no_soportadas_no_se_adivinan(tmp_path, shape):
    """Vectores y cubos no RGB requieren datos explícitos en vez de proyectarse silenciosamente a 2D."""
    frame = _frame(tmp_path, shape=shape)
    assert read_geometry([frame]) == {}


@pytest.mark.parametrize("scale", [0, -1, float("nan"), float("inf"), True, "2"])
def test_escala_invalida_se_rechaza(scale):
    """La estimación no produce tamaños negativos, infinitos ni conversiones implícitas."""
    with pytest.raises(ValueError):
        estimate_processing([], {}, scale=scale)


def test_tiempo_solo_extrapola_medida_comparable_y_cambia_con_drizzle(tmp_path):
    """No existe velocidad por defecto; una muestra exacta da su tiempo y más píxeles incrementan el coste."""
    frame = _frame(tmp_path)
    geometry = read_geometry([frame])
    options = dict(drizzle=True, scale=1)
    base = estimate_processing([frame], geometry, **options)
    sample = TimingSample(base.signature, base.work_pixels, 60)
    measured = estimate_processing([frame], geometry, sample=sample, **options)
    assert measured.seconds == 60
    enlarged = estimate_processing([frame], geometry, drizzle=True, scale=2, sample=sample)
    assert enlarged.seconds > measured.seconds
    changed = estimate_processing([frame], geometry, drizzle=True, kernel="point", sample=sample)
    assert changed.seconds is None
    invalid = TimingSample(base.signature, base.work_pixels, float("inf"))
    assert estimate_processing([frame], geometry, sample=invalid, **options).seconds is None


def test_cancelacion_de_cabeceras_no_publica_resultado_parcial(tmp_path):
    """La lectura informativa obedece cierre/reinicio antes de acceder al siguiente FITS."""
    frame = _frame(tmp_path)

    def stop():
        """Simula la cancelación cooperativa antes de leer."""
        raise CancelledError

    with pytest.raises(CancelledError):
        read_geometry([frame], stop)


def test_ui_drizzle_y_seleccion_recalculan_fuera_de_qt_sin_siril(qt_app, memory_db, tmp_path, monkeypatch):
    """La UI usa todas las cabeceras en worker, recalcula sin lecturas y no toca la selección ni SirIL."""
    from ui import stacker_tab

    page = stacker_tab.StackerPage()
    frames = [_frame(tmp_path, name=str(i)) for i in range(2)]
    threads = []
    reader = stacker_tab.read_geometry

    def observe(*args):
        """Registra el hilo conservando el lector FITS real."""
        threads.append(get_ident())
        return reader(*args)

    monkeypatch.setattr(stacker_tab, "read_geometry", observe)
    accepted = [1, 2]
    monkeypatch.setattr(page.panel_auditar, "aceptados", lambda: list(accepted))
    try:
        registry = Registro(tmp_path, "test_", frames)
        page.registro = registry
        page._actualizar_estimacion()
        end = monotonic() + 5
        while page._geometry is None and monotonic() < end:
            qt_app.processEvents()
            sleep(.005)
        assert page._geometry is not None
        assert threads and all(thread != get_ident() for thread in threads)
        before = page._estimacion_actual()
        page.panel_apilar._drizzle.setChecked(True)
        page.panel_apilar._scale.setCurrentIndex(3)
        assert page._estimacion_actual().working_bytes == before.working_bytes * 4
        assert "2 tomas" in page.panel_apilar._estimacion.text()
        accepted.clear()
        page.panel_auditar.seleccion_cambiada.emit()
        assert "no se ejecutará" in page.panel_apilar._estimacion.text()
        assert len(threads) == 1 and page._worker is None
        page.reiniciar()
        page._recibir_geometria(registry, reader(frames))
        assert page._geometry is None and page._geometry_registry is None
    finally:
        page._cancelar_geometria()
        page.deleteLater()


@pytest.mark.parametrize("recovered", [False, True])
def test_tiempo_se_mide_solo_en_corrida_completa(qt_app, memory_db, tmp_path, monkeypatch, recovered):
    """Una recuperación omite registro y no debe convertirse en una falsa previsión rápida para próximas pilas."""
    from stacks.global_pool import GlobalPool
    from stacks.session_parser import Session
    from ui import stacker_tab

    page = stacker_tab.StackerPage()
    working = tmp_path / "working"
    frame = _frame(tmp_path)
    registry = Registro(working / "registrados" / "pila", "test_", [frame])
    registry.dir.mkdir(parents=True)
    monkeypatch.setattr(stacker_tab, "WORKING_FOLDER", working)
    monkeypatch.setattr(page, "_asegurar_siril", lambda: True)
    monkeypatch.setattr(page.panel_auditar, "aceptados", lambda: [1])
    monkeypatch.setattr(stacker_tab.work_recovery, "registration_context", lambda *args: {})
    monkeypatch.setattr(stacker_tab.work_recovery, "seal_registry", lambda *args: {"context": {}})
    monkeypatch.setattr(page._draft, "changed", lambda: True)
    monkeypatch.setattr(page._draft, "clear", lambda: True)
    monkeypatch.setattr(stacker_tab, "register_pool", lambda *args, **kwargs: registry)
    monkeypatch.setattr(stacker_tab, "apilar_pool", lambda *args, **kwargs: [working / "pila.fit"])
    monkeypatch.setattr(stacker_tab, "exportar_apilados", lambda paths, mother: paths)
    monkeypatch.setattr(stacker_tab, "monotonic", iter([100., 160.]).__next__)

    def run(task, completed, **kwargs):
        """Ejecuta solo dobles de SirIL en el hilo Qt; permite verificar la confirmación sin procesos externos."""
        completed(task(lambda *args: None, lambda *args: None))
        return True

    monkeypatch.setattr(page, "_lanzar", run)
    try:
        page.sesiones = [Session(tmp_path / "sesion")]
        page.registro = registry
        page._pool = GlobalPool(entries=[frame])
        page.panel_apilar._nombre.setText("pila")
        page._geometry_registry, page._geometry = registry, read_geometry([frame])
        if recovered:
            page._final_checkpoint = {"context": {}}
            monkeypatch.setattr(stacker_tab.work_recovery, "recover_registry", lambda *args: registry)
        page.apilar()
        if recovered:
            assert page._timing_sample is None
        else:
            assert page._timing_sample.seconds == 60
            assert page._timing_sample.work_pixels > 0
    finally:
        page._cancelar_geometria()
        page.deleteLater()
