"""Tests de equipo: modelos, lecturas de la base y anotaciones (auditoría).

Cubren los hallazgos C-1 (Camera sin datos de FOV), C-2 y M-16 (funciones
implementadas que anotaban ``EquipmentSetup``/``Location`` y devolvían dicts).
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _memoria() -> sqlite3.Connection:
    """Conexión en memoria con el esquema completo."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    return conn


def test_camera_expone_los_datos_del_fov():
    """C-1: Camera lleva píxel y tamaño de sensor, ya presentes en el esquema."""
    from equipment.models import Camera

    cam = Camera(name="ASI2600", pixel_size_um=3.76, width_px=6248, height_px=4176)

    assert (cam.pixel_size_um, cam.width_px, cam.height_px) == (3.76, 6248, 4176)
    schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    for columna in ("camera_pixel_size_um", "camera_width_px", "camera_height_px"):
        assert columna in schema


def test_anotaciones_de_equipo_coinciden_con_lo_devuelto():
    """C-2/M-16: lo implementado anota dict, el contrato que ya usa la UI."""
    from equipment import localizations, manager

    assert manager.list_setups.__annotations__["return"] == list[dict]
    assert manager.get.__annotations__["return"] == dict | None
    assert localizations.list_locations.__annotations__["return"] == list[dict]


def test_list_setups_devuelve_dicts_de_fila(monkeypatch):
    """La tabla se lee como dicts completos (incluidas las columnas camera_*)."""
    from equipment import manager

    conn = _memoria()
    conn.execute(
        "INSERT INTO equipment_setups (name, category, camera_pixel_size_um,"
        " camera_width_px, camera_height_px) VALUES (?, ?, ?, ?, ?)",
        ("ASI2600", "nebulosas", 3.76, 6248, 4176),
    )
    conn.commit()
    monkeypatch.setattr(manager, "get_connection", lambda: conn)

    setups = manager.list_setups()

    assert setups and all(isinstance(s, dict) for s in setups)
    assert setups[0]["name"] == "ASI2600"
    assert setups[0]["camera_pixel_size_um"] == pytest.approx(3.76)
    assert manager.list_setups("campo_amplio") == []  # filtro por categoría
    conn.close()


def test_list_locations_devuelve_dicts_de_fila(monkeypatch):
    """M-16: list_locations devuelve dicts (lo que anota y lo que espera la UI)."""
    from equipment import localizations

    conn = _memoria()
    conn.execute(
        "INSERT INTO locations (name, latitude, longitude) VALUES (?, ?, ?)",
        ("Casa", 40.4, -3.7),
    )
    conn.commit()
    monkeypatch.setattr(localizations, "get_connection", lambda: conn)

    sitios = localizations.list_locations()

    assert len(sitios) == 1 and isinstance(sitios[0], dict)
    assert sitios[0]["name"] == "Casa"
    assert sitios[0]["latitude"] == pytest.approx(40.4)
    conn.close()


def test_migra_precio_y_peso_del_equipo():
    """D-3: una base antigua recibe `price_eur`/`weight_kg` al abrir.

    Las columnas las pide la comparativa del paso 6; se añadieron ya
    (decisión del usuario) para que `equipment_setups` se migre una sola vez.
    """
    import sqlite3

    from db import connection as db_conn

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE equipment_setups ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL)"
    )

    db_conn.init_db(conn)  # schema (IF NOT EXISTS → no toca la tabla) + migración

    columnas = {row[1] for row in conn.execute("PRAGMA table_info(equipment_setups)")}
    assert "price_eur" in columnas
    assert "weight_kg" in columnas
    # El esquema de una base nueva también los trae
    frescas = {row[1] for row in _memoria().execute("PRAGMA table_info(equipment_setups)")}
    assert {"price_eur", "weight_kg"} <= frescas
    conn.close()


def test_attach_copia_la_imagen_a_data(monkeypatch, tmp_path):
    """D-1: `attach()` copia el fichero a `data/equipment_images/<id>/`.

    Antes se persistía la ruta absoluta del `QFileDialog`: si el usuario
    movía o borraba el original, la imagen adjunta se perdía.
    """
    from equipment import images

    conn = _memoria()
    conn.execute("INSERT INTO equipment_setups (name) VALUES (?)", ("ASI2600",))
    conn.commit()
    monkeypatch.setattr(images, "get_connection", lambda: conn)
    monkeypatch.setattr(images, "IMAGES_ROOT", tmp_path / "equipment_images")

    original = tmp_path / "originales" / "spot.png"
    original.parent.mkdir()
    original.write_bytes(b"contenido de prueba")

    images.attach(1, str(original), "spot")

    guardada = Path(images.list_images(1)[0]["path"])
    assert guardada != original                     # la ruta guardada es la copia
    assert guardada.parent == tmp_path / "equipment_images" / "1"
    assert guardada.read_bytes() == b"contenido de prueba"

    # Re-adjuntar el mismo original: ya está copiado, no revienta
    images.attach(1, str(original), "spot")
    assert len(images.list_images(1)) == 2

    # Original perdido: se persiste la ruta tal cual en vez de fallar
    fantasma = tmp_path / "borrado.png"
    images.attach(1, str(fantasma), "otra")
    assert images.list_images(1)[2]["path"] == str(fantasma)
    conn.close()
