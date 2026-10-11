"""global_pool: solo referencias a lights calibrados, con sus metadatos.

SirIL no interviene aquí (nada de subprocess): lo que se prueba es que el
pool nunca copia ni apunta fuera de la carpeta de trabajo, y que lee filtro
y exposición de las cabeceras FITS.
"""
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from stacks.calibrator import output_dir_for
from stacks.global_pool import GlobalPool, pool_desde_calibradas


def _fit(path: Path, **cabecera) -> Path:
    """FITS mínimo (2×2) de 16 bits con la cabecera indicada."""
    path.parent.mkdir(parents=True, exist_ok=True)
    datos = np.full((2, 2), 1, dtype=np.uint16)
    fits.writeto(path, datos, header=fits.Header(cabecera) if cabecera else None, overwrite=True)
    return path


@pytest.fixture
def pool(tmp_path) -> GlobalPool:
    """Pool con la raíz en una carpeta de calibrados de mentira."""
    return GlobalPool(root=tmp_path / "calibrados")


def test_add_session_referencia_sin_copiar(pool):
    """Referencia, nunca copia: los ficheros quedan donde estaban."""
    carpeta = pool.root / "noche1" / "light"
    _fit(carpeta / "pp_light_00001.fit", FILTER="Ha", EXPOSURE=300.0)
    _fit(carpeta / "pp_light_00002.fit", FILTER="Ha", EXPOSURE=300.0)
    antes = sorted(p.name for p in carpeta.iterdir())

    assert pool.add_session("noche1", carpeta) == 2
    assert sorted(p.name for p in carpeta.iterdir()) == antes  # cero escrituras
    assert [ref.ruta.name for ref in pool.entries] == [
        "pp_light_00001.fit", "pp_light_00002.fit",
    ]
    assert all(ref.sesion == "noche1" for ref in pool.entries)


def test_metadata_de_las_cabeceras(pool):
    """Filtro y exposición salen de las cabeceras; sin ellas, None."""
    carpeta = pool.root / "noche1" / "light"
    _fit(carpeta / "pp_light_00001.fit", FILTER=" Ha ", EXPOSURE=300.0)
    _fit(carpeta / "pp_light_00002.fit")  # sin FILTER ni EXPOSURE
    pool.add_session("noche1", carpeta)

    ha, sin = pool.entries
    assert (ha.filtro, ha.exposicion_s) == ("Ha", 300.0)  # recortado
    assert (sin.filtro, sin.exposicion_s) == (None, None)


def test_re_anadir_sustituye_la_sesion(pool):
    """Recalibrar la misma sesión no duplica entradas."""
    carpeta = pool.root / "noche1" / "light"
    _fit(carpeta / "pp_light_00001.fit", EXPOSURE=30.0)
    pool.add_session("noche1", carpeta)
    _fit(carpeta / "pp_light_00002.fit", EXPOSURE=30.0)

    assert pool.add_session("noche1", carpeta) == 2
    assert len(pool.entries) == 2


def test_fuera_de_la_carpeta_de_trabajo_se_rechaza(pool, tmp_path):
    """El pool jamás referencia fuera de la raíz (protege los originales)."""
    ajena = tmp_path / "sesion original" / "light"
    _fit(ajena / "light_0001.fits", EXPOSURE=30.0)

    with pytest.raises(ValueError, match="fuera de"):
        pool.add_session("origen", ajena)
    assert pool.entries == []


def test_pool_desde_calibradas_ignora_lo_borrado(tmp_path):
    """Se reconstruye desde la BD; las carpetas ya borradas se ignoran."""
    raiz = tmp_path / "calibrados"
    luz = raiz / "noche1" / "light"
    _fit(luz / "pp_light_00001.fit", EXPOSURE=300.0)
    filas = [
        {"session_dir": "/origen/noche1", "calibrated_dir": str(raiz / "noche1"),
         "n_frames": 1, "exposure_s": 300.0},
        {"session_dir": "/origen/borrada", "calibrated_dir": str(raiz / "borrada"),
         "n_frames": 5, "exposure_s": 300.0},  # carpeta ya inexistente
    ]

    pool = pool_desde_calibradas(filas, root=raiz)
    assert [ref.sesion for ref in pool.entries] == [str(Path("/origen/noche1").resolve())]
    assert pool.entries[0].exposicion_s == 300.0


def test_pool_ignora_salida_ajena_y_legacy_ambiguo(tmp_path):
    """Una fila mal atribuida o dos filas en el mismo legacy no contaminan el pool."""
    raiz = tmp_path / "calibrados"
    a, b = tmp_path / "a" / "noche", tmp_path / "b" / "noche"
    nueva = output_dir_for(a, root=raiz)
    antigua = raiz / "noche"
    _fit(nueva / "light" / "pp_1.fit")
    _fit(antigua / "light" / "pp_2.fit")
    filas = [
        {"session_dir": str(b), "calibrated_dir": str(nueva)},
        {"session_dir": str(a), "calibrated_dir": str(antigua)},
        {"session_dir": str(b), "calibrated_dir": str(antigua)},
    ]
    assert pool_desde_calibradas(filas, root=raiz).entries == []
    assert len(pool_desde_calibradas(filas[1:2], root=raiz).entries) == 1
