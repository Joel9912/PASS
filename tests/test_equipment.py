"""Tests de equipo: modelos, CRUD de la Equipo v2, lecturas y anotaciones.

Cubren los hallazgos C-1 (datos de FOV de la cámara), C-2 y M-16 (contrato
dict), M-17 (``list_setups()`` con `location_name`), M-20
(``count_sessions()``), D-8 (fixture ``memory_db`` con FK activas) y el plan
de la pestaña Equipo: migraciones de esquema, CRUD de componentes, claves
FOV, imágenes por entidad, sitio de las ubicaciones, validaciones y
categorías.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from equipment.models import (
    CATEGORIES,
    DIRECTIONS,
    Camera,
    EquipmentSetup,
    Filter,
    Location,
    Mount,
    Telescope,
)
from equipment.validaciones import (
    validar_camara,
    validar_filtro,
    validar_montura,
    validar_setup,
    validar_telescopio,
    validar_ubicacion,
)


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


def test_migra_precio_y_peso_de_las_piezas(memory_db):
    """Las 4 tablas de piezas reciben precio/peso al abrir una base antigua.

    La cabecera del equipo suma esos campos en vivo; si solo estuvieran en
    ``schema.sql``, una base fresca los tendría y una creada antes, no
    (por eso la entrada en ``_MIGRATIONS`` es obligatoria). Los filtros
    llevan solo precio: su peso no suma en los totales.
    """
    from db import connection as db_conn

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for tabla in ("telescopes", "cameras", "mounts", "filters"):
        conn.execute(
            f"CREATE TABLE {tabla} ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name TEXT NOT NULL)"
        )

    db_conn.init_db(conn)  # schema (IF NOT EXISTS → no toca las tablas) + migración

    for tabla in ("telescopes", "cameras", "mounts", "filters"):
        columnas = {row[1] for row in conn.execute(f"PRAGMA table_info({tabla})")}
        frescas = {row[1] for row in memory_db.execute(f"PRAGMA table_info({tabla})")}
        assert "price_eur" in columnas and "price_eur" in frescas
        if tabla != "filters":
            assert "weight_kg" in columnas and "weight_kg" in frescas
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


def test_migracion_no_descarta_datos_embebidos_de_equipo_v1():
    """Una BD v1 con datos debe rechazarse sin perder las piezas embebidas."""
    from db import connection as db_conn

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE equipment_setups (id INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL, telescope_name TEXT)"
    )
    conn.execute(
        "INSERT INTO equipment_setups (name, telescope_name) VALUES (?, ?)",
        ("Equipo antiguo", "Telescopio propio"),
    )
    with pytest.raises(sqlite3.DatabaseError, match="datos de equipo"):
        db_conn.init_db(conn)
    assert conn.execute(
        "SELECT telescope_name FROM equipment_setups WHERE name = ?",
        ("Equipo antiguo",),
    ).fetchone()[0] == "Telescopio propio"
    conn.close()


def test_migra_el_sitio_de_las_ubicaciones(memory_db):
    """Una base antigua recibe las columnas de sitio (y el seeing)."""
    from db import connection as db_conn

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE locations (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL)"
    )

    db_conn.init_db(conn)

    sitio = {"obstacles", "lp", "bortle", "sqm", "seeing_arcsec", "consider_lp"}
    columnas = {row[1] for row in conn.execute("PRAGMA table_info(locations)")}
    assert sitio <= columnas
    frescas = {row[1] for row in memory_db.execute("PRAGMA table_info(locations)")}
    assert sitio <= frescas  # la fresca las trae directas del esquema
    conn.close()


def test_attach_copia_la_imagen_a_data(memory_db, monkeypatch, tmp_path):
    """D-1: `_attach()` copia a `data/equipment_images/<entidad>/<id>/`.

    Antes se persistía la ruta absoluta del `QFileDialog`: si el usuario
    movía o borraba el original, la imagen adjunta se perdía. El layout es
    uniforme por entidad (Equipo v2) y una entidad desconocida no llega ni
    a tocar el SQL.
    """
    from equipment import images

    memory_db.execute("INSERT INTO equipment_setups (name) VALUES (?)", ("ASI2600",))
    memory_db.commit()
    monkeypatch.setattr(images, "IMAGES_ROOT", tmp_path / "equipment_images")

    original = tmp_path / "originales" / "spot.png"
    original.parent.mkdir()
    original.write_bytes(b"contenido de prueba")

    images._attach("setup", 1, str(original), "spot")

    guardada = Path(images.list_images("setup", 1)[0]["path"])
    assert guardada != original                     # la ruta guardada es la copia
    assert guardada.parent == tmp_path / "equipment_images" / "setup" / "1"
    assert guardada.read_bytes() == b"contenido de prueba"

    # Re-adjuntar el mismo original: ya está copiado, no revienta
    images._attach("setup", 1, str(original), "spot")
    assert len(images.list_images("setup", 1)) == 2

    # Original perdido: se persiste la ruta tal cual en vez de fallar
    fantasma = tmp_path / "borrado.png"
    images._attach("setup", 1, str(fantasma), "otra")
    assert images.list_images("setup", 1)[2]["path"] == str(fantasma)

    # Entidad fuera del mapa cerrado: ValueError, nunca SQL dinámico suelto
    with pytest.raises(ValueError, match="Entidad"):
        images._attach("banana", 1, str(original))


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
    0 — por eso hay que avisar *antes* (la UI usa ``count_sessions``). Aquí el
    borrado se hace con SQL directo para no arrastrar el resto de efectos de
    ``manager.delete`` (imágenes, filtros).
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


def _ubicacion(**kwargs) -> Location:
    """Ubicación válida de fábrica: sitio completo de las 8 direcciones.

    ``kwargs`` pisa los valores por defecto (nombre, bortle, imagen de CL…),
    así que los casos de validación solo describen lo que quieren provocar.
    """
    datos = dict(
        name="Casa",
        latitude=40.4,
        longitude=-3.7,
        bortle=3,
        obstacles={d: 0 for d in DIRECTIONS},
        lp={d: {"fuente": None, "km": 0.0} for d in DIRECTIONS},
    )
    datos.update(kwargs)
    return Location(**datos)


#: (objeto inválido, validador, fragmento del mensaje): la tabla de reglas
#: del plan (paso 1) convertida en casos — una fila por regla.
_CASOS_INVALIDOS = [
    # Ubicación
    (Location(name="  "), validar_ubicacion, "nombre"),
    (Location(name="X", latitude=91), validar_ubicacion, "Latitud"),
    (Location(name="X", longitude=200), validar_ubicacion, "Longitud"),
    (Location(name="X", utc_offset_hours=15), validar_ubicacion, "Desfase"),
    (_ubicacion(bortle=None), validar_ubicacion, "Bortle"),
    (_ubicacion(bortle=0), validar_ubicacion, "Bortle"),
    (_ubicacion(bortle=10), validar_ubicacion, "Bortle"),
    (_ubicacion(sqm=-1), validar_ubicacion, "SQM"),
    (_ubicacion(seeing_arcsec=-1), validar_ubicacion, "seeing"),
    (_ubicacion(obstacles={}), validar_ubicacion, "8 direcciones"),
    (
        _ubicacion(obstacles={d: (99 if d == "N" else 0) for d in DIRECTIONS}),
        validar_ubicacion,
        "obstáculo",
    ),
    (
        _ubicacion(obstacles={d: (["alien"] if d == "N" else 0) for d in DIRECTIONS}),
        validar_ubicacion,
        "obstáculo",
    ),
    (_ubicacion(lp={}), validar_ubicacion, "contaminación"),
    (
        _ubicacion(lp={d: (5 if d == "N" else {"fuente": None, "km": 0.0})
                   for d in DIRECTIONS}),
        validar_ubicacion,
        "mal formada",
    ),
    (
        _ubicacion(lp={d: ({"fuente": "alien", "km": 5.0} if d == "N"
                       else {"fuente": None, "km": 0.0})
                   for d in DIRECTIONS}),
        validar_ubicacion,
        "Fuente",
    ),
    (
        _ubicacion(lp={d: ({"fuente": "pueblo", "km": 0} if d == "N"
                       else {"fuente": None, "km": 0.0})
                   for d in DIRECTIONS}),
        validar_ubicacion,
        "mayores que 0",
    ),
    # Telescopio
    (Telescope(name=""), validar_telescopio, "nombre"),
    (Telescope(name="X", aperture_mm=-1), validar_telescopio, "apertura"),
    (Telescope(name="X", focal_mm=-1), validar_telescopio, "focal"),
    (Telescope(name="X", reducer=True, reducer_factor=0), validar_telescopio, "reductor"),
    (Telescope(name="X", optical_type="aberración"), validar_telescopio, "óptica"),
    (Telescope(name="X", price_eur=-1), validar_telescopio, "precio"),
    (Telescope(name="X", weight_kg=-1), validar_telescopio, "peso"),
    # Cámara
    (Camera(name=""), validar_camara, "nombre"),
    (Camera(name="X", pixel_size_um=-1), validar_camara, "píxel"),
    (Camera(name="X", width_px=-1), validar_camara, "ancho"),
    (Camera(name="X", height_px=-1), validar_camara, "alto"),
    (Camera(name="X", bit_depth=0), validar_camara, "bits"),
    (Camera(name="X", bit_depth=11), validar_camara, "bits"),  # fuera de BIT_DEPTHS
    (Camera(name="X", price_eur=-1), validar_camara, "precio"),
    (Camera(name="X", weight_kg=-1), validar_camara, "peso"),
    # Montura
    (Mount(name=""), validar_montura, "nombre"),
    (Mount(name="X", payload_kg=-1), validar_montura, "capacidad"),
    (Mount(name="X", mount_type="voladora"), validar_montura, "montura"),
    (Mount(name="X", price_eur=-1), validar_montura, "precio"),
    (Mount(name="X", weight_kg=-1), validar_montura, "peso"),
    # Filtro
    (Filter(name=""), validar_filtro, "nombre"),
    (Filter(name="X", filter_type="magenta"), validar_filtro, "filtro"),
    (Filter(name="X", price_eur=-1), validar_filtro, "precio"),
    # Setup
    (EquipmentSetup(name=""), validar_setup, "nombre"),
    (EquipmentSetup(name="X", category="nebulosas"), validar_setup, "Categoría"),
]


@pytest.mark.parametrize("objeto, validador, mensaje", _CASOS_INVALIDOS)
def test_validaciones_de_equipo(objeto, validador, mensaje):
    """Cada regla de la tabla del plan lanza ``ValueError`` con su mensaje."""
    with pytest.raises(ValueError, match=mensaje):
        validador(objeto)


def test_actualizar_sin_id_es_error(memory_db):
    """Sin id no se actualiza nada: el orden es create → update."""
    from equipment import components, localizations, manager

    with pytest.raises(ValueError, match="falta el id"):
        manager.update(EquipmentSetup(name="X"))
    with pytest.raises(ValueError, match="falta el id"):
        components.update_telescope(Telescope(name="X"))
    with pytest.raises(ValueError, match="falta el id"):
        components.update_camera(Camera(name="X"))
    with pytest.raises(ValueError, match="falta el id"):
        components.update_mount(Mount(name="X"))
    with pytest.raises(ValueError, match="falta el id"):
        components.update_filter(Filter(name="X"))
    with pytest.raises(ValueError, match="falta el id"):
        localizations.update(_ubicacion())


def test_crud_de_las_cuatro_piezas(memory_db):
    """CRUD completo de componentes: alta, lectura como dict, edición y baja."""
    from equipment import components

    telescopio = Telescope(
        name="Refractor 72",
        aperture_mm=72,
        focal_mm=420,
        optical_type="refractor",
        subtype="Doblete",
        price_eur=650,
        weight_kg=2.7,
    )
    tid = components.create_telescope(telescopio)
    assert telescopio.id == tid
    assert components.get_telescope(tid)["focal_mm"] == pytest.approx(420)
    assert components.get_telescope(tid)["price_eur"] == pytest.approx(650)
    assert components.get_telescope(tid)["weight_kg"] == pytest.approx(2.7)

    telescopio.focal_mm = 490
    telescopio.price_eur = 599
    components.update_telescope(telescopio)
    assert components.get_telescope(tid)["focal_mm"] == pytest.approx(490)
    assert components.get_telescope(tid)["price_eur"] == pytest.approx(599)
    assert isinstance(components.list_telescopes()[0], dict)  # contrato C-2

    camara = Camera(
        name="ASI2600",
        cooled=True,
        pixel_size_um=3.76,
        width_px=6248,
        height_px=4176,
        bit_depth=16,
        price_eur=1550,
        weight_kg=0.7,
    )
    cid = components.create_camera(camara)
    assert components.get_camera(cid)["cooled"] == 1  # bool → 0/1 en la fila
    assert components.get_camera(cid)["price_eur"] == pytest.approx(1550)
    assert components.get_camera(cid)["weight_kg"] == pytest.approx(0.7)

    montura = Mount(
        name="AM5", mount_type="armonica", payload_kg=20, price_eur=2100, weight_kg=5.5
    )
    mid = components.create_mount(montura)
    assert components.get_mount(mid)["payload_kg"] == pytest.approx(20)
    assert components.get_mount(mid)["price_eur"] == pytest.approx(2100)
    assert components.get_mount(mid)["weight_kg"] == pytest.approx(5.5)

    filtro = Filter(name="UHC", filter_type="uhc", price_eur=45)
    fid = components.create_filter(filtro)
    assert components.get_filter(fid)["filter_type"] == "uhc"
    assert components.get_filter(fid)["price_eur"] == pytest.approx(45)
    assert "weight_kg" not in components.get_filter(fid)  # los filtros no pesan

    components.delete_filter(fid)
    components.delete_mount(mid)
    components.delete_camera(cid)
    components.delete_telescope(tid)
    assert components.list_telescopes() == []
    assert components.list_cameras() == []
    assert components.list_mounts() == []
    assert components.list_filters() == []
    assert components.get_telescope(tid) is None


def test_setups_con_referencias_exponen_las_claves_del_fov(memory_db):
    """El dict trae el contrato de claves de `calculate_fov` (C-1 en la v2)."""
    from equipment import components, manager

    tid = components.create_telescope(Telescope(name="ED80", aperture_mm=80, focal_mm=400))
    cid = components.create_camera(
        Camera(name="ASI533", pixel_size_um=3.76, width_px=3008, height_px=3008)
    )
    setup_id = manager.create(
        EquipmentSetup(name="Rápido", category="paisaje", telescope_id=tid, camera_id=cid)
    )

    fila = manager.get(setup_id)
    assert fila["telescope_focal_mm"] == pytest.approx(400)
    assert fila["camera_pixel_size_um"] == pytest.approx(3.76)
    assert fila["camera_width_px"] == 3008
    assert fila["camera_height_px"] == 3008
    assert manager.list_setups()[0]["camera_pixel_size_um"] == pytest.approx(3.76)

    # Sin piezas: las claves siguen ahí con None (LEFT JOIN, contrato .get())
    pelon = manager.get(manager.create(EquipmentSetup(name="Pelón")))
    assert pelon["telescope_focal_mm"] is None
    assert pelon["camera_width_px"] is None


def test_fov_con_reductor_usa_la_focal_efectiva(memory_db):
    """El alias de FOV trae la focal efectiva: FOV correcto sin tocar `planners/`."""
    from equipment import components, manager
    from planners.framing import calculate_fov

    tid = components.create_telescope(
        Telescope(
            name="Newton 200",
            aperture_mm=200,
            focal_mm=1000,
            reducer=True,
            reducer_factor=0.8,
        )
    )
    cid = components.create_camera(
        Camera(name="ASI2600", pixel_size_um=3.76, width_px=6248, height_px=4176)
    )
    setup_id = manager.create(
        EquipmentSetup(name="Reducido", telescope_id=tid, camera_id=cid)
    )

    fila = manager.get(setup_id)
    assert fila["telescope_focal_mm"] == pytest.approx(800)  # 1000 × 0.8

    con_reductor = calculate_fov(fila)
    sin_reductor = calculate_fov({**fila, "telescope_focal_mm": 1000.0})
    assert con_reductor is not None
    # Menor focal ⇒ campo más amplio: si el dict llevara la focal nominal,
    # el FOV saldría estrecho y esta comparación no distinguiría los casos.
    assert con_reductor[0] > sin_reductor[0]


def test_borrar_componentes_desvincula_y_el_conteo_avisa(memory_db):
    """SET NULL + ``count_setups_using``: el número previo a la confirmación."""
    from equipment import components, localizations, manager

    t_principal = components.create_telescope(Telescope(name="Principal", focal_mm=400))
    t_guia = components.create_telescope(Telescope(name="Guía", focal_mm=200))
    camara = components.create_camera(Camera(name="ASI2600", pixel_size_um=3.76))
    montura = components.create_mount(Mount(name="AM5"))
    filtro = components.create_filter(Filter(name="UHC"))
    sitio = localizations.create(_ubicacion())
    setup_id = manager.create(
        EquipmentSetup(
            name="Completo",
            location_id=sitio,
            telescope_id=t_principal,
            guide_telescope_id=t_guia,
            camera_id=camara,
            mount_id=montura,
            filter_ids=[filtro],
        )
    )

    assert manager.count_setups_using("telescope", t_principal) == 1
    assert manager.count_setups_using("telescope", t_guia) == 1
    assert manager.count_setups_using("camera", camara) == 1
    assert manager.count_setups_using("mount", montura) == 1
    assert manager.count_setups_using("filter", filtro) == 1
    assert manager.count_setups_using("location", sitio) == 1
    with pytest.raises(ValueError, match="desconocido"):
        manager.count_setups_using("banana", 1)

    components.delete_telescope(t_principal)
    components.delete_camera(camara)
    components.delete_mount(montura)
    components.delete_filter(filtro)
    localizations.delete(sitio)

    fila = manager.get(setup_id)
    assert fila["telescope_id"] is None          # SET NULL en cualquier rol
    assert fila["guide_telescope_id"] == t_guia  # la de guía no se tocó
    assert fila["camera_id"] is None
    assert fila["mount_id"] is None
    assert fila["location_id"] is None
    assert manager.count_setups_using("telescope", t_principal) == 0
    assert manager.count_setups_using("camera", camara) == 0
    assert manager.count_setups_using("filter", filtro) == 0


def test_setup_filters_asignacion_y_cascada(memory_db):
    """M2M: la lista es la verdad al guardar y el borrado limpia las filas."""
    from equipment import components, manager

    def asignados(setup_id: int) -> list[int]:
        """Filtros asignados a ``setup_id`` en la tabla intermedia, ordenados."""
        filas = memory_db.execute(
            "SELECT filter_id FROM setup_filters WHERE setup_id = ?", (setup_id,)
        ).fetchall()
        return sorted(row[0] for row in filas)

    uhc = components.create_filter(Filter(name="UHC", filter_type="uhc"))
    cpl = components.create_filter(Filter(name="CPL", filter_type="cpl"))
    setup = EquipmentSetup(name="Con filtros", filter_ids=[uhc, cpl])
    setup_id = manager.create(setup)
    assert asignados(setup_id) == sorted([uhc, cpl])
    # get() carga la asignación completa (la necesita el formulario de edición)
    assert manager.get(setup_id)["filter_ids"] == sorted([uhc, cpl])

    setup.filter_ids = [uhc]  # quito uno al guardar → diff por conjunto
    manager.update(setup)
    assert asignados(setup_id) == [uhc]

    # Borrar el filtro borra sus asignaciones (FK en cascada)
    components.delete_filter(uhc)
    assert memory_db.execute("SELECT COUNT(*) FROM setup_filters").fetchone()[0] == 0


def test_borrar_setup_limpia_filtros_e_imagenes(memory_db, monkeypatch, tmp_path):
    """DELETE del setup: filas de filtros e imágenes en cascada, ficheros purgados."""
    from equipment import components, images, manager

    monkeypatch.setattr(images, "IMAGES_ROOT", tmp_path / "equipment_images")
    original = tmp_path / "spot.png"
    original.write_bytes(b"foto")

    filtro = components.create_filter(Filter(name="UHC"))
    setup = EquipmentSetup(name="Borrable", filter_ids=[filtro], images=[str(original)])
    setup_id = manager.create(setup)
    assert images.list_images("setup", setup_id)  # adjuntada en el create

    manager.delete(setup_id)

    assert images.list_images("setup", setup_id) == []  # FK cascade
    assert not (tmp_path / "equipment_images" / "setup" / str(setup_id)).exists()
    assert memory_db.execute("SELECT COUNT(*) FROM setup_filters").fetchone()[0] == 0


def test_ubicaciones_roundtrip_del_sitio(memory_db):
    """El sitio viaja a JSON con las 8 direcciones y vuelve parseado."""
    from equipment import localizations

    obstaculos = {d: 0 for d in DIRECTIONS}
    obstaculos["N"] = 45
    obstaculos["E"] = 15
    fuentes = {d: {"fuente": None, "km": 0.0} for d in DIRECTIONS}
    fuentes["S"] = {"fuente": "gran_ciudad", "km": 25.0}
    fuentes["NE"] = {"fuente": "pueblo", "km": 5.0}

    ubicacion = _ubicacion(
        altitude_m=650,
        utc_offset_hours=2,
        bortle=4,
        sqm=21.2,
        consider_lp=False,
        obstacles=obstaculos,
        lp=fuentes,
    )
    pk = localizations.create(ubicacion)

    fila = localizations.list_locations()[0]
    assert fila["obstacles"] == obstaculos
    assert fila["lp"] == fuentes
    assert fila["bortle"] == 4
    assert fila["sqm"] == pytest.approx(21.2)
    assert fila["consider_lp"] == 0  # crudo 0/1, como en el resto de dicts
    assert set(fila["lp"]) == set(DIRECTIONS)  # siempre las 8

    ubicacion.id = pk
    ubicacion.bortle = 2
    localizations.update(ubicacion)
    assert localizations.list_locations()[0]["bortle"] == 2

    # Fila corrupta (JSON roto): nunca revienta al listar, vuelve al defecto
    memory_db.execute(
        "UPDATE locations SET obstacles = 'no-es-json' WHERE id = ?", (pk,)
    )
    memory_db.commit()
    fila = localizations.list_locations()[0]
    assert fila["obstacles"] == {d: 0 for d in DIRECTIONS}

    # Formato viejo (tipos de obstáculo y niveles 0-3) → defectos, sin error
    memory_db.execute(
        "UPDATE locations SET obstacles = ?, lp = ? WHERE id = ?",
        ('{"N": ["arboles"], "E": ["edificios"]}', '{"S": 3, "NE": 1}', pk),
    )
    memory_db.commit()
    fila = localizations.list_locations()[0]
    assert fila["obstacles"] == {d: 0 for d in DIRECTIONS}
    assert fila["lp"] == {d: {"fuente": None, "km": 0.0} for d in DIRECTIONS}


def test_imagenes_por_entidad_sync_y_purge(memory_db, monkeypatch, tmp_path):
    """API generalizada: kinds por defecto, sync D-5, purge y cascada de filas."""
    from equipment import components, images, localizations

    monkeypatch.setattr(images, "IMAGES_ROOT", tmp_path / "equipment_images")
    tid = components.create_telescope(Telescope(name="ED80"))
    cid = components.create_camera(Camera(name="ASI533"))

    originales = tmp_path / "originales"
    originales.mkdir()
    chart = originales / "chart.png"
    chart.write_bytes(b"chart")
    ganancia = originales / "ganancia.png"
    ganancia.write_bytes(b"gain")

    # kind por defecto por entidad y layout uniforme
    images._attach("telescope", tid, str(chart))
    images._attach("camera", cid, str(ganancia))
    assert images.list_images("telescope", tid)[0]["kind"] == "chart"
    assert images.list_images("camera", cid)[0]["kind"] == "ganancia"
    copia = Path(images.list_images("telescope", tid)[0]["path"])
    assert copia.parent == tmp_path / "equipment_images" / "telescope" / str(tid)

    # sync (D-5): partir de list_images + orígenes nuevos; vaciar, vacía
    otra = originales / "otra.png"
    otra.write_bytes(b"x")
    images.sync("telescope", tid, [copia, str(otra)])
    assert len(images.list_images("telescope", tid)) == 2
    images.sync("telescope", tid, [])
    assert images.list_images("telescope", tid) == []
    assert not copia.exists()  # la copia propia se fue con el remove

    # purge: al borrar el padre no quedan ficheros huérfanos (D-1)
    images._attach("telescope", tid, str(chart))
    carpeta = tmp_path / "equipment_images" / "telescope" / str(tid)
    assert carpeta.exists()
    components.delete_telescope(tid)
    assert not carpeta.exists()
    assert images.list_images("telescope", tid) == []  # filas en cascada (FK)

    # Ubicación: imagen única de CL; al guardar, una sustituye y None borra
    pk = localizations.create(_ubicacion(lp_map=str(chart)))
    assert images.list_images("location", pk)[0]["kind"] == "mapa_lp"
    localizations.update(_ubicacion(id=pk, lp_map=None))
    assert images.list_images("location", pk) == []


def test_categorias_del_enum_del_usuario(memory_db):
    """Las 6 categorías aprobadas, con etiqueta y default ``general``."""
    from equipment import manager

    assert list(CATEGORIES) == [
        "paisaje",
        "campo_amplio",
        "espacio_profundo",
        "espacio_profundo_largo",
        "planetario",
        "general",
    ]
    assert all(label for label in CATEGORIES.values())
    assert EquipmentSetup().category == "general"
    pk = manager.create(EquipmentSetup(name="Nuevo"))
    assert manager.get(pk)["category"] == "general"


def test_subtipos_de_optica_por_tipo():
    """La taxonomía de subtipos es exactamente la del usuario (combo cerrado).

    Refractor ×5 (el Sextuplete quedó fuera), Reflector ×2 y
    Catadióptrico ×4; el campo deja de ser texto libre, así que las listas
    son el catálogo completo y nada más.
    """
    from equipment.models import SUBTYPE_SUGGESTIONS

    assert SUBTYPE_SUGGESTIONS["refractor"] == (
        "Acromático",
        "Doblete (ED)",
        "Triplete Apocromático",
        "Quad (FF)",
        "Petzval",
    )
    assert SUBTYPE_SUGGESTIONS["reflector"] == ("Newtoniano", "Ritchey-Chrétien (RC)")
    assert SUBTYPE_SUGGESTIONS["catadioptrico"] == (
        "Schmidt-Cassegrain (SCT)",
        "Maksutov-Cassegrain (Mak)",
        "Maksutov-Newtonian",
        "Schmidt-Newtonian",
    )
    assert SUBTYPE_SUGGESTIONS["otro"] == ()
    assert "Sextuplete" not in SUBTYPE_SUGGESTIONS["refractor"]
