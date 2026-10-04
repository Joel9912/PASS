"""Modelos de datos de equipo (datos fríos comparables).

Datos que el programa guarda y SÍ puede comparar: apertura, distancia focal,
resolución, profundidad de bits, refrigeración, etc.
Las imágenes adjuntas (spot, etc.) son SOLO visuales: el programa no las compara.
"""
from dataclasses import dataclass, field


@dataclass
class Location:
    """Ubicación geográfica desde donde se observa.

    ``utc_offset_hours`` es el desfase de la hora de reloj frente a UTC
    (p. ej. España en verano = +2). Si es ``None`` se usa la longitud como
    hora solar local, que es una aproximación.
    """

    id: int | None = None
    name: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_m: float | None = None
    utc_offset_hours: float | None = None


@dataclass
class Telescope:
    """Telescopio u óptica."""

    name: str = ""
    aperture_mm: float = 0.0
    focal_mm: float = 0.0


@dataclass
class Camera:
    """Cámara: datos fríos comparables.

    ``pixel_size_um``/``width_px``/``height_px`` son los que permiten
    calcular el FOV; ya existen en el esquema
    (``equipment_setups.camera_*``) pero faltaban en el modelo, con lo
    que el dato guardado no era utilizable (C-1 de la auditoría).
    """

    name: str = ""
    cooled: bool = False
    resolution: str = ""        # p. ej. '6248x4176'
    bit_depth: int = 16
    pixel_size_um: float | None = None
    width_px: int | None = None
    height_px: int | None = None


@dataclass
class Mount:
    """Montura."""

    name: str = ""


@dataclass
class EquipmentSetup:
    """Setup completo: combinación de equipo + ubicación + categoría."""

    id: int | None = None
    name: str = ""
    category: str = "campo_amplio"
        # 'campo_amplio' | 'nebulosas' | 'galaxias' | 'planetario' (futuro)
    location: Location | None = None
    telescope: Telescope = field(default_factory=Telescope)
    camera: Camera = field(default_factory=Camera)
    mount: Mount = field(default_factory=Mount)
    notes: str = ""
    images: list[str] = field(default_factory=list)  # rutas adjuntas (solo visuales)
