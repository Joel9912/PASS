"""Validaciones de las entidades de equipo (ValueError con mensaje en castellano).

Un solo sitio para las reglas de la tabla del plan (paso 1): los CRUD llaman
a éstas antes de tocar la base y los tests las ejercitan por entero. La UI
no valida a medias — si un valor no pasa aquí, no se guarda.
"""
from .models import (
    BIT_DEPTHS,
    CATEGORIES,
    DIRECTIONS,
    FILTER_TYPES,
    LP_SOURCES,
    MOUNT_TYPES,
    OBSTRUCTION_ALTITUDES,
    OPTICAL_TYPES,
    Camera,
    EquipmentSetup,
    Filter,
    Location,
    Mount,
    Telescope,
)


def _nombre(nombre: str, entidad: str) -> None:
    """Exige un nombre no vacío (espacios en blanco = vacío)."""
    if not str(nombre or "").strip():
        raise ValueError(f"{entidad}: el nombre no puede estar vacío.")


def _precio_peso(price_eur: float | None, weight_kg: float | None = None) -> None:
    """Precio y peso de la pieza ≥ 0 (``None`` = no informado, no valida).

    El filtro solo tiene precio: se le pasa el peso como ``None``.
    """
    if price_eur is not None and price_eur < 0:
        raise ValueError("El precio no puede ser negativo.")
    if weight_kg is not None and weight_kg < 0:
        raise ValueError("El peso no puede ser negativo.")


def validar_ubicacion(location: Location) -> None:
    """Rangos geográficos, bloque de sitio y Bortle obligatorio (1-9)."""
    _nombre(location.name, "Ubicación")
    if not -90 <= location.latitude <= 90:
        raise ValueError("Latitud fuera de rango: debe estar entre -90 y 90.")
    if not -180 <= location.longitude <= 180:
        raise ValueError("Longitud fuera de rango: debe estar entre -180 y 180.")
    if location.utc_offset_hours is not None and not -12 <= location.utc_offset_hours <= 14:
        raise ValueError("Desfase horario fuera de rango: debe estar entre -12 y 14 horas.")
    if location.bortle is None or not 1 <= location.bortle <= 9:
        raise ValueError("Bortle obligatorio: indica un nivel del 1 al 9.")
    if location.sqm is not None and location.sqm < 0:
        raise ValueError("El SQM no puede ser negativo.")
    # El sitio se guarda SIEMPRE con las 8 direcciones (roundtrip completo).
    if set(location.obstacles) != set(DIRECTIONS):
        raise ValueError("El horizonte debe describir las 8 direcciones (N, NE, E, SE, S, SO, O, NO).")
    for direccion, grados in location.obstacles.items():
        if not isinstance(grados, int) or grados not in OBSTRUCTION_ALTITUDES:
            raise ValueError(f"Altura de obstáculo desconocida {grados!r} en {direccion}.")
    if set(location.lp) != set(DIRECTIONS):
        raise ValueError("La contaminación lumínica debe describir las 8 direcciones.")
    for direccion, cl in location.lp.items():
        if not isinstance(cl, dict) or "fuente" not in cl:
            raise ValueError(f"CL mal formada en {direccion} (falta «fuente»).")
        fuente = cl.get("fuente")
        if fuente is not None and fuente not in LP_SOURCES:
            raise ValueError(f"Fuente de CL desconocida {fuente!r} en {direccion}.")
        if fuente is not None:
            km = cl.get("km")
            if not isinstance(km, (int, float)) or km <= 0:
                raise ValueError(f"Los km de CL en {direccion} deben ser mayores que 0.")


def validar_telescopio(telescope: Telescope) -> None:
    """Óptica: nombre, no negativos y tipos del catálogo."""
    _nombre(telescope.name, "Telescopio")
    if telescope.aperture_mm is not None and telescope.aperture_mm < 0:
        raise ValueError("La apertura no puede ser negativa.")
    if telescope.focal_mm is not None and telescope.focal_mm < 0:
        raise ValueError("La distancia focal no puede ser negativa.")
    if telescope.reducer_factor is not None and telescope.reducer_factor <= 0:
        raise ValueError("El factor del reductor debe ser mayor que 0.")
    _precio_peso(telescope.price_eur, telescope.weight_kg)
    if telescope.optical_type is not None and telescope.optical_type not in OPTICAL_TYPES:
        raise ValueError(f"Tipo de óptica desconocido: {telescope.optical_type!r}.")


def validar_camara(camera: Camera) -> None:
    """Cámara: nombre, sensor/píxel no negativos y bits > 0."""
    _nombre(camera.name, "Cámara")
    if camera.pixel_size_um is not None and camera.pixel_size_um < 0:
        raise ValueError("El tamaño de píxel no puede ser negativo.")
    if camera.width_px is not None and camera.width_px < 0:
        raise ValueError("El ancho del sensor no puede ser negativo.")
    if camera.height_px is not None and camera.height_px < 0:
        raise ValueError("El alto del sensor no puede ser negativo.")
    if camera.bit_depth is not None and camera.bit_depth not in BIT_DEPTHS:
        raise ValueError(
            f"Profundidad de bits no admitida: {camera.bit_depth} "
            f"(admite {', '.join(str(bits) for bits in BIT_DEPTHS)})."
        )
    _precio_peso(camera.price_eur, camera.weight_kg)


def validar_montura(mount: Mount) -> None:
    """Montura: nombre, capacidad no negativa y tipo del catálogo."""
    _nombre(mount.name, "Montura")
    if mount.payload_kg is not None and mount.payload_kg < 0:
        raise ValueError("La capacidad de carga no puede ser negativa.")
    _precio_peso(mount.price_eur, mount.weight_kg)
    if mount.mount_type is not None and mount.mount_type not in MOUNT_TYPES:
        raise ValueError(f"Tipo de montura desconocido: {mount.mount_type!r}.")


def validar_filtro(filt: Filter) -> None:
    """Filtro: nombre, precio no negativo y tipo del catálogo."""
    _nombre(filt.name, "Filtro")
    _precio_peso(filt.price_eur)
    if filt.filter_type is not None and filt.filter_type not in FILTER_TYPES:
        raise ValueError(f"Tipo de filtro desconocido: {filt.filter_type!r}.")


def validar_setup(setup: EquipmentSetup) -> None:
    """Setup: nombre y categoría del enum del usuario."""
    _nombre(setup.name, "Equipo")
    if setup.category not in CATEGORIES:
        raise ValueError(f"Categoría desconocida: {setup.category!r}.")
