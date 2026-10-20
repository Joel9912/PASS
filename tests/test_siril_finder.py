"""stacks/siril_finder: localización del binario de SirIL y versión instalada.

El descubrimiento (ruta guardada primero, PATH solo sin configuración) no
toca la BD: `settings` lo lee la UI y se lo pasa por parámetro (A-03). La
lectura de ``--version`` va con ``subprocess.run`` sustituido: nunca se
ejecuta SirIL.
"""
import pytest

from stacks import siril_finder


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_version_sin_consola(monkeypatch, platform):
    """S-0023: comprobar versión tampoco abre terminales ni pierde stdout o timeout."""
    import subprocess
    from types import SimpleNamespace

    monkeypatch.setattr(siril_finder, "sys", SimpleNamespace(platform=platform), raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    calls = []

    def run(args, **kwargs):
        """Simula una versión válida capturando las opciones del proceso."""
        calls.append(kwargs)
        return subprocess.CompletedProcess(args, 0, "Siril prueba\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert siril_finder.siril_version("siril-falso") == "Siril prueba"
    assert calls[0].get("creationflags", 0) == (0x08000000 if platform == "win32" else 0)
    assert calls[0]["capture_output"]
    assert calls[0]["timeout"] == 10


def test_find_siril_falls_back_to_saved_path(monkeypatch):
    """Sin SirIL en el PATH usa la ruta que aporta el llamante."""
    monkeypatch.setattr(siril_finder, "which", lambda _name: None)
    assert siril_finder.find_siril() is None

    assert (
        siril_finder.find_siril(r"C:\Program Files\Siril\bin\siril-cli.exe")
        == r"C:\Program Files\Siril\bin\siril-cli.exe"
    )


@pytest.mark.parametrize("saved", ["ruta-inexistente", "D:/otra instalacion/siril-cli.exe"])
def test_find_siril_prefiere_guardada_sin_fallback(monkeypatch, saved):
    """La elección, incluso inválida, no se sustituye por otra instalación del PATH."""
    calls = []
    monkeypatch.setattr(siril_finder, "which", lambda name: calls.append(name) or "C:/bin/siril.exe")
    assert siril_finder.find_siril(saved) == saved
    assert calls == []


def test_find_siril_auto_prefiere_cli(monkeypatch):
    """Sin elección se permite detección, con preferencia por CLI sobre GUI."""
    monkeypatch.setattr(siril_finder, "which", lambda name: f"D:/auto/{name}.exe")
    assert siril_finder.find_siril("") == "D:/auto/siril-cli.exe"


@pytest.mark.parametrize("present", [True, False])
def test_gui_configurada_no_salta_a_otra_instalacion(monkeypatch, tmp_path, present):
    """La apertura gráfica busca solo la compañera de la instalación elegida."""
    cli = tmp_path / "siril-cli.exe"
    cli.touch()
    gui = tmp_path / "siril.exe"
    if present:
        gui.touch()
    calls = []
    monkeypatch.setattr(siril_finder, "which", lambda name: calls.append(name) or "D:/otra/siril.exe")
    assert siril_finder.find_siril_gui(str(cli)) == (str(gui) if present else None)
    assert calls == []


def test_ruta_invalida_avisa_sin_ejecutar_el_path(monkeypatch, tmp_path):
    """El runner informa del fallo de la elección en lugar de ejecutar otra instalación."""
    from stacks import siril_runner

    selected = str(tmp_path / "inexistente.exe")
    monkeypatch.setattr(siril_finder, "which", lambda name: "D:/otra/siril.exe")
    calls = []

    def start(args, **kwargs):
        """Falla de forma controlada sin iniciar procesos externos."""
        calls.append(args[0])
        raise FileNotFoundError("Binario configurado ausente")

    monkeypatch.setattr(siril_runner.subprocess, "Popen", start)
    with (siril_runner.binario_de_tarea(siril_finder.find_siril(selected)),
          pytest.raises(siril_runner.SirilError, match="No se pudo arrancar SirIL")):
        siril_runner.ejecutar_script(["noop"])
    assert calls == [selected]


def test_find_siril_ignores_empty_saved_path(monkeypatch):
    """Una ruta vacía cuenta como «no guardado»."""
    monkeypatch.setattr(siril_finder, "which", lambda _name: None)
    assert siril_finder.find_siril("") is None


def test_find_siril_gui_sin_settings_ni_preferencia_cli(monkeypatch):
    """La variante gráfica viene del PATH, sin mirar ruta guardada (A-12)."""
    monkeypatch.setattr(siril_finder, "which", lambda name: "C:/bin/siril.exe" if name == "siril" else None)
    assert siril_finder.find_siril_gui() == "C:/bin/siril.exe"

    monkeypatch.setattr(siril_finder, "which", lambda _name: None)
    assert siril_finder.find_siril_gui() is None


def test_siril_version_reads_first_line(monkeypatch):
    """siril_version devuelve la primera línea de `--version` si todo va bien."""
    import subprocess as sp

    def fake_run(_cmd, **_kwargs):
        """Sustituto de `subprocess.run`: SirIL responde con la 1.2.1 en stdout."""
        return sp.CompletedProcess(
            _cmd, 0, stdout="Siril 1.2.1\notra línea\n", stderr=""
        )

    monkeypatch.setattr(siril_finder.subprocess, "run", fake_run)
    assert siril_finder.siril_version("C:/siril/siril-cli.exe") == "Siril 1.2.1"


def test_siril_version_none_on_failure(monkeypatch):
    """Fallo de ejecución (código ≠ 0 o error del sistema) → None, sin excepciones."""
    import subprocess as sp

    def fake_run(_cmd, **_kwargs):
        """Sustituto de `subprocess.run`: SirIL devuelve código de salida 1 (fallo)."""
        return sp.CompletedProcess(_cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(siril_finder.subprocess, "run", fake_run)
    assert siril_finder.siril_version("malo.exe") is None

    def raise_oserror(_cmd, **_kwargs):
        """Sustituto de `subprocess.run` que revienta como si SirIL no existiera."""
        raise OSError("no existe")

    monkeypatch.setattr(siril_finder.subprocess, "run", raise_oserror)
    assert siril_finder.siril_version("otro.exe") is None


def test_find_siril_does_not_crash():
    """Detección de SirIL funciona aunque no esté instalado (None o ruta)."""
    from stacks.siril_finder import find_siril

    result = find_siril()
    assert result is None or isinstance(result, str)
