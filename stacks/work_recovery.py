"""Puntos de recuperación de SirIL: solo metadatos y lecturas, nunca procesamiento."""

import math
import re
from pathlib import Path

from .calibrator import CALIBRATED_DIR, output_matches_source
from .global_pool import LightRef
from .registration import REGISTRADOS_DIR, Registro, _mapear
from .session_parser import Session, parse_session
from .siril_runner import WORKING_FOLDER, SirilError


def signature(paths) -> dict:
    """Sella ruta, tamaño, fecha e identidad física; no es un hash criptográfico de píxeles."""
    result = {}
    for path in paths:
        path = Path(path).absolute()
        if not path.is_file():
            raise ValueError(f"Archivo no disponible: {path}")
        stat = path.stat()
        result[str(path)] = [stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino]
    return result


def verify_signature(data: dict) -> bool:
    """Rechaza archivos ausentes, reemplazados o con metadatos cambiados."""
    if not isinstance(data, dict) or not data:
        return False
    try:
        for path, stamp in data.items():
            if (not isinstance(path, str) or not Path(path).is_absolute()
                or not isinstance(stamp, list) or len(stamp) != 4
                or any(type(value) is not int or value < 0 for value in stamp)):
                return False
        return signature(data) == data
    except (ValueError, OSError):
        return False


def dump_sessions(sessions: list[Session]) -> list[dict]:
    """Conserva rutas y agrupaciones exactas; dos sesiones homónimas siguen separadas."""
    return [{
        "path": str(session.path.absolute()), "kind": session.kind,
        "frames": {kind: [str(path.absolute()) for path in paths] for kind, paths in session.frames.items()},
        "masters": {kind: str(path.absolute()) for kind, path in session.masters.items()},
        "filters": {kind: [str(path.absolute()) for path in paths] for kind, paths in session.filters.items()},
    } for session in sessions]


def load_sessions(data: list) -> list[Session]:
    """Reconstruye referencias sin afirmar que los archivos siguen disponibles."""
    if not isinstance(data, list):
        raise TypeError("Sesiones del borrador inválidas")
    sessions = []
    for item in data:
        if not isinstance(item, dict) or set(item) != {"path", "kind", "frames", "masters", "filters"}:
            raise ValueError("Sesión del borrador incompatible")
        path = _absolute(item["path"])
        if not isinstance(item["kind"], str):
            raise TypeError("Tipo de sesión inválido")
        groups = []
        for key in ("frames", "filters"):
            group = item[key]
            if not isinstance(group, dict) or any(not isinstance(k, str) or not isinstance(v, list) for k, v in group.items()):
                raise ValueError("Agrupación de tomas inválida")
            groups.append({kind: [_absolute(value) for value in values] for kind, values in group.items()})
        if not isinstance(item["masters"], dict) or any(not isinstance(k, str) for k in item["masters"]):
            raise ValueError("Másters inválidos")
        sessions.append(Session(path, groups[0], {k: _absolute(v) for k, v in item["masters"].items()}, groups[1], item["kind"]))
    if len({str(session.path) for session in sessions}) != len(sessions):
        raise ValueError("Sesiones duplicadas en el borrador")
    return sessions


def input_signature(sessions: list[Session]) -> dict:
    """Identifica todas las entradas escaneadas, no solo el primer light."""
    return signature(
        path for session in sessions
        for path in [*(p for paths in session.frames.values() for p in paths), *session.masters.values()]
    )


def verify_inputs(sessions: list[Session], stamps: dict) -> bool:
    """Detecta también tomas añadidas o retiradas respecto al escaneo confirmado."""
    if not sessions:
        return not stamps
    try:
        return (verify_signature(stamps) and input_signature(sessions) == stamps
                and dump_sessions([parse_session(session.path) for session in sessions]) == dump_sessions(sessions))
    except (OSError, ValueError):
        return False


def seal_calibration(row: dict) -> dict:
    """Sella únicamente una salida atribuible y con el número completo de lights registrado."""
    source, output = Path(row["session_dir"]), Path(row["calibrated_dir"])
    if not output_matches_source(source, output, root=WORKING_FOLDER / CALIBRATED_DIR):
        raise ValueError("Calibración no atribuible a su origen")
    lights = sorted((output / "light").glob("pp_*.fit*"))
    if type(row["n_frames"]) is not int or row["n_frames"] <= 0 or len(lights) != row["n_frames"]:
        raise ValueError("Calibración incompleta")
    return {"row": dict(row), "signature": signature(lights)}


def verified_calibrations(checkpoints: dict, rows: list[dict]) -> list[dict]:
    """No acredita una calibración por una carpeta existente ni por una bandera guardada."""
    result = []
    for row in rows:
        key = str(Path(row["session_dir"]).resolve())
        checkpoint = checkpoints.get(key)
        if not isinstance(checkpoint, dict) or set(checkpoint) != {"row", "signature"}:
            continue
        try:
            if checkpoint["row"] == row and seal_calibration(row)["signature"] == checkpoint["signature"]:
                result.append(row)
        except (OSError, ValueError, KeyError):
            continue
    return result


