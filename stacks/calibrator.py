"""Calibración automática de sesiones con SirIL.

Flujo: para cada sesión, calibra sus lights usando sus propios flats/darks/bias
(o los másters si la sesión los trae, o la carpeta global de calibrado que el
usuario haya configurado) y escribe la salida en la CARPETA DE TRABAJO:
``working_folder/calibrados/<sesion>/``.

Los originales NUNCA se tocan: la calibración produce ficheros nuevos en la
carpeta de trabajo (salida controlada de SirIL, no una copia redundante) y
SirIL ni siquiera entra en la sesión (los enlaces los crea Python).

Orden de preferencia del material de cada tipo (bias/dark/flat/dark_flat):
1. másters que trae la sesión (``masters/``), 2. sus frames sueltos (se
apilan másters nuevos), 3. másters de la carpeta global configurada,
4. frames sueltos de la carpeta global (el máster global se apila una vez y
se reutiliza). Si falta todo, se calibra sin esa corrección y se avisa.

Gotchas de SirIL 1.4.4 (validados con el binario real, ver ``stacks/README.md``):
- ``calibrate`` solo calibra secuencias de 16 bits; con lights float32 aborta,
  así que se comprueba antes de ejecutar (``_exigir_enteros_16bit``).
- Las rutas con espacios solo se aceptan entrecomillando TODO el argumento
  (``"-dark=/ruta con espacios/m.fits"``): ver ``siril_runner.arg_ruta``.
- ``-opt`` a secas provoca SIGSEGV en el CLI; se usa ``-opt=exp`` (y solo si
  los lights traen EXPOSURE, si no se avisa y se omite).
- La calibración es CRUDA: sin ``-debayer`` (el rebayerizado lo decide el
  usuario en el paso Apilar, con la casilla Drizzle) y sin ``-cfa`` (no
  cambia ni un píxel, verificado comparando salidas con y sin la bandera).
- SirIL resta dark Y bias si recibe los dos: si el máster de dark ya
  trae el bias dentro (mediana ≈ bias), la doble sustracción recorta el
  fondo a cero — ``dark_incluye_bias`` lo detecta y omite el ``-bias``.
- Los avisos «...solo se pueden mantener si ... 16 bits. Anulando.» del log
  son ruido no fatal: el éxito lo decide el runner (exit + marcadores + salida).
"""
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from astropy.io import fits

from db.connection import get_connection

from .session_parser import RAW_EXTS, Session, exposure_de, parse_calibration_folder
from .siril_runner import (
    WORKING_FOLDER,
    SirilError,
    arg_ruta,
    ejecutar_script,
    enlazar,
    limpiar_trabajo,
    ultima_secuencia,
)

CALIBRATED_DIR = Path("calibrados")

#: Carpeta de trabajo del material de calibrado global (másters apilados una
#: vez y reutilizados por todas las sesiones que los necesiten).
GLOBAL_DIR_NAME = "_global_"

#: Setting donde el usuario apunta a la carpeta global de calibrado
#: (bias/darks compartidos entre sesiones; puede traer másters o frames).
SETTING_GLOBAL_DIR = "stacks_global_calibration_dir"

#: De nombre de subcarpeta de sesión a tipo canónico de material.
#: (``Session.frames`` usa nombres de carpeta; ``masters`` y el material
#: global usan el canónico.)
A_CANONICO = {"bias": "bias", "darks": "dark", "flats": "flat", "dark_flats": "dark_flat"}
#: Inversa: tipo canónico → nombre de subcarpeta dentro de la sesión.
A_CARPETA = {canonico: carpeta for carpeta, canonico in A_CANONICO.items()}

#: Nombre de la secuencia SirIL (y del enlace base) por tipo canónico.
SEQ_POR_TIPO = {"bias": "bias", "dark": "dark", "flat": "flat",
                "dark_flat": "darkflat", "light": "light"}


@dataclass
class CalibrationResult:
    """Resultado de calibrar una sesión."""

    session: Session
    dir: Path                          # data/working/calibrados/<sesion>
    n_lights: int = 0                  # ficheros pp_light_* generados
    exposure_s: float | None = None    # exposición por frame (cabecera FITS)
    masters: dict[str, Path] = field(default_factory=dict)  # tipo -> máster usado
    avisos: list[str] = field(default_factory=list)         # p. ej. «sin flat»


def calibrated_dir_for(session: Session) -> Path:
    """Devuelve la subcarpeta de calibrados de esa sesión (y la crea si falta)."""
    target = WORKING_FOLDER / CALIBRATED_DIR / session.path.name
    target.mkdir(parents=True, exist_ok=True)
    return target


