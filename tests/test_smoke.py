"""Smoke tests: la estructura y la base de PASS están sanas (arranque, docs, esquema y ventana)."""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_main_imports_and_tabs():
    """main.py importa y define las 6 pestañas esperadas."""
    import main  # noqa: F401
    from ui.main_window import TABS

    assert len(TABS) == 6
    keys = [key for key, _title in TABS]
    assert keys == [
        "summary_tab",
        "planetary_tab",
        "equipment_tab",
        "planner_equip_tab",
        "planner_tab",
        "stacker_tab",
    ]


def test_root_docs_exist():
    """Los documentos de nivel raíz están; los de trabajo, si los incluye la copia."""
    for doc in ("README.md", "LICENSE", "requirements.txt", ".gitignore"):
        assert (ROOT / doc).exists(), f"Falta {doc}"

    # PROGRAM/MEMORY/STRUCTURE son documentos de trabajo: pueden faltar en una copia.
    internos = ("PROGRAM.md", "MEMORY.md", "STRUCTURE.md")
    if not any((ROOT / doc).exists() for doc in internos):
        pytest.skip("Documentos de trabajo ausentes")
    for doc in internos:
        assert (ROOT / doc).exists(), f"Falta {doc}"


def test_readme_publico_no_cita_documentos_internos():
    """El README público no dirige a documentos de trabajo no distribuidos."""
    contenido = (ROOT / "README.md").read_text(encoding="utf-8")

    for nombre in ("PROGRAM.md", "MEMORY.md", "STRUCTURE.md"):
        assert nombre not in contenido


def test_every_code_folder_has_readme():
    """Convención: toda carpeta con código tiene su README.md (4 secciones)."""
    folders = [
        "db",
        "planners",
        "planners/weather",
        "stacks",
        "equipment",
        "planetary",
        "ui",
        "ui/summary_tab",
        "ui/planetary_tab",
        "ui/equipment_tab",
        "ui/planner_equip_tab",
        "ui/planner_tab",
        "ui/planner_tab/busqueda",
        "ui/planner_tab/catalogo_personal",
        "ui/planner_tab/planificacion",
        "ui/planner_tab/sesiones",
        "ui/stacker_tab",
        "i18n",
        "tests",
    ]
    # Los README de carpeta son documentos de trabajo: pueden faltar en una copia.
    faltantes = [f for f in folders if not (ROOT / f / "README.md").exists()]
    if len(faltantes) == len(folders):
        pytest.skip("READMEs de carpeta ausentes")
    assert not faltantes, f"Falta README.md en: {', '.join(faltantes)}"

    for folder in folders:
        readme = ROOT / folder / "README.md"
        text = readme.read_text(encoding="utf-8")
        for section in ("## Qué es", "## Estado actual", "## Qué hacer aquí", "## Planes futuros"):
            assert section in text, f"{folder}/README.md sin sección {section!r}"


def test_schema_applies():
    """El esquema SQLite se aplica sin errores (idempotente)."""
    conn = sqlite3.connect(":memory:")
    schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "locations",
        "equipment_setups",
        "equipment_images",
        "personal_catalog",
        "planned_sessions",
        "settings",
        "catalog",
        "stars",
        # Componentes globales + imágenes por entidad (Equipo v2)
        "telescopes",
        "cameras",
        "mounts",
        "filters",
        "setup_filters",
        "telescope_images",
        "camera_images",
        "location_images",
    } <= tables
    conn.close()


def test_tab_glyphs_cover_all_tabs():
    """Cada pestaña tiene su glifo de icono en la barra lateral."""
    from ui.main_window import TAB_GLYPHS, TABS

    for key, _title in TABS:
        assert TAB_GLYPHS.get(key), f"Falta glifo para {key}"


def test_main_window_layout(qt_app):
    """La ventana crea barra lateral (6 filas + config), contenido y pie con versión."""

    from PyQt6.QtWidgets import QLabel, QTabWidget

    from ui.main_window import APP_VERSION, MainWindow

    _app = qt_app
    window = MainWindow()

    # Barra lateral: 6 pestañas + botón de configuración
    assert window.sidebar.nav.count() == 6
    assert window.sidebar.settings_button is not None

    # Contenido: 6 páginas; el Planificador (índice 4) tiene 4 subpestañas
    assert window.content.count() == 6
    planner_tabs = window.content.widget(4).findChild(QTabWidget)
    assert planner_tabs is not None and planner_tabs.count() == 4

    # Pie de página con nombre y versión
    footer = window.findChild(QLabel, "Footer")
    assert footer is not None
    assert APP_VERSION in footer.text()

    # Navegación: cambiar de fila cambia la página
    window.sidebar.nav.setCurrentRow(5)
    assert window.content.currentIndex() == 5

    window.close()

