"""Registro de los lights calibrados con SirIL: auditoría y registro final.

Dos registros distintos, según el flujo decidido por el usuario:

1. **Auditoría** (``audit_pool``): registro RÁPIDO con ``register -2pass``
   SIN aplicar transformadas, debayer ni drizzle. SirIL solo calcula las
   transformadas y deja las métricas (FWHM, redondez, fondo…) en el
   ``.seq``, que es lo que ``stacks/frame_metrics.py`` lee para puntuar y
   descartar. Validado sobre CFA crudo: mide sin necesidad de rebayerizar.
2. **Registro final** (``register_pool``): SOBRE los frames que el usuario
   aceptó en la auditoría, ya con sus opciones: solo registrar, debayer
   (``debayer=True``: los CFA cuando NO hay drizzle) o drizzle
   (``drizzle=True``). Los dos nunca van juntos: SirIL 1.4.4 debayeriza
   él mismo al drizzlezar CFA (validado: la salida sale RGB).

Los enlaces los crea Python con nombre único por frame (varias sesiones
comparten nombres tipo ``pp_light_00001.fit``), nunca se copia nada y
SirIL nunca sale de la carpeta de trabajo. El mapeo sesión↔frame se
recupera resolviendo esos symlinks: el ``.seq`` no guarda nombres.

Validado con SirIL 1.4.4 (gotchas en ``stacks/README.md``):

- ``register <seq> -2pass``: SirIL elige la MEJOR referencia; con -2pass
  solo calcula las transformadas, que aplica ``seqapplyreg`` después.
- ``debayer`` NO existe como comando de la CLI («todavía no
  implementado»): la vía válida es ``calibrate <seq> -debayer`` SIN
  másters, que solo rebayeriza — ``_debayerizar``.
- Si TODAS las transformadas son de identidad (frames sin dither), SirIL
  se niega a aplicarlas y sale con código 1: no es un fallo, los frames ya
  están alineados y se apila la secuencia de entrada
  (``Registro.transformadas = False``); con drizzle pedido, en cambio, sí
  es un error (no hay salida posible).
- La salida usa el prefijo ``r_`` (``registro_`` → ``r_registro_``).
 - Drizzle va en ``seqapplyreg`` con escala configurable (por defecto x2).
SirIL usa todos los hilos disponibles por sí solo.
"""
import json
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from .global_pool import GlobalPool, LightRef, nombre_sesion
from .session_parser import necesita_debayer
from .siril_runner import (
    WORKING_FOLDER,
    SirilError,
    arg_ruta,
    ejecutar_script,
    enlazar,
    limpiar_trabajo,
    ultima_secuencia,
)

#: Subcarpeta de trabajo del registro (bajo ``WORKING_FOLDER``).
REGISTRADOS_DIR = Path("registrados")

#: Carpeta de la auditoría (fija: se vacía en cada corrida).
AUDITORIA_DIR = Path("auditoria")

#: Subcarpeta dentro del registro final donde SirIL rebayeriza (si se pide).
DEBAYER_DIR = Path("debayer")

#: Base de la secuencia SirIL en la carpeta de registro (el ``.seq`` real es
#: ``<SEQ_BASE>_.seq`` y SirIL la normaliza con guion bajo final).
SEQ_BASE = "registro"

#: Marcador de SirIL (mensaje hardcodeado en inglés, inmune al locale) con el
#: que avisa de que todas las transformadas son de identidad y ``seqapplyreg``
#: se niega a regenerar nada: los frames ya están alineados.
MARCADOR_IDENTIDAD = "identity matrices"


@dataclass
class Registro:
    """Secuencia registrada por SirIL, con su mapeo a los lights del pool."""

    dir: Path                 # working/registrados/<nombre>/
    seq: str                  # nombre real de la secuencia (p. ej. 'registro_')
    frames: list[LightRef]    # refs en el orden de índices de la secuencia
    transformadas: bool = True  # False: identidad → apilar la entrada (sin r_*)
    capture_times: dict[str, datetime | None] = field(default_factory=dict, compare=False, repr=False)
    capture_sites: dict[str, tuple[float, float] | None] = field(default_factory=dict, compare=False, repr=False)

    @property
    def ruta_seq(self) -> Path:
        """Fichero ``.seq`` de la secuencia (contiene las métricas de registro)."""
        return self.dir / f"{self.seq}.seq"

    @property
    def seq_apilable(self) -> str:
        """Secuencia que hay que apilar: la transformada (``r_``) o la de entrada."""
        return f"r_{self.seq}" if self.transformadas else self.seq


