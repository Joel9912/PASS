"""Ejecución de SirIL por CLI: el único punto de contacto con el binario.

SirIL manda — esto es un envoltorio fino y honesto alrededor de su CLI
(validado contra SirIL 1.4.4 real):

- El guion entra por **stdin** (``siril-cli -s -``): sin ficheros temporales.
- La configuración se aísla con ``-i <ini propio>``: SirIL persiste sus
  preferencias al salir del guion y un ``set`` en el propio guion mancharía
  la configuración global del usuario. El ini propio fija
  ``core.force_16bit=false``: sin eso SirIL aborta al calibrar entradas de
  32 bits porque su preferencia de salida es de 16.
- El **exit code** distingue éxito (0) y fallo (1) y el guion termina con
  «Script ejecutado correctamente.» o «Ejecución de script fallida.»
  (marcadores también en inglés, por si el SirIL del usuario está en otro
  idioma). Se comprueban los dos: ni el código ni el marcador mienten.
- El avance llega en líneas ``progress: ..., NN.NN%`` del stdout.

Además, la carpeta de trabajo es de SirIL y de nadie más: `limpiar_trabajo`
borra solo lo que esté anclado a `WORKING_FOLDER` y `ultima_secuencia` lee
del `.seq` el nombre real que SirIL dio a la secuencia (él manda, no las
suposiciones).

Ni el locale ni la ruta son inocentes: SirIL hereda el CWD y el idioma del
sistema, y sus rutas pueden llevar acentos — nunca se fuerza ``LC_ALL=C``
(rompe SirIL al fijar CWD con caracteres no ASCII) y toda comparación de
mensajes se hace en ambos idiomas.
"""
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from .siril_finder import find_siril

_binario_tarea: ContextVar[str | None] = ContextVar("binario_siril_tarea", default=None)


@contextmanager
def binario_de_tarea(ruta: str) -> Iterator[None]:
    """Usa el SirIL resuelto en la UI sin consultar SQLite en el hilo de trabajo."""
    token = _binario_tarea.set(ruta)
    try:
        yield
    finally:
        _binario_tarea.reset(token)

#: Cabecera obligatoria de todo guion: valida la compatibilidad con 1.4+.
REQUIRES = "requires 1.4"

#: Marcadores de fallo final del guion, en español e inglés (SirIL traduce
#: sus mensajes al idioma del sistema; no se fuerza el locale por lo explicado
#: en el docstring).
MARCAS_FALLO = ("ejecución de script fallida", "script execution failed")

#: Porcentaje de avance en líneas «progress: ..., NN.NN%» (siril imprime el
#: número con coma o punto según el locale).
_RE_PROGRESO = re.compile(r"progress:.*?(\d+(?:[.,]\d+)?)%")
_RE_CONTROL_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")

#: Carpeta de trabajo del programa (anclada a la raíz del proyecto, igual que
#: ``db.connection``: el CWD del proceso no es fiable). Compartida con
#: ``calibrator``: ahí viven el ini y las salidas de SirIL.
WORKING_FOLDER = Path(__file__).resolve().parent.parent / "data" / "working"

#: Nombre del ini de PASS. SirIL lo reescribe al salir (con todas sus
#: preferencias), conservando el ``force_16bit=false`` que ponemos aquí.
INI_PROPIO = "siril_pss.ini"

#: Proceso SirIL en curso (si lo hay): la cancelación de la UI lo mata.
#: Se marca al arrancar y se limpia siempre al salir de la corrida.
_proc_actual = None


class SirilError(RuntimeError):
    """SirIL no se encontró, no arrancó o el guion falló."""


@dataclass
class SirilResult:
    """Resultado de una corrida de SirIL."""

    ok: bool
    comandos: list[str]                       # guion enviado, para diagnóstico
    lineas: list[str] = field(default_factory=list)  # log completo (sin «log: »)
    progreso: float | None = None             # 0..1, último porcentaje leído
    motivo: str = ""                          # por qué ok=False (resumen)


def cancelar_siril() -> None:
    """Mata la corrida de SirIL en curso, si la hay (cancelación desde la UI).

    El bucle de lectura de ``ejecutar_script`` termina al cerrarse el stdout
    y devuelve un fallo normal (exit −9): quien decide el mensaje de
    «cancelado» es el llamador, no el runner.
    """
    if _proc_actual is not None and _proc_actual.poll() is None:
        _proc_actual.kill()


