"""Migración v1 conservadora: piezas independientes, referencias estables y rollback sin datos reales."""

import sqlite3

import pytest

from db import connection


@pytest.fixture
def legacy():
    """Base v1 mínima en memoria con dos equipos homónimos y una sesión vinculada."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE equipment_setups (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, notes TEXT,
            telescope_name TEXT, telescope_aperture_mm REAL, telescope_focal_mm REAL,
            camera_name TEXT, camera_cooled INTEGER, camera_resolution TEXT,
            camera_bit_depth INTEGER, camera_pixel_size_um REAL,
            camera_width_px INTEGER, camera_height_px INTEGER, mount_name TEXT);
        CREATE TABLE planned_sessions (
            id INTEGER PRIMARY KEY, object_id TEXT NOT NULL, session_date TEXT,
            setup_id INTEGER REFERENCES equipment_setups(id), notes TEXT);
        INSERT INTO equipment_setups VALUES
            (1,'Equipo','Notas propias','Óptica',80,400,'Cámara',1,'6000x4000',14,3.9,6000,4000,'Montura'),
            (2,'Equipo','Otras notas','Óptica',100,600,'Cámara',0,'Texto legado',NULL,NULL,NULL,NULL,NULL);
        INSERT INTO planned_sessions VALUES (7,'M31','2026-10-20',1,'Sesión personal');
    """)
    yield conn
    conn.close()


def test_migra_valores_y_vinculos_sin_fundir_homonimos(legacy):
    """Cada equipo obtiene sus propias piezas; nombres compartidos no prueban identidad."""
    connection.init_db(legacy)
    setups = legacy.execute("SELECT * FROM equipment_setups ORDER BY id").fetchall()
    a, b = setups
    assert a["telescope_id"] != b["telescope_id"]
    assert a["camera_id"] != b["camera_id"]
    scope = legacy.execute("SELECT * FROM telescopes WHERE id=?", (a["telescope_id"],)).fetchone()
    assert (scope["name"], scope["aperture_mm"], scope["focal_mm"], scope["optical_type"], scope["reducer"]
            ) == ("Óptica", 80, 400, None, 0)
    camera = legacy.execute("SELECT * FROM cameras WHERE id=?", (a["camera_id"],)).fetchone()
    assert (camera["name"], camera["cooled"], camera["width_px"], camera["height_px"], camera["bit_depth"]
            ) == ("Cámara", 1, 6000, 4000, 14)
    assert camera["pixel_size_um"] == 3.9
    assert (camera["mono"], camera["ampglow"], camera["price_eur"], camera["weight_kg"]) == (0, 0, None, None)
    assert (a["notes"], b["notes"]) == ("Notas propias", "Otras notas")
    assert tuple(legacy.execute("SELECT setup_id,notes FROM planned_sessions WHERE id=7").fetchone()
                 ) == (1, "Sesión personal")
    assert legacy.execute("PRAGMA foreign_key_check").fetchall() == []


def test_conserva_legacy_y_ausencias_sin_inferir_resolucion(legacy):
    """El texto original no se destruye ni se convierte por suposiciones en dimensiones numéricas."""
    connection.init_db(legacy)
    setup = legacy.execute("SELECT * FROM equipment_setups WHERE id=2").fetchone()
    assert setup["camera_resolution"] == "Texto legado"
    assert setup["telescope_name"] == "Óptica"
    camera = legacy.execute("SELECT * FROM cameras WHERE id=?", (setup["camera_id"],)).fetchone()
    assert camera["width_px"] is None and camera["height_px"] is None
    assert camera["bit_depth"] is None and camera["pixel_size_um"] is None
    assert camera["cooled"] == 0
    assert setup["legacy_components_migrated"] == 1


