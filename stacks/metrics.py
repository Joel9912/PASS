"""Métricas y auditoría de los lights registrados.

SirIL entrega métricas al registrar y las escribe en el ``.seq`` de la
secuencia (una línea ``R<capa>`` por imagen: fwhm_x, fwhm_y, redondez,
fondo y nº de estrellas). Con ellas se:

- grafica el comportamiento a lo largo de todas las sesiones,
- puntúa cada frame 0–100 con pesos ajustables y evalúa si descartarlo
  —puntuación mínima + cortes por métrica, cada uno con su motivo—,
  todo dinámico: repuntuar con otros pesos no vuelve a registrar.

SirIL no puntúa: la escala 0–100 y sus pesos son nuestros y los define el
usuario (los de aquí son solo un arranque razonable); las métricas crudas,
en cambio, son suyas.
"""
import math
import statistics
from dataclasses import dataclass

from .registration import Registro


@dataclass
class FrameMetrics:
    """Métricas de un light registrado por SirIL."""

    path: str                # light calibrado de origen (referencia del pool)
    session: str             # sesión a la que pertenece
    fwhm: float              # píxeles (media de fwhm_x/fwhm_y del registro)
    roundness: float         # 0..1 (1 = perfectamente redondo)
    transparency: float      # 0..1 (proxy: fondo mínimo del pool / fondo)
    background: float        # ADU equivalentes 16-bit/s (fracción .seq × 65535 ÷ exposición)
    weighted: float          # puntuación 0..100 para el apilado (puntuar)


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
    conocida se deja crudo.

    Lanza ``ValueError`` si el ``.seq`` no tiene filas de registro, si hay
    más que frames, o si no quedó registrado ni un frame: es mejor fallar
    claro que atribuir métricas a la sesión equivocada.
    """
    datos = _leer_filas_R(registro.ruta_seq)
    if len(datos) > len(registro.frames):
        raise ValueError(
            f"{registro.ruta_seq.name}: {len(datos)} filas de registro para "
            f"{len(registro.frames)} frames."
        )
    metricas = []
    for ref, campos in zip(registro.frames, datos, strict=False):
        fwhm = (float(campos[0]) + float(campos[1])) / 2.0
        roundness = float(campos[2])
        exposicion = ref.exposicion_s or 0.0
        fondo_adu = float(campos[4]) * 65535.0
        fondo = fondo_adu / exposicion if exposicion > 0 else fondo_adu
        if not (fwhm > 0 and fondo > 0 and roundness > 0 and math.isfinite(roundness)):
            continue  # frame descartado por SirIL al registrar: sin métricas
        metricas.append(FrameMetrics(
            path=str(ref.ruta),
            session=ref.sesion,
            fwhm=fwhm,
            roundness=roundness,
            transparency=0.0,  # calculado abajo: depende del fondo del pool
            background=fondo,
            weighted=0.0,
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
    total = pesos.fwhm + pesos.redondez + pesos.transparencia + pesos.fondo
    if total <= 0:
        raise ValueError("La suma de los pesos tiene que ser positiva.")
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
    """
    if not metricas:
        return []
    pesos = pesos or Pesos()
    puntuar(metricas, pesos)
    cortes: dict[str, float | None] = {}
    if pesos.fwhm > 0:
        cortes["fwhm"] = _corte([m.fwhm for m in metricas], sigma, peor="alto")
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
        if cortes.get("fwhm") is not None and m.fwhm > cortes["fwhm"]:
            motivos.append(MOTIVOS["fwhm"])
        if cortes.get("roundness") is not None and m.roundness < cortes["roundness"]:
            motivos.append(MOTIVOS["roundness"])
        if cortes.get("background") is not None and m.background > cortes["background"]:
            motivos.append(MOTIVOS["background"])
        evaluaciones.append(Evaluacion(m, bool(motivos), ", ".join(motivos)))
    return evaluaciones


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
def _leer_filas_R(ruta_seq) -> list[list[str]]:
    """Campos de las líneas ``R<capa>`` del ``.seq``, de la capa más baja.

    El formato .seq de SirIL es texto: ``R<capa> fwhm_x fwhm_y redondez …
    fondo nº_estrellas <tipo> <matriz>``. En RGB hay tres capas (R0/R1/R2);
    con la primera basta (las métricas de registro son por imagen).
    """
    por_capa: dict[int, list[list[str]]] = {}
    for linea in ruta_seq.read_text(encoding="utf-8", errors="replace").splitlines():
        if linea.startswith("R") and linea[1:2].isdigit():
            partes = linea.split()
            por_capa.setdefault(int(partes[0][1:]), []).append(partes[1:])
    if not por_capa:
        raise ValueError(f"{ruta_seq.name} no tiene datos de registro: ¿register no corrió?")
    return por_capa[min(por_capa)]


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
