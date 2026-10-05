"""Cálculos de muestreo y resolución óptica de una pareja telescopio+cámara.

Funciones puras (sin UI ni BD): la lógica vive en backend y tanto
``manager.list_setups`` (focal efectiva del FOV) como el bloque «Cálculos»
de la ficha del equipo las reutilizan (R2 — una sola regla).

El veredicto de muestreo no impone verdad: usa dos **umbrales
configurables** (claves de ``settings``: ``sampling_under_ratio`` y
``sampling_over_ratio`` sobre el límite de Dawes, defaults 1.0 y 0.5). Se
leen con ``db.settings.get_float`` y llegan aquí como parámetros: las
métricas las define el usuario.
"""
from .models import Camera, Telescope

#: Segundos de arco por radián (180·3600/π ≈ 206264,806) en unidades de
#: µm/mm: ``píxel/focal`` ya sale en radianes (mm/mm), por eso el factor es
#: 206,265 y no 206264.
_ARCSEC_POR_RADIAN = 206.264806

#: Fórmula de Dawes: resolución resoluble en ″ ≈ 116 / apertura(mm).
_DAWES = 116.0


def focal_efectiva(
    focal_mm: float | None, reducer: bool, reducer_factor: float | None
) -> float | None:
    """Focal que rige el FOV y el muestreo: nominal × factor si hay reductor.

    Única fuente de la regla (la usan ``manager.list_setups`` y
    ``calculos``). Sin focal — o con 0 — no hay dato: ``None``. Un factor
    no positivo se ignora (no debería llegar: ``validar_telescopio`` lo
    rechaza).
    """
    if not focal_mm or focal_mm <= 0:
        return None
    if reducer and reducer_factor and reducer_factor > 0:
        return focal_mm * reducer_factor
    return focal_mm


def escala_imagen(focal_efectiva_mm: float | None, pixel_um: float | None) -> float | None:
    """Escala angular en ″/px = 206,265 × píxel(µm) / focal efectiva(mm).

    Sin focal o sin píxel (≤ 0) no hay escala: ``None``.
    """
    if not focal_efectiva_mm or focal_efectiva_mm <= 0:
        return None
    if pixel_um is None or pixel_um <= 0:
        return None
    return _ARCSEC_POR_RADIAN * pixel_um / focal_efectiva_mm


def limite_dawes(aperture_mm: float | None) -> float | None:
    """Resolución óptica del telescopio (límite de Dawes) en ″ = 116/apertura.

    Es lo que la óptica puede resolver: sirve de referencia para el
    veredicto de muestreo. Sin apertura (o 0): ``None``.
    """
    if not aperture_mm or aperture_mm <= 0:
        return None
    return _DAWES / aperture_mm


def relacion_focal(
    focal_efectiva_mm: float | None, aperture_mm: float | None
) -> float | None:
    """Relación focal F/d = focal efectiva / apertura (None si falta alguno)."""
    if not focal_efectiva_mm or focal_efectiva_mm <= 0:
        return None
    if not aperture_mm or aperture_mm <= 0:
        return None
    return focal_efectiva_mm / aperture_mm


def veredicto_muestreo(
    escala: float | None,
    resolucion: float | None,
    umbral_sub: float = 1.0,
    umbral_sob: float = 0.5,
) -> str | None:
    """«Submuestreado» / «Adecuado» / «Sobremuestreado» según los umbrales.

    - ``escala > umbral_sub × resolución`` → «Submuestreado»: el píxel es
      tan grueso que no resuelve lo que la óptica da.
    - ``escala < umbral_sob × resolución`` → «Sobremuestreado»: píxeles
      más finos de lo que la óptica permite aprovechar.
    - En el intervalo → «Adecuado».

    Sin escala o sin resolución no hay veredicto: ``None`` (la UI pinta
    «—»).
    """
    if escala is None or resolucion is None or resolucion <= 0:
        return None
    if escala > umbral_sub * resolucion:
        return "Submuestreado"
    if escala < umbral_sob * resolucion:
        return "Sobremuestreado"
    return "Adecuado"


def calculos(
    telescopio: Telescope,
    camara: Camera,
    umbral_sub: float = 1.0,
    umbral_sob: float = 0.5,
) -> dict[str, float | str | None]:
    """Todas las filas del bloque «Cálculos» para la pareja en pantalla.

    Toma el telescopio y la cámara **principales tal como están en los
    formularios** (con la entrada del reductor dentro del telescopio) y
    devuelve ``focal_efectiva``, ``escala``, ``dawes``, ``relacion_focal``
    y ``muestreo``; cada clave vale ``None`` cuando falta un dato (la UI
    pinta «—» y explica qué falta).
    """
    focal = focal_efectiva(
        telescopio.focal_mm, telescopio.reducer, telescopio.reducer_factor
    )
    escala = escala_imagen(focal, camara.pixel_size_um)
    dawes = limite_dawes(telescopio.aperture_mm)
    return {
        "focal_efectiva": focal,
        "escala": escala,
        "dawes": dawes,
        "relacion_focal": relacion_focal(focal, telescopio.aperture_mm),
        "muestreo": veredicto_muestreo(escala, dawes, umbral_sub, umbral_sob),
    }