def audit_pool(
    pool: GlobalPool, *, progress_cb=None, log_cb=None
) -> Registro:
    """Registro RÁPIDO de la auditoría: solo ``-2pass``, sin aplicar nada.

    SirIL calcula las transformadas y escribe una fila ``R`` por imagen en
    el ``.seq`` (métricas de registro); con eso basta para puntuar y
    descartar. NO hay ``r_*``, ni debayer, ni drizzle: eso va después, en
    el registro final de los aceptados, cuando el usuario ya eligió.

    Devuelve el ``Registro`` con ``transformadas=False`` (aquí no se aplica
    nada, la secuencia de entrada sigue siendo la apilable).
    """
    if not pool.entries:
        raise SirilError("El pool está vacío: no hay lights que registrar.")
    destino = WORKING_FOLDER / REGISTRADOS_DIR / AUDITORIA_DIR
    limpiar_trabajo(destino, raiz=WORKING_FOLDER / REGISTRADOS_DIR)
    registro = _preparar_secuencia(pool.entries, destino, log_cb=log_cb)

    res = ejecutar_script(
        [f"register {registro.seq} -2pass"], cwd=destino,
        progress_cb=progress_cb, log_cb=log_cb,
    )
    if not res.ok:
        raise SirilError(f"El registro de SirIL falló: {res.motivo}")
    registro.transformadas = False
    (destino / "pool.json").write_text(
        json.dumps({"entrada": _firma_pool(pool), "orden": [str(r.ruta.resolve())
                    for r in registro.frames]}), encoding="utf-8"
    )
    return registro


def auditoria_guardada(pool: GlobalPool) -> Registro | None:
    """Recupera el .seq solo si coincide exactamente con los lights actuales."""
    destino = WORKING_FOLDER / REGISTRADOS_DIR / AUDITORIA_DIR
    manifiesto = destino / "pool.json"
    secuencia = destino / f"{SEQ_BASE}_.seq"
    if not manifiesto.is_file() or not secuencia.is_file():
        return None
    try:
        datos = json.loads(manifiesto.read_text(encoding="utf-8"))
        if datos.get("entrada") != _firma_pool(pool):
            return None
        if any(not (destino / f"{SEQ_BASE}_{i:05d}.fit").is_file()
               for i in range(1, len(pool.entries) + 1)):
            return None
        orden = _mapear(destino, f"{SEQ_BASE}_", pool.entries)
        if [str(r.ruta.resolve()) for r in orden] != datos.get("orden"):
            return None
    except (OSError, ValueError, SirilError, AttributeError):
        return None
    return Registro(destino, f"{SEQ_BASE}_", orden, transformadas=False)


def _firma_pool(pool: GlobalPool) -> list[list]:
    """Identifica orden, ruta y contenido aparente de cada entrada calibrada."""
    return [[str(ref.ruta.resolve()), ref.ruta.stat().st_size,
             ref.ruta.stat().st_mtime_ns, ref.sesion, ref.exposicion_s]
            for ref in pool.entries]


def register_pool(
    pool: GlobalPool,
    nombre: str,
    *,
    aceptados: list[LightRef] | None = None,
    debayer: bool = False,
    drizzle: bool = False,
    scale: float = 2.0,
    framing: str = "current",
    pixfrac: float = 1.0,
    kernel: str = "square",
    flat: Path | None = None,
    progress_cb=None,
    log_cb=None,
) -> Registro:
    """Registro FINAL de los frames aceptados, con debayer o drizzle.

    Crea la secuencia solo con ``aceptados`` (lo marcado en la auditoría),
    registra con ``-2pass`` (referencia automática) y aplica las
    transformadas con ``seqapplyreg``.

    Args:
        pool: pool del que salen los frames (sus lights, por referencias).
        nombre: carpeta de trabajo del registro (la UI usa la del apilado).
        aceptados: subconjunto de ``LightRef`` del pool; ``None`` = todos.
        debayer: rebayeriza los CFA antes de registrar (para cuando NO se
            pide drizzle). Solo toca los frames con patrón Bayer crudo.
        drizzle: exporta con el algoritmo HST drizzle; scale, pixfrac y
            kernel definen el remuestreo elegido por el usuario.
            Nunca se pide junto a ``debayer``: SirIL drizzlee CFA→RGB solo.
        progress_cb/log_cb: repartidos por cada corrida de SirIL.
    """
    if not pool.entries:
        raise SirilError("El pool está vacío: no hay lights que registrar.")
    refs = list(pool.entries) if aceptados is None else list(aceptados)
    if not refs:
        raise SirilError("No hay frames aceptados que registrar.")
    _validar_aplicacion(drizzle, scale, framing, kernel, flat)

    destino = WORKING_FOLDER / REGISTRADOS_DIR / nombre
    limpiar_trabajo(destino, raiz=WORKING_FOLDER / REGISTRADOS_DIR)
    if debayer:
        refs = _debayerizar(refs, destino, progress_cb=progress_cb,
                            log_cb=log_cb)
    registro = _preparar_secuencia(refs, destino, log_cb=log_cb)

    res = ejecutar_script(
        [f"register {registro.seq} -2pass"], cwd=destino,
        progress_cb=progress_cb, log_cb=log_cb,
    )
    if not res.ok:
        raise SirilError(f"El registro de SirIL falló: {res.motivo}")
    return _aplicar_transformadas(
        registro, drizzle=drizzle, scale=scale, framing=framing,
        pixfrac=pixfrac, kernel=kernel, flat=flat,
        progress_cb=progress_cb, log_cb=log_cb,
    )


