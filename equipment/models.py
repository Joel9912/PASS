"""Modelos de datos de equipo (datos fríos comparables).

Los componentes (telescopios, cámaras, monturas, filtros) son **globales**:
varios setups los referencian con rol principal o de guía (pestaña Equipo
v2). Datos que el programa guarda y SÍ puede comparar: apertura, distancia
focal, resolución, profundidad de bits, refrigeración, etc.
Las imágenes adjuntas (spot, charts, mapas de CL) son SOLO visuales: el
programa las muestra para que el usuario las compare por su cuenta; nunca
las analiza ni las compara automáticamente.
"""
from dataclasses import dataclass, field

#: Categorías del equipo (enum decidido por el usuario) → etiqueta para la
#: UI. El orden es el de los combos; ``general`` es el valor por defecto y
#: sirve de «sin clasificar». Dueño del dato: pinta la pestaña Equipo y
#: ``planificacion/tab.py`` (R2 — una sola fuente para las etiquetas).
CATEGORIES: dict[str, str] = {
    "paisaje": "Paisaje",
    "campo_amplio": "Campo Amplio",
    "espacio_profundo": "Espacio Profundo",
    "espacio_profundo_largo": "Espacio Profundo Largo",
    "planetario": "Planetario",
    "general": "General",
}

#: Tipos de óptica (``Telescope.optical_type``) → etiqueta.
OPTICAL_TYPES: dict[str, str] = {
    "refractor": "Refractor",
    "reflector": "Reflector",
    "catadioptrico": "Catadióptrico",
    "otro": "Otro",
}

#: Sugerencias de subtipo según el tipo de óptica. El campo es texto libre
#: (la UI ofrece estas opciones en un combo rellenable y guarda lo que el
#: usuario escriba tal cual): cerrarlo a un enum dejaría fuera modelos que
#: aún no conocemos.
SUBTYPE_SUGGESTIONS: dict[str, tuple[str, ...]] = {
    "refractor": (
        "Doblete",
        "Triplete apocromático",
        "ED",
        "Petzval",
        "Cuádruple (quad)",
        "Sextuplete",
    ),
    "reflector": ("Newton", "Cassegrain", "Ritchey-Chrétien", "Dall-Kirkham"),
    "catadioptrico": ("Schmidt-Cassegrain", "Maksutov-Cassegrain"),
    "otro": (),
}

#: Tipos de montura (``Mount.mount_type``) → etiqueta.
MOUNT_TYPES: dict[str, str] = {
    "ecuatorial": "Ecuatorial",
    "altaz": "Altazimutal",
    "star_tracker": "Star tracker",
    "armonica": "Harmónica",
    "otro": "Otro",
}

#: Tipos de filtro (``Filter.filter_type``) → etiqueta.
FILTER_TYPES: dict[str, str] = {
    "cpl": "CPL (polarizador)",
    "uhc": "UHC",
    "uvir_cut": "UV/IR cut",
    "broadband": "Broadband",
    "narrowband": "Narrowband",
    "lrgb": "LRGB",
    "otro": "Otro",
}

#: Tipos de obstáculo del horizonte (``Location.obstacles``) → etiqueta.
OBSTACLE_TYPES: dict[str, str] = {
    "arboles": "Árboles",
    "edificios": "Edificios",
    "colinas": "Colinas",
    "otro": "Otro",
}

#: Niveles de contaminación lumínica por dirección (``Location.lp``) → etiqueta.
LP_LEVELS: dict[int, str] = {
    0: "Despejado",
    1: "Leve",
    2: "Moderada",
    3: "Intensa",
}

#: 8 direcciones del horizonte en español (O = oeste), en orden de rosación.
DIRECTIONS: tuple[str, ...] = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")


