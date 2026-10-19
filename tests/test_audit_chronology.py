"""Fechas UTC y recorrido por sesión, sin inferir cronología del número del frame."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from astropy.io import fits

from stacks.audit_metadata import capture_dates, chronological_indices
from stacks.frame_metrics import FrameMetrics, extract_metrics
from stacks.global_pool import LightRef
from stacks.registration import Registro


@pytest.mark.parametrize("value,system,expected", [
    ("2026-03-01T07:00:00", None, datetime(2026,3,1,7,tzinfo=UTC)),
    ("2026-03-01T07:00:00Z", "UTC", datetime(2026,3,1,7,tzinfo=UTC)),
    ("2026-02-28T23:00:00-06:00", "UTC", datetime(2026,3,1,5,tzinfo=UTC)),
    ("2026-03-01T07:00:00.1234", "UTC", datetime(2026,3,1,7,microsecond=123400,tzinfo=UTC)),
    ("ilegible", "UTC", None),
    ("2026-03-01", "UTC", None),
    (" 2026-03-01 ", "UTC", None),
    (None, "UTC", None),
    ("01/03/2026", "UTC", None),
    ("2026-03-01T07:00:00", "TAI", None),
    ("9999-12-31T23:59:59-10:00", "UTC", None),
])
def test_fecha_fits_solo_lectura_sin_horas_inventadas(tmp_path, value, system, expected):
    """Normaliza UTC/offset explícito; falta de hora, formato o sistema no soportado queda desconocido."""
    path = tmp_path/"frame.fit"
    header = fits.Header()
    if value is not None:
        header["DATE-OBS"] = value
    if system is not None:
        header["TIMESYS"] = system
    fits.writeto(path, np.zeros((4,4),dtype=np.uint16),header)
    before = path.read_bytes()
    assert capture_dates([LightRef(path,"noche",None,60)])[str(path)] == expected
    assert path.read_bytes() == before


@pytest.mark.parametrize("content", [None, b"ilegilble"])
def test_cabecera_ausente_o_ilegible_no_crea_archivos(tmp_path, content):
    """La ausencia de fecha no bloquea la auditoría ni se convierte en una fecha ficticia."""
    path = tmp_path/"frame.fit"
    if content is not None:
        path.write_bytes(content)
    assert capture_dates([LightRef(path,"noche",None,60)])[str(path)] is None
    assert (path.read_bytes() if path.exists() else None) == content


def test_orden_por_sesion_y_hora_con_empates_y_fechas_ausentes(tmp_path):
    """Cada sesión permanece contigua, por su primera captura; desconocidas/empates son estables."""
    names = ["A","B","A","B","C","A","A"]
    frames = [LightRef(tmp_path/f"f{i}.fit",name,None,60) for i,name in enumerate(names)]
    zero = datetime(2026,3,1,tzinfo=UTC)
    dates = {str(ref.ruta): (zero+timedelta(hours=hour) if hour is not None else None)
             for ref,hour in zip(frames,[3,0,1,None,None,None,1],strict=True)}
    assert chronological_indices(frames,dates) == [2,4,3,7,1,6,5]
    assert [ref.sesion for ref in frames] == names


def test_sesiones_homonimas_sin_fechas_no_se_funden(tmp_path):
    """La identidad completa de sesión evita mezclar dos carpetas llamadas noche."""
    frames = [LightRef(tmp_path/f"f{i}.fit",name,None,60)
              for i,name in enumerate(["D:/A/noche","D:/B/noche","D:/A/noche","D:/B/noche"])]
    assert chronological_indices(frames,{}) == [1,3,2,4]


def test_extractor_recoge_fecha_incluso_de_rechazada_siril(tmp_path):
    """La revisión temporal no expulsa del orden las tomas que carecen de métricas."""
    frames = []
    for i in range(2):
        path = tmp_path/f"f{i}.fit"
        fits.writeto(path,np.zeros((4,4),dtype=np.uint16),fits.Header({"DATE-OBS":f"2026-03-01T07:0{i}:00"}))
        frames.append(LightRef(path,"noche",None,60))
    registry = Registro(tmp_path,"probe_",frames,False)
    registry.ruta_seq.write_text(
        "S 'probe_' 1 2 2 5 0 6 0 0 0\nL 1\nI 1 1\nI 2 1\n"
        "R0 4 4 0.9 0 0.001 100 H 1 0 0 0 1 0 0 0 1\n"
        "R0 0 0 0 0 0 0 H 1 0 0 0 1 0 0 0 1\n", encoding="utf-8")
    assert len(extract_metrics(registry)) == 1
    assert registry.capture_times[str(frames[1].ruta)] == datetime(2026,3,1,7,1,tzinfo=UTC)


def test_ui_orden_temporal_no_aplica_pesos_pendientes_y_preserva_seleccion(qt_app, tmp_path):
    """Ordenar es solo vista: conserva toma visible, casillas y veredictos incluso con criterios editados."""
    from PyQt6.QtCore import Qt

    from ui.stacker_tab.paneles.auditar import PanelAuditar

    frames = [LightRef(tmp_path/f"f{i}.fit",session,None,60) for i,session in enumerate(["A","A","B","B"])]
    zero = datetime(2026,3,1,tzinfo=UTC)
    registry = Registro(tmp_path,"probe_",frames,False)
    registry.capture_times = {str(ref.ruta): zero+timedelta(hours=hour)
                             for ref,hour in zip(frames,[25,24,1,2],strict=True)}
    metrics = [FrameMetrics(str(ref.ruta),ref.sesion,fwhm,0.9,1,1,0)
               for ref,fwhm in zip(frames[:3],[4,3,5],strict=True)]
    panel = PanelAuditar()

    def order():
        """Recupera índices de secuencia, no números de fila."""
        return [panel._tabla.item(i,0).data(Qt.ItemDataRole.UserRole) for i in range(panel._tabla.rowCount())]

    try:
        panel.mostrar(registry,metrics)
        assert order() == [2,1,3,4]
        panel.restaurar_aceptados({str(frames[1].ruta.absolute())})
        panel._tabla.setCurrentCell(0,1)
        previous = [(e.metricas.weighted,e.motivo) for e in panel._evaluaciones.values()]
        panel._pesos["fwhm"].setValue(20)
        panel._orden.setCurrentIndex(panel._orden.findData("cronologico"))
        assert order() == [3,4,2,1]
        assert panel.aceptados() == [2]
        assert panel._tabla.item(panel._tabla.currentRow(),0).data(Qt.ItemDataRole.UserRole) == 2
        assert [(e.metricas.weighted,e.motivo) for e in panel._evaluaciones.values()] == previous
        assert "2 marzo" in panel._pie_completo and "UTC" in panel._pie_completo
        assert "2026-03-02" in panel._preview_pie.toolTip()
        assert "2026-03-01" in panel._tabla.item(0,2).toolTip()
        assert panel._seleccion_plot.data["x"].tolist() == [3]
        assert "no a escala" in panel._plot.getAxis("bottom").labelText
        assert not panel._tabla.item(1,0).flags() & Qt.ItemFlag.ItemIsUserCheckable
        panel._boton_seleccionar_todo.click()
        assert np.isnan(panel._curva.getData()[1]).any()
        panel.bloquear(True)
        assert not panel._orden.isEnabled()
    finally:
        panel.deleteLater()


@pytest.mark.parametrize("site,selected,expected,source", [
    (None, 1, -6, "alternativa"),
    ((10.0, -84.0), 2, -6, "FITS coincidente"),
    ((40.0, -3.0), 1, 2, "FITS coincidente"),
    ((20.0, 30.0), 1, 0, "sin desfase"),
    (None, None, 0, "UTC"),
])
def test_hora_local_prioriza_captura_sobre_alternativa(site, selected, expected, source):
    """El desfase afecta solo la presentación; no se adivina una zona por longitud."""
    from stacks.audit_metadata import local_capture_time

    locations = [dict(id=1, name="Casa", latitude=10., longitude=-84., utc_offset_hours=-6),
                 dict(id=2, name="Viaje", latitude=40., longitude=-3., utc_offset_hours=2)]
    moment = datetime(2026, 3, 1, 5, 18, 12, tzinfo=UTC)
    default = next((loc for loc in locations if loc["id"] == selected), None)
    local, detail = local_capture_time(moment, site, locations, default)
    assert local.utcoffset() == timedelta(hours=expected)
    assert local == moment
    assert source in detail
    if expected == -6:
        assert (local.day, local.hour, local.minute) == (28, 23, 18)


@pytest.mark.parametrize("offset", [None, float("nan"), 15])
def test_ubicacion_sin_desfase_valido_conserva_utc(offset):
    """Un sitio sin huso no se presenta como si su longitud fuera una zona política."""
    from stacks.audit_metadata import local_capture_time

    moment = datetime(2026, 3, 1, tzinfo=UTC)
    local, detail = local_capture_time(moment, None, [], dict(name="X", utc_offset_hours=offset))
    assert local.tzinfo == UTC and "sin desfase" in detail


def test_huso_automatico_ubicacion_se_etiqueta_aproximado():
    """Mantiene la convención de PASS sin presentarla como zona política ni horario histórico."""
    from stacks.audit_metadata import local_capture_time

    moment = datetime(2026, 3, 1, 5, 18, tzinfo=UTC)
    local, detail = local_capture_time(moment, None, [],
                                     dict(name="Casa", longitude=-84, utc_offset_hours=None))
    assert local.hour == 23 and local.day == 28
    assert "aproximado por longitud" in detail


def test_extractor_conserva_posicion_fits_sin_modificarlo(tmp_path):
    """Recoge coordenadas del observatorio, nunca RA/DEC del objeto."""
    path = tmp_path / "capture.fit"
    fits.writeto(path, np.zeros((2, 2)), fits.Header({
        "DATE-OBS": "2026-03-01T05:18:12", "OBSGEO-B": 10., "OBSGEO-L": -84.}))
    before = path.read_bytes()
    sites = {}
    dates = capture_dates([LightRef(path, "s", None, 60)], sites)
    assert sites[str(path)] == (10., -84.)
    assert dates[str(path)].hour == 5
    assert path.read_bytes() == before


def test_pie_compacto_no_reduce_visor_y_revela_motivos(qt_app, tmp_path):
    """Un motivo largo no crea segunda línea; hora alternativa no cambia orden ni selección."""
    from ui.stacker_tab.paneles.auditar import PanelAuditar

    ref = LightRef(tmp_path / "f.fit", "noche", None, 60)
    registry = Registro(tmp_path, "probe_", [ref], False)
    registry.capture_times = {str(ref.ruta): datetime(2026, 3, 1, 5, 18, 12, tzinfo=UTC)}
    panel = PanelAuditar()
    try:
        panel.configurar_ubicaciones([dict(id=1, name="Casa", utc_offset_hours=-6)], "1")
        panel.mostrar(registry, [FrameMetrics(str(ref.ruta), "noche", 4, .9, 1, 1, 0)])
        panel.resize(1500, 760)
        panel.show()
        qt_app.processEvents()
        panel._tabla.setCurrentCell(0, 1)
        qt_app.processEvents()
        height = panel._preview_label.height()
        assert "28 febrero 23:18:12" in panel._pie_completo
        assert "Descartar: no" in panel._pie_completo
        assert "alternativa" in panel._preview_pie.toolTip()
        assert not panel._preview_pie.wordWrap()
        panel._evaluaciones[str(ref.ruta)].descartada = True
        panel._evaluaciones[str(ref.ruta)].motivo = "Motivo muy largo " * 100
        panel._alSeleccionar()
        qt_app.processEvents()
        assert panel._preview_label.height() == height
        assert "Descartar: sí" in panel._pie_completo
        assert "Motivo muy largo" not in panel._preview_pie.text()
        assert "Motivo muy largo" in panel._preview_pie.toolTip()
        assert panel._preview_pie.height() < 2 * panel._preview_pie.fontMetrics().lineSpacing()
        assert panel.aceptados() == [1]
    finally:
        panel.close()
        panel.deleteLater()


def test_ubicacion_alternativa_se_recuerda_sin_elegir_entre_varias(qt_app, memory_db):
    """La página persiste una elección explícita y la vuelve a cargar sin usar la primera ubicación."""
    from db.settings import get_setting
    from ui.stacker_tab import StackerPage

    first = memory_db.execute(
        "INSERT INTO locations(name,latitude,longitude,utc_offset_hours) VALUES ('A',10,-84,-6)").lastrowid
    second = memory_db.execute(
        "INSERT INTO locations(name,latitude,longitude,utc_offset_hours) VALUES ('B',40,-3,2)").lastrowid
    memory_db.commit()
    page = StackerPage()
    try:
        selector = page.panel_auditar._ubicacion_horaria
        assert selector.currentData() == ""
        selector.setCurrentIndex(selector.findData(str(second)))
        assert get_setting("audit_default_location") == str(second)
        page._recargar_ubicacion_horaria()
        assert selector.currentData() == str(second)
        assert selector.currentData() != str(first)
    finally:
        page.deleteLater()
