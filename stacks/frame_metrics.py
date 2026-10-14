"""Métricas y auditoría de los lights registrados.

SirIL entrega métricas al registrar y las escribe en el ``.seq`` de la
secuencia (una línea ``R<capa>`` por imagen: FWHM, FWHM ponderado,
redondez, calidad, fondo y nº de estrellas). Con ellas se:

- grafica el comportamiento a lo largo de todas las sesiones,
- puntúa cada frame 0–100 con pesos ajustables y evalúa si descartarlo
  —puntuación mínima + cortes por métrica, cada uno con su motivo—,
  todo dinámico: repuntuar con otros pesos no vuelve a registrar.

SirIL no puntúa: la escala 0–100 y sus pesos son nuestros y los define el
usuario (los de aquí son solo un arranque razonable); las métricas crudas,
en cambio, son suyas.
"""
import math
import shlex
import statistics
from dataclasses import dataclass

from .registration import Registro


@dataclass
class FrameMetrics:
    """Métricas de un light registrado por SirIL."""

    path: str                # light calibrado de origen (referencia del pool)
    session: str             # sesión a la que pertenece
    fwhm: float              # FWHM de SirIL, sin mezclar su penalización por estrellas
    roundness: float         # 0..1 (1 = perfectamente redondo)
    transparency: float      # 0..1 (proxy: fondo mínimo del pool / fondo)
    background: float        # ADU equivalentes 16-bit/s (fracción .seq × 65535 ÷ exposición)
    weighted: float          # puntuación 0..100 para el apilado (puntuar)
    wfwhm: float | None = None
    stars: int | None = None
    registration_layer: int | None = None
    filtro: str | None = None


@dataclass
class Pesos:
    """Pesos relativos de la puntuación 0–100 (los ajusta el usuario).

    Da igual la suma: se normaliza. Solo puede ser todo cero si no hay nada
    que puntuar.
    """

    fwhm: float = 40.0
    redondez: float = 25.0
    transparencia: float = 20.0
    fondo: float = 15.0


def extract_metrics(registro: Registro, pesos: Pesos | None = None) -> list[FrameMetrics]:
    """Lee las métricas que SirIL dejó en el ``.seq`` durante el registro.

    Cada fila ``R`` corresponde a un índice de la secuencia (el mapeo
    sesión↔frame lo aporta el propio ``Registro``). Las filas de los frames
    que SirIL descartó al registrar (fwhm/fondo a 0 y redondez NaN o 0) se
    saltan: no hay métricas que medir en ellas. Quien quiera avisar del
    descarte compara ``len(metricas)`` con ``len(registro.frames)``.

    El fondo se pasa a **ADU de 16 bits/s** (el ``.seq`` contiene valores
    normalizados 0..1, al igual que los FITS float32 que escribe SirIL):
    crece con la exposición y sin normalizar, una sesión a 60 s parecería
    más contaminada que una a 45 s solo por durar más. Sin exposición
    conocida se deja crudo (limitación pendiente S-0027).

    Lanza ``ValueError`` si el ``.seq`` no tiene filas de registro, si hay
    más que frames, o si no quedó registrado ni un frame: es mejor fallar
    claro que atribuir métricas a la sesión equivocada.
    """
    datos, seleccion, capa = _leer_filas_R(registro)
    metricas = []
    for indice, (ref, campos, incluida) in enumerate(zip(registro.frames, datos, seleccion, strict=True), 1):
        values = _metricas_fila(campos, indice)
        if values is None or not incluida:
            continue
        fwhm, wfwhm, roundness, fondo_normalizado, stars = values
        exposicion = ref.exposicion_s or 0.0
        if not math.isfinite(exposicion) or exposicion < 0:
            raise ValueError(f"Exposición inválida en frame {indice}.")
        fondo_adu = fondo_normalizado * 65535.0
        fondo = fondo_adu / exposicion if exposicion > 0 else fondo_adu
        metricas.append(FrameMetrics(
            path=str(ref.ruta),
            session=ref.sesion,
            fwhm=fwhm,
            roundness=roundness,
            transparency=0.0,  # calculado abajo: depende del fondo del pool
            background=fondo,
            weighted=0.0,
            wfwhm=wfwhm,
            stars=stars,
            registration_layer=capa,
            filtro=ref.filtro,
        ))
    if not metricas:
        raise ValueError("Ningún frame quedó registrado: no hay métricas que extraer.")
    fondo_min = min(m.background for m in metricas)
    for m in metricas:
        m.transparency = fondo_min / m.background
    puntuar(metricas, pesos)
    return metricas


