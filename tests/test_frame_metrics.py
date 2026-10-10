"""stacks/frame_metrics: lectura de las métricas del .seq, puntuación 0–100 y evaluación.

Ojo: no confundir con `test_metrics.py`, que prueba `equipment/metrics.py`.
Nada de SirIL aquí: los .seq se escriben a mano con el formato real
validado (líneas R0: fwhm_x, fwhm_y, redondez, fondo, nº de estrellas).
"""
from pathlib import Path

import pytest

from stacks.frame_metrics import (
    FrameMetrics,
    Pesos,
    evaluar,
    extract_metrics,
    puntuar,
)
from stacks.global_pool import LightRef
from stacks.registration import Registro


def _R(fwhm_x=5.0, fwhm_y=5.0, roundness=0.98, fondo=690.0) -> str:
    """Fila de registro como la escribe SirIL (R0 + campos)."""
    return f"R0 {fwhm_x} {fwhm_y} {roundness} 0 {fondo / 65535} 27 H 1 0 0 0 1 0 0 0 1"


def _registro(
    tmp_path: Path,
    filas_R: list[str],
    exposiciones: list[float | None] | None = None,
) -> Registro:
    """Registro de mentira: .seq con las filas dadas y un light por fila."""
    frames = [
        LightRef(
            ruta=Path(f"/cal/{i:04d}.fit"),
            sesion=f"noche{(i - 1) % 2 + 1}",
            filtro=None,
            exposicion_s=(
                exposiciones[i - 1] if exposiciones is not None else 30.0
            ),
        )
        for i in range(1, len(filas_R) + 1)
    ]
    registro = Registro(dir=tmp_path, seq="registro_", frames=frames)
    n = len(filas_R)
    registro.ruta_seq.write_text(
        f"S 'registro_' 1 {n} {n} {n} 0 6 0 0 0\n"
        + "".join(f"I {i} 1\n" for i in range(1, n + 1))
        + "".join(fila + "\n" for fila in filas_R)
    )
    return registro


def _metrica(path="f1", fwhm=5.0, roundness=0.95, transparency=1.0, fondo=600.0):
    return FrameMetrics(
        path=path, session="s", fwhm=fwhm, roundness=roundness,
        transparency=transparency, background=fondo, weighted=0.0,
    )


def test_extract_lee_las_metricas_del_seq(tmp_path):
    """Del .seq salen fwhm (media x/y), redondez, fondo, sesión y transparencia."""
    registro = _registro(tmp_path, [
        _R(fwhm_x=4.0, fwhm_y=6.0, roundness=0.9, fondo=800.0),
        _R(fwhm_x=5.0, fwhm_y=5.0, roundness=1.0, fondo=400.0),
    ])

    a, b = extract_metrics(registro)

    assert a.fwhm == 5.0 and a.roundness == 0.9
    # El fondo sale en ADU/s: 800 ADU sobre 30 s de exposición (del LightRef).
    assert a.background == pytest.approx(800.0 / 30.0)
    assert (a.path, a.session) == (str(Path("/cal/0001.fit")), "noche1")
    assert (b.path, b.session) == (str(Path("/cal/0002.fit")), "noche2")
    # La transparencia es un proxy del fondo dentro del pool (mejor = 1).
    assert (a.transparency, b.transparency) == (0.5, 1.0)
    assert 0.0 <= a.weighted <= 100.0 and a.weighted < b.weighted


def test_extract_normaliza_el_fondo_por_exposicion(tmp_path):
    """Lo de 60 s y lo de 45 s con la misma tasa miden lo mismo (ADU/s)."""
    registro = _registro(
        tmp_path,
        [
            _R(fondo=90.0),    # 45 s → 2,0 ADU/s
            _R(fondo=120.0),   # 60 s → 2,0 ADU/s: ¡igual que el anterior!
            _R(fondo=135.0),   # 45 s → 3,0 ADU/s: más contaminación real
            _R(fondo=500.0),   # sin exposición: se deja crudo
        ],
        exposiciones=[45.0, 60.0, 45.0, None],
    )

    a, b, c, d = extract_metrics(registro)

    assert a.background == pytest.approx(2.0)
    assert b.background == pytest.approx(2.0)  # sin normalizar sería 120 vs 90
    assert c.background == pytest.approx(3.0)
    assert d.background == 500.0
    # La transparencia deja de penalizar la sesión más larga…
    assert a.transparency == pytest.approx(1.0)
    assert b.transparency == pytest.approx(1.0)
    # …y sigue castigando la contaminación lumínica de verdad.
    assert c.transparency == pytest.approx(2.0 / 3.0)


