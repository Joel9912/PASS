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
#: ``planificacion/tab.py`` (una sola fuente para las etiquetas).
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

#: Subtipos de óptica (``Telescope.subtype``) por tipo, según la
#: taxonomía decidida por el usuario. El combo de la UI es **solo
#: seleccionable**; un valor guardado que no esté en la lista (otra BD o
#: texto de la versión anterior) se conserva añadiéndolo al combo al
#: cargar (patrón de ``_asegurar_categoria``).
SUBTYPE_SUGGESTIONS: dict[str, tuple[str, ...]] = {
    "refractor": (
        "Acromático",
        "Doblete (ED)",
        "Triplete Apocromático",
        "Quad (FF)",
        "Petzval",
    ),
    "reflector": ("Newtoniano", "Ritchey-Chrétien (RC)"),
    "catadioptrico": (
        "Schmidt-Cassegrain (SCT)",
        "Maksutov-Cassegrain (Mak)",
        "Maksutov-Newtonian",
        "Schmidt-Newtonian",
    ),
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

#: Profundidades de bits de las cámaras (``Camera.bit_depth``): solo existen
#: estas en sensores. Dueño de la opción — el combo de la UI y
#: ``validar_camara`` leen de aquí; si algún día aparece otra, se añade a la
#: tupla y nada más hay que tocar.
BIT_DEPTHS: tuple[int, ...] = (10, 12, 14, 16)

#: Alturas de obstrucción del horizonte (`Location.obstacles`) → etiqueta:
#: a cuántos grados de elevación llega lo que obstruye cada dirección.
#: Dueño del dato: el disco de entrada de la rosácea y
#: ``validar_ubicacion`` leen de aquí.
OBSTRUCTION_ALTITUDES: dict[int, str] = {
    0: "Ninguna (0°)",
    15: "Pequeña (15°)",
    30: "Media (30°)",
    45: "Grande (45°)",
    60: "Total (60°)",
}

#: Fuentes de contaminación lumínica (`Location.lp`) → etiqueta; cada
#: dirección lleva como mucho una, con su distancia en km. Dueño del dato
#: los tooltips que describen cada fuente son texto de la UI y viven
#: en ``ui/equipment_tab/rosaceas.py``, junto al panel que los muestra.
LP_SOURCES: dict[str, str] = {
    "pueblo": "Pueblo",
    "pueblo_grande": "Pueblo Grande",
    "ciudad": "Ciudad",
    "gran_ciudad": "Gran Ciudad",
}

#: 8 direcciones del horizonte en español (O = oeste), en orden de rosación.
DIRECTIONS: tuple[str, ...] = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")


@dataclass
class Location:
    """Ubicación geográfica desde donde se observa, con su sitio.

    ``timezone_id`` selecciona reglas IANA según fecha; alternativamente
    ``utc_offset_hours`` fija un desfase sin ajuste estacional. Ambos ausentes
    conservan la aproximación heredada por longitud, nunca una zona legal inferida.

    El bloque de sitio describe el horizonte por direcciones, siempre con
    las 8 claves de ``DIRECTIONS``: ``obstacles`` guarda a cuántos grados
    obstruye cada una (claves de ``OBSTRUCTION_ALTITUDES``: 0/15/30/45/60)
    y ``lp`` la fuente de CL de cada una como
    ``{"fuente": clave de LP_SOURCES | None, "km": distancia}`` — una sola
    fuente por dirección, con km > 0 solo si hay fuente. ``bortle`` es
    obligatorio en el formulario (1-9), ``sqm`` y ``seeing_arcsec``
    (seeing típico FWHM en ″: el muestreo del equipo lo usa si está
    informado y, sin él, no se inventa) opcionales, y
    ``consider_lp`` decide si la CL y los obstáculos entran en las
    decisiones de captura de esta ubicación (etiqueta «Usar CL y
    Obstáculos al Planificar») — de momento solo se guarda (paso 6 lo
    cablea).
    ``lp_map`` es la imagen única de referencia (Light Pollution Map): al
    subir otra sustituye a la anterior.
    """

    id: int | None = None
    name: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_m: float | None = None
    utc_offset_hours: float | None = None
    obstacles: dict[str, int] = field(default_factory=dict)
    lp: dict[str, dict[str, str | float | None]] = field(default_factory=dict)
    bortle: int | None = None
    sqm: float | None = None
    seeing_arcsec: float | None = None  # FWHM en ″ (None = sin dato)
    consider_lp: bool = True
    lp_map: str | None = None
    timezone_id: str | None = None


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
    subtype: str | None = None         # ver SUBTYPE_SUGGESTIONS (combo solo seleccionable)
    reducer: bool = False
    reducer_factor: float | None = None  # p. ej. 0.8 (None = desconocido)
    price_eur: float | None = None    # precio de esta pieza (None = no informado)
    weight_kg: float | None = None    # peso real (sin el aplanador: +0,5 kg se añade al sumar el equipo)
    notes: str = ""
    images: list[str] = field(default_factory=list)


@dataclass
class Camera:
    """Cámara global reutilizable (principal/guía): datos fríos comparables.

    ``pixel_size_um``/``width_px``/``height_px`` son los que permiten
    calcular el FOV y la escala de muestreo (el dato estaba sin modelo).
    No hay campo ``resolution``: la resolución se deriva
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
    price_eur: float | None = None     # precio de esta pieza (None = no informado)
    weight_kg: float | None = None     # peso real (None = no informado)
    notes: str = ""
    images: list[str] = field(default_factory=list)  # gráficas de ganancia


@dataclass
class Mount:
    """Montura global reutilizable: tipo y capacidad de carga."""

    id: int | None = None
    name: str = ""
    mount_type: str | None = None      # ver MOUNT_TYPES
    payload_kg: float | None = None    # capacidad / carga útil
    price_eur: float | None = None     # precio de esta pieza (None = no informado)
    weight_kg: float | None = None     # peso real (None = no informado)
    notes: str = ""


@dataclass
class Filter:
    """Filtro global: los equipos lo llevan vía ``setup_filters`` (M2M)."""

    id: int | None = None
    name: str = ""
    filter_type: str | None = None     # ver FILTER_TYPES
    price_eur: float | None = None     # precio del filtro (None = no informado)
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