def calibrate_session(
    session: Session,
    *,
    opt: bool = False,
    cc: bool = False,
    progress_cb=None,
    log_cb=None,
    global_dir: str | None = None,
) -> CalibrationResult:
    """Calibra los lights de una sesión con SirIL y devuelve la carpeta de salida.

    - Si la sesión trae másters, los usa directamente.
    - Si no, genera los másters con SirIL a partir de flats/darks/bias.
    - Si le faltan bias/darks, recurre a ``global_dir`` (la carpeta global
      que la UI resuelve del setting ``stacks_global_calibration_dir`` y
      pasa por parámetro: aquí no se toca la BD).
    - Nunca escribe dentro de ``session.path`` (origen de solo lectura).

    Args:
        opt: optimiza la sustracción de dark (``-opt=exp``, usando la
            exposición de los frames); solo se emite con bias+dark+EXPOSURE,
            si no se omite avisando en ``resultado.avisos``.
        cc: corrección cosmética con el dark (``-cc=dark``); idem con dark.
        progress_cb: recibe la fracción 0..1 del trabajo de la sesión por
            etapas: 0–0.5 másters y flats, 0.5–1.0 calibrado de lights
            (la fase larga). El log detalla cada paso intermedio.
        log_cb: recibe cada línea del log de SirIL (terminal de la UI).
    """
    destino = WORKING_FOLDER / CALIBRATED_DIR / session.path.name
    origen = session.path.resolve()
    salida = destino.resolve()
    entradas = (
        path.resolve()
        for paths in session.frames.values()
        for path in paths
    )
    if (
        origen.is_relative_to(salida)
        or salida.is_relative_to(origen)
        or any(path.is_relative_to(salida) for path in entradas)
        or any(path.resolve().is_relative_to(salida) for path in session.masters.values())
    ):
        raise ValueError("La sesión o sus tomas se solapan con la salida de calibración.")
    destino = calibrated_dir_for(session)
    limpiar_trabajo(destino, raiz=WORKING_FOLDER / CALIBRATED_DIR)

    resultado = CalibrationResult(session=session, dir=destino)
    if progress_cb:
        progress_cb(0.0)

    masters_usados = _reunir_masters(
        session, destino, resultado, log_cb=log_cb, global_dir=global_dir
    )
    if log_cb:
        for tipo, ruta in masters_usados.items():
            procedencia = (
                "sesión" if ruta.is_relative_to(session.path) else
                "generado en working" if ruta.is_relative_to(WORKING_FOLDER) else
                "carpeta global/externa"
            )
            log_cb(f"Máster {tipo} ({procedencia}): {ruta.absolute()}")
    flats_calibrados = _preparar_flats(session, destino, masters_usados, log_cb=log_cb)
    if progress_cb:
        progress_cb(0.5)

    _calibrar_lights(
        session, destino, masters_usados, resultado,
        flats_calibrados=flats_calibrados,
        opt=opt, cc=cc,
        progress_cb=(lambda f: progress_cb(0.5 + 0.5 * f)) if progress_cb else None,
        log_cb=log_cb,
    )
    if progress_cb:
        progress_cb(1.0)
    return resultado


