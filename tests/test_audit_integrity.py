"""Regresiones del contrato real de SirIL y rechazo de métricas inseguras."""

import pytest

from stacks.frame_metrics import FrameMetrics, Pesos, evaluar, extract_metrics, puntuar
from stacks.global_pool import LightRef
from stacks.registration import Registro


def _sequence(tmp_path, rows=None):
    """Construye una secuencia FITS sintética completa sin datos ni BD personales."""
    row = "R0 4 8 0.9 0 0.001 100 H 1 0 0 0 1 0 0 0 1"
    rows = rows if rows is not None else [row, row, row]
    header = "S 'probe_' 1 3 3 5 0 6 0 0 0\nL 1\nI 1 1\nI 2 1\nI 3 1\n"
    registry = Registro(tmp_path, "probe_", [
        LightRef(tmp_path / f"frame{i}.fit", "sesión", None, 60.0) for i in range(3)
    ], False)
    registry.ruta_seq.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    return registry


def test_fwhm_no_promedia_el_ponderado(tmp_path):
    """S-0024: los primeros campos son FWHM y wfwhm, no los ejes X/Y."""
    metrics = extract_metrics(_sequence(tmp_path))
    assert [m.fwhm for m in metrics] == [4.0, 4.0, 4.0]


@pytest.mark.parametrize("damage", [
    "missing_row", "duplicate_index", "wrong_count", "unknown_version",
    "missing_header", "wrong_name", "short_row", "bad_selection", "bad_reference",
])
def test_secuencia_incoherente_no_produce_veredictos(tmp_path, damage):
    """S-0025: no convierte un formato roto en métricas atribuibles o descartes de SirIL."""
    registry = _sequence(tmp_path)
    text = registry.ruta_seq.read_text(encoding="utf-8")
    if damage == "missing_row":
        text = "\n".join(text.splitlines()[:-1]) + "\n"
    elif damage == "duplicate_index":
        text = text.replace("I 2 1", "I 1 1")
    elif damage == "wrong_count":
        text = text.replace("1 3 3 5", "1 4 3 5")
    elif damage == "unknown_version":
        text = text.replace("5 0 6 0", "5 0 99 0")
    elif damage == "missing_header":
        text = text.split("\n", 1)[1]
    elif damage == "wrong_name":
        text = text.replace("'probe_'", "'otra_'")
    elif damage == "short_row":
        text = text.replace(" H 1 0 0 0 1 0 0 0 1", "")
    elif damage == "bad_selection":
        text = text.replace("I 2 1", "I 2 2")
    else:
        text = text.replace("5 0 6 0", "5 999 6 0")
    registry.ruta_seq.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        extract_metrics(registry)


@pytest.mark.parametrize("field", [0, 1, 2, 3, 4, 7])
@pytest.mark.parametrize("value", ["inf", "nan"])
def test_valores_no_finitos_no_contaminan_la_puntuacion(tmp_path, field, value):
    """S-0026: cualquier campo numérico inválido falla antes de asignar puntuaciones."""
    registry = _sequence(tmp_path)
    lines = registry.ruta_seq.read_text(encoding="utf-8").splitlines()
    fields = lines[-1].split()
    fields[field + 1] = value
    lines[-1] = " ".join(fields)
    registry.ruta_seq.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        extract_metrics(registry)


@pytest.mark.parametrize("field", ["fwhm", "roundness", "transparency", "background"])
def test_puntuar_valida_tambien_metricas_en_memoria(field):
    """S-0026: la API y los refrescos de UI no aceptan NaN aunque no proceda del parser."""
    metric = FrameMetrics("frame", "sesión", 4, 0.9, 1, 1, 0)
    setattr(metric, field, float("nan"))
    with pytest.raises(ValueError):
        puntuar([metric])


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), -1.0])
def test_pesos_invalidos_no_producen_veredictos(weight):
    """Los pesos programáticos tienen el mismo contrato seguro que los controles de la UI."""
    metric = FrameMetrics("frame", "sesión", 4, 0.9, 1, 1, 0)
    with pytest.raises(ValueError):
        evaluar([metric], Pesos(fwhm=weight))


