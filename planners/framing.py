"""Campo de visión (FOV) calculado desde el equipo del usuario.

El encuadre se deriva de tres datos del equipo:
- resolución de la cámara (píxeles) y tamaño de píxel (µm) → sensor;
- focal del telescopio → ángulo.

Si falta cualquiera de esos datos, :func:`calculate_fov` devuelve ``None`` y
la UI desactiva el encuadre (requisito: nunca inventar un FOV).

Todo trabaja en grados; la UI convierte a arcmin o a grados según convenga.
"""
from __future__ import annotations

import math

#: Conversiones.
_UM_TO_MM = 1e-3
_RAD_TO_DEG = 180.0 / math.pi


def _sensor_size_mm(width_px: int, height_px: int, pixel_size_um: float) -> tuple[float, float]:
    """Tamaño del sensor en mm: (ancho, alto) = píxeles × tamaño píxel."""
    pixel_mm = pixel_size_um * _UM_TO_MM
    return width_px * pixel_mm, height_px * pixel_mm


def _resolution_px(equipment_setup: dict) -> tuple[int | None, int | None]:
    """Resolución del sensor: columnas dedicadas o respaldo de ``camera_resolution``.

    Los setups antiguos guardan la resolución como texto (``'6048x4032'``);
    si ``camera_width_px``/``camera_height_px`` están vacíos se parsea ese
    texto en lugar de desactivar el encuadre sin motivo.
    """
    width = equipment_setup.get("camera_width_px")
    height = equipment_setup.get("camera_height_px")
    if width and height:
        try:
            return int(width), int(height)
        except (TypeError, ValueError):
            pass

    text = str(equipment_setup.get("camera_resolution") or "")
    parts = text.lower().replace("×", "x").split("x")
    if len(parts) == 2:
        try:
            return int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            pass
    return None, None


def calculate_fov(equipment_setup: dict) -> tuple[float, float] | None:
    """FOV del equipo como ``(fov_major_deg, fov_minor_deg)`` o ``None``.

    Requiere en ``equipment_setup``:

    - ``telescope_focal_mm``: focal del telescopio (> 0).
    - ``camera_width_px`` y ``camera_height_px``: resolución (> 0); si faltan,
      se usa ``camera_resolution`` (``'6048x4032'``).
    - ``camera_pixel_size_um``: tamaño de píxel (> 0).

    Fórmula::

        fov = 2 · arctan(sensor / (2 · focal))

    Si algún dato falta o no es válido → ``None`` (encuadre desactivado).
    """
    try:
        focal = float(equipment_setup.get("telescope_focal_mm"))
        pixel_um = float(equipment_setup.get("camera_pixel_size_um"))
    except (TypeError, ValueError):
        return None

    width_px, height_px = _resolution_px(equipment_setup)
    if width_px is None or height_px is None:
        return None

    if focal <= 0 or width_px <= 0 or height_px <= 0 or pixel_um <= 0:
        return None

    sensor_w, sensor_h = _sensor_size_mm(width_px, height_px, pixel_um)
    fov_major = 2.0 * math.atan(sensor_w / (2.0 * focal)) * _RAD_TO_DEG
    fov_minor = 2.0 * math.atan(sensor_h / (2.0 * focal)) * _RAD_TO_DEG
    return round(fov_major, 4), round(fov_minor, 4)


def fov_to_arcmin(fov_deg: float) -> float:
    """Grados → minutos de arco (1° = 60')."""
    return fov_deg * 60.0


def calculate_mosaic_extent(
    fov_major_deg: float,
    fov_minor_deg: float,
    tiles_x: int,
    tiles_y: int,
) -> tuple[float, float]:
    """Extensión total de un mosaico ``(ancho_grados, alto_grados)``.

    Un mosaico de ``tiles_x`` × ``tiles_y`` teselas solapadas se calcula
    como si las teselas se dispusieran sin solape (encuadre nominal total).
    El solape real lo decide el usuario al capturar; aquí solo damos la
    extensión de referencia para la tabla y el planetario.
    """
    tiles_x = max(1, int(tiles_x))
    tiles_y = max(1, int(tiles_y))
    return fov_major_deg * tiles_x, fov_minor_deg * tiles_y