# ------------------------------------------------------------------ internas
def _preparar_secuencia(
    refs: list[LightRef], destino: Path, *, log_cb=None
) -> Registro:
    """Enlaza ``refs`` con nombre único, crea la secuencia y recupera el mapeo.

    El orden de SirIL no se supone: cada symlink resuelve al light de
    origen y así se recupera el mapeo sesión↔frame. ``destino`` debe estar
    ya limpia (la limpieza la hace quien llama, porque el debayer escribe
    dentro antes).
    """
    for indice, ref in enumerate(refs, start=1):
        enlazar(
            ref.ruta,
            destino / f"{indice:04d}_{nombre_sesion(ref)}_{ref.ruta.name}",
        )
    res = ejecutar_script([f"link {SEQ_BASE}"], cwd=destino, log_cb=log_cb)
    if not res.ok:
        raise SirilError(f"No se pudo crear la secuencia de registro: {res.motivo}")
    seq = ultima_secuencia(destino, SEQ_BASE)
    return Registro(dir=destino, seq=seq, frames=_mapear(destino, seq, refs))


def _aplicar_transformadas(
    registro: Registro, *, drizzle: bool, scale: float = 2.0,
    framing: str = "current", pixfrac: float, kernel: str,
    flat: Path | None = None,
    progress_cb=None, log_cb=None,
) -> Registro:
    """Aplica las transformadas con ``seqapplyreg`` (con drizzle si se pide)."""
    comando = [f"seqapplyreg {registro.seq}"]
    if framing != "current":
        comando[0] += f" -framing={framing}"
    if drizzle:
        comando[0] += f" -drizzle -pixfrac={pixfrac} -kernel={kernel} -scale={scale:g}"
        if flat is not None:
            comando[0] += " " + arg_ruta(f"-flat={flat.resolve()}")
    res = ejecutar_script(comando, cwd=registro.dir,
                          progress_cb=progress_cb, log_cb=log_cb)
    if not res.ok:
        identidad = any(MARCADOR_IDENTIDAD in linea.lower() for linea in res.lineas)
        if identidad and not drizzle:
            # Frames idénticos (p. ej. sin dither): SirIL se niega a «aplicar»
            # la identidad. No es un fallo: ya están alineados y se apila la
            # secuencia de entrada (Registro.transformadas=False).
            if log_cb:
                log_cb(
                    "Transformadas de identidad: los frames ya estaban "
                    "alineados; se apilará la secuencia de entrada."
                )
            registro.transformadas = False
            return registro
        if identidad:
            raise SirilError(
                "Los frames están tan alineados que SirIL no aplica nada "
                "(transformadas de identidad): no hay salida drizzle posible."
            )
        raise SirilError(f"No se pudieron aplicar las transformadas: {res.motivo}")
    salidas = list(registro.dir.glob("r_*.fit"))
    if not salidas:
        raise SirilError("SirIL no generó ningún frame registrado (r_*).")
    esperados = {f"r_{registro.seq}{i:05d}.fit"
                 for i in range(1, len(registro.frames) + 1)}
    if any(p.name not in esperados or not p.is_file() for p in salidas):
        raise SirilError("SirIL generó salidas de registro mal nombradas o inválidas.")
    return registro


def _validar_aplicacion(
    drizzle: bool, scale: float, framing: str, kernel: str, flat: Path | None,
) -> None:
    """Rechaza opciones inviables antes de limpiar la carpeta de registro."""
    if framing not in ("current", "min", "max", "cog"):
        raise ValueError(f"Encuadre no válido: {framing}.")
    if not 0.1 <= scale <= 3.0:
        raise ValueError("Escala drizzle fuera del rango de SirIL (0,1–3).")
    if kernel not in ("point", "turbo", "square", "gaussian", "lanczos2", "lanczos3"):
        raise ValueError(f"Kernel drizzle no válido: {kernel}.")
    if flat is not None and (not drizzle or not flat.is_file()):
        raise ValueError("El flat de drizzle exige drizzle y un FITS existente.")


