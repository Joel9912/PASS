"""Maestro portable de captura: JSON versionado, confirmación explícita y referencias locales sin duplicar la autoridad."""

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from db.connection import get_connection

from .multinight import (
    Allocation,
    Balance,
    Opportunity,
    Request,
    Result,
    distribute,
    objective_from_data,
    validate,
    validate_editor,
)

_MAX_BYTES = 64*1024*1024
_INDEX_KEY = "capture_plan_index_v1"


def _utc_now():
    """Marca metadatos del documento, no una hora inventada para las capturas."""
    return datetime.now(UTC).isoformat()


def _json_value(value):
    """Codifica solo instantes con zona; las horas de ejecución se conservan en UTC."""
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).isoformat()
    raise TypeError("El documento contiene un valor no serializable.")


def _reject_constant(_value):
    """JSON no admite NaN ni infinitos como objetivos u horas válidos."""
    raise ValueError("El documento contiene números no finitos.")


def _object(pairs):
    """Rechaza claves duplicadas para no interpretar dos autoridades distintas en el mismo archivo."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("El documento contiene claves JSON duplicadas.")
        result[key] = value
    return result


def _identifier(value):
    """Identidades opacas por plan/objetivo/revisión, independientes de carpetas y nombres."""
    if not isinstance(value, str) or len(value) != 32 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("Identidad del documento inválida.")


def _moment(value):
    """Solo admite instantes con zona, sin asumir el huso de la máquina al abrir otro proyecto."""
    if not isinstance(value, str):
        raise TypeError("Instante de documento inválido.")
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError("El documento contiene una hora sin zona.")
    return moment.astimezone(UTC)


def decode_request(data):
    """Restaura una petición por valor, sin buscar catálogos/equipos ni cambiar sus coordenadas guardadas."""
    if not isinstance(data, dict) or set(data) != set(Request.__dataclass_fields__):
        raise ValueError("Petición del documento incompatible.")
    fields = dict(data)
    for item in data["objectives"]:
        exposures = [goal["exposure_s"] for goal in item["demands"]]
        if not exposures or any(value != exposures[0] for value in exposures):
            raise ValueError("El documento no usa una exposición común para los Valores del plan.")
    fields["objectives"] = tuple(objective_from_data(item, item["demands"][0]["exposure_s"]) for item in data["objectives"])
    fields["weekdays"] = tuple(data["weekdays"])
    fields["obstacles"] = tuple(data["obstacles"]) if data["obstacles"] is not None else None
    request = Request(**fields)
    validate(request)
    return request


def decode_result(data):
    """Restaura los bloques y balances; nunca procesa imágenes al leer un maestro."""
    if not isinstance(data, dict) or set(data) != set(Result.__dataclass_fields__):
        raise ValueError("Resultado del documento incompatible.")
    if any(not isinstance(data[key], list) for key in data):
        raise ValueError("Colecciones del resultado incompatibles.")
    opportunities, allocations = [], []
    for source, cls, output in ((data["opportunities"], Opportunity, opportunities), (data["allocations"], Allocation, allocations)):
        for item in source:
            values = dict(item)
            values["start"], values["end"] = _moment(item["start"]), _moment(item["end"])
            output.append(cls(**values))
    return Result(tuple(opportunities), tuple(allocations), tuple(Balance(**item) for item in data["balances"]),
                  tuple(data["accuracy"]), tuple(data["warnings"]))


def validate_document(document):
    """Valida estructura e integridad lógica del calendario antes de leer o publicar; no certifica efemérides externas."""
    required = {"format", "version", "id", "revision", "created_at", "updated_at", "state", "objective_ids",
                "editor", "request", "result"}
    if not isinstance(document, dict) or set(document) != required:
        raise ValueError("Estructura de maestro incompatible.")
    if document["format"] != "pass-capture-plan" or type(document["version"]) is not int or document["version"] != 1:
        raise ValueError("Formato o versión de maestro no compatible; se conserva sin modificar.")
    if document["state"] != "created":
        raise ValueError("El archivo no es un plan creado confirmado.")
    _identifier(document["id"])
    _identifier(document["revision"])
    if _moment(document["updated_at"]) < _moment(document["created_at"]):
        raise ValueError("Revisión anterior a la creación del plan.")
    validate_editor(document["editor"])
    if not document["editor"]["name"].strip():
        raise ValueError("El plan creado necesita un nombre.")
    identities = document["objective_ids"]
    if not isinstance(identities, dict) or set(identities) != {item["objective"]["key"] for item in document["editor"]["objectives"]}:
        raise ValueError("Las identidades del maestro no corresponden a los objetivos.")
    for value in identities.values():
        _identifier(value)
    if len(set(identities.values())) != len(identities):
        raise ValueError("El maestro repite una identidad de objetivo.")
    request = decode_request(document["request"])
    result = decode_result(document["result"])
    for allocation in result.allocations:
        if type(allocation.frames) is not int or allocation.frames <= 0 or type(allocation.exposure_s) is not int:
            raise ValueError("El documento contiene tomas no válidas.")
    for balance in result.balances:
        if type(balance.assigned_s) is not int or balance.assigned_s < 0 or type(balance.requested_s) not in (int, float):
            raise ValueError("El documento contiene un balance no válido.")
    if request.policy == "windows_only":
        raise ValueError("Consultar ventanas no crea un plan de captura distribuido.")
    if not result.allocations:
        raise ValueError("El plan creado necesita al menos un bloque de capturas distribuido.")
    if {item.key for item in request.objectives} != set(identities.values()):
        raise ValueError("La petición no usa las identidades estables del maestro.")
    for item in document["editor"]["objectives"]:
        source = objective_from_data(item["objective"], document["editor"]["exposure"])
        saved = next(obj for obj in request.objectives if obj.key == identities[source.key])
        if replace(source, key=saved.key) != saved:
            raise ValueError("La configuración y los objetivos del calendario no coinciden.")
    editor = document["editor"]
    for name in ("start", "end", "start_minute", "end_minute", "minimum_altitude", "policy", "horizon_policy"):
        if editor[name] != getattr(request, name):
            raise ValueError("Las restricciones guardadas no corresponden al calendario.")
    if tuple(editor["weekdays"]) != request.weekdays or editor["use_obstacles"] != (request.obstacles is not None):
        raise ValueError("La disponibilidad guardada no corresponde al calendario.")
    calculated = distribute(request, result.opportunities, result.accuracy)
    if calculated.allocations != result.allocations or calculated.balances != result.balances:
        raise ValueError("El reparto guardado no corresponde a sus ventanas/objetivos.")
    if any(not isinstance(value, str) for value in result.accuracy+result.warnings):
        raise ValueError("Procedencia del resultado inválida.")
    return request, result


def make_document(editor, request, result, previous=None):
    """Prepara un maestro solo tras el cálculo; la UI pide confirmación antes de escribirlo."""
    if previous is not None:
        validate_document(previous)
    old_ids = previous["objective_ids"] if previous else {}
    identities = {obj.key:old_ids.get(obj.key, uuid4().hex) for obj in request.objectives}
    stable_request = replace(request, objectives=tuple(replace(obj, key=identities[obj.key]) for obj in request.objectives))
    stable_result = replace(result,
                            opportunities=tuple(replace(item, objective=identities[item.objective]) for item in result.opportunities),
                            allocations=tuple(replace(item, objective=identities[item.objective]) for item in result.allocations),
                            balances=tuple(replace(item, objective=identities[item.objective]) for item in result.balances))
    now = _utc_now()
    document = {"format":"pass-capture-plan", "version":1, "id":previous["id"] if previous else uuid4().hex,
                "revision":uuid4().hex, "created_at":previous["created_at"] if previous else now, "updated_at":now,
                "state":"created", "objective_ids":identities, "editor":editor,
                "request":asdict(stable_request), "result":asdict(stable_result)}
    document = json.loads(json.dumps(document, default=_json_value, ensure_ascii=False, allow_nan=False))
    validate_document(document)
    return document


def read_document(path):
    """Lee un maestro limitado y calcula su huella, sin seguir vínculos ni recorrer fotografías."""
    path = Path(path)
    with path.open("rb") as stream:
        raw = stream.read(_MAX_BYTES+1)
    if len(raw) > _MAX_BYTES:
        raise ValueError("El maestro supera el tamaño admitido.")
    try:
        document = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant, object_pairs_hook=_object)
        validate_document(document)
    except (TypeError, KeyError, IndexError, OverflowError, RecursionError) as exc:
        raise ValueError("Maestro inválido; se conserva sin modificar.") from exc
    return document, hashlib.sha256(raw).hexdigest()


def _publish_new(temporary, path):
    """Publica sin reemplazo: rename exclusivo en Windows, enlace temporal atómico en POSIX.

    El maestro final es un archivo normal, no un descriptor basado en enlaces.
    Windows no necesita soporte de hardlinks en discos FAT/exFAT para guardarlo.
    """
    if os.name == "nt":
        os.rename(temporary, path)
    else:
        os.link(temporary, path)


def write_document(path, document, expected_sha=None):
    """Escribe por sustitución atómica, sin adoptar un archivo existente o sobrescribir otra revisión.

    El bloqueo lateral coordina instancias PASS; no pretende impedir que otras
    aplicaciones ignoren ese bloqueo. Un archivo nuevo se publica sin reemplazo.
    """
    validate_document(document)
    raw = json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")+b"\n"
    if len(raw) > _MAX_BYTES:
        raise ValueError("El maestro supera el tamaño admitido.")
    path = Path(path).absolute()
    lock = path.with_name(path.name+".lock")
    lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    temporary = None
    try:
        if expected_sha is None:
            if path.exists():
                raise FileExistsError("El destino ya existe; no se reemplaza un archivo no abierto como este plan.")
        else:
            previous, digest = read_document(path)
            if digest != expected_sha or previous["id"] != document["id"]:
                raise ValueError("El maestro cambió desde su apertura; vuelve a abrirlo antes de guardar.")
        fd, temporary = tempfile.mkstemp(prefix=".pass-plan-", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if expected_sha is None:
            _publish_new(temporary, path)
        else:
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
                raise ValueError("El maestro cambió mientras se preparaba el guardado.")
            os.replace(temporary, path)
            temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
        os.close(lock_fd)
        lock.unlink()
    return hashlib.sha256(raw).hexdigest()


def index_document(path, document):
    """El índice local guarda solo identidad y ruta; el maestro externo sigue siendo la única autoridad editable."""
    _identifier(document["id"])
    conn = get_connection()
    with conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (_INDEX_KEY,)).fetchone()
        raw = row[0] if row else None
        index = json.loads(raw, object_pairs_hook=_object) if raw else {"version":1, "plans":{}}
        if not isinstance(index, dict) or set(index) != {"version", "plans"} or type(index["version"]) is not int or index["version"] != 1 or not isinstance(index["plans"], dict):
            raise ValueError("El índice local no es compatible; el maestro ya guardado se conserva.")
        for identity, location in index["plans"].items():
            _identifier(identity)
            if not isinstance(location, str) or not location:
                raise ValueError("El índice contiene una ruta inválida; se conserva sin modificar.")
        known = index["plans"].get(document["id"])
        if known and Path(known).absolute() != Path(path).absolute() and Path(known).exists():
            raise ValueError("Ya hay otro maestro accesible con esta identidad; no se sustituye su referencia automáticamente.")
        index["plans"][document["id"]] = str(Path(path).absolute())
        value = json.dumps(index, ensure_ascii=False)
        if raw is None:
            conn.execute("INSERT INTO settings(key,value) VALUES(?,?)", (_INDEX_KEY, value))
        else:
            updated = conn.execute("UPDATE settings SET value=? WHERE key=? AND value=?", (value, _INDEX_KEY, raw))
            if updated.rowcount != 1:
                raise ValueError("Otra instancia cambió el índice; el maestro se conserva.")
