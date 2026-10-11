"""Símbolos retirados por la auditoría v0.2 (A-06): no deben volver.

Cada test fija que el símbolo ya no existe en su módulo: si alguien lo
reaparece sin consumidores, este test avisa. Verificación previa: los
cuatro tests fallaban con los símbolos aún presentes y pasan tras la poda.
"""
import inspect


def test_db_close_connection_retirada():
    """`close_connection`: la conexión única vive mientras vive el proceso."""
    from db import connection

    assert not hasattr(connection, "close_connection")


def test_planners_sin_utilidades_sin_llamantes():
    """`window_hours`, `list_constellations`, `ldn_count` y `WEATHER_FACTORS`."""
    from planners import capture_plan, celestial_search, ldn_loader, ranking

    assert not hasattr(capture_plan, "window_hours")
    assert not hasattr(celestial_search, "list_constellations")
    assert not hasattr(ldn_loader, "ldn_count")
    assert not hasattr(ranking, "WEATHER_FACTORS")


def test_session_parser_sin_master_kinds_ni_kinds():
    """Solo `FRAME_KINDS` tiene consumidores; las otras dos constantes no."""
    from stacks import session_parser

    assert not hasattr(session_parser, "MASTER_KINDS")
    assert not hasattr(session_parser, "KINDS")


def test_spin_dato_sin_parametro_solo_lectura():
    """Todos los spins son de solo lectura: el parámetro no decidía nada."""
    from ui.stacker_tab.pasos_common import _spin_dato

    assert "solo_lectura" not in inspect.signature(_spin_dato).parameters


def test_images_sin_api_publica_attach_remove():
    """`attach`/`remove` son internas de `sync`: ahora `_attach`/`_remove` (A-25)."""
    from equipment import images

    assert not hasattr(images, "attach")
    assert not hasattr(images, "remove")
    assert hasattr(images, "_attach")
    assert hasattr(images, "_remove")


def test_global_pool_sin_agregados_para_resumen():
    """`total_exposure_s`/`por_filtro` sin consumidor real (A-27): fuera."""
    from stacks import global_pool

    assert not hasattr(global_pool.GlobalPool, "total_exposure_s")
    assert not hasattr(global_pool.GlobalPool, "por_filtro")