def test_rgb_usa_canal_verde_del_registro(tmp_path):
    """La selección de métricas RGB sigue la preferencia de SirIL por el verde."""
    registry = _sequence(tmp_path)
    text = registry.ruta_seq.read_text(encoding="utf-8").replace("L 1", "L 3")
    row = "R1 2 3 0.95 0 0.001 100 H 1 0 0 0 1 0 0 0 1\n"
    registry.ruta_seq.write_text(text + row * 3, encoding="utf-8")
    assert [m.fwhm for m in extract_metrics(registry)] == [2, 2, 2]


def test_seleccion_siril_excluye_metricas_antiguas(tmp_path):
    """Un frame excluido en I no vuelve a ser utilizable por conservar una fila R antigua."""
    registry = _sequence(tmp_path)
    text = registry.ruta_seq.read_text(encoding="utf-8")
    text = text.replace("1 3 3 5", "1 3 2 5").replace("I 2 1", "I 2 0")
    registry.ruta_seq.write_text(text, encoding="utf-8")
    assert len(extract_metrics(registry)) == 2


@pytest.mark.parametrize("version", [4, 5, 6])
def test_versiones_de_contrato_conocido(tmp_path, version):
    """Las versiones conocidas conservan campos independientes y no mutan la secuencia."""
    registry = _sequence(tmp_path)
    text = registry.ruta_seq.read_text(encoding="utf-8").replace("5 0 6 0", f"5 0 {version} 0")
    registry.ruta_seq.write_text(text, encoding="utf-8")
    before = registry.ruta_seq.read_bytes()
    metrics = extract_metrics(registry)
    assert metrics[0].fwhm == 4 and metrics[0].wfwhm == 8 and metrics[0].stars == 100
    assert registry.ruta_seq.read_bytes() == before


@pytest.mark.parametrize("channel", [0, 2])
def test_rgb_sin_verde_usa_canal_disponible(tmp_path, channel):
    """Sin métricas verdes se conserva el fallback de SirIL, no se inventan mediciones."""
    registry = _sequence(tmp_path)
    text = registry.ruta_seq.read_text(encoding="utf-8").replace("L 1", "L 3").replace("R0", f"R{channel}")
    registry.ruta_seq.write_text(text, encoding="utf-8")
    metrics = extract_metrics(registry)
    assert all(m.registration_layer == channel and m.fwhm == 4 for m in metrics)


def test_ui_explica_fwhm_ponderado_y_estrellas(qt_app, tmp_path):
    """La tabla muestra FWHM real y conserva sus datos complementarios en la ayuda."""
    from ui.stacker_tab.paneles.auditar import PanelAuditar

    registry = _sequence(tmp_path)
    panel = PanelAuditar()
    try:
        panel.mostrar(registry, extract_metrics(registry))
        cell = panel._tabla.item(0, 3)
        assert cell.text() == "4.00"
        assert "ponderado SirIL: 8.0" in cell.toolTip()
        assert "Estrellas: 100" in cell.toolTip()
        assert "Canal registrado: 0" in cell.toolTip()
    finally:
        panel.deleteLater()


@pytest.mark.parametrize("version", [4, 5])
def test_cabecera_antigua_sin_flags_opcionales(tmp_path, version):
    """SirIL admite cabeceras antiguas sin los flags añadidos en v6."""
    registry = _sequence(tmp_path)
    text = registry.ruta_seq.read_text(encoding="utf-8").replace("5 0 6 0 0 0", f"5 0 {version}")
    registry.ruta_seq.write_text(text, encoding="utf-8")
    assert len(extract_metrics(registry)) == 3


def test_cabecera_v6_sin_flags_es_incompleta(tmp_path):
    """No aplica a una cabecera v6 las tolerancias de versiones anteriores."""
    registry = _sequence(tmp_path)
    text = registry.ruta_seq.read_text(encoding="utf-8").replace("5 0 6 0 0 0", "5 0 6")
    registry.ruta_seq.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="incompleta"):
        extract_metrics(registry)
