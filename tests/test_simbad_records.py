"""Preparación SIMBAD con respuestas sintéticas locales, procedencia intacta y registro transaccional independiente."""

import copy
import hashlib
import json

import pytest

from db.catalog_identity import identify, identity_registry
from planners.simbad_records import FIELDS, SOURCE, prepare_simbad


def snapshot(rows):
    """Describe columnas/unidades/referencia explícitas para no atribuir significado a números sin metadatos."""
    metadata = [{"name": name} for name in FIELDS]
    for field in metadata:
        if field["name"] in ("ra", "dec"):
            field.update(unit="deg", utype="mango:EpochPosition[CS.spaceSys=ICRS CT.epoch=J2000]")
        elif field["name"] in ("galdim_majaxis", "galdim_minaxis"):
            field["unit"] = "arcmin"
        elif field["name"] == "V":
            field["ucd"] = "phot.mag;em.opt.V"
    return {"metadata": metadata, "data": rows}


def entry(name="LDN    1", oid=123):
    """Una ficha ficticia con ceros de tamaño y magnitud ausente, nunca tomados por magnitud cero."""
    return [name, oid, "Objeto sintético", "DNe", 30.0, -10.0, "Referencia sintética",
            0.0, None, None, None, None]


def encode(content):
    """Serializa una respuesta de prueba sin usar red ni archivos del usuario."""
    return json.dumps(content, ensure_ascii=False).encode("utf-8")


def test_ficha_conserva_fuente_unidades_y_ausencias(tmp_path):
    """La proyección convierte grados a horas, pero conserva datos originales, clave literal y huella de instantánea."""
    content = snapshot([entry()])
    data = encode(content)
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        result = prepare_simbad(registry, data, revision="synthetic-A")
    assert result["openngc"] == {"rows": [], "records": []}
    row = result["ldn"]["rows"][0]
    assert row[:2] == ["LDN 1", "ldn"]
    assert row[6:12] == ["DrkN", None, 2, -10, None, None]
    source = result["ldn"]["records"][0]["sources"][0]
    assert source["key"] == "LDN    1" and source["license"] == "ODbL-1.0"
    assert source["data"]["row"] == dict(zip(FIELDS, entry(), strict=True))
    assert source["data"]["snapshot_sha256"] == hashlib.sha256(data).hexdigest()


def test_mismo_oid_explicito_una_proyeccion_y_alias_entre_catalogos(tmp_path):
    """El cruce viene de SIMBAD, no de semejanza de coordenadas; Barnard queda como alias del objeto LDN."""
    data = encode(snapshot([entry(), entry("Barnard  1")]))
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        result = prepare_simbad(registry, data, revision="synthetic-A")
        assert registry.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 1
    record = result["ldn"]["records"][0]
    assert len(record["sources"]) == 2
    assert {"namespace": "barnard", "designation": "B 1"} in record["aliases"]
    assert result["openngc"]["rows"] == []


def test_coordenadas_iguales_no_fusionan_oid_distintos(tmp_path):
    """Dos objetos con medidas iguales mantienen identidad propia si la fuente no los identifica como uno."""
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        result = prepare_simbad(registry, encode(snapshot([entry(), entry("Barnard  1", 124)])), revision="A")
    assert result["ldn"]["records"][0]["pass_id"] != result["openngc"]["records"][0]["pass_id"]


def test_alias_nuevo_anterior_lexicografico_no_cambia_identidad(tmp_path):
    """La identidad procede de claves ya registradas, no del primer alias o del orden de filas de la nueva edición."""
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        before = prepare_simbad(registry, encode(snapshot([entry("LDN 9")])), revision="A")
        after = prepare_simbad(registry, encode(snapshot([entry("LDN 1"), entry("LDN 9")])), revision="B")
    assert before["ldn"]["records"][0]["pass_id"] == after["ldn"]["records"][0]["pass_id"]


