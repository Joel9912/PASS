"""Cálculos de muestreo y resolución óptica de una pareja telescopio+cámara.

Funciones puras (sin UI ni BD): la lógica vive en backend y tanto
``manager.list_setups`` (focal efectiva del FOV) como el bloque «Cálculos»
de la ficha del equipo las reutilizan (R2 — una sola regla).

El veredicto de muestreo no impone verdad: usa dos **umbrales
configurables** (claves de ``settings``: ``sampling_under_ratio`` y
``sampling_over_ratio`` sobre el límite de Dawes, defaults 1.0 y 0.5). Se
leen con ``db.settings.get_float`` y llegan aquí como parámetros: las
métricas las define el usuario. Si la ubicación informa su **seeing**,
`rango_muestreo` recorta el intervalo adecuado con él y el veredicto
pasa por el mismo filtro (sin veredicto ni rango si no hay dato: nada se
inventa).
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


def rango_muestreo(
    resolucion: float | None,
    umbral_sub: float = 1.0,
    umbral_sob: float = 0.5,
    seeing: float | None = None,
) -> tuple[float, float] | None:
    """Rango de escala adecuado ``[bajo, alto]`` en ″/px (None sin resolución).

    La banda de Dawes es ``[resolución × umbral_sob, resolución ×
    umbral_sub]`` — los mismos umbrales del veredicto: dentro de ella la
    escala no está ni sub ni sobremuestreada. Si la ubicación informa su
    seeing FWHM, se recorta además a lo que ese ciel permite muestrear
    bien: ``[máx(bajo_dawes, seeing/4), mín(alto_dawes, seeing/2)]``.

    Si las dos bandas salen disjuntas (el seeing y la resolución se
    contradicen), gana la de escala más fina: es la que nunca pierde
    detalle real; la otra solo aportaba eficiencia.
    """
    if not resolucion or resolucion <= 0:
        return None
    banda_optica = (resolucion * umbral_sob, resolucion * umbral_sub)
    if seeing is None or seeing <= 0:
        return banda_optica
    banda_seeing = (seeing / 4.0, seeing / 2.0)
    bajo = max(banda_optica[0], banda_seeing[0])
    alto = min(banda_optica[1], banda_seeing[1])
    if bajo > alto:  # disjuntas → la banda inferior (escala más fina)
        return banda_seeing if banda_seeing[1] < banda_optica[0] else banda_optica
    return (bajo, alto)


def veredicto_muestreo(
    escala: float | None,
    resolucion: float | None,
    umbral_sub: float = 1.0,
    umbral_sob: float = 0.5,
    seeing: float | None = None,
) -> str | None:
    """«Submuestreado» / «Adecuado» / «Sobremuestreado» según los umbrales.

    El veredicto es la posición de ``escala`` dentro de `rango_muestreo`
    (con los mismos umbrales y, si se pasa, el seeing de la ubicación):

    - por encima del alto → «Submuestreado»: el píxel es tan grueso que
      no resuelve lo que se ve.
    - por debajo del bajo → «Sobremuestreado»: píxeles más finos de lo
      que la óptica permite aprovechar.
    - dentro, **fronteras incluidas** → «Adecuado».

    Sin escala o sin resolución no hay veredicto: ``None`` (la UI pinta
    «—»).
    """
    rango = rango_muestreo(resolucion, umbral_sub, umbral_sob, seeing)
    if escala is None or rango is None:
        return None
    bajo, alto = rango
    if escala > alto:
        return "Submuestreado"
    if escala < bajo:
        return "Sobremuestreado"
    return "Adecuado"


def calculos(
    telescopio: Telescope,
    camara: Camera,
    umbral_sub: float = 1.0,
    umbral_sob: float = 0.5,
    seeing: float | None = None,
) -> dict[str, float | str | tuple[float, float] | None]:
    """Todas las filas del bloque «Cálculos» para la pareja en pantalla.

    Toma el telescopio y la cámara **principales tal como están en los
    formularios** (con la entrada del reductor dentro del telescopio) y
    devuelve ``focal_efectiva``, ``escala``, ``dawes``, ``relacion_focal``,
    ``muestreo`` y ``muestreo_rango`` (el intervalo adecuado ″/px que
    pintan la pista y la barra, recortado por el ``seeing`` de la
    ubicación si la hay); cada clave vale ``None`` cuando falta un dato
    (la UI pinta «—» y explica qué falta).
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
        "muestreo": veredicto_muestreo(escala, dawes, umbral_sub, umbral_sob, seeing),
        "muestreo_rango": rango_muestreo(dawes, umbral_sub, umbral_sob, seeing),
    }
