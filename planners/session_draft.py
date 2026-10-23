"""Valida borradores de planificación sin crear sesiones ni calcular recomendaciones."""

import math
from datetime import date

from db.work_drafts import DraftError


def validate(data: dict) -> dict:
    """Rechaza estados incompletos o fuera de rango antes de modificar controles."""
    required = {
        "target", "setup_id", "date", "ra", "dec", "tiles_x", "tiles_y",
        "name", "exposure", "notes", "location", "view_fov", "frame_fov",
    }
    if set(data) != required:
        raise DraftError("Campos de planificación incompatibles.")
    target = data["target"]
    if target is not None and (
        not isinstance(target, list) or len(target) != 2
        or any(not isinstance(value, str) or not value for value in target)
    ):
        raise DraftError("Referencia del objetivo inválida.")
    if data["setup_id"] is not None and (
        type(data["setup_id"]) is not int or data["setup_id"] <= 0
    ):
        raise DraftError("Referencia del equipo inválida.")
    if not isinstance(data["date"], str):
        raise DraftError("Fecha inválida.")
    moment = date.fromisoformat(data["date"])
    if moment.isoformat() != data["date"]:
        raise DraftError("La fecha no usa el formato ISO del editor.")
    if moment < date(1752, 9, 14):
        raise DraftError("Fecha fuera del rango del editor.")
    for field in ("name", "notes"):
        if not isinstance(data[field], str):
            raise DraftError(f"Texto inválido: {field}.")
    for field, low, high in (
        ("ra", 0, 24), ("dec", -90, 90), ("view_fov", 0.01, 360),
        ("tiles_x", 1, 20), ("tiles_y", 1, 20), ("exposure", 1, 7200),
    ):
        _number(data[field], low, high)
        if field in ("tiles_x", "tiles_y", "exposure") and type(data[field]) is not int:
            raise DraftError(f"Entero inválido: {field}.")
    location = data["location"]
    if not isinstance(location, list) or len(location) != 3:
        raise DraftError("Ubicación inválida.")
    for index, (value, low, high) in enumerate(zip(location, (-90, -180, -24), (90, 180, 24), strict=True)):
        if index == 2 and isinstance(value, str):
            from .timezones import zone

            zone(value)
            continue
        if value is not None:
            _number(value, low, high)
    if (location[0] is None) != (location[1] is None):
        raise DraftError("Ubicación incompleta.")
    fov = data["frame_fov"]
    if fov is not None:
        if not isinstance(fov, list) or len(fov) != 2:
            raise DraftError("Campo de visión inválido.")
        for value in fov:
            _number(value, 0.000001, 360)
    return data


def _number(value, low: float, high: float) -> None:
    """No acepta booleanos, números no finitos ni valores que Qt truncaría."""
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise DraftError("Número de planificación inválido.")
