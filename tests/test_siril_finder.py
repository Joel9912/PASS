"""stacks/siril_finder: localización del binario de SirIL y versión instalada.

El descubrimiento (PATH primero, ruta guardada que aporta el llamante) no
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


def test_find_siril_prefers_path_over_saved(monkeypatch):
    """El PATH del sistema tiene prioridad sobre la ruta guardada."""
    monkeypatch.setattr(siril_finder, "which", lambda _name: "C:/bin/siril.exe")
    assert siril_finder.find_siril("ruta-antigua") == "C:/bin/siril.exe"


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
