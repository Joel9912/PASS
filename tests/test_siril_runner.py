"""siril_runner: guion por stdin, detección de fallo, progreso y enlaces.

SirIL está mockeado aquí: los tests no dependen del binario instalado (la
corrida real end-to-end vive fuera de pytest).
"""
import io

import pytest

from stacks import siril_runner
from stacks.siril_runner import SirilError


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_cli_no_crea_consola_y_conserva_pipes(monkeypatch, platform):
    """S-0023: Windows no abre terminales; otras plataformas conservan flags neutros y el log."""
    import subprocess
    from types import SimpleNamespace

    from stacks import siril_finder

    monkeypatch.setattr(siril_finder, "sys", SimpleNamespace(platform=platform), raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(siril_runner, "find_siril", lambda: "siril-falso")
    received = []

    def start(args, **kwargs):
        """Captura opciones de creación sin lanzar SirIL ni cambiar datos personales."""
        received.append(kwargs)
        return _ProcFalso("log: salida conservada\nprogress: trabajo, 25%\n")

    monkeypatch.setattr(siril_runner.subprocess, "Popen", start)
    logs, progress = [], []
    result = siril_runner.ejecutar_script(["noop"], log_cb=logs.append, progress_cb=progress.append)
    options = received[0]
    assert options.get("creationflags", 0) == (0x08000000 if platform == "win32" else 0)
    assert options["stdin"] == subprocess.PIPE
    assert options["stdout"] == subprocess.PIPE
    assert options["stderr"] == subprocess.STDOUT
    assert "log: salida conservada" in logs
    assert progress == [0.25]
    assert result.ok


def test_hijo_real_desde_pythonw_no_tiene_consola(tmp_path):
    """S-0023: un padre real sin consola ejecuta el runner sin crear consola en el hijo."""
    import json
    import subprocess
    import sys
    from pathlib import Path

    if sys.platform != "win32":
        pytest.skip("La consola Win32 solo se verifica en Windows.")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        pytest.skip("Este intérprete no incluye pythonw.exe.")
    script = tmp_path / "probe_pythonw.py"
    script.write_text('''"""Sondeo aislado de procesos Win32; no abre la base personal ni ejecuta SirIL."""
import ctypes
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[2])
from db import connection
from stacks import siril_runner

base = Path(sys.argv[1])
connection.DATA_DIR = base
siril_runner.WORKING_FOLDER = base / "working"
siril_runner.find_siril = lambda: "hijo-python-sintetico"
popen = subprocess.Popen

def start(args, **kwargs):
    """Oculta cualquier consola del caso rojo para no robar foco al usuario."""
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    kwargs["startupinfo"] = startup
    code = "import sys, ctypes; sys.stdin.read(); print('console=' + str(ctypes.windll.kernel32.GetConsoleWindow())); print('progress: probe, 50%')"
    return popen([str(Path(sys.executable).with_name("python.exe")), "-c", code], **kwargs)

siril_runner.subprocess.Popen = start
progress = []
result = siril_runner.ejecutar_script(["noop"], progress_cb=progress.append)
(base / "result.json").write_text(json.dumps({
    "parent_console": ctypes.windll.kernel32.GetConsoleWindow(),
    "lines": result.lineas, "ok": result.ok, "progress": progress,
}), encoding="utf-8")
''', encoding="utf-8")
    subprocess.run(
        [str(pythonw), str(script), str(tmp_path), str(Path(__file__).resolve().parents[1])],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=20, check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["parent_console"] == 0
    assert "console=0" in result["lines"]
    assert result["progress"] == [0.5]
    assert result["ok"]


class _ProcFalso:
    """Sustituto mínimo de ``subprocess.Popen``: siril escribe ``lineas`` y termina."""

    def __init__(self, lineas, returncode=0):
        self.stdout = io.StringIO(lineas)
        self.stdin = io.StringIO()  # write/close inofensivos
        self.returncode = returncode

    def wait(self):
        return self.returncode

    def poll(self):
        """Expone el estado del proceso simulado como Popen."""
        return self.returncode


def test_log_completo_en_disco_y_resultado_acotado(monkeypatch):
    """S-0018: persiste incluso ruido filtrado y conserva marcadores tempranos."""
    from db import connection
    from pass_logging import MAX_LOG_LINES

    inicio = "log: identity matrices; script execution failed"
    oculto = "HDU 1: type=0, EXTNAME=LIGHT"
    lineas = [inicio, oculto] + [f"log: frame {i}" for i in range(MAX_LOG_LINES + 100)]
    _siril(monkeypatch, "\n".join(lineas) + "\n")
    visible = []
    resultado = siril_runner.ejecutar_script(["comando"], log_cb=visible.append)
    assert not resultado.ok
    assert len(resultado.lineas) <= MAX_LOG_LINES + 3
    assert any("identity matrices" in linea for linea in resultado.lineas)
    assert oculto not in visible
    completo = (connection.DATA_DIR / "logs" / "apilador.log").read_text(encoding="utf-8")
    assert inicio in completo and oculto in completo
    assert "log: frame 0" in completo and lineas[-1] in completo


@pytest.mark.parametrize("fallo", ["write", "close", "callback"])
def test_fallo_de_io_no_deja_proceso_vivo(monkeypatch, fallo):
    """S-0013: los fallos tras Popen matan/recolectan al hijo y liberan sus pipes."""
    proc = _ProcFalso("log: trabajando\n", returncode=None)
    pipes = []
    waits = []

    class Entrada(io.StringIO):
        """Pipe capaz de fallar al enviar o cerrar stdin."""
        def write(self, texto):
            """Reproduce un pipe roto sin ocultarlo en el doble."""
            if fallo == "write":
                raise BrokenPipeError("write roto")
            return super().write(texto)

        def close(self):
            """Falla una vez y permite el cierre posterior de limpieza."""
            if fallo == "close" and not pipes:
                pipes.append(True)
                raise BrokenPipeError("close roto")
            super().close()

    proc.stdin = Entrada()

    def kill():
        """El hijo continúa vivo hasta que alguien lo mata."""
        proc.returncode = -9

    def wait(*args, **kwargs):
        """Registra la recolección del hijo."""
        waits.append(True)
        return proc.returncode

    def log(texto):
        """Falla solo al recibir stdout, después de lanzar el proceso."""
        if fallo == "callback" and texto == "log: trabajando":
            raise RuntimeError("callback roto")

    proc.kill, proc.wait = kill, wait
    monkeypatch.setattr(siril_runner, "find_siril", lambda: "siril-falso")
    monkeypatch.setattr(siril_runner.subprocess, "Popen", lambda *args, **kwargs: proc)
    with pytest.raises((BrokenPipeError, RuntimeError)):
        siril_runner.ejecutar_script(["comando"], log_cb=log)
    assert proc.returncode == -9
    assert waits
    assert proc.stdin.closed and proc.stdout.closed
    assert siril_runner._proc_actual is None


def test_stdin_roto_recolecta_hijo_real(monkeypatch):
    """Comprueba la terminación de un hijo Python propio, sin invocar SirIL real."""
    import subprocess
    import sys

    popen = subprocess.Popen
    children = []

    class PipeRoto:
        """Provoca el fallo conservando el pipe real para su cierre."""
        def __init__(self, pipe):
            """Retiene únicamente el stdin del hijo de prueba."""
            self.pipe = pipe

        def write(self, text):
            """Simula que SirIL deja de aceptar comandos."""
            raise BrokenPipeError("stdin roto")

        def close(self):
            """Cierra el descriptor real al limpiar."""
            self.pipe.close()

    def start(*args, **kwargs):
        """Lanza un hijo controlado que permanecería vivo sin el finally correcto."""
        proc = popen([sys.executable, "-c", "import time; time.sleep(60)"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        proc.stdin = PipeRoto(proc.stdin)
        children.append(proc)
        return proc

    monkeypatch.setattr(siril_runner, "find_siril", lambda: "hijo-python-controlado")
    monkeypatch.setattr(siril_runner.subprocess, "Popen", start)
    try:
        with pytest.raises(BrokenPipeError):
            siril_runner.ejecutar_script(["comando"])
        assert children[0].poll() is not None
        assert children[0].stdout.closed
    finally:
        for proc in children:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            proc.stdin.close()
            proc.stdout.close()


def _siril(monkeypatch, lineas, returncode=0):
    """Parchea find_siril y Popen: devuelve un procio fijo con esas líneas."""
    monkeypatch.setattr(siril_runner, "find_siril", lambda: "/usr/bin/siril")
    monkeypatch.setattr(
        siril_runner.subprocess,
        "Popen",
        lambda *args, **kwargs: _ProcFalso(lineas, returncode),
    )


# ------------------------------------------------------------- construir_script
def test_script_incluye_requires_y_cd(tmp_path):
    """Todo guion abre con requires y fija el CWD con cd."""
    script = siril_runner.construir_script(["stack light"], tmp_path)
    lineas = script.splitlines()
    assert lineas[0] == "requires 1.4"
    assert lineas[1] == f"cd {tmp_path.as_posix()}"
    assert lineas[2] == "stack light"


def test_script_sin_cwd_no_incluye_cd():
    """Sin cwd no hay cd (SirIL usa el suyo)."""
    script = siril_runner.construir_script(["a", "b"], None)
    assert script.splitlines() == ["requires 1.4", "a", "b"]


def test_script_comilla_rutas_con_espacios(tmp_path):
    """Ruta con espacios: SirIL exige comillar el argumento entero."""
    con_espacios = tmp_path / "mis datos"
    con_espacios.mkdir()
    script = siril_runner.construir_script([], con_espacios)
    assert f'cd "{con_espacios.as_posix()}"' in script


# ------------------------------------------------------------- ejecutar_script
def test_ejecucion_ok(monkeypatch, tmp_path):
    """Exit 0 + marcador de éxito → ok; el log queda completo."""
    _siril(
        monkeypatch,
        "log: Apilado completado.\n"
        "log: Script ejecutado correctamente.\n",
    )
    res = siril_runner.ejecutar_script(["stack light"], cwd=tmp_path)
    assert res.ok and res.motivo == ""
    assert any("Apilado completado" in linea for linea in res.lineas)


def test_marcador_de_fallo_en_espanol_no_es_ok(monkeypatch):
    """Marcador «fallida» en español → ok=False aunque el exit sea 0."""
    _siril(monkeypatch, "log: Ejecución de script fallida.\n", returncode=0)
    res = siril_runner.ejecutar_script(["malo"])
    assert not res.ok and res.motivo


def test_marcador_de_fallo_en_ingles_no_es_ok(monkeypatch):
    """El mismo SirIL en inglés también se detecta."""
    _siril(monkeypatch, "log: Script execution failed.\n", returncode=0)
    res = siril_runner.ejecutar_script(["malo"])
    assert not res.ok


def test_exit_distinto_de_cero_es_fallo(monkeypatch):
    """Exit 1 (p. ej. comando no scriptable) → fallo con el código en el motivo."""
    _siril(monkeypatch, "log: Saliendo del proceso por lotes.\n", returncode=1)
    res = siril_runner.ejecutar_script(["ls"])
    assert not res.ok and "1" in res.motivo


def test_esperados_faltantes_son_fallo(monkeypatch, tmp_path):
    """SirIL puede fallar en silencio: si el fichero pedido no existe, es fallo."""
    _siril(monkeypatch, "log: Script ejecutado correctamente.\n")
    res = siril_runner.ejecutar_script(
        ["stack light"], esperados=[tmp_path / "apilado.fits"]
    )
    assert not res.ok and "apilado.fits" in res.motivo


def test_esperados_presentes_son_ok(monkeypatch, tmp_path):
    """Los ficheros esperados creados → ok."""
    objetivo = tmp_path / "apilado.fits"
    objetivo.write_bytes(b"fits")
    _siril(monkeypatch, "log: Script ejecutado correctamente.\n")
    res = siril_runner.ejecutar_script(["stack light"], esperados=[objetivo])
    assert res.ok


def test_sin_siril_lanza_error(monkeypatch):
    """Sin binario no se intenta siquiera lanzar el proceso."""
    monkeypatch.setattr(siril_runner, "find_siril", lambda: None)
    with pytest.raises(SirilError):
        siril_runner.ejecutar_script(["stack light"])


def test_binario_de_tarea_no_consulta_sqlite_en_worker(monkeypatch):
    """La ruta capturada en UI se usa sin consultar settings desde otro hilo."""
    import concurrent.futures

    rutas = []

    def no_buscar():
        """Una búsqueda desde el worker sería acceso a la BD equivocada."""
        raise AssertionError("find_siril no debe ejecutarse en el worker")

    monkeypatch.setattr(siril_runner, "find_siril", no_buscar)
    monkeypatch.setattr(
        siril_runner.subprocess, "Popen",
        lambda args, **_kw: (
            rutas.append(args[0]) or _ProcFalso("Script ejecutado correctamente.\n")
        ),
    )

    def ejecutar():
        """Simula el hilo Qt con su propio contexto de SirIL."""
        with siril_runner.binario_de_tarea("/bin/siril-capturado"):
            return siril_runner.ejecutar_script(["stack light"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(ejecutar).result().ok
    assert rutas == ["/bin/siril-capturado"]
    assert siril_runner._binario_tarea.get() is None


def test_progreso_y_log_en_vivo(monkeypatch):
    """Las líneas progress alimentan progress_cb (0..1) y log_cb recibe el log."""
    _siril(
        monkeypatch,
        "progress: Registro. Procesando imagen 1, 18.87%\n"
        "progress: Registro. Procesando imagen 5, 100,00%\n"
        "log: Script ejecutado correctamente.\n",
    )
    fracciones, lineas = [], []
    res = siril_runner.ejecutar_script(
        ["register pp_light"],
        progress_cb=fracciones.append,
        log_cb=lineas.append,
    )
    assert res.ok
    assert fracciones == [pytest.approx(0.1887), pytest.approx(1.0)]
    assert any("Registro" in linea for linea in lineas)


def test_log_muestra_guion_pero_oculta_solo_hdu_repetitivo(monkeypatch, tmp_path):
    """El log visible permite auditar órdenes y no se llena de líneas HDU."""
    _siril(monkeypatch, "HDU 1: type=0, EXTNAME=\n"
           "log: Saving FITS: pp_light_00001.fit\n"
           "Script ejecutado correctamente.\n")
    visible = []
    res = siril_runner.ejecutar_script(
        ["calibrate light_ -dark=master_dark.fit"], cwd=tmp_path,
        log_cb=visible.append,
    )
    assert res.ok
    assert any("calibrate light_ -dark=master_dark.fit" in l for l in visible)
    assert any("Saving FITS" in l for l in visible)
    assert not any(l.startswith("HDU 1: type=0") for l in visible)
    assert any(l.startswith("HDU 1: type=0") for l in res.lineas)


def test_log_visible_sin_controles_ansi_pero_con_diagnostico_y_progreso(monkeypatch):
    """Los controles de cursor de SirIL no ocultan mensajes ni alteran el progreso."""
    _siril(monkeypatch, "\x1b[A\x1b[2K\n"
           "\x1b[2Kprogress: Apilando, 72.5%\n"
           "\x1b[2Klog: Stacked sequence successfully.\n"
           "Script execution finished successfully.\n")
    visible, progreso = [], []
    res = siril_runner.ejecutar_script(
        ["stack r_registro_"], log_cb=visible.append, progress_cb=progreso.append,
    )
    assert res.ok
    assert progreso == [pytest.approx(0.725)]
    assert not any("\x1b" in linea for linea in visible)
    assert any("Stacked sequence successfully" in linea for linea in visible)
    assert "\x1b[A\x1b[2K" in res.lineas


def test_eliminar_todo_working_solo_desvincula_originales(monkeypatch, tmp_path):
    """La limpieza total exige raíz propia y nunca sigue enlaces a originales."""
    raiz = tmp_path / "working"
    raiz.mkdir()
    origen = tmp_path / "original.fit"
    origen.write_bytes(b"original")
    (raiz / "apilado.fit").write_bytes(b"salida")
    enlace = raiz / "light.fit"
    siril_runner.enlazar(origen, enlace)
    monkeypatch.setattr(siril_runner, "WORKING_FOLDER", raiz)
    with pytest.raises(SirilError):
        siril_runner.eliminar_salidas_trabajo(tmp_path)
    siril_runner.eliminar_salidas_trabajo(raiz)
    assert list(raiz.iterdir()) == []
    assert origen.read_bytes() == b"original"


# ----------------------------------------------------------------------- ini
def test_ini_se_crea_con_force_16bit(monkeypatch, tmp_path):
    """El ini propio nace con force_16bit=false (y en la carpeta de trabajo)."""
    monkeypatch.setattr(siril_runner, "WORKING_FOLDER", tmp_path)
    ruta = siril_runner.ini_path()
    assert ruta.exists() and "force_16bit=false" in ruta.read_text(encoding="utf-8")


def test_ini_se_repara_si_esta_roto(monkeypatch, tmp_path):
    """Si el usuario borra o corrompe el ini, la siguiente corrida lo restaura."""
    monkeypatch.setattr(siril_runner, "WORKING_FOLDER", tmp_path)
    (tmp_path / siril_runner.INI_PROPIO).write_text("basura", encoding="utf-8")
    ruta = siril_runner.ini_path()
    assert "force_16bit=false" in ruta.read_text(encoding="utf-8")


# ------------------------------------------------------------------- enlazar
def test_enlazar_no_duplica_el_original(tmp_path):
    """En Windows sin privilegios acepta hardlink sin copiar; si puede, symlink."""
    origen = tmp_path / "original.fits"
    origen.write_bytes(b"fits")
    enlace = tmp_path / "enlace.fits"
    siril_runner.enlazar(origen, enlace)
    if enlace.is_symlink():
        assert enlace.resolve() == origen.resolve()
    else:
        assert enlace.stat().st_ino == origen.stat().st_ino
        assert enlace.stat().st_dev == origen.stat().st_dev


def test_argumentos_windows_usados_en_script_son_portables(tmp_path):
    """SirIL no recibe barras inversas (escapes) ni pierde espacios o acentos."""
    destino = tmp_path / "sesión con espacios" / "pila.fit"
    argumento = siril_runner.arg_ruta(f"-out={destino}")
    assert argumento == f'"-out={destino.as_posix()}"'
    assert "\\" not in argumento


def test_limpieza_no_puede_borrar_la_raiz_de_trabajo(tmp_path):
    """Una limpieza mal dirigida no debe vaciar toda la carpeta working."""
    raiz = tmp_path / "working"
    raiz.mkdir()
    centinela = raiz / "no_borrar.fit"
    centinela.write_bytes(b"original")
    with pytest.raises(SirilError):
        siril_runner.limpiar_trabajo(raiz, raiz=raiz)
    assert centinela.read_bytes() == b"original"


def test_limpieza_incompleta_no_reutiliza_restos(tmp_path, monkeypatch):
    """Si falla el borrado, no se continúa sobre archivos de otra corrida."""
    raiz = tmp_path / "working"
    destino = raiz / "calibrados" / "noche"
    destino.mkdir(parents=True)
    viejo = destino / "resto.fit"
    viejo.write_bytes(b"corrida anterior")
    monkeypatch.setattr(siril_runner.shutil, "rmtree", lambda *_a, **_kw: None)

    with pytest.raises(SirilError, match="limpiar|borrar"):
        siril_runner.limpiar_trabajo(destino, raiz=raiz)
    assert viejo.read_bytes() == b"corrida anterior"


def test_enlazar_falla_a_hardlink_si_no_hay_symlink(tmp_path, monkeypatch):
    """Sin symlinks (Windows sin privilegios) cae a hardlink: mismo contenido, cero copias."""
    origen = tmp_path / "original.fits"
    origen.write_bytes(b"fits")
    enlace = tmp_path / "enlace.fits"

    def _sin_symlink(self, *args, **kwargs):
        raise OSError("symlink no soportado")

    monkeypatch.setattr(type(enlace), "symlink_to", _sin_symlink)
    siril_runner.enlazar(origen, enlace)
    assert not enlace.is_symlink() and enlace.read_bytes() == b"fits"
    # Hardlink de verdad: mismo inodo, no una copia nueva.
    assert origen.stat().st_ino == enlace.stat().st_ino


def test_enlazar_sin_nada_disponible_lanza(tmp_path, monkeypatch):
    """Ni symlink ni hardlink → error claro, jamás una copia."""
    origen = tmp_path / "original.fits"
    origen.write_bytes(b"fits")
    enlace = tmp_path / "enlace.fits"

    def _sin_symlink(self, *args, **kwargs):
        raise OSError("symlink no soportado")

    monkeypatch.setattr(type(enlace), "symlink_to", _sin_symlink)
    monkeypatch.setattr(siril_runner.os, "link", lambda *a: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(SirilError):
        siril_runner.enlazar(origen, enlace)
    assert not enlace.exists()


# ------------------------------------------------------------- cancelación
def test_cancelar_siril_mata_el_proceso_en_curso():
    """El gancho de cancelación mata el SirIL vivo (lo usa la UI con Cancelar)."""
    proc = _ProcFalso("")
    proc.poll = lambda: None  # sigue vivo
    matado = []
    proc.kill = lambda: matado.append(True)
    siril_runner._proc_actual = proc
    try:
        siril_runner.cancelar_siril()
    finally:
        siril_runner._proc_actual = None
    assert matado == [True]


def test_cancelar_siril_sin_corrida_o_ya_terminada_no_hace_nada():
    """Sin proceso marcado, o con uno ya finado, no revienta ni mata nada."""
    siril_runner._proc_actual = None
    siril_runner.cancelar_siril()  # no debe lanzar

    proc = _ProcFalso("")
    proc.poll = lambda: -1  # ya terminado
    proc.kill = lambda: (_ for _ in ()).throw(AssertionError("no debe matar"))
    siril_runner._proc_actual = proc
    try:
        siril_runner.cancelar_siril()
    finally:
        siril_runner._proc_actual = None


def test_ejecutar_script_registra_y_limpia_el_proceso(monkeypatch):
    """La corrida expone su Popen (para poder cancelarla) y lo limpia al salir."""
    monkeypatch.setattr(siril_runner, "find_siril", lambda: "/usr/bin/siril")
    durante = []
    proc = _ProcFalso("ok\n")
    proc.wait = lambda: durante.append(siril_runner._proc_actual) or 0
    monkeypatch.setattr(siril_runner.subprocess, "Popen", lambda *a, **k: proc)

    res = siril_runner.ejecutar_script(["echo hola"])

    assert res.ok
    assert durante == [proc]  # dentro de la corrida estaba marcado
    assert siril_runner._proc_actual is None  # y fuera, nunca se cuelga