def _debayerizar(
    refs: list[LightRef], destino: Path, *, progress_cb=None, log_cb=None
) -> list[LightRef]:
    """Rebayeriza con SirIL los frames CFA de ``refs``; devuelve la lista.

    Solo pasan por SirIL los frames con patrón Bayer crudo (los ya RGB o
    mono quedan tal cual) y se conserva el orden. Como la CLI de SirIL
    1.4.4 no tiene comando ``debayer`` («todavía no implementado»), la vía
    validada es ``calibrate <seq> -debayer`` sin másters, que solo
    rebayeriza. Los resultados son ficheros nuevos en
    ``<destino>/debayer/``: ni el pool ni los originales se tocan.
    """
    indices_cfa = [i for i, ref in enumerate(refs) if necesita_debayer(ref.ruta)]
    if not indices_cfa:
        return list(refs)

    sub = destino / DEBAYER_DIR
    sub.mkdir(parents=True, exist_ok=True)
    for numero, i in enumerate(indices_cfa, start=1):
        ref = refs[i]
        enlazar(
            ref.ruta,
            sub / f"{numero:04d}_{nombre_sesion(ref)}_{ref.ruta.name}",
        )
    res = ejecutar_script(["link d", "calibrate d_ -debayer"], cwd=sub,
                          progress_cb=progress_cb, log_cb=log_cb)
    if not res.ok:
        raise SirilError(f"El debayer de SirIL falló: {res.motivo}")
    # La salida es ``pp_`` + el nombre enlazado (``pp_d_00001.fit``…) y
    # ``link`` numeró en el mismo orden: posición a posición.
    salidas = sorted(sub.glob("pp_d_*.fit"))
    if len(salidas) != len(indices_cfa):
        raise SirilError(
            f"Debayer: SirIL generó {len(salidas)} ficheros de "
            f"{len(indices_cfa)} frames CFA."
        )
    esperados = {f"pp_d_{i:05d}.fit" for i in range(1, len(indices_cfa) + 1)}
    if {p.name for p in salidas} != esperados or any(not p.is_file() for p in salidas):
        raise SirilError("Debayer: índices de salida mal nombrados o inválidos.")
    resultado = list(refs)
    for posicion, i in enumerate(indices_cfa):
        resultado[i] = replace(refs[i], ruta=salidas[posicion])
    if log_cb:
        log_cb(
            f"Debayer: {len(indices_cfa)} frames CFA rebayerizados "
            "(calibrate -debayer)."
        )
    return resultado


def _mapear(destino: Path, seq: str, refs: list[LightRef]) -> list[LightRef]:
    """Asocia cada índice a su archivo físico, tanto con symlinks como con hardlinks.

    ``link`` renombra por índice (``registro_00001.fit``…) y el ``.seq`` no
    guarda nombres: la verdad está en la identidad del archivo enlazado (el light
    calibrado original — o su versión debayerizada). Si un destino no está
    en la lista, hay basura en la carpeta y se rinde en lugar de atribuir
    a la sesión equivocada.
    """
    def identidad(path: Path) -> tuple[int, int]:
        """stat sigue symlinks y reconoce hardlinks sin confundirlos con copias."""
        stat = path.stat()
        if not stat.st_ino:
            raise SirilError("El sistema no permite identificar de forma segura los frames.")
        return stat.st_dev, stat.st_ino

    por_destino = {identidad(ref.ruta): ref for ref in refs}
    if len(por_destino) != len(refs):
        raise SirilError("El pool contiene referencias duplicadas al mismo archivo.")
    enlaces = sorted(destino.glob(f"{seq}*.fit"))
    esperados = {f"{seq}{i:05d}.fit" for i in range(1, len(refs) + 1)}
    if {p.name for p in enlaces} != esperados:
        raise SirilError("Índices de registro incompletos o mal nombrados.")
    if Counter(identidad(p) for p in enlaces) != Counter(identidad(r.ruta) for r in refs):
        raise SirilError("Los enlaces de registro no corresponden uno a uno al pool.")
    try:
        return [por_destino[identidad(enlace)] for enlace in enlaces]
    except KeyError as exc:
        raise SirilError(
            f"El enlace {exc.args[0]} no apunta a ningún light registrado: "
            "carpeta de registro sucia."
        ) from None