def ini_path() -> Path:
    """Ruta al ini propio de PASS; lo crea con ``force_16bit=false`` si falta.

    Se llama antes de cada corrida: si el usuario borra el fichero (o
    alguien lo corrompe), la siguiente ejecución lo restaura mínimo.
    """
    ruta = WORKING_FOLDER / INI_PROPIO
    contenido = "[core]\nforce_16bit=false\n"
    if not ruta.exists() or "force_16bit=false" not in ruta.read_text(encoding="utf-8"):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido, encoding="utf-8")
    return ruta


def construir_script(comandos: list[str], cwd: Path | None) -> str:
    """Texto del guion: ``requires`` + ``cd`` + comandos, uno por línea.

    ``cwd`` se fija con ``cd`` (SirIL arranca con su propio CWD —normalmente
    el directorio personal—, no con el del proceso). Las rutas con espacios
    van entrecomilladas: SirIL exige comillar el argumento entero.
    """
    lineas = [REQUIRES]
    if cwd is not None:
        ruta = cwd.as_posix()
        if " " in ruta:
            ruta = f'"{ruta}"'
        lineas.append(f"cd {ruta}")
    lineas.extend(comandos)
    return "\n".join(lineas) + "\n"


def ejecutar_script(
    comandos: list[str],
    *,
    cwd: Path | None = None,
    progress_cb=None,
    log_cb=None,
    esperados: list[Path] | None = None,
) -> SirilResult:
    """Ejecuta ``comandos`` en SirIL y devuelve el resultado.

    El guion se envía por stdin (``siril-cli -s -``) con el ini propio y la
    configuración aislada. Durante la corrida:

    - cada línea de log se entrega a ``log_cb(linea)`` (para el registro en
      vivo de la UI),
    - cada porcentaje ``progress: ... NN%`` se entrega a
      ``progress_cb(fraction)`` (0..1, para la barra de progreso).

    ``esperados`` lista ficheros que deben existir al terminar: es la
    comprobación lingüísticamente neutra del éxito (SirIL devuelve exit 0
    también en algunos fallos de guion; el marcador de idioma y los ficheros
    de salida son la verdad).

    Raises:
        SirilError: si SirIL no está instalado o el proceso no arranca.
    """
    binario = _binario_tarea.get() or find_siril()
    if not binario:
        raise SirilError("SirIL no está instalado o no se encontró en el PATH.")

    script = construir_script(comandos, cwd)
    if log_cb is not None:
        log_cb(f"Guion SirIL ({cwd or 'sin directorio'}): {script.strip()}")
    try:
        proc = subprocess.Popen(
            [binario, "-i", str(ini_path()), "-s", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",  # un log con acentos no debe tumbar la corrida
        )
    except OSError as exc:
        raise SirilError(f"No se pudo arrancar SirIL ({binario}): {exc}") from exc

    global _proc_actual
    _proc_actual = proc
    try:
        # El guion se escribe entero y se cierra stdin: SirIL no pide nada más.
        proc.stdin.write(script)  # type: ignore[union-attr]
        proc.stdin.close()  # type: ignore[union-attr]

        resultado = SirilResult(ok=True, comandos=comandos)
        for linea in proc.stdout:  # type: ignore[union-attr]
            texto = linea.rstrip("\n")
            resultado.lineas.append(texto)
            visible = _RE_CONTROL_ANSI.sub("", texto).strip()
            if log_cb is not None and visible and not re.fullmatch(
                r"HDU \d+: type=\d+, EXTNAME=.*", visible
            ):
                log_cb(visible)
            porcentaje = _RE_PROGRESO.search(texto)
            if porcentaje:
                resultado.progreso = min(max(float(porcentaje.group(1).replace(",", ".")) / 100.0, 0.0), 1.0)
                if progress_cb is not None:
                    progress_cb(resultado.progreso)

        proc.wait()
        resultado.ok = _marcado_ok(proc.returncode, resultado.lineas, esperados)
        if not resultado.ok:
            resultado.motivo = _motivo_fallo(proc.returncode, resultado.lineas, esperados)
        return resultado
    finally:
        # Cancelada o normal: nunca dejar el proceso colgado como actual.
        _proc_actual = None


def _marcado_ok(returncode: int, lineas: list[str], esperados: list[Path] | None) -> bool:
    """Éxito = exit 0 + sin marcador de fallo + (si se pidieron) los ficheros esperados."""
    if returncode != 0:
        return False
    if any(marca in linea.lower() for linea in lineas for marca in MARCAS_FALLO):
        return False
    return not esperados or all(ruta.exists() for ruta in esperados)


def _motivo_fallo(returncode: int, lineas: list[str], esperados: list[Path] | None) -> str:
    """Resumen breve del fallo para el log/UI (primera pista útil disponible)."""
    if returncode != 0:
        return f"SirIL terminó con código {returncode}."
    if esperados:
        faltan = [str(ruta) for ruta in esperados if not ruta.exists()]
        return "No se crearon: " + ", ".join(faltan)
    # Última línea de log que no sea ruido de progreso ni el cierre.
    for linea in reversed(lineas):
        texto = linea.removeprefix("log: ").strip()
        if texto and not texto.startswith("progress:") and "script" not in texto.lower():
            return texto
    return "El guion de SirIL falló."


def arg_ruta(argumento: str) -> str:
    """Argumento de SirIL que lleva ruta: entrecomillado TODO si hay espacios.

    Validado con SirIL 1.4.4: solo acepta rutas con espacios si el argumento
    entero va entrecomillado (``"-dark=/r con esp/m.fits"``); comillas
    parciales o escapes a medias del espacio dan «invalid arguments».
    """
    # SirIL analiza un script, no la línea de comandos de Windows: la barra
    # inversa escapa caracteres en sus argumentos incluso sin espacios.
    argumento = argumento.replace("\\", "/")
    return f'"{argumento}"' if " " in argumento else argumento


def enlazar(origen: Path, enlace: Path) -> None:
    """Apunta ``enlace`` a ``origen`` SIN copiar: symlink y, si no se puede, hardlink.

    Es el único punto del programa donde el port a Windows necesita cuidado:
    los symlinks requieren privilegios de desarrollador allí, y el hardlink
    solo funciona dentro del mismo volumen. Si ambos fallan, se rinde con un
    error claro en lugar de copiar (regla del proyecto: cero copias).
    """
    try:
        enlace.symlink_to(origen.resolve())
    except OSError:
        try:
            os.link(origen, enlace)
        except OSError as exc:
            raise SirilError(
                f"No se pudo enlazar {origen.name} en {enlace} "
                f"(sin symlink ni hardlink: {exc})."
            ) from exc


def limpiar_trabajo(destino: Path, *, raiz: Path | None = None) -> None:
    """Vacía una carpeta de trabajo propia antes de (re)usarla.

    Solo se admite lo que viva bajo la raíz de trabajo (por defecto
    ``WORKING_FOLDER``; los módulos estrechan su raíz): jamás se borra una
    sesión original ni nada externo. Evita que salidas viejas se mezclen con
    las nuevas y que un re-``link`` acoja ficheros de corridas parciales.
    """
    base = (raiz or WORKING_FOLDER).resolve()
    if destino.resolve() == base or not destino.resolve().is_relative_to(base):
        raise SirilError(f"No se puede limpiar {destino}: no es una subcarpeta de trabajo.")
    shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True, exist_ok=True)