@dataclass
class Location:
    """Ubicación geográfica desde donde se observa, con su sitio.

    ``utc_offset_hours`` es el desfase de la hora de reloj frente a UTC
    (p. ej. España en verano = +2). Si es ``None`` se usa la longitud como
    hora solar local, que es una aproximación.

    El bloque de sitio describe el horizonte por direcciones: ``obstacles``
    (tipos de obstáculo por dirección) y ``lp`` (nivel de CL 0-3 por
    dirección), siempre con las 8 claves de ``DIRECTIONS``. ``bortle`` es
    obligatorio en el formulario (1-9), ``sqm`` opcional, y
    ``consider_lp`` decide si la CL entra en las decisiones de captura de
    esta ubicación — de momento solo se guarda (paso 6 lo cablea).
    ``lp_map`` es la imagen única de referencia (Light Pollution Map): al
    subir otra sustituye a la anterior.
    """

    id: int | None = None
    name: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_m: float | None = None
    utc_offset_hours: float | None = None
    obstacles: dict[str, list[str]] = field(default_factory=dict)
    lp: dict[str, int] = field(default_factory=dict)
    bortle: int | None = None
    sqm: float | None = None
    consider_lp: bool = True
    lp_map: str | None = None


@dataclass
class Telescope:
    """Óptica global reutilizable: la referencian los equipos (principal/guía).

    ``reducer``/``reducer_factor`` describen el aplanador/reductor: la focal
    que importa para el FOV y el muestreo es la **efectiva**
    (``equipment.metrics.focal_efectiva``), no la nominal. ``images`` son
    charts de rendimiento (solo visuales).
    """

    id: int | None = None
    name: str = ""
    aperture_mm: float | None = None   # NULL = el usuario no lo sabe
    focal_mm: float | None = None
    optical_type: str | None = None    # ver OPTICAL_TYPES
    subtype: str | None = None         # texto libre (SUBTYPE_SUGGESTIONS)
    reducer: bool = False
    reducer_factor: float | None = None  # p. ej. 0.8 (None = desconocido)
    notes: str = ""
    images: list[str] = field(default_factory=list)


@dataclass
class Camera:
    """Cámara global reutilizable (principal/guía): datos fríos comparables.

    ``pixel_size_um``/``width_px``/``height_px`` son los que permiten
    calcular el FOV y la escala de muestreo (C-1 de la auditoría: el dato
    estaba sin modelo). No hay campo ``resolution``: la resolución se deriva
    de ancho × alto al pintarla.
    """

    id: int | None = None
    name: str = ""
    cooled: bool = False
    bit_depth: int | None = None
    pixel_size_um: float | None = None
    width_px: int | None = None
    height_px: int | None = None
    mono: bool = False                 # monocromática vs color
    ampglow: bool = False
    notes: str = ""
    images: list[str] = field(default_factory=list)  # gráficas de ganancia


@dataclass
class Mount:
    """Montura global reutilizable: tipo y capacidad de carga."""

    id: int | None = None
    name: str = ""
    mount_type: str | None = None      # ver MOUNT_TYPES
    payload_kg: float | None = None    # capacidad / carga útil
    notes: str = ""


@dataclass
class Filter:
    """Filtro global: los equipos lo llevan vía ``setup_filters`` (M2M)."""

    id: int | None = None
    name: str = ""
    filter_type: str | None = None     # ver FILTER_TYPES
    notes: str = ""


@dataclass
class EquipmentSetup:
    """Setup: combinación de componentes globales + ubicación + categoría.

    Los componentes se referencian **por id** (la misma óptica o cámara
    puede estar en varios setups y en rol principal o de guía);
    ``filter_ids`` es la asignación M2M que ``manager`` sincroniza contra
    ``setup_filters`` al guardar.
    """

    id: int | None = None
    name: str = ""
    category: str = "general"          # ver CATEGORIES
    location_id: int | None = None
    telescope_id: int | None = None
    guide_telescope_id: int | None = None
    camera_id: int | None = None
    guide_camera_id: int | None = None
    mount_id: int | None = None
    filter_ids: list[int] = field(default_factory=list)
    price_eur: float | None = None
    weight_kg: float | None = None
    notes: str = ""
    images: list[str] = field(default_factory=list)  # rutas adjuntas (solo visuales)
