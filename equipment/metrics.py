"""Cálculos de muestreo y resolución óptica de una pareja telescopio+cámara.

Funciones puras (sin UI ni BD): la lógica vive en backend y tanto
``manager.list_setups`` (focal efectiva del FOV) como el bloque «Cálculos»
de la ficha del equipo las reutilizan (una sola regla).

El veredicto de muestreo no impone verdad: usa dos **umbrales
configurables** (claves de ``settings``: ``sampling_under_ratio`` y
``sampling_over_ratio`` sobre el límite de Dawes, defaults 1.0 y 0.5) y
un **margen «Ligero»** (`sampling_light_factor`, default 1.4) que abre
los dos niveles intermedios. Este módulo es el **dueño de esas claves**:
`umbrales_desde_settings` las recaba de ``settings`` (la UI no las lee
sueltas) y llegan aquí como parámetros: las métricas las define el
usuario. Si la
ubicación informa su **seeing**, `rango_muestreo` recorta el intervalo
adecuado con él y el veredicto pasa por el mismo filtro (sin veredicto
ni límites si no hay dato: nada se inventa).
"""
from .models import Camera, Telescope

#: Segundos de arco por radián (180·3600/π ≈ 206264,806) en unidades de
#: µm/mm: ``píxel/focal`` ya sale en radianes (mm/mm), por eso el factor es
#: 206,265 y no 206264. **Única fuente** (A-10): la usan `escala_imagen`,
#: `stacks/session_parser.campo_vision` y el panel Sesiones del Apilador.
ARCSEC_POR_RADIAN = 206.264806

#: Fórmula de Dawes: resolución resoluble en ″ ≈ 116 / apertura(mm).
_DAWES = 116.0


def umbrales_desde_settings() -> dict[str, float]:
    """Los tres umbrales configurables del muestreo leídos de ``settings``.

    Dueño de las claves de Configuración ``sampling_*``: la UI llama a
    esto en vez de leer las claves sueltas. El
    import de ``db`` es local para no ensuciar la pureza del resto.
    """
    from db.settings import get_float

    return {
        "umbral_sub": get_float("sampling_under_ratio", 1.0),
        "umbral_sob": get_float("sampling_over_ratio", 0.5),
        "factor_ligero": get_float("sampling_light_factor", 1.4),
    }


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
    return ARCSEC_POR_RADIAN * pixel_um / focal_efectiva_mm


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


def limites_muestreo(
    resolucion: float | None,
    umbral_sub: float = 1.0,
    umbral_sob: float = 0.5,
    seeing: float | None = None,
    factor_ligero: float = 1.4,
) -> tuple[float, float, float, float] | None:
    """Los 4 bordes de los 5 niveles de muestreo (None sin resolución).

    Sobre `rango_muestreo` — ``(bajo, alto)`` es «Muestreo Correcto» —
    se abren los márgenes «Ligero» multiplicando por ``factor_ligero``
    (de Configuración: ``sampling_light_factor``). Devuelve
    ``(bajo_ligero, bajo, alto, alto_ligero)``: entre ``bajo_ligero`` y
    ``bajo`` manda «Sobremuestreado Ligero» y entre ``alto`` y
    ``alto_ligero`` «Submuestreado Ligero». Factor < 1 → se trata como
    1 (sin margen) para no invertir las zonas.
    """
    rango = rango_muestreo(resolucion, umbral_sub, umbral_sob, seeing)
    if rango is None:
        return None
    factor = max(1.0, factor_ligero)
    bajo, alto = rango
    return (bajo / factor, bajo, alto, alto * factor)


def veredicto_muestreo(
    escala: float | None,
    resolucion: float | None,
    umbral_sub: float = 1.0,
    umbral_sob: float = 0.5,
    seeing: float | None = None,
    factor_ligero: float = 1.4,
) -> str | None:
    """Los 5 niveles de muestreo según la posición de ``escala``.

    De píxel grueso a fino, contra `limites_muestreo` (los mismos
    umbrales, el seeing de la ubicación si se pasa y el margen
    «Ligero»):

    - «Submuestreado» / «Submuestreado Ligero»: por encima del alto del
      rango (más allá del margen «Ligero» o dentro de él).
    - «Muestreo Correcto»: dentro del rango, **fronteras incluidas**.
    - «Sobremuestreado Ligero» / «Sobremuestreado»: por debajo del bajo.

    Sin escala o sin resolución no hay veredicto: ``None`` (la UI pinta
    «—»).
    """
    limites = limites_muestreo(
        resolucion, umbral_sub, umbral_sob, seeing, factor_ligero
    )
    if escala is None or limites is None:
        return None
    bajo_ligero, bajo, alto, alto_ligero = limites
    if escala > alto_ligero:
        return "Submuestreado"
    if escala > alto:
        return "Submuestreado Ligero"
    if escala < bajo_ligero:
        return "Sobremuestreado"
    if escala < bajo:
        return "Sobremuestreado Ligero"
    return "Muestreo Correcto"


def calculos(
    telescopio: Telescope,
    camara: Camera,
    umbral_sub: float = 1.0,
    umbral_sob: float = 0.5,
    seeing: float | None = None,
    factor_ligero: float = 1.4,
) -> dict[str, float | str | tuple[float, float, float, float] | None]:
    """Todas las filas del bloque «Cálculos» para la pareja en pantalla.

    Toma el telescopio y la cámara **principales tal como están en los
    formularios** (con la entrada del reductor dentro del telescopio) y
    devuelve ``focal_efectiva``, ``escala``, ``dawes``,
    ``relacion_focal``, ``muestreo`` (veredicto de 5 niveles) y
    ``muestreo_limites`` (los 4 bordes que pinta la barra, sobre la
    banda recortada por el ``seeing`` de la ubicación si la hay); cada
    clave vale ``None`` cuando falta un dato (la UI pinta «—» y explica
    qué falta).
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
        "muestreo": veredicto_muestreo(
            escala, dawes, umbral_sub, umbral_sob, seeing, factor_ligero
        ),
        "muestreo_limites": limites_muestreo(
            dawes, umbral_sub, umbral_sob, seeing, factor_ligero
        ),
    }
