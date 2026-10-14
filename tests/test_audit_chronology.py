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
        assert "2026-03-02" in panel._preview_pie.text() and "UTC" in panel._preview_pie.text()
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