def test_no_reutiliza_piezas_homonimas_ni_pisa_la_guia(legacy):
    """La coincidencia de nombres con el inventario no fusiona piezas ni altera el rol de guía."""
    legacy.executescript(connection.SCHEMA_PATH.read_text(encoding="utf-8"))
    legacy.executescript("""
        INSERT INTO telescopes(id,name,aperture_mm) VALUES (90,'Óptica',999);
        ALTER TABLE equipment_setups ADD COLUMN guide_telescope_id INTEGER REFERENCES telescopes(id);
        UPDATE equipment_setups SET guide_telescope_id=90 WHERE id=1;
    """)
    connection.init_db(legacy)
    row = legacy.execute("SELECT telescope_id,guide_telescope_id FROM equipment_setups WHERE id=1").fetchone()
    assert row[0] != 90 and row[1] == 90
    assert legacy.execute("SELECT aperture_mm FROM telescopes WHERE id=90").fetchone()[0] == 999


def test_reabrir_no_duplica_ni_resucita_pieza_retirada(legacy):
    """La marca de migración impide recrear piezas si después el usuario las borra o desvincula."""
    connection.init_db(legacy)
    snapshot = list(legacy.iterdump())
    connection.init_db(legacy)
    assert list(legacy.iterdump()) == snapshot
    setup = legacy.execute("SELECT * FROM equipment_setups WHERE id=1").fetchone()
    legacy.execute("DELETE FROM cameras WHERE id=?", (setup["camera_id"],))
    legacy.commit()
    assert legacy.execute("SELECT camera_id FROM equipment_setups WHERE id=1").fetchone()[0] is None
    snapshot = list(legacy.iterdump())
    connection.init_db(legacy)
    assert list(legacy.iterdump()) == snapshot


def test_default_no_marcado_no_crea_camara_fantasma(legacy):
    """Un 0 heredado de una casilla sin otros datos no demuestra que exista una cámara."""
    legacy.execute("INSERT INTO equipment_setups(id,name,camera_cooled) VALUES (3,'Vacío',0)")
    legacy.commit()
    connection.init_db(legacy)
    row = legacy.execute("SELECT * FROM equipment_setups WHERE id=3").fetchone()
    assert row["camera_id"] is None and row["telescope_id"] is None and row["mount_id"] is None


def test_pieza_sin_nombre_recibe_etiqueta_de_procedencia_no_caracteristicas(legacy):
    """Una focal conocida sin nombre se conserva como pieza editable con etiqueta explícita de migración."""
    legacy.execute("INSERT INTO equipment_setups(id,name,telescope_focal_mm) VALUES (3,'Parcial',500)")
    legacy.commit()
    connection.init_db(legacy)
    row = legacy.execute("SELECT * FROM telescopes WHERE focal_mm=500").fetchone()
    assert "sin nombre" in row["name"].lower() and "3" in row["name"]
    assert row["aperture_mm"] is None and row["optical_type"] is None


def test_conflicto_no_pisa_pieza_ni_modifica_esquema_o_sesion(legacy):
    """Si hay asignación moderna y datos legacy, no se decide su identidad ni se los fusiona."""
    legacy.executescript("""
        CREATE TABLE telescopes(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        INSERT INTO telescopes VALUES (90,'Pieza actual');
        ALTER TABLE equipment_setups ADD COLUMN telescope_id INTEGER REFERENCES telescopes(id);
        UPDATE equipment_setups SET telescope_id=90 WHERE id=1;
    """)
    before = list(legacy.iterdump())
    with pytest.raises(sqlite3.DatabaseError, match="conflicto"):
        connection.init_db(legacy)
    assert list(legacy.iterdump()) == before


def test_error_tras_insertar_pieza_revierte_migracion_y_esquema(legacy, monkeypatch):
    """DDL y piezas pertenecen a una transacción; un fallo intermedio conserva exactamente la base inicial."""
    before = list(legacy.iterdump())
    migrate = connection._migrate_legacy_equipment

    def fail_after_data(conn):
        """Falla después del traslado para probar rollback, no solo rechazo antes de empezar."""
        migrate(conn)
        raise sqlite3.DatabaseError("fallo intermedio")

    monkeypatch.setattr(connection, "_migrate_legacy_equipment", fail_after_data)
    with pytest.raises(sqlite3.DatabaseError, match="fallo intermedio"):
        connection.init_db(legacy)
    assert list(legacy.iterdump()) == before