def test_fondo_seq_normalizado_siril_a_adu_por_segundo(tmp_path):
    """Un fondo real 0,00094 de SirIL no se muestra como 0,0 ADU/s."""
    registro = _registro(tmp_path, [
        "R0 3.93578 3.94007 0.888609 0 0.000940359 1835 H 1 0 0 0 1 0 0 0 1"
    ])
    registro.frames[0].exposicion_s = 45.0
    valor = extract_metrics(registro)[0].background
    assert valor == pytest.approx(0.000940359 * 65535 / 45)
    assert round(valor, 1) == 1.4


def test_extract_sin_datos_de_registro_falla(tmp_path):
    """Un .seq sin registrar no inventa métricas."""
    registro = _registro(tmp_path, [])
    registro.ruta_seq.write_text("S 'registro_' 1 0 0 0 0 6 0 0 0\n")
    with pytest.raises(ValueError, match="datos de registro"):
        extract_metrics(registro)


def test_extract_con_mas_filas_que_frames_falla(tmp_path):
    """Si el .seq trae más filas R que frames, no se atribuye a ciegas."""
    frames = [
        LightRef(ruta=Path(f"/cal/{i}.fit"), sesion="s", filtro=None, exposicion_s=None)
        for i in range(1, 3)
    ]
    registro = Registro(dir=tmp_path, seq="registro_", frames=frames)
    registro.ruta_seq.write_text(
        f"S 'registro_' 1 3 3 3 0 6 0 0 0\n{_R()}\n{_R()}\n{_R()}\n"
    )
    with pytest.raises(ValueError, match="filas de registro"):
        extract_metrics(registro)


def test_extract_salta_los_frames_descartados(tmp_path):
    """Filas en ceros (frames que SirIL descartó) no se puntúan: se saltan."""
    registro = _registro(tmp_path, [
        _R(fwhm_x=4.0, fwhm_y=6.0, roundness=0.9, fondo=800.0),
        _R(fwhm_x=0.0, fwhm_y=0.0, roundness=0.0, fondo=0.0),  # descartado
        _R(fwhm_x=5.0, fwhm_y=5.0, roundness=float("-nan"), fondo=0.0),  # descartado
        _R(fwhm_x=3.0, fwhm_y=3.0, roundness=1.0, fondo=400.0),
    ])

    metricas = extract_metrics(registro)

    assert [(m.path, m.session) for m in metricas] == [
        (str(Path("/cal/0001.fit")), "noche1"),
        (str(Path("/cal/0004.fit")), "noche2"),
    ]
    assert all(m.fwhm > 0 and m.background > 0 for m in metricas)


def test_extract_si_todo_fue_descartado_falla(tmp_path):
    """Si no quedó registrado ni un frame, no hay auditoría que hacer."""
    registro = _registro(tmp_path, [_R(fwhm_x=0.0, fwhm_y=0.0, roundness=0.0, fondo=0.0)])
    with pytest.raises(ValueError, match="registrado"):
        extract_metrics(registro)


def test_puntuar_respeta_los_pesos():
    """Con un solo peso mandan solo sus frames; el mejor saca 100, el peor 0."""
    metricas = [
        _metrica(path="a", fwhm=4.0, roundness=0.9, transparency=1.0, fondo=400.0),
        _metrica(path="b", fwhm=8.0, roundness=1.0, transparency=0.5, fondo=800.0),
    ]

    puntuar(metricas, Pesos(fwhm=100.0, redondez=0.0, transparencia=0.0, fondo=0.0))
    assert [m.weighted for m in metricas] == [100.0, 0.0]

    puntuar(metricas, Pesos(fwhm=0.0, redondez=100.0, transparencia=0.0, fondo=0.0))
    assert [m.weighted for m in metricas] == [0.0, 100.0]


def test_pesos_en_cero_no_puntuan():
    """Sin pesos no hay escala que sostener."""
    with pytest.raises(ValueError, match="pesos"):
        puntuar([_metrica()], Pesos(fwhm=0.0, redondez=0.0, transparencia=0.0, fondo=0.0))


