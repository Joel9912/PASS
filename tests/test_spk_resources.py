"""Validación de SPK sintéticos propios antes de activar una edición; sin datos JPL, red o base personal."""

import hashlib
from struct import pack_into

import pytest

from db import data_resources
from db.spk_resources import validate_spk
from tests.spk_factory import synthetic_spk


@pytest.mark.parametrize("kind", [2, 3])
def test_spk_sintetico_valido_y_bytes_intactos(kind):
    """Los dos tipos polinómicos admitidos pasan por el lector real sin modificar el contenido."""
    data = synthetic_spk(kind=kind)
    before = hashlib.sha256(data).hexdigest()
    validate_spk(data)
    data_resources.validate_content(data, {"format": "spk-planets-v1", "size": len(data), "sha256": before})
    assert hashlib.sha256(data).hexdigest() == before


@pytest.mark.parametrize("options", [
    {"missing": [(0, 10)]}, {"missing": [(3, 399)]}, {"missing": [(3, 301)]},
    {"missing": [(1, 199)]}, {"frame": 2}, {"kind": 9}, {"value": float("nan")},
    {"start_jd": 2440000.5}, {"end_jd": 2488000.5},
])
def test_spk_invalido_no_se_publica(tmp_path, options):
    """Ni una huella correcta permite publicar un kernel sin cobertura, cadenas o coeficientes válidos."""
    data = synthetic_spk(**options)
    item = {"format": "spk-planets-v1", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "url": "synthetic"}
    with pytest.raises(ValueError):
        data_resources.prepare_resource(tmp_path, item, lambda *_: data)
    assert not list(tmp_path.rglob("*.blob"))


@pytest.mark.parametrize("damage", ["header", "truncated", "cycle", "count", "radius", "index"])
def test_spk_directorio_y_registros_corruptos_rechazados(damage):
    """El preflight acota directorios cíclicos y rechaza intervalos o índices ajenos antes de calcular."""
    data = bytearray(synthetic_spk())
    if damage == "header":
        data[:8] = b"DAF/CK  "
    elif damage == "truncated":
        data = data[:-1]
    elif damage == "cycle":
        pack_into("<d", data, 1024, 2)
    elif damage == "count":
        pack_into("<d", data, 1040, 999)
    elif damage == "radius":
        pack_into("<d", data, 3072 + 8, 0)
    else:
        pack_into("<i", data, 1048 + 32, 1)
    with pytest.raises(ValueError):
        validate_spk(bytes(data))


def test_formato_desconocido_no_se_trata_como_texto():
    """La API directa también rechaza formatos futuros, aunque sus bytes sean texto y su huella coincida."""
    data = b"texto"
    with pytest.raises(ValueError):
        data_resources.validate_content(data, {"format": "future", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