@pytest.mark.parametrize("field,value", [("telescope_aperture_mm", -1), ("camera_cooled", 9),
                                        ("camera_width_px", 1.5)])
def test_dato_invalido_no_se_corrige_ni_migra_parcialmente(legacy, field, value):
    """Valores incompatibles se conservan sin sustituirlos ni dejar medio esquema actualizado."""
    legacy.execute(f"UPDATE equipment_setups SET {field}=? WHERE id=1", (value,))
    legacy.commit()
    before = list(legacy.iterdump())
    with pytest.raises(sqlite3.DatabaseError, match="Datos de equipo v1 inválidos"):
        connection.init_db(legacy)
    assert list(legacy.iterdump()) == before


def test_casilla_ausente_se_migra_como_no_segun_acuerdo(legacy):
    """No introduce tres estados: una característica no marcada conserva la semántica binaria actual."""
    legacy.execute("UPDATE equipment_setups SET camera_cooled=NULL WHERE id=1")
    legacy.commit()
    connection.init_db(legacy)
    assert legacy.execute("SELECT cooled,mono,ampglow FROM cameras ORDER BY id").fetchone()[:] == (0, 0, 0)


def test_migracion_persiste_al_reabrir_fichero_sin_tocar_origen(legacy, tmp_path):
    """La conservación e idempotencia sobreviven a otra conexión, no solo al estado en memoria."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    try:
        legacy.backup(conn)
        connection.init_db(conn)
        before = list(conn.iterdump())
    finally:
        conn.close()
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        connection.init_db(conn)
        assert list(conn.iterdump()) == before
    finally:
        conn.close()
    assert legacy.execute("SELECT telescope_name FROM equipment_setups WHERE id=1").fetchone()[0] == "Óptica"
    assert "telescope_id" not in {row[1] for row in legacy.execute("PRAGMA table_info(equipment_setups)")}


def test_migracion_no_confirma_por_su_cuenta_transaccion_del_llamante(legacy):
    """Un savepoint no confirma ni descarta trabajo previo del llamante al aplicar el esquema."""
    before = list(legacy.iterdump())
    legacy.execute("UPDATE equipment_setups SET notes='Edición pendiente' WHERE id=1")
    connection.init_db(legacy)
    assert legacy.in_transaction
    assert legacy.execute("SELECT notes FROM equipment_setups WHERE id=1").fetchone()[0] == "Edición pendiente"
    legacy.rollback()
    assert list(legacy.iterdump()) == before


def test_fallo_de_migracion_no_publica_conexion_y_conserva_datos_en_fichero(legacy, tmp_path, monkeypatch):
    """Un arranque fallido conserva datos/esquema en disco, sin exigir bytes idénticos al contador SQLite."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    legacy.backup(conn)
    before = list(conn.iterdump())
    conn.close()
    monkeypatch.setattr(connection, "_connection", None)
    monkeypatch.setattr(connection, "DATA_DIR", tmp_path)
    monkeypatch.setattr(connection, "DB_PATH", path)
    migrate = connection._migrate_legacy_equipment

    def fail_after_data(conn):
        """Simula fallo del arranque tras trasladar valores dentro de la transacción."""
        migrate(conn)
        raise sqlite3.DatabaseError("fallo intermedio")

    monkeypatch.setattr(connection, "_migrate_legacy_equipment", fail_after_data)
    with pytest.raises(sqlite3.DatabaseError, match="fallo intermedio"):
        connection.get_connection()
    assert connection._connection is None
    conn = sqlite3.connect(path)
    try:
        assert list(conn.iterdump()) == before
    finally:
        conn.close()