def test_frames_idénticos_son_igual_de_buenos():
    """Todos iguales en una métrica: nadie es peor en ella (1.0 para todos)."""
    metricas = [_metrica(path=f"f{i}") for i in range(3)]
    puntuar(metricas)
    assert [m.weighted for m in metricas] == [100.0, 100.0, 100.0]


def test_evaluar_un_frame_peor_en_todo_lleva_todos_los_motivos():
    """El veredicto junta el mínimo y los cortes que toquen, en orden."""
    buenos = [
        _metrica(
            path=f"f{i}",
            fwhm=5.0 + 0.02 * i,
            roundness=[0.94, 0.95, 0.96, 0.94, 0.95][i],
            fondo=600.0 + 0.5 * i,
        )
        for i in range(5)
    ]
    peor = _metrica(path="peor", fwhm=9.0, roundness=0.6, fondo=1200.0)

    por_ruta = {e.metricas.path: e for e in evaluar(buenos + [peor])}

    assert por_ruta["peor"].descartada
    assert por_ruta["peor"].motivo == "Puntuación, FWHM, Redondez, Fondo"
    assert not any(por_ruta[f"f{i}"].descartada for i in range(5))


def test_evaluar_cortan_solo_el_lado_malo_y_con_mad():
    """Un fwhm excelente no corta; el alto sí (y el fondo alto, no el bajo)."""
    buenos = [
        _metrica(path=f"f{i}", fwhm=5.0 + 0.02 * i, roundness=0.95, fondo=600.0 + i)
        for i in range(8)
    ]
    guiado = _metrica(path="guiado", fwhm=6.5, fondo=603.0)
    nublado = _metrica(path="nublado", fwhm=5.0, fondo=700.0)

    por_ruta = {
        e.metricas.path: e
        for e in evaluar(buenos + [guiado, nublado], umbral=0.0, sigma=2.0)
    }

    assert por_ruta["guiado"].motivo == "FWHM"
    assert por_ruta["nublado"].motivo == "Fondo"
    assert not any(por_ruta[f"f{i}"].descartada for i in range(8))


def test_evaluar_un_peso_a_cero_no_corta_esa_metrica():
    """Peso 0 = la métrica no decide nada: con Fondo a 0 no corta el fondo."""
    buenos = [
        _metrica(path=f"f{i}", fwhm=5.0 + 0.02 * i, roundness=0.95, fondo=600.0 + i)
        for i in range(8)
    ]
    nublado = _metrica(path="nublado", fwhm=5.0, roundness=0.95, fondo=700.0)
    sin_fondo = Pesos(fwhm=40.0, redondez=25.0, transparencia=20.0, fondo=0.0)

    por_ruta = {
        e.metricas.path: e
        for e in evaluar(buenos + [nublado], sin_fondo, umbral=0.0, sigma=2.0)
    }

    # Con el mismo pool, con fondo>0 el corte salía (test de arriba).
    assert por_ruta["nublado"].motivo == ""


def test_evaluar_sin_dispersion_solo_manda_el_minimo():
    """Sin dispersión (MAD 0) ninguna métrica corta: solo el mínimo de puntos."""
    iguales = [_metrica(path=f"f{i}") for i in range(4)]

    assert all(not e.descartada for e in evaluar(iguales, umbral=50.0))
    assert {e.motivo for e in evaluar(iguales, umbral=100.1)} == {"Puntuación"}
    assert evaluar([]) == []


def test_evaluar_repuntua_con_los_pesos_actuales():
    """Cambiar pesos y repuntuar no vuelve a registrar: cambia el veredicto."""
    metricas = [
        _metrica(path="a", fwhm=4.0, roundness=0.9, transparency=1.0, fondo=400.0),
        _metrica(path="b", fwhm=8.0, roundness=1.0, transparency=0.5, fondo=800.0),
    ]

    por_ruta = {
        e.metricas.path: e
        for e in evaluar(
            metricas,
            Pesos(fwhm=0.0, redondez=100.0, transparencia=0.0, fondo=0.0),
            umbral=80.0,
        )
    }

    assert por_ruta["a"].metricas.weighted == 0.0
    assert por_ruta["b"].metricas.weighted == 100.0
    assert por_ruta["a"].motivo == "Puntuación"
    assert not por_ruta["b"].descartada