def puntuar(metrics: list[FrameMetrics], pesos: Pesos | None = None) -> None:
    """Puntúa cada frame 0–100 dentro del pool y lo deja en ``weighted``.

    Cada métrica se normaliza (mejor del pool = 1, peor = 0) y se combina
    con los pesos: puntúan el fwhm bajo, la redondez alta, la transparencia
    alta y el fondo bajo. Los pesos los fija el usuario; si todos son cero
    no hay escala posible y se rechaza.
    """
    if not metrics:
        return
    pesos = pesos or Pesos()
    valores_pesos = (pesos.fwhm, pesos.redondez, pesos.transparencia, pesos.fondo)
    if any(not math.isfinite(value) or value < 0 for value in valores_pesos):
        raise ValueError("Los pesos deben ser finitos y no negativos.")
    total = pesos.fwhm + pesos.redondez + pesos.transparencia + pesos.fondo
    if not math.isfinite(total) or total <= 0:
        raise ValueError("La suma de los pesos tiene que ser positiva.")
    for m in metrics:
        for value in (m.fwhm, m.roundness, m.transparency, m.background):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Métrica inválida para {m.path}; no se puede puntuar.")
    norm = {
        "fwhm": _normalizar([m.fwhm for m in metrics], peor="alto"),
        "roundness": _normalizar([m.roundness for m in metrics], peor="bajo"),
        "transparency": _normalizar([m.transparency for m in metrics], peor="bajo"),
        "background": _normalizar([m.background for m in metrics], peor="alto"),
    }
    for i, m in enumerate(metrics):
        m.weighted = 100.0 * (
            pesos.fwhm * norm["fwhm"][i]
            + pesos.redondez * norm["roundness"][i]
            + pesos.transparencia * norm["transparency"][i]
            + pesos.fondo * norm["background"][i]
        ) / total


@dataclass
class Evaluacion:
    """Veredicto de calidad de un frame para la auditoría.

    El motivo es el texto que pinta la tabla: «Puntuación» si el frame
    queda por debajo del mínimo, y el nombre de cada métrica que pasa su
    corte (el lado malo); vacío si el frame entra al apilado.
    """

    metricas: FrameMetrics
    descartada: bool
    motivo: str
    corte_fwhm: float | None = None


#: Textos de motivo (lo que el usuario ve en la tabla de la auditoría).
MOTIVOS = {
    "weighted": "Puntuación",
    "fwhm": "FWHM",
    "roundness": "Redondez",
    "background": "Fondo",
}