def registration_context(options: dict, accepted: list[LightRef]) -> dict:
    """Asocia el registro final con opciones y conjunto de entradas realmente ejecutados."""
    flat = options.get("flat")
    config = dict(options, flat=str(Path(flat).absolute()) if flat else None)
    return {"options": config, "accepted": signature(ref.ruta for ref in accepted),
            "flat": signature([flat]) if flat else {}}


def seal_registry(registry: Registro, context: dict) -> dict:
    """Sella el registro terminado antes de apilar, incluidos secuencia y archivos aplicados."""
    directory = registry.dir.absolute()
    _working_registry(directory)
    paths = [path for path in directory.rglob("*") if path.is_file()]
    if not paths or not registry.ruta_seq.is_file():
        raise ValueError("Registro incompleto")
    frames = [{"path": str(ref.ruta.absolute()), "session": ref.sesion,
               "filter": ref.filtro, "exposure": ref.exposicion_s} for ref in registry.frames]
    checkpoint = {
        "dir": str(directory), "seq": registry.seq, "transformed": registry.transformadas,
        "frames": frames, "signature": signature(paths), "context": context,
    }
    recover_registry(checkpoint)
    return checkpoint


def recover_registry(data: dict) -> Registro:
    """Devuelve solo un registro íntegro dentro de working; nunca ejecuta SirIL."""
    if not isinstance(data, dict) or set(data) != {"dir", "seq", "transformed", "frames", "signature", "context"}:
        raise ValueError("Registro del borrador incompatible")
    directory = _absolute(data["dir"])
    _working_registry(directory)
    if not isinstance(data["seq"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", data["seq"]):
        raise ValueError("Nombre de secuencia inválido")
    if type(data["transformed"]) is not bool or not isinstance(data["frames"], list) or not data["frames"]:
        raise ValueError("Frames de registro inválidos")
    if not verify_signature(data["signature"]):
        raise ValueError("El registro falta o cambió")
    if signature(path for path in directory.rglob("*") if path.is_file()) != data["signature"]:
        raise ValueError("El contenido del registro cambió")
    frames = []
    for item in data["frames"]:
        if not isinstance(item, dict) or set(item) != {"path", "session", "filter", "exposure"}:
            raise ValueError("Referencia registrada inválida")
        path = _absolute(item["path"])
        if not path.resolve().is_relative_to(WORKING_FOLDER.resolve()) or not path.is_file():
            raise ValueError("Referencia fuera de working o ausente")
        if not isinstance(item["session"], str) or (item["filter"] is not None and not isinstance(item["filter"], str)):
            raise ValueError("Identidad de frame inválida")
        exposure = item["exposure"]
        if exposure is not None and (type(exposure) not in (int, float) or not math.isfinite(exposure) or exposure <= 0):
            raise ValueError("Exposición inválida")
        frames.append(LightRef(path, item["session"], item["filter"], exposure))
    registry = Registro(directory, data["seq"], frames, data["transformed"])
    try:
        mapped = _mapear(directory, registry.seq, frames)
    except SirilError as exc:
        raise ValueError(str(exc)) from exc
    if mapped != frames:
        raise ValueError("El orden de los frames registrados no coincide")
    if not registry.ruta_seq.is_file():
        raise ValueError("Secuencia no disponible")
    prefix = registry.seq_apilable
    expected = {f"{prefix}{i:05d}.fit" for i in range(1, len(frames) + 1)}
    actual = {path.name for path in directory.glob(f"{prefix}*.fit") if path.is_file()}
    if registry.transformadas:
        if not actual or not actual <= expected or not (directory / f"{prefix}.seq").is_file():
            raise ValueError("Salidas transformadas inválidas")
    elif actual != expected:
        raise ValueError("Secuencia de entrada incompleta")
    context = data["context"]
    if not isinstance(context, dict) or set(context) != {"options", "accepted", "flat"}:
        raise ValueError("Contexto de registro inválido")
    if not verify_signature(context["accepted"]) or (context["flat"] and not verify_signature(context["flat"])):
        raise ValueError("Las entradas o el flat del registro cambiaron")
    return registry


def _absolute(value) -> Path:
    """Rechaza referencias relativas o no textuales sin normalizarlas silenciosamente."""
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ValueError("Ruta de borrador inválida")
    return Path(value)


def _working_registry(directory: Path) -> None:
    """Ancla los registros recuperados a la carpeta específica de PASS."""
    root = (WORKING_FOLDER / REGISTRADOS_DIR).resolve()
    if not directory.resolve().is_relative_to(root) or directory.resolve() == root:
        raise ValueError("Registro fuera de la carpeta de trabajo")
