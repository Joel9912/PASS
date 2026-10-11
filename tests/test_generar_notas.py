"""`scripts/generar_notas.py`: las notas de versión salen de `BUGS.md` y de git."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "scripts" / "generar_notas.py"


def _modulo():
    """Carga el script como módulo para probar su lógica sin invocar git."""
    spec = importlib.util.spec_from_file_location("generar_notas", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["generar_notas"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_filtra_solo_corregidos_con_commit_en_el_rango(tmp_path):
    """El rango y el estado deciden: ✅ dentro, pendientes y de otra rama fuera."""
    registro = tmp_path / "BUGS.md"
    registro.write_text(
        "# Registro\n\n"
        "| Letra | Área |\n|---|---|\n| **S** | Apilador |\n\n"
        "## 🔴 Graves\n\n"
        "| ID | Bug | Evidencia | Estado |\n|---|---|---|---|\n"
        "| **S-0001** | Arreglado en el rango | `cafe001` | ✅ `cafe001` |\n"
        "| **S-0002** | Pendiente | `cafe002` | ⏳ |\n"
        "| **S-0003** | Arreglado en otra rama | `cafe003` | ✅ `cafe003` |\n"
        # Fila sin columna de evidencia (3 celdas): el parser debe tolerarla.
        "| **S-0004** | Corregido sin commit | ✅ sin commit registrado |\n"
        "| **S-0005** | Contenido a medias | `cafe005` | 🟡 `cafe005` |\n",
        encoding="utf-8",
    )
    modulo = _modulo()

    hallazgos = modulo.leer_bugs(registro)
    assert [h.identificador for h in hallazgos] == [
        "S-0001",
        "S-0002",
        "S-0003",
        "S-0004",
        "S-0005",
    ]
    assert modulo.leer_areas(registro) == {"S": "Apilador"}
    assert next(h for h in hallazgos if h.identificador == "S-0004").estado == (
        "✅ sin commit registrado"
    )

    rango = {("cafe001" * 6)[:40], ("cafe005" * 6)[:40]}
    seleccion = modulo.filtrar(hallazgos, rango)
    parciales = modulo.filtrar(hallazgos, rango, estados=("🟡",))
    assert [h.identificador for h in seleccion] == ["S-0001"]
    assert [h.identificador for h in parciales] == ["S-0005"]

    texto = modulo.componer(
        seleccion,
        modulo.leer_areas(registro),
        desde="v0.1-alpha",
        hasta="v0.2",
        parciales=parciales,
    )
    assert texto.startswith("<!-- NOTAS:INICIO -->")
    assert texto.endswith("<!-- NOTAS:FIN -->")
    assert "### Apilador (S)" in texto
    assert "S-0001" in texto and "S-0002" not in texto and "S-0004" not in texto
    assert "`cafe001`" in texto
    # El fix parcial no se pierde: sale en su propia sección, no en la principal.
    assert "### Mejoras parciales" in texto and "S-0005" in texto
    assert texto.index("### Mejoras parciales") > texto.index("### Apilador")


def test_sustituye_el_bloque_sin_tocar_lo_demas():
    """Regenerar solo reescribe entre marcadores; lo escrito a mano se conserva."""
    modulo = _modulo()
    previo = (
        "## v0.1\n\n- entrada vieja\n\n"
        "<!-- NOTAS:INICIO -->\nViejo\n<!-- NOTAS:FIN -->\n\n### Cola\n"
    )
    nuevo = modulo.sustituir_bloque(
        previo, "<!-- NOTAS:INICIO -->\nNuevo\n<!-- NOTAS:FIN -->"
    )
    assert "Viejo" not in nuevo and "Nuevo" in nuevo
    assert "- entrada vieja" in nuevo and "### Cola" in nuevo

    # Sin marcadores, el bloque nuevo se añade al final del texto existente.
    añadido = modulo.sustituir_bloque("## v0.1\n", "BLOCK")
    assert añadido.endswith("BLOCK\n")


@pytest.mark.skipif(shutil.which("git") is None, reason="git no está en el PATH")
def test_genera_notas_reales_del_repo():
    """Contra el repo real, el rango v0.1-alpha..HEAD recoge lo ya cerrado."""
    res = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(SCRIPT),
            "--desde",
            "v0.1-alpha",
            "--hasta",
            "HEAD",
            "--bugs",
            str(RAIZ / "BUGS.md"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=RAIZ,
    )
    assert res.returncode == 0, res.stderr
    assert "S-0001" in res.stdout and "S-0002" in res.stdout
    assert "264b5d0" in res.stdout
    # Los contenidos a medias con commit en el rango no se olvidan.
    assert "### Mejoras parciales" in res.stdout
    assert "B-0001" in res.stdout and "E-0002" in res.stdout