def evaluar(
    metricas: list[FrameMetrics],
    pesos: Pesos | None = None,
    *,
    umbral: float = 80.0,
    sigma: float = 3.0,
    criterio_fwhm: str = "mad",
) -> list[Evaluacion]:
    """Repuntúa el pool y decide frame a frame si descartarlo y por qué.

    Dos reglas, cada una con su motivo para que el usuario lo vea en la
    tabla: puntuación por debajo de ``umbral`` («Puntuación») y cortes por
    métrica en el lado malo —fwhm alto, redondez baja, fondo alto— con
    umbral robusto mediana ± σ × 1,4826 × MAD del propio pool. **Una
    métrica con peso 0 no decide nada**: ni puntúa ni corta (si el usuario
    pone Fondo a 0, que no le descarte por fondo). La transparencia no
    corta aparte: dentro del pool es el inverso del fondo. Sin dispersión
    (MAD 0 o menos de 3 frames) esa métrica no corta. Al repuntuar con
    ``pesos`` no hace falta registrar de nuevo.

    El criterio alternativo ``media_minimo`` sustituye solo el corte FWHM
    por media+(media−mínimo)/6 en cada sesión/filtro. No cambia el ranking
    global ni los otros cortes; sigma no interviene en esa fórmula.
    """
    if criterio_fwhm not in ("mad", "media_minimo"):
        raise ValueError("El criterio FWHM no es compatible.")
    if not metricas:
        return []
    if not math.isfinite(umbral) or not math.isfinite(sigma) or umbral < 0 or sigma <= 0:
        raise ValueError("El mínimo y sigma deben ser finitos; sigma debe ser positivo.")
    pesos = pesos or Pesos()
    puntuar(metricas, pesos)
    cortes: dict[str, float | None] = {}
    cortes_fwhm = {}
    if pesos.fwhm > 0:
        if criterio_fwhm == "mad":
            limite = _corte([m.fwhm for m in metricas], sigma, peor="alto")
            cortes_fwhm = {m.path: limite for m in metricas}
        else:
            cortes_fwhm = _cortes_media_minimo(metricas)
    if pesos.redondez > 0:
        cortes["roundness"] = _corte([m.roundness for m in metricas], sigma, peor="bajo")
    if pesos.fondo > 0:
        cortes["background"] = _corte(
            [m.background for m in metricas], sigma, peor="alto"
        )
    evaluaciones = []
    for m in metricas:
        motivos = []
        if m.weighted < umbral:
            motivos.append(MOTIVOS["weighted"])
        limite_fwhm = cortes_fwhm.get(m.path)
        if limite_fwhm is not None and m.fwhm > limite_fwhm:
            motivos.append(MOTIVOS["fwhm"])
        if cortes.get("roundness") is not None and m.roundness < cortes["roundness"]:
            motivos.append(MOTIVOS["roundness"])
        if cortes.get("background") is not None and m.background > cortes["background"]:
            motivos.append(MOTIVOS["background"])
        evaluaciones.append(Evaluacion(m, bool(motivos), ", ".join(motivos), limite_fwhm))
    return evaluaciones


def _cortes_media_minimo(metricas: list[FrameMetrics]) -> dict[str, float]:
    """Aplica media+(media−mínimo)/6 por identidad de sesión/filtro, no por nombre."""
    grupos: dict[tuple[str, str | None], list[FrameMetrics]] = {}
    for m in metricas:
        grupos.setdefault((m.session, m.filtro), []).append(m)
    cortes = {}
    for grupo in grupos.values():
        media = statistics.fmean(m.fwhm for m in grupo)
        minimo = min(m.fwhm for m in grupo)
        limite = media + (media - minimo) / 6
        if not math.isfinite(limite):
            raise ValueError("El límite FWHM calculado no es finito.")
        cortes.update((m.path, limite) for m in grupo)
    return cortes


def _corte(valores: list[float], sigma: float, *, peor: str) -> float | None:
    """Umbral del lado malo: mediana ± σ × 1,4826 × MAD (robusto a extremos).

    La MAD (desviación mediana) no la arrastra el propio extremo, como sí
    hace la desviación típica. Devuelve ``None`` cuando no hay base para
    cortar: menos de tres frames o dispersión cero (todos iguales → nadie
    es un extremo).
    """
    if len(valores) < 3:
        return None
    mediana = statistics.median(valores)
    mad = statistics.median([abs(v - mediana) for v in valores])
    if mad == 0:
        return None
    dispersa = sigma * 1.4826 * mad
    return mediana + dispersa if peor == "alto" else mediana - dispersa


