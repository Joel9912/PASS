"""Tests de las métricas de muestreo y resolución óptica (equipment/metrics).

Funciones puras: fórmulas (focal efectiva, escala ″/px, Dawes, F/d),
veredicto de muestreo con umbrales configurables y el bloque «Cálculos»
completo de la ficha del equipo. Los umbrales se leen de settings aquí
(mismo teclado que Configuración) — el módulo no toca la BD por su cuenta.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from equipment.metrics import (
    calculos,
    escala_imagen,
    focal_efectiva,
    limite_dawes,
    relacion_focal,
    veredicto_muestreo,
)
from equipment.models import Camera, Telescope

#: 206,264806 × 3,76 µm / 500 mm (los valores canónicos del plan).
_ESCALA_500_376 = 1.551111


def test_focal_efectiva_con_y_sin_reductor():
    """La focal que rige FOV/muestreo es la nominal × factor; sin dato, None."""
    assert focal_efectiva(1000.0, True, 0.8) == pytest.approx(800.0)
    assert focal_efectiva(1000.0, False, 0.8) == 1000.0  # reductor desactivado
    assert focal_efectiva(1000.0, True, None) == 1000.0  # factor desconocido
    assert focal_efectiva(1000.0, True, -0.8) == 1000.0  # factor inválido → nominal

    assert focal_efectiva(None, False, None) is None  # no informado
    assert focal_efectiva(0.0, False, None) is None


def test_escala_imagen_formula_y_entradas_vacias():
    """″/px = 206,265 × píxel(µm) / focal(mm); sin un dato no hay escala."""
    assert escala_imagen(500.0, 3.76) == pytest.approx(_ESCALA_500_376, abs=1e-6)
    assert escala_imagen(1000.0, 3.76) == pytest.approx(_ESCALA_500_376 / 2)

    assert escala_imagen(None, 3.76) is None
    assert escala_imagen(500.0, None) is None
    assert escala_imagen(0.0, 3.76) is None
    assert escala_imagen(500.0, 0.0) is None


def test_limite_dawes_formula_y_entradas_vacias():
    """Resolución resoluble (″) = 116 / apertura(mm); sin apertura, None."""
    assert limite_dawes(200.0) == pytest.approx(0.58)
    assert limite_dawes(80.0) == pytest.approx(1.45)

    assert limite_dawes(None) is None
    assert limite_dawes(0.0) is None
    assert limite_dawes(-200.0) is None


def test_relacion_focal():
    """F/d = focal efectiva / apertura; si falta cualquiera de las dos, None."""
    assert relacion_focal(1000.0, 200.0) == pytest.approx(5.0)
    assert relacion_focal(None, 200.0) is None
    assert relacion_focal(1000.0, None) is None
    assert relacion_focal(0.0, 200.0) is None


@pytest.mark.parametrize(
    "escala, resolucion, esperado",
    [
        (1.0, 0.58, "Submuestreado"),    # píxel más grueso que la óptica resuelve
        (0.75, 1.0, "Adecuado"),         # dentro de [0.5×, 1×] la resolución
        (0.3, 1.0, "Sobremuestreado"),   # píxeles más finos de lo aprovechable
        (None, 1.0, None),               # sin escala no hay veredicto
        (1.0, None, None),               # sin resolución (sin apertura) tampoco
        (1.0, 0.0, None),                # apertura 0 = no informada
    ],
)
def test_veredicto_muestreo_con_los_umbrales_por_defecto(escala, resolucion, esperado):
    """Veredicto con los defaults del plan (umbral_sub 1.0, umbral_sob 0.5)."""
    assert veredicto_muestreo(escala, resolucion) == esperado


def test_veredicto_muestreo_respeta_los_umbrales_configurados():
    """Los umbrales son parámetros: la comparativa no impone la verdad."""
    # Con sub=0.5 una escala de 0.75 sobre resolución 1.0 ya es «submuestreado».
    assert veredicto_muestreo(0.75, 1.0, umbral_sub=0.5) == "Submuestreado"
    # Con sob=0.9 la misma escala queda por debajo → «sobremuestreado».
    assert veredicto_muestreo(0.85, 1.0, umbral_sob=0.9) == "Sobremuestreado"


def test_veredicto_muestreo_en_la_frontera_es_adecuado():
    """Escala justo en el umbral (comparación estricta) → «Adecuado».

    Los `<`/`>` son estrictos: tocar el umbral superior o el inferior sin
    pasarlo sigue siendo muestreo adecuado.
    """
    assert veredicto_muestreo(1.0, 1.0) == "Adecuado"   # == umbral_sub × res
    assert veredicto_muestreo(0.5, 1.0) == "Adecuado"   # == umbral_sob × res


def test_calculos_del_bloque_completo():
    """El bloque «Cálculos» devuelve las 5 filas de la pareja en pantalla."""
    telescopio = Telescope(
        name="Newton 200",
        aperture_mm=200.0,
        focal_mm=1000.0,
        reducer=True,
        reducer_factor=0.8,
    )
    camara = Camera(name="ASI2600", pixel_size_um=3.76)

    filas = calculos(telescopio, camara)

    assert filas["focal_efectiva"] == pytest.approx(800.0)
    assert filas["escala"] == pytest.approx(_ESCALA_500_376 / 1.6, abs=1e-6)
    assert filas["dawes"] == pytest.approx(0.58)
    assert filas["relacion_focal"] == pytest.approx(4.0)
    assert filas["muestreo"] == "Submuestreado"  # 0.969 ″/px > Dawes 0.58

    # Umbrales ampliados por Configuración → mismo equipo, «Adecuado»
    amable = calculos(telescopio, camara, umbral_sub=2.0)
    assert amable["muestreo"] == "Adecuado"


def test_calculos_sin_datos_pintan_none():
    """Equipo vacío → todas las claves presentes con None (la UI pinta «—»)."""
    filas = calculos(Telescope(), Camera())

    assert set(filas) == {"focal_efectiva", "escala", "dawes", "relacion_focal", "muestreo"}
    assert all(valor is None for valor in filas.values())


def test_umbrales_de_muestreo_se_leen_de_settings(memory_settings):
    """Las claves de Configuración (`sampling_*_ratio`) con defaults defensivos.

    Ausente → default del plan (1.0 / 0.5); texto raro → default; numérico →
    se usa. El bloque «Cálculos» las recaba en cada recálculo (sin señal).
    """
    from db import settings

    assert settings.get_float("sampling_under_ratio", 1.0) == 1.0
    assert settings.get_float("sampling_over_ratio", 0.5) == 0.5

    settings.set_setting("sampling_under_ratio", "2.0")
    assert settings.get_float("sampling_under_ratio", 1.0) == pytest.approx(2.0)

    settings.set_setting("sampling_over_ratio", "basura")
    assert settings.get_float("sampling_over_ratio", 0.5) == 0.5
