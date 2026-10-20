"""Identidades persistentes sin fusiones implícitas ni lecturas de datos personales."""

import sqlite3

import pytest

from db.catalog_identity import (
    add_designation,
    identify,
    identity_registry,
    link_personal_references,
    resolve_designation,
)


def test_identidad_sobrevive_orden_nombres_y_reapertura(tmp_path):
    """Las claves no se recalculan por nombre principal, posición de exportación ni número de edición."""
    path = tmp_path / "identidades.sqlite"
    with identity_registry(path) as conn:
        first = identify(conn, "VII/220A", "B 131a")
        second = identify(conn, "VII/220A", "B 131b")
        add_designation(conn, first, "barnard", "B 131a")
        add_designation(conn, first, "nombre", "Nombre antiguo")
    with identity_registry(path) as conn:
        assert identify(conn, "VII/220A", "B 131b") == second
        assert identify(conn, "VII/220A", "B 131a") == first
        add_designation(conn, first, "nombre", "Nombre nuevo")
        assert resolve_designation(conn, "nombre", "Nombre antiguo") == first
        assert resolve_designation(conn, "nombre", "Nombre nuevo") == first
        assert first != second


def test_misma_designacion_no_fusiona_subregiones(tmp_path):
    """Un cruce compartido no acredita identidad uno a uno entre nubes de dos fuentes."""
    with identity_registry(tmp_path / "identidades.sqlite") as conn:
        first = identify(conn, "fuente A", "registro A")
        second = identify(conn, "fuente B", "registro B")
        add_designation(conn, first, "ldn", "LDN 1")
        add_designation(conn, second, "ldn", "LDN 1")
        assert first != second
        assert resolve_designation(conn, "ldn", "LDN 1") is None
        assert resolve_designation(conn, "ldn", "LDN ausente") is None


def test_cruce_explicito_y_conflicto_sin_sobrescritura(tmp_path):
    """Solo evidencia de cruce suministrada al preparador une fuentes; una contradicción no reasigna IDs."""
    with identity_registry(tmp_path / "identidades.sqlite") as conn:
        first = identify(conn, "OpenNGC", "NGC0224")
        assert identify(conn, "Messier", "31", same_as=first) == first
        other = identify(conn, "Otra fuente", "registro independiente")
        with pytest.raises(ValueError, match="contradice"):
            identify(conn, "Messier", "31", same_as=other)
        assert identify(conn, "Messier", "31") == first
        with pytest.raises(ValueError, match="inexistente"):
            identify(conn, "Fuente", "nuevo", same_as="PASS-inventado")


def test_sin_designacion_se_conserva_clave_original_sin_inventar_numero_ldn(tmp_path):
    """Un registro sin designación pública conserva identidad de fuente, no un nombre astronómico ficticio."""
    with identity_registry(tmp_path / "identidades.sqlite") as conn:
        key = "identificador literal aportado por la fuente"
        pass_id = identify(conn, "fuente sintética", key)
        assert identify(conn, "fuente sintética", key) == pass_id
        assert conn.execute("SELECT count(*) FROM designations").fetchone()[0] == 0


def test_error_de_lote_revierte_identidades_y_alias(tmp_path):
    """Un preparador fallido no confirma media tabla de cruces."""
    path = tmp_path / "identidades.sqlite"
    with identity_registry(path) as conn:
        first = identify(conn, "Fuente", "original")
    with pytest.raises(ValueError), identity_registry(path) as conn:
        second = identify(conn, "Fuente", "nuevo")
        add_designation(conn, second, "nombre", "Nuevo")
        raise ValueError("Fallo sintético del lote")
    with identity_registry(path) as conn:
        assert identify(conn, "Fuente", "original") == first
        assert conn.execute("SELECT count(*) FROM objects").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM designations").fetchone()[0] == 0


@pytest.mark.parametrize("key", [None, "", "  ", " nombre", "nombre ", "a\x00b", 1])
def test_claves_ausentes_o_normalizadas_silenciosamente_se_rechazan(tmp_path, key):
    """No sustituye una clave ilegible por número de fila ni recorta sufijos o espacios originales."""
    with identity_registry(tmp_path / "identidades.sqlite") as conn:
        with pytest.raises(ValueError):
            identify(conn, "Fuente", key)
        assert conn.execute("SELECT count(*) FROM objects").fetchone()[0] == 0


def test_registro_no_acepta_base_ajena_ni_nombre_personal(tmp_path):
    """La ruta explícita no autoriza añadir tablas del preparador a una base de usuario."""
    path = tmp_path / "ajena.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE equipo(nota TEXT)")
        conn.execute("INSERT INTO equipo VALUES ('personal sintético')")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="no es un registro"), identity_registry(path):
        pytest.fail("No debe abrir una base ajena")
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="independiente"), identity_registry(tmp_path / "pass.db"):
        pytest.fail("No debe aceptar el nombre de la base personal")
    assert not (tmp_path / "pass.db").exists()


def test_version_futura_no_se_migra_ni_modifica(tmp_path):
    """Un registro de una herramienta más nueva se conserva para recuperación manual."""
    path = tmp_path / "identidades.sqlite"
    with identity_registry(path):
        pass
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE identity_schema SET version=999")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Versión"), identity_registry(path):
        pytest.fail("No debe convertir formatos futuros")
    assert path.read_bytes() == before


