"""Regresiones de entorno en subprocesos: sin permisos de symlink ni datos personales."""
import subprocess
import sys
from pathlib import Path


def test_sin_privilegio_symlink_no_oculta_fallos():
    """Las secuencias usan hardlinks; solo los dos casos de symlink real se omiten."""
    script = '''
import errno
from pathlib import Path
import pytest
def negar(*args, **kwargs):
    raise PermissionError(errno.EACCES, "symlink sin privilegios")
Path.symlink_to = negar
raise SystemExit(pytest.main([
    "tests/test_registration.py", "tests/test_stacker.py",
    "tests/test_calibrator.py::test_enlaza_lights_homonimos_de_filtros_distintos",
    "tests/test_stacker_tab.py::test_limpieza_calibrados_no_sigue_enlaces",
    "tests/test_siril_runner.py::test_enlazar_falla_a_hardlink_si_no_hay_symlink",
    "tests/test_siril_runner.py::test_enlazar_sin_nada_disponible_lanza",
    "-q", "--tb=short"
]))
'''
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", script],
                            cwd=Path(__file__).resolve().parent.parent,
                            capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 skipped" in result.stdout
