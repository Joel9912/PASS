"""Preparación offline del modelo aprobado; huellas simuladas solo para el contrato sintético, sin datos físicos ficticios publicados."""

import hashlib
import json

import pytest

from scripts import preparar_efemerides as preparation
from tests.spk_factory import synthetic_spk


@pytest.fixture
def local_inputs(tmp_path, monkeypatch):
    """Archivos propios: simula la aprobación de sus huellas sin leer kernels reales ni fuentes personales en pytest."""
    kernel, rules = tmp_path / "synthetic.bsp", tmp_path / "synthetic-rules.txt"
    kernel.write_bytes(synthetic_spk())
    rules.write_bytes(b"Reglas originales sinteticas: no son las condiciones reales NAIF.")
    monkeypatch.setattr(preparation, "EXPECTED_KERNEL_SHA256", hashlib.sha256(kernel.read_bytes()).hexdigest())
    monkeypatch.setattr(preparation, "EXPECTED_RULES_SHA256", hashlib.sha256(rules.read_bytes()).hexdigest())
    return kernel, rules


def test_referencia_productiva_fija_el_kernel_oficial_aprobado():
    """La receta no acepta cualquier SPK solo porque alguien lo llame DE442s."""
    assert preparation.EXPECTED_KERNEL_SHA256 == "54d97562a5b094d298b1b8eafa5a2e17e3e010ce85e1a366d07f003ad159323c"
    assert preparation.EXPECTED_RULES_SHA256 == "ae85f851646e7c4f0a762db852907bc090a2ab50c815eb2a6cd8639e96b7e047"


def test_preparador_conserva_bytes_y_avisos_obligatorios(local_inputs, tmp_path):
    """El contrato sintético conserva originales y dependencias; no es validación de precisión del modelo oficial."""
    kernel, rules = local_inputs
    before = kernel.read_bytes(), rules.read_bytes()
    resources = preparation.prepare(kernel, rules, tmp_path / "output", release_tag="v0.2-alpha")
    assert (tmp_path / "output/de442s.bsp").read_bytes() == before[0] == kernel.read_bytes()
    assert (tmp_path / "output/naif-rules-original.html.txt").read_bytes() == before[1] == rules.read_bytes()
    assert not resources["ephemeris"]["optional"]
    assert resources["ephemeris"]["requires"] == {"naif_notice": resources["naif_notice"]["version"],
                                                "naif_rules": resources["naif_rules"]["version"]}
    assert "No se garantiza precisión uniforme" in (tmp_path / "output/naif-notice.txt").read_text(encoding="utf-8")
    assert resources == json.loads((tmp_path / "output/resources-manifest.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("component", ["kernel", "rules"])
def test_fuente_alterada_no_crea_adjuntos(local_inputs, tmp_path, component):
    """Una revisión con bytes distintos exige volver a revisar la fuente, no recalcular una huella aprobada en silencio."""
    kernel, rules = local_inputs
    (kernel if component == "kernel" else rules).write_bytes(b"Contenido sustituido")
    with pytest.raises(ValueError, match="DE442s|NAIF"):
        preparation.prepare(kernel, rules, tmp_path / "output", release_tag="v0.2-alpha")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("tag", ["", "../otro", "rama/release"])
def test_destino_de_release_no_admite_rutas(local_inputs, tmp_path, tag):
    """Declarar URLs futuras no permite escapar de nombres de adjuntos ni crear releases mediante este comando."""
    with pytest.raises(ValueError, match="release"):
        preparation.prepare(*local_inputs, tmp_path / "output", release_tag=tag)
    assert not (tmp_path / "output").exists()


def test_destino_existente_no_se_sobrescribe(local_inputs, tmp_path):
    """La preparación no modifica el trabajo de otra tanda, aunque el kernel sea válido."""
    output = tmp_path / "output"
    output.mkdir()
    (output / "keep.txt").write_text("Conservar", encoding="utf-8")
    with pytest.raises(ValueError, match="nuevo"):
        preparation.prepare(*local_inputs, output, release_tag="v0.2-alpha")
    assert (output / "keep.txt").read_text(encoding="utf-8") == "Conservar"


def test_lectura_de_reglas_acotada(local_inputs, tmp_path, monkeypatch):
    """Incluso las entradas locales se leen con límite antes de generar archivos."""
    monkeypatch.setattr(preparation, "MAX_RULES_BYTES", 8)
    with pytest.raises(ValueError, match="grande"):
        preparation.prepare(*local_inputs, tmp_path / "output", release_tag="v0.2-alpha")
    assert not (tmp_path / "output").exists()


def test_huella_simulada_no_sustituye_validacion_estructural(local_inputs, tmp_path, monkeypatch):
    """La firma esperada y el lector SPK son verificaciones distintas, no una alternativa que se omite al coincidir bytes."""
    kernel, rules = local_inputs
    kernel.write_bytes(b"No es un SPK")
    monkeypatch.setattr(preparation, "EXPECTED_KERNEL_SHA256", hashlib.sha256(kernel.read_bytes()).hexdigest())
    with pytest.raises(ValueError):
        preparation.prepare(kernel, rules, tmp_path / "output", release_tag="v0.2-alpha")
    assert not (tmp_path / "output").exists()

