"""Tests de equipo: modelos, lecturas de la base y anotaciones (auditoría).

Cubren los hallazgos C-1 (Camera sin datos de FOV), C-2 y M-16 (funciones
implementadas que anotaban ``EquipmentSetup``/``Location`` y devolvían dicts),
M-17 (``list_setups()`` con `location_name`), M-20 (``count_sessions()``) y
D-8: el fixture compartido ``memory_db`` con las FK activas.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_camera_expone_los_datos_del_fov(memory_db):
    """C-1: Camera lleva píxel y tamaño de sensor, en su tabla (Equipo v2).

    El FOV depende de esos tres datos; antes vivían embebidos en
    ``equipment_setups`` sin modelo y hoy están en ``cameras``, de donde
    ``list_setups()`` los expone como alias (lo comprueba el test de claves
    FOV del backend).
    """
    from equipment.models import Camera

    cam = Camera(name="ASI2600", pixel_size_um=3.76, width_px=6248, height_px=4176)

    assert (cam.pixel_size_um, cam.width_px, cam.height_px) == (3.76, 6248, 4176)
    columnas = {row[1] for row in memory_db.execute("PRAGMA table_info(cameras)")}
    assert {"pixel_size_um", "width_px", "height_px"} <= columnas


def test_anotaciones_de_equipo_coinciden_con_lo_devuelto():
    """C-2/M-16: lo implementado anota dict, el contrato que ya usa la UI."""
    from equipment import localizations, manager

    assert manager.list_setups.__annotations__["return"] == list[dict]
    assert manager.get.__annotations__["return"] == dict | None
    assert localizations.list_locations.__annotations__["return"] == list[dict]


def test_list_setups_devuelve_dicts_de_fila(memory_db):
    """La tabla se lee como dicts de fila con sus columnas (C-2)."""
    from equipment import manager

    memory_db.execute(
        "INSERT INTO equipment_setups (name, category, price_eur, weight_kg)"
        " VALUES (?, ?, ?, ?)",
        ("ASI2600", "espacio_profundo", 1200.0, 8.5),
    )
    memory_db.commit()

    setups = manager.list_setups()

    assert setups and all(isinstance(s, dict) for s in setups)
    assert setups[0]["name"] == "ASI2600"
    assert setups[0]["price_eur"] == pytest.approx(1200.0)
    assert manager.list_setups("campo_amplio") == []  # filtro por categoría


def test_list_setups_trae_el_nombre_de_la_ubicacion(memory_db):
    """M-17: el dict trae ``location_name`` (LEFT JOIN) para la tabla del plan.

    Sin ubicación — o con la ubicación borrada, que el esquema desvincula con
    ``ON DELETE SET NULL`` — la clave existe y vale ``None``: ``.get()`` sirve
    para los dos casos.
    """
    from equipment import manager

    cur = memory_db.execute(
        "INSERT INTO locations (name, latitude, longitude) VALUES (?, ?, ?)",
        ("Casa", 40.4, -3.7),
    )
    memory_db.execute(
        "INSERT INTO equipment_setups (name, location_id) VALUES (?, ?)",
        ("ASI2600", cur.lastrowid),
    )
    memory_db.execute("INSERT INTO equipment_setups (name) VALUES (?)", ("Sin sitio",))
    memory_db.commit()

    por_nombre = {s["name"]: s for s in manager.list_setups()}
    assert por_nombre["ASI2600"]["location_name"] == "Casa"
    assert por_nombre["Sin sitio"].get("location_name") is None

    # Borrar la ubicación desvincula el setup (SET NULL): sigue sin nombre
    memory_db.execute("DELETE FROM locations WHERE id = ?", (cur.lastrowid,))
    memory_db.commit()
    por_nombre = {s["name"]: s for s in manager.list_setups()}
    assert por_nombre["ASI2600"]["location_name"] is None


def test_list_locations_devuelve_dicts_de_fila(memory_db):
    """M-16: list_locations devuelve dicts (lo que anota y lo que espera la UI)."""
    from equipment import localizations

    memory_db.execute(
        "INSERT INTO locations (name, latitude, longitude) VALUES (?, ?, ?)",
        ("Casa", 40.4, -3.7),
    )
    memory_db.commit()

    sitios = localizations.list_locations()

    assert len(sitios) == 1 and isinstance(sitios[0], dict)
    assert sitios[0]["name"] == "Casa"
    assert sitios[0]["latitude"] == pytest.approx(40.4)


def test_migra_precio_y_peso_del_equipo(memory_db):
    """D-3: una base antigua recibe `price_eur`/`weight_kg` al abrir.

    Las columnas las pide la comparativa del paso 6; se añadieron ya
    (decisión del usuario) para que `equipment_setups` se migre una sola vez.
    """
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
    frescas = {row[1] for row in memory_db.execute("PRAGMA table_info(equipment_setups)")}
    assert {"price_eur", "weight_kg"} <= frescas
    conn.close()


def test_migra_las_referencias_y_quita_las_columnas_de_la_v1(memory_db):
    """Equipo v2: una base antigua gana las FK de componentes y pierde lo embebido.

    Las columnas de la v1 (``telescope_name``, ``camera_*``, ``mount_name``)
    pasaron a sus tablas; si la migración no las quitara, una base antigua
    conviviría con datos muertos. Se comprueba además que el borrado es
    idempotente y que una base fresca sale sin esquema huérfano.
    """
    from db import connection as db_conn

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE equipment_setups ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL,"
        " telescope_name TEXT, camera_resolution TEXT,"
        " camera_pixel_size_um REAL, mount_name TEXT)"
    )

    db_conn.init_db(conn)

    columnas = {row[1] for row in conn.execute("PRAGMA table_info(equipment_setups)")}
    assert {
        "price_eur",
        "weight_kg",
        "telescope_id",
        "guide_telescope_id",
        "camera_id",
        "guide_camera_id",
        "mount_id",
    } <= columnas
    assert not (
        {"telescope_name", "camera_resolution", "camera_pixel_size_um", "mount_name"}
        & columnas
    )
    db_conn.init_db(conn)  # segunda pasada: idempotente, no revienta

    frescas = {row[1] for row in memory_db.execute("PRAGMA table_info(equipment_setups)")}
    assert not (set(db_conn._LEGACY_SETUP_COLUMNS) & frescas)
    conn.close()


def test_migra_el_sitio_de_las_ubicaciones(memory_db):
    """Una base antigua recibe las columnas de sitio de la Equipo v2."""
    from db import connection as db_conn

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE locations (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL)"
    )

    db_conn.init_db(conn)

    sitio = {"obstacles", "lp", "bortle", "sqm", "consider_lp"}
    columnas = {row[1] for row in conn.execute("PRAGMA table_info(locations)")}
    assert sitio <= columnas
    frescas = {row[1] for row in memory_db.execute("PRAGMA table_info(locations)")}
    assert sitio <= frescas  # la fresca las trae directas del esquema
    conn.close()


def test_attach_copia_la_imagen_a_data(memory_db, monkeypatch, tmp_path):
    """D-1: `attach()` copia el fichero a `data/equipment_images/<id>/`.

    Antes se persistía la ruta absoluta del `QFileDialog`: si el usuario
    movía o borraba el original, la imagen adjunta se perdía.
    """
    from equipment import images

    memory_db.execute("INSERT INTO equipment_setups (name) VALUES (?)", ("ASI2600",))
    memory_db.commit()
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


def test_memory_db_dispara_los_on_delete_del_esquema(memory_db):
    """D-8: el fixture trae las FK activas y el ``SET NULL`` se aplica.

    Sin ``PRAGMA foreign_keys`` (SQLite lo trae desactivado), borrar un setup
    dejaría sus ``planned_sessions`` colgando de él y ningún test lo notaría.
    """
    cur = memory_db.execute(
        "INSERT INTO equipment_setups (name) VALUES (?)", ("ASI2600",)
    )
    memory_db.execute(
        "INSERT INTO planned_sessions (object_id, session_date, setup_id)"
        " VALUES (?, ?, ?)",
        ("M31", "2026-09-01", cur.lastrowid),
    )
    memory_db.commit()

    memory_db.execute(
        "DELETE FROM equipment_setups WHERE id = ?", (cur.lastrowid,)
    )
    memory_db.commit()

    fila = memory_db.execute(
        "SELECT setup_id FROM planned_sessions WHERE object_id = ?", ("M31",)
    ).fetchone()
    assert fila["setup_id"] is None  # SET NULL disparado: las FK están activas


def test_count_sessions_cuenta_antes_y_tras_el_set_null(memory_db):
    """M-20: ``count_sessions`` es el nº que la confirmación de borrado muestra.

    Refleja el contrato del esquema: al borrar el setup las sesiones **no se
    borran**, quedan desvinculadas (``ON DELETE SET NULL``) y el conteo pasa a
    0 — por eso hay que avisar *antes*. ``delete()`` aún es stub, así que el
    borrado se simula con SQL.
    """
    from equipment import manager

    cur = memory_db.execute(
        "INSERT INTO equipment_setups (name) VALUES (?)", ("ASI2600",)
    )
    setup_pk = cur.lastrowid
    for fecha in ("2026-09-01", "2026-09-02"):
        memory_db.execute(
            "INSERT INTO planned_sessions (object_id, session_date, setup_id)"
            " VALUES (?, ?, ?)",
            ("M31", fecha, setup_pk),
        )
    memory_db.commit()
    assert manager.count_sessions(setup_pk) == 2

    memory_db.execute("DELETE FROM equipment_setups WHERE id = ?", (setup_pk,))
    memory_db.commit()

    assert manager.count_sessions(setup_pk) == 0  # desvinculadas, no borradas
    total = memory_db.execute(
        "SELECT COUNT(*) FROM planned_sessions"
    ).fetchone()[0]
    assert total == 2  # las sesiones siguen existiendo