def save_calibration(result: CalibrationResult) -> None:
    """Persiste la sesión calibrada en la tabla ``calibrated_sessions`` (upsert)."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO calibrated_sessions (session_dir, calibrated_dir, n_frames, exposure_s)"
        " VALUES (?, ?, ?, ?)"
        " ON CONFLICT(session_dir) DO UPDATE SET"
        "   calibrated_dir = excluded.calibrated_dir,"
        "   n_frames = excluded.n_frames,"
        "   exposure_s = excluded.exposure_s,"
        "   created_at = datetime('now')",
        (str(result.session.path), str(result.dir), result.n_lights, result.exposure_s),
    )
    conn.commit()


def list_calibrated() -> list[dict]:
    """Sesiones calibradas guardadas (para reconstruir el pool sin recalibrar)."""
    conn = get_connection()
    filas = conn.execute(
        "SELECT session_dir, calibrated_dir, n_frames, exposure_s FROM calibrated_sessions"
        " ORDER BY session_dir"
    ).fetchall()
    return [dict(fila) for fila in filas]


def delete_calibrated(session_dir: str) -> None:
    """Olvida una sesión calibrada (no borra ficheros: eso es limpieza manual)."""
    conn = get_connection()
    conn.execute("DELETE FROM calibrated_sessions WHERE session_dir = ?", (session_dir,))
    conn.commit()


# ------------------------------------------------------------------ internas
def _reunir_masters(
    session: Session, destino: Path, resultado: CalibrationResult, *,
    log_cb=None, global_dir: str | None = None,
) -> dict[str, Path]:
    """Reúne (y si hace falta genera) los másters de la sesión.

    Los tipos que falten se anotan como aviso en ``resultado``: la
    calibración sigue adelante sin esa corrección.
    """
    masters: dict[str, Path] = {}
    faltan: set[str] = set()
    global_masters, global_frames = _material_global(global_dir)

    for tipo in ("bias", "dark", "flat", "dark_flat"):
        # 1) Máster traido por la propia sesión.
        if tipo in session.masters:
            masters[tipo] = session.masters[tipo]
            continue
        # 2) Frames sueltos de la sesión → máster nuevo en su subcarpeta.
        carpeta = A_CARPETA.get(tipo)
        frames = session.frames.get(carpeta, []) if carpeta else []
        if frames:
            if tipo == "flat":
                # El máster de flat se apila en _preparar_flats (puede
                # requerir calibrar los flats con dark_flat antes).
                continue
            masters[tipo] = _apilar_master(tipo, frames, destino, log_cb=log_cb)
            continue
        # 3/4) Carpeta global: másters directos o frames apilados una vez.
        if tipo in global_masters:
            masters[tipo] = global_masters[tipo]
            continue
        if tipo in global_frames:
            masters[tipo] = _apilar_master_global(tipo, global_frames[tipo], log_cb=log_cb)
            continue
        faltan.add(tipo)

    resultado.masters = masters
    resultado.avisos.extend(_avisos_de_faltantes(faltan))
    return masters


def _preparar_flats(
    session: Session,
    destino: Path,
    masters: dict[str, Path],
    *,
    log_cb=None,
) -> Path | None:
    """Apila el máster de flat, calibrando los flats crudos si hay dark_flat.

    Devuelve la ruta del máster de flat (o ``None`` si no hay flat de
    ninguna forma). Los flats de la sesión se apilan aquí (no en
    ``_reunir_masters``) porque pueden necesitar el paso de calibrado con el
    dark_flat justo antes.
    """
    if "flat" in masters:  # la sesión (o el global) ya traían máster
        return masters["flat"]

    frames = session.frames.get(A_CARPETA["flat"], [])
    if not frames:
        return None

    trabajo = destino / "flat"
    if "dark_flat" in masters:
        _exigir_enteros_16bit(frames, "Los flats")
        seq = _enlazar_frames(frames, trabajo, SEQ_POR_TIPO["flat"], log_cb=log_cb)
        arg_dark_flat = arg_ruta(f"-dark={masters['dark_flat']}")
        res = ejecutar_script(
            [f"calibrate {seq} {arg_dark_flat}"],
            cwd=trabajo, log_cb=log_cb,
        )
        if not res.ok:
            raise SirilError(f"No se pudieron calibrar los flats: {res.motivo}")
        seq = ultima_secuencia(trabajo, f"pp_{seq}")
    else:
        seq = _enlazar_frames(frames, trabajo, SEQ_POR_TIPO["flat"], log_cb=log_cb)

    # Mismo camino de `stack` que el resto de másters (A-08): allí vive la
    # regla de mediana vs rechazo sigma según el número de frames.
    master = _apilar_master_en(trabajo, seq, "flat", len(frames), log_cb=log_cb)
    masters["flat"] = master
    return master


def _apilar_master(
    tipo: str, frames: list[Path], destino: Path, *, log_cb=None
) -> Path:
    """Apila un máster de la sesión a partir de sus frames sueltos."""
    trabajo = destino / A_CARPETA[tipo]
    seq = _enlazar_frames(frames, trabajo, SEQ_POR_TIPO[tipo], log_cb=log_cb)
    return _apilar_master_en(trabajo, seq, tipo, len(frames), log_cb=log_cb)


def _apilar_master_en(
    trabajo: Path,
    seq: str,
    tipo: str,
    n_frames: int,
    *,
    log_cb=None,
) -> Path:
    """Ejecuta ``stack`` de la secuencia ``seq`` en ``trabajo`` (máster).

    La secuencia debe existir ya (la crea ``_enlazar_frames`` con
    ``link``/``convertraw``); aquí solo se apila. Con pocos frames el
    rechazo sigma no tiene muestras con qué trabajar: mediana y punto.
    """
    master = trabajo / f"master_{tipo}.fits"
    modo = "rej s 3 3" if n_frames >= 5 else "med"
    res = ejecutar_script(
        [f"stack {seq} {modo} -nonorm -32b -out={master.name}"],
        cwd=trabajo, log_cb=log_cb,
    )
    if not res.ok or not master.exists():
        raise SirilError(f"No se pudo apilar el máster de {tipo}: {res.motivo}")
    return master


def _apilar_master_global(
    tipo: str, frames: list[Path], *, log_cb=None
) -> Path:
    """Apila (o reutiliza) el máster global de un tipo en ``_global_``.

    Se apila una sola vez y se cachea en la carpeta de trabajo: la siguiente
    sesión que necesite ese máster lo reutiliza. La limpieza manual de
    intermedios lo borra para regenerarlo con frames nuevos.
    """
    trabajo = WORKING_FOLDER / CALIBRATED_DIR / GLOBAL_DIR_NAME / A_CARPETA[tipo]
    master = trabajo / f"master_{tipo}.fits"
    if master.exists():
        return master
    # Estado a medias de una corrida anterior: vaciar para que link solo
    # coja los frames nuevos (un link con salidas viejas duplica frames).
    limpiar_trabajo(trabajo, raiz=WORKING_FOLDER / CALIBRATED_DIR)
    seq = _enlazar_frames(frames, trabajo, SEQ_POR_TIPO[tipo], log_cb=log_cb)
    return _apilar_master_en(trabajo, seq, tipo, len(frames), log_cb=log_cb)


def _enlazar_frames(
    frames: list[Path], trabajo: Path, base_seq: str, *, log_cb=None
) -> str:
    """Crea enlaces a los frames y la secuencia SirIL en ``trabajo``.

    Los enlaces los crea Python (SirIL nunca entra en la sesión original).
    Después SirIL forma la secuencia en la carpeta de trabajo:
    ``convertraw`` para RAW (los RAW no son FITS enlazables: hay que
    convertirlos) o ``link`` para FITS. Los directorios mezclando FITS y RAW
    no se soportan (los capture servers los separan en la práctica).

    Returns:
        El nombre real de la secuencia creada, leído del ``.seq`` en disco
        (SirIL normaliza ``light_0001`` → secuencia ``light_``).
    """
    trabajo.mkdir(parents=True, exist_ok=True)
    hay_raw = any(f.suffix.lower() in RAW_EXTS for f in frames)
    for frame in frames:
        enlace = trabajo / frame.name
        if not enlace.exists():
            enlazar(frame, enlace)
        if log_cb and base_seq == "light":
            log_cb(f"Origen → enlace: {frame.absolute()} → {enlace.absolute()}")
    orden = f"convertraw {base_seq}" if hay_raw else f"link {base_seq}"
    res = ejecutar_script([orden], cwd=trabajo, log_cb=log_cb)
    if not res.ok:
        raise SirilError(f"No se pudo crear la secuencia {base_seq}: {res.motivo}")
    return ultima_secuencia(trabajo, base_seq)


def _exigir_enteros_16bit(frames: list[Path], contexto: str) -> None:
    """Rechaza lights/flats float32 antes de invocar a SirIL.

    ``calibrate`` de SirIL 1.4.4 solo procesa secuencias de 16 bits y con
    float32 aborta en mitad con un log enrevesado; aquí sale un error claro
    sin haber ejecutado nada.
    """
    try:
        with fits.open(frames[0], memmap=True) as hdul:
            bitpix = int(hdul[0].header.get("BITPIX", 16))
    except Exception:  # cabecera ilegible: que decida SirIL
        return
    if bitpix < 0:  # -32/-64: punto flotante
        raise SirilError(
            f"{contexto}: SirIL solo calibra secuencias de 16 bits y "
            f"{frames[0].name} es de punto flotante (BITPIX {bitpix}). "
            "Convierte los frames a 16 bits antes de calibrar."
        )


def _avisos_de_faltantes(faltan: set[str]) -> list[str]:
    """Avisos en español de las correcciones que no se aplicarán."""
    nombres = {"bias": "bias", "dark": "darks", "flat": "flats", "dark_flat": "dark flats"}
    return [
        f"Sin {nombres[tipo]} disponibles: se calibró sin esa corrección."
        for tipo in sorted(faltan)
        if tipo in ("bias", "dark", "flat")  # el dark_flat ausente no es noticia
    ]


def dark_incluye_bias(med_bias: float | None, med_dark: float | None) -> bool:
    """¿El máster de dark ya contiene el nivel de bias? (comparación de medianas).

    SirIL 1.4.4 resta dark Y bias cuando recibe los dos (validado con el
    binario): si el dark ya traía el bias dentro —típico al apilar los
    darks sin restar el bias—, la doble sustracción recorta el fondo a cero
    y corta señal. Umbral 0,7: con dark ≥ 0,7×bias se da por «con bias
    dentro» (también lo es el oscuro con corriente apreciable); un dark
    apilado SIN bias tiene la mediana de la corriente sola y sale muy por
    debajo, así que sí se le pasa el bias.
    """
    if not med_bias or med_dark is None or med_bias <= 0:
        return False
    return med_dark >= 0.7 * med_bias


def _mediana_frame(ruta: Path) -> float | None:
    """Mediana de píxeles del FITS (muestra rala), o ``None`` si no es legible.

    Se lee sin ``memmap``: astropy no puede escalar así los uint16 de los
    másters (BZERO/BSCALE) y aborta. La muestra cada 8 filas/columnas basta
    para comparar niveles ADU y evita partir arrays de 24 Mpx enteros.
    """
    try:
        datos = fits.getdata(ruta, memmap=False)
        if datos is None or datos.size == 0:
            return None
        muestra = datos[::8, ::8] if datos.ndim >= 2 else datos
        return float(np.median(muestra))
    except Exception:  # fichero ilegible: mejor pasar el bias de más
        return None


def _calibrar_lights(
    session: Session,
    destino: Path,
    masters: dict[str, Path],
    resultado: CalibrationResult,
    *,
    flats_calibrados: Path | None,
    opt: bool = False,
    cc: bool = False,
    progress_cb=None,
    log_cb=None,
) -> None:
    """Enlaza los lights, los calibra con SirIL y mide el resultado."""
    lights = session.frames.get("lights", [])
    if not lights:
        raise SirilError(f"La sesión {session.path.name} no tiene lights.")
    if masters or flats_calibrados is not None:
        _exigir_enteros_16bit(lights, f"Los lights de {session.path.name}")

    trabajo = destino / "light"
    seq = _enlazar_frames(lights, trabajo, SEQ_POR_TIPO["light"], log_cb=log_cb)

    args = ["calibrate", seq]
    bias = masters.get("bias")
    dark = masters.get("dark")
    if bias is not None and dark is not None:
        # SirIL restaría los DOS: solo evitamos el bias si el dark ya lo trae.
        med_bias = _mediana_frame(bias)
        med_dark = _mediana_frame(dark)
        if dark_incluye_bias(med_bias, med_dark):
            aviso = (
                "el máster de dark ya incluye el bias "
                f"(medianas FITS {med_dark:.6g} ≈ {med_bias:.6g}): "
                "no se resta dos veces"
            )
            resultado.avisos.append(aviso)
        else:
            args.append(arg_ruta(f"-bias={bias}"))
    elif bias is not None:
        args.append(arg_ruta(f"-bias={bias}"))
    if dark is not None:
        args.append(arg_ruta(f"-dark={dark}"))
    if flats_calibrados is not None:
        args.append(arg_ruta(f"-flat={flats_calibrados}"))
    if opt:
        if {"bias", "dark"} <= masters.keys():
            if exposure_de(lights[0]) is not None:
                # -opt a secas: SIGSEGV en el CLI de SirIL 1.4.4 (validado).
                args.append("-opt=exp")
            else:
                resultado.avisos.append("-opt omitido: los lights no traen EXPOSURE.")
        else:
            resultado.avisos.append("-opt omitido: requiere bias y dark.")
    if cc:
        if "dark" in masters:
            args.append("-cc=dark")
        else:
            resultado.avisos.append("-cc omitido: requiere dark.")

    res = ejecutar_script(
        [" ".join(args)], cwd=trabajo, progress_cb=progress_cb, log_cb=log_cb
    )
    if not res.ok:
        raise SirilError(f"El calibrado de {session.path.name} falló: {res.motivo}")

    calibrados = sorted(trabajo.glob("pp_*.fit*"))
    resultado.n_lights = len(calibrados)
    if not calibrados:
        raise SirilError(
            f"SirIL no generó ningún light calibrado en {session.path.name}."
        )
    resultado.exposure_s = exposure_de(calibrados[0])


def _material_global(ruta: str | None) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    """(masters, frames) de la carpeta global de calibrado del usuario.

    La ruta la resuelve la UI (settings) y la pasa por parámetro: aquí no
    se lee la BD, porque esta función corre en el hilo de trabajo de SirIL
    (A-03 de la auditoría). Sin ruta, no hay carpeta global.
    """
    if not ruta or not Path(ruta).is_dir():
        return {}, {}
    return parse_calibration_folder(Path(ruta))