def eliminar_salidas_trabajo(destino: Path) -> None:
    """Borra una salida concreta o todo working, sin seguir enlaces ni tocar originales.

    La raíz debe ser la carpeta working de PASS; una ruta ajena, un
    enlace en la propia ruta o un destino que aún no existe se rechazan.
    Un enlace dentro de la carpeta se desenlaza, nunca se sigue.
    """
    base = WORKING_FOLDER.absolute()
    ruta = destino.absolute()
    if ruta != base and not ruta.is_relative_to(base):
        raise SirilError(f"Fuera de la carpeta de trabajo: {ruta}")
    if base.resolve() != base or not ruta.exists() or ruta.resolve() != ruta:
        raise SirilError(f"No se puede eliminar esta ruta de trabajo: {ruta}")
    for padre in ruta.parents:
        if padre == base:
            break
        if padre.is_symlink() or padre.is_junction():
            raise SirilError(f"Ruta de trabajo con enlace intermedio: {ruta}")
    if ruta == base:
        for hijo in ruta.iterdir():
            if hijo.is_symlink() or hijo.is_junction() or hijo.is_file():
                hijo.unlink()
            elif hijo.is_dir():
                shutil.rmtree(hijo)
    else:
        shutil.rmtree(ruta)


def ultima_secuencia(trabajo: Path, base_seq: str) -> str:
    """Nombre real de la secuencia SirIL tras link/convertraw/calibrate.

    SirIL normaliza nombres y escribe la secuencia con un guion bajo final
    (``light_0001.fit`` → secuencia ``light_``); el ``.seq`` en disco manda,
    así que se lee de ahí. Si no hay ``.seq`` se devuelve la base.
    """
    seqs = sorted(trabajo.glob("*.seq"))
    if not seqs:
        return base_seq
    # Entre varios .seq (p. ej. el de flats y el de flats calibrados) se
    # coge el que empieza por la base pedida; si ninguno, el más reciente.
    por_base = [s for s in seqs if s.stem.startswith(base_seq)]
    return (por_base[-1] if por_base else seqs[-1]).stem