# ------------------------------------------------------------------ internas
def _leer_filas_R(registro: Registro) -> tuple[list[list[str]], list[bool], int]:
    """Valida el contrato FITS de SirIL v4–v6; RGB prefiere verde, azul y rojo.

    No interpreta formatos futuros ni datos CFA de respaldo R* como el canal
    activo. Un déficit de filas no es evidencia de descarte de una imagen.
    """
    ruta_seq = registro.ruta_seq
    por_capa: dict[int, list[list[str]]] = {}
    cabecera = None
    capas = None
    indices = []
    seleccion = []
    for linea in ruta_seq.read_text(encoding="utf-8").splitlines():
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        partes = linea.split()
        if partes[0] == "S":
            if cabecera is not None:
                raise ValueError("Cabecera de secuencia duplicada.")
            cabecera = shlex.split(linea)
        elif partes[0] == "L":
            if capas is not None or len(partes) != 2:
                raise ValueError("Número de canales de secuencia inválido.")
            capas = int(partes[1])
        elif partes[0] == "I":
            if len(partes) != 3 or partes[2] not in ("0", "1"):
                raise ValueError("Selección de imagen de SirIL inválida.")
            indices.append(int(partes[1]))
            seleccion.append(partes[2] == "1")
        elif partes[0].startswith("R"):
            if partes[0] == "R*":
                continue  # registro CFA de respaldo, no canal activo de esta secuencia FITS
            if partes[0] not in ("R0", "R1", "R2"):
                raise ValueError("Canal de registro no compatible.")
            if len(partes) != 17 or partes[7] != "H":
                raise ValueError("Fila de registro incompleta o de formato no compatible.")
            por_capa.setdefault(int(partes[0][1]), []).append(partes[1:])
    if not por_capa:
        raise ValueError(f"{ruta_seq.name} no tiene datos de registro: ¿register no corrió?")
    if cabecera is None or not 8 <= len(cabecera) <= 11:
        raise ValueError("Falta una cabecera de secuencia compatible.")
    version = int(cabecera[7])
    if version not in (4, 5, 6):
        raise ValueError("Versión de secuencia no compatible; no se interpretarán sus métricas.")
    if version == 6 and len(cabecera) != 11:
        raise ValueError("La cabecera v6 de SirIL está incompleta.")
    total = len(registro.frames)
    if cabecera[1] != registro.seq or int(cabecera[3]) != total:
        raise ValueError("La cabecera no corresponde al registro actual.")
    if int(cabecera[2]) != 1 or indices != list(range(1, total + 1)):
        raise ValueError("Índices de secuencia incompletos, duplicados o fuera de orden.")
    if int(cabecera[4]) != sum(seleccion):
        raise ValueError("El número de imágenes seleccionadas no coincide con sus índices.")
    if not 0 <= int(cabecera[6]) < total:
        raise ValueError("La referencia del registro está fuera de la secuencia.")
    if capas not in (1, 3) or any(capa >= capas for capa in por_capa):
        raise ValueError("Los canales de registro no corresponden a la secuencia.")
    for capa, filas in por_capa.items():
        if len(filas) != total:
            raise ValueError(f"{ruta_seq.name}: {len(filas)} filas de registro R{capa} para {total} frames.")
    capa = next(capa for capa in ((1, 2, 0) if capas == 3 else (0,)) if capa in por_capa)
    return por_capa[capa], seleccion, capa


def _metricas_fila(campos: list[str], indice: int) -> tuple | None:
    """Acepta filas medidas y marcadores nulos de SirIL, no NaN como buena calidad."""
    fwhm, wfwhm, roundness, quality, background = map(float, campos[:5])
    stars = int(campos[5])
    matriz = [float(value) for value in campos[7:]]
    if any(not math.isfinite(value) for value in matriz) or stars < 0:
        raise ValueError(f"Registro inválido en frame {indice}.")
    if fwhm == wfwhm == quality == background == stars == 0 and (roundness == 0 or math.isnan(roundness)):
        return None
    values = (fwhm, wfwhm, roundness, quality, background)
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f"Datos no finitos en frame {indice}; auditoría no evaluable.")
    if fwhm <= 0 or roundness <= 0 or background <= 0 or stars == 0:
        raise ValueError(f"Métricas fuera de rango en frame {indice}; auditoría no evaluable.")
    return fwhm, wfwhm, roundness, background, stars


def _normalizar(valores: list[float], *, peor: str) -> list[float]:
    """Normaliza a 0..1 dentro del pool (1 = mejor); `peor` es el extremo malo."""
    if not valores:
        return []
    lo, hi = min(valores), max(valores)
    if hi == lo:
        return [1.0] * len(valores)  # todos iguales: nadie es peor
    if peor == "alto":
        return [(hi - v) / (hi - lo) for v in valores]
    return [(v - lo) / (hi - lo) for v in valores]
