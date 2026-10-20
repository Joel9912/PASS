"""Contrato de paquetes con identidades/procedencia explícitas; validar estructura no acredita derechos ni identidad física."""

import json
import re
from uuid import UUID

from db.catalog_identity import add_designation, identify


def _text(value):
    """Exige identificadores literales sin corregir nombres, sufijos o claves de fuente."""
    if not isinstance(value, str) or not value.strip() or value != value.strip() or "\x00" in value:
        raise ValueError("Identificador o procedencia inválidos en el paquete.")


def _pass_id(value):
    """Acepta solo el formato persistente del preparador, no nombres astronómicos usados como IDs internos."""
    _text(value)
    if re.fullmatch(r"PASS-[0-9a-f-]{36}", value) is None:
        raise ValueError("Identidad PASS inválida.")
    try:
        if str(UUID(value[5:])) != value[5:]:
            raise ValueError("Identidad PASS no canónica.")
    except ValueError as exc:
        raise ValueError("Identidad PASS inválida.") from exc


def validate_records(rows: list, records: list) -> None:
    """Comprueba una vinculación por fila y fuentes explícitas, sin generar IDs ni normalizar los datos originales.

    ``row`` solo enlaza la proyección de esta exportación: la identidad
    procede del registro persistente, nunca de su posición en el archivo.
    Las relaciones son evidencias aportadas, no fusiones de objetos.
    """
    if not isinstance(records, list) or len(records) != len(rows):
        raise ValueError("Cada fila requiere una identidad y procedencia explícitas.")
    positions, identities, source_keys = set(), set(), set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {"row", "pass_id", "sources", "aliases", "relations"}:
            raise ValueError("Registro de identidad incompatible.")
        position = record["row"]
        if type(position) is not int or not 0 <= position < len(rows) or position in positions:
            raise ValueError("Proyección de identidad repetida o fuera del paquete.")
        positions.add(position)
        _pass_id(record["pass_id"])
        if record["pass_id"] in identities:
            raise ValueError("Una identidad no puede representar dos filas distintas; conserva relaciones sin fusionarlas.")
        identities.add(record["pass_id"])
        sources = record["sources"]
        if not isinstance(sources, list) or not sources:
            raise ValueError("Identidad sin fuente verificable declarada.")
        for source in sources:
            required = {"source", "key", "revision", "data"}
            optional = {"url", "license", "attribution"}
            if not isinstance(source, dict) or not required <= source.keys() or source.keys() - required - optional:
                raise ValueError("Procedencia de fuente incompatible.")
            for field in (required - {"data"}) | (optional & source.keys()):
                _text(source[field])
            if not isinstance(source["data"], dict):
                raise TypeError("Los campos originales de fuente deben conservarse como objeto JSON.")
            try:
                encoded = json.dumps(source, allow_nan=False)
                if json.loads(encoded) != source:
                    raise ValueError("Los campos de fuente deben conservar sus tipos JSON originales.")
            except (TypeError, ValueError, OverflowError, RecursionError) as exc:
                raise ValueError("Campos originales no serializables o no finitos.") from exc
            key = source["source"], source["key"]
            if key in source_keys:
                raise ValueError("Registro de fuente repetido; no se fusiona automáticamente.")
            source_keys.add(key)
        aliases = record["aliases"]
        if not isinstance(aliases, list):
            raise TypeError("Lista de designaciones inválida.")
        seen_aliases = set()
        for alias in aliases:
            if not isinstance(alias, dict) or set(alias) != {"namespace", "designation"}:
                raise ValueError("Designación incompatible.")
            _text(alias["namespace"])
            _text(alias["designation"])
            key = alias["namespace"], alias["designation"]
            if key in seen_aliases:
                raise ValueError("Designación repetida en una identidad.")
            seen_aliases.add(key)
        if not isinstance(record["relations"], list):
            raise TypeError("Lista de relaciones inválida.")
        seen_relations = set()
        for relation in record["relations"]:
            if not isinstance(relation, dict) or set(relation) != {"target", "kind", "evidence"}:
                raise ValueError("Relación incompatible.")
            _pass_id(relation["target"])
            _text(relation["kind"])
            _text(relation["evidence"])
            key = relation["target"], relation["kind"]
            if key in seen_relations or relation["target"] == record["pass_id"]:
                raise ValueError("Relación repetida o autorreferente.")
            seen_relations.add(key)


def prepare_record(registry, row: int, source: dict, *, aliases=(), relations=(), same_as=None) -> dict:
    """Vincula una fuente ya revisada al registro persistente; no descarga, fusiona ni fabrica designaciones."""
    if type(row) is not int or row < 0 or not isinstance(source, dict) or not {"source", "key"} <= source.keys():
        raise ValueError("Proyección o fuente de preparación inválidas.")
    registry.execute("SAVEPOINT prepare_catalog_record")
    try:
        pass_id = identify(registry, source["source"], source["key"], same_as=same_as)
        record = {"row": row, "pass_id": pass_id, "sources": [source],
                  "aliases": list(aliases), "relations": list(relations)}
        validate_records([None], [{**record, "row": 0}])
        for alias in record["aliases"]:
            add_designation(registry, pass_id, alias["namespace"], alias["designation"])
        registry.execute("RELEASE SAVEPOINT prepare_catalog_record")
        return record
    except Exception:
        registry.execute("ROLLBACK TO SAVEPOINT prepare_catalog_record")
        registry.execute("RELEASE SAVEPOINT prepare_catalog_record")
        raise