def test_primer_lote_fallido_no_deja_esquema_incompleto(tmp_path):
    """También la creación del registro es transaccional; reintentar no exige borrar el fichero."""
    path = tmp_path / "identidades.sqlite"
    with pytest.raises(ValueError), identity_registry(path) as conn:
        identify(conn, "Fuente", "nuevo")
        raise ValueError("Fallo sintético")
    with identity_registry(path) as conn:
        assert conn.execute("SELECT count(*) FROM objects").fetchone()[0] == 0


def test_vinculos_aditivos_preservan_sesiones_y_regiones(memory_db, tmp_path):
    """Resolver identidades no normaliza coordenadas, borra ambigüedades ni fusiona sesiones repetidas."""
    memory_db.execute("INSERT INTO personal_catalog(object_id,catalog,notes,ra_hours,dec_deg) "
                      "VALUES ('M31','messier','Notas propias',1,20)")
    memory_db.execute("INSERT INTO personal_catalog(object_id,catalog) VALUES ('Alias ambiguo','ldn')")
    memory_db.execute("INSERT INTO personal_catalog(object_id,catalog,kind,ra_hours,dec_deg) "
                      "VALUES ('Mi región','region','region',2,30)")
    for _ in range(2):
        memory_db.execute("INSERT INTO planned_sessions(object_id,session_date,ra_hours,notes) "
                          "VALUES ('M31','2026-10-20',3,'Encuadre propio')")
    memory_db.commit()
    before = [tuple(row) for row in memory_db.execute("SELECT * FROM planned_sessions")]
    with identity_registry(tmp_path / "identidades.sqlite") as registry:
        first = identify(registry, "OpenNGC", "NGC0224")
        add_designation(registry, first, "messier", "M31")
        add_designation(registry, first, "ldn", "Alias ambiguo")
        other = identify(registry, "Otra fuente", "Otro")
        add_designation(registry, other, "ldn", "Alias ambiguo")
        counts = link_personal_references(memory_db, registry)
        assert counts == {"linked": 3, "unresolved": 1, "preserved": 0, "regions": 1}
        assert memory_db.execute("SELECT pass_object_id FROM personal_catalog WHERE object_id='M31'").fetchone()[0] == first
        after = [tuple(row) for row in memory_db.execute("SELECT * FROM planned_sessions")]
        columns = [item[1] for item in memory_db.execute("PRAGMA table_info(planned_sessions)")]
        index = columns.index("pass_object_id")
        assert len(after) == len(before) == 2
        assert [row[:index]+row[index+1:] for row in after] == [row[:index]+row[index+1:] for row in before]
        assert {row[index] for row in after} == {first}
        counts = link_personal_references(memory_db, registry)
        assert counts == {"linked": 0, "unresolved": 1, "preserved": 3, "regions": 1}
        assert memory_db.execute("SELECT notes,ra_hours,dec_deg FROM personal_catalog WHERE object_id='M31'").fetchone()[:] == ("Notas propias", 1, 20)


def test_fallo_y_transaccion_ajena_conservan_control_y_vinculos(memory_db, tmp_path):
    """Un fallo posterior revierte todos los vínculos y nunca confirma trabajo ajeno."""
    memory_db.execute("INSERT INTO personal_catalog(object_id,catalog) VALUES ('M31','messier')")
    memory_db.execute("INSERT INTO planned_sessions(object_id,session_date) VALUES ('M31','2026-10-20')")
    memory_db.commit()
    memory_db.execute("INSERT INTO settings VALUES ('trabajo_ajeno','no confirmado')")
    with identity_registry(tmp_path / "identidades.sqlite") as registry:
        pass_id = identify(registry, "Fuente", "1")
        add_designation(registry, pass_id, "messier", "M31")
        memory_db.execute("CREATE TRIGGER fallo BEFORE UPDATE OF pass_object_id ON planned_sessions "
                          "BEGIN SELECT RAISE(ABORT,'Fallo sintético'); END")
        with pytest.raises(sqlite3.IntegrityError):
            link_personal_references(memory_db, registry)
        assert memory_db.in_transaction
        assert memory_db.execute("SELECT pass_object_id FROM personal_catalog").fetchone()[0] is None
        memory_db.execute("DROP TRIGGER fallo")
        assert link_personal_references(memory_db, registry)["linked"] == 2
        assert memory_db.in_transaction
        memory_db.rollback()
        assert memory_db.execute("SELECT pass_object_id FROM personal_catalog").fetchone()[0] is None
        assert memory_db.execute("SELECT * FROM settings WHERE key='trabajo_ajeno'").fetchone() is None


def test_esquema_legacy_recibe_solo_vinculos_nulos_sin_reescribir_datos(tmp_path):
    """La migración de columnas también sirve para bases existentes; no supone que las creó el esquema nuevo."""
    from db.connection import SCHEMA_PATH, _apply_schema

    schema = "\n".join(line for line in SCHEMA_PATH.read_text(encoding="utf-8").splitlines()
                       if "pass_object_id" not in line)
    path = tmp_path / "personal-sintetica.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(schema)
        conn.execute("INSERT INTO personal_catalog(object_id,catalog,notes) VALUES ('M31','messier','Notas')")
        conn.execute("INSERT INTO planned_sessions(object_id,session_date,ra_hours) VALUES ('M31','2026-10-20',3)")
        conn.commit()
        _apply_schema(conn)
        _apply_schema(conn)
        assert conn.execute("SELECT object_id,notes,pass_object_id FROM personal_catalog").fetchone() == ("M31", "Notas", None)
        assert conn.execute("SELECT object_id,ra_hours,pass_object_id FROM planned_sessions").fetchone() == ("M31", 3, None)