@pytest.mark.parametrize("damage", ["unit", "frame", "band", "column", "boolean", "nan", "negative", "range", "duplicate", "contradiction"])
def test_instantanea_invalida_no_escribe_registro(tmp_path, damage):
    """Metadatos/filas contradictorias o no finitas fallan antes de generar identidades o artefactos."""
    content = snapshot([entry()])
    if damage == "unit":
        content["metadata"][4]["unit"] = "hour"
    elif damage == "frame":
        content["metadata"][4]["utype"] = "FK4"
    elif damage == "band":
        content["metadata"][-1]["ucd"] = "phot.mag;em.opt.B"
    elif damage == "column":
        content["metadata"][2]["name"] = "unknown"
    elif damage in ("boolean", "nan", "negative", "range"):
        index = 7 if damage == "negative" else 4
        content["data"][0][index] = {"boolean": True, "nan": float("nan"), "negative": -1, "range": 361}[damage]
    else:
        other = copy.deepcopy(content["data"][0])
        if damage == "contradiction":
            other[0], other[4] = "Barnard 1", 40
        content["data"].append(other)
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        with pytest.raises(ValueError):
            prepare_simbad(registry, encode(content), revision="A")
        assert registry.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 0


def test_cruce_explicito_conserva_identidad_y_conflicto_revierte_lote(tmp_path):
    """Un lote que ya creó una ficha revierte entero si otro cruce contradice el registro previo."""
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        first = identify(registry, "fuente-sintetica", "original-1")
        second = identify(registry, "fuente-sintetica", "original-2")
        identify(registry, SOURCE, "Barnard 2", same_as=first)
        before = registry.execute("SELECT * FROM source_records ORDER BY source,source_key").fetchall()
        with pytest.raises(ValueError):
            prepare_simbad(registry, encode(snapshot([entry("LDN 1", 1), entry("Barnard 2", 2)])),
                           revision="A", same_as={"Barnard 2": second})
        assert registry.execute("SELECT * FROM source_records ORDER BY source,source_key").fetchall() == before


def test_renumeracion_oid_con_clave_literal_conservada_no_recicla_id(tmp_path):
    """El OID sirve al cruce de esta instantánea, pero no se convierte en clave persistente entre ediciones."""
    with identity_registry(tmp_path / "registry.sqlite") as registry:
        before = prepare_simbad(registry, encode(snapshot([entry()])), revision="A")
        after = prepare_simbad(registry, encode(snapshot([entry(oid=999)])), revision="B")
    assert before["ldn"]["records"][0]["pass_id"] == after["ldn"]["records"][0]["pass_id"]


def test_instantanea_a_exportador_instalador_y_vinculo_personal(tmp_path):
    """Recorrido real con fichas ficticias: alias Barnard en componente LDN conserva nombre y nota al vincular."""
    import sqlite3

    from db import catalog_editions, connection
    from db.catalog_records import lookup
    from planners.catalog_packages import GROUPS, update_packages
    from planners.catalog_records import prepare_record
    from scripts.preparar_catalogos import export_identified

    personal_path = tmp_path / "personal.sqlite"
    personal = sqlite3.connect(personal_path)
    try:
        personal.executescript(connection.SCHEMA_PATH.read_text(encoding="utf-8"))
        personal.execute("INSERT INTO personal_catalog(object_id,catalog,notes) VALUES ('Barnard 1','barnard','Nota manual')")
        personal.commit()
        output = tmp_path / "artifacts"
        with identity_registry(tmp_path / "registry.sqlite") as registry:
            components = prepare_simbad(registry, encode(snapshot([
                entry(), entry("Barnard  1"), entry("Barnard  2", 124),
            ])), revision="synthetic-A")
            components["hyg"] = {"rows": [["Estrella ficticia", 1, 2, 3, None, None]], "records": [
                prepare_record(registry, 0, {"source": "Fuente sintética", "key": "A", "revision": "A", "data": {}}),
            ]}
            export_identified("synthetic-A", output, components, registry)
        manifest = json.loads((output / "catalogs-manifest.json").read_text(encoding="utf-8"))
        update_packages(personal_path, manifest["packages"], GROUPS,
                        reader=lambda url, limit: (output / url.rsplit("/", 1)[1]).read_bytes())
        note = personal.execute("SELECT object_id,notes,pass_object_id FROM personal_catalog").fetchone()
        assert note[:2] == ("Barnard 1", "Nota manual") and note[2] is not None
        with catalog_editions.catalog_snapshot(personal) as catalog:
            result = lookup(catalog, "Barnard 1", "barnard")
            assert result["object_id"] == "LDN 1" and result["pass_id"] == note[2]
            assert result["magnitude"] is None
    finally:
        personal.close()
