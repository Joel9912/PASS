"""Smoke tests: la estructura y la base de PAS.S están sanas."""
import sqlite3
import sys
from pathlib import Path

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
    """Los documentos de nivel raíz existen."""
    for doc in (
        "README.md",
        "AGENTS.md",
        "PROGRAM.md",
        "MEMORY.md",
        "STRUCTURE.md",
        "LICENSE",
        "requirements.txt",
        ".gitignore",
    ):
        assert (ROOT / doc).exists(), f"Falta {doc}"


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
        "ui/stacker_tab",
        "i18n",
        "tests",
    ]
    for folder in folders:
        readme = ROOT / folder / "README.md"
        assert readme.exists(), f"Falta README.md en {folder}/"
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
    } <= tables
    conn.close()


def test_tab_glyphs_cover_all_tabs():
    """Cada pestaña tiene su glifo de icono en la barra lateral."""
    from ui.main_window import TABS, TAB_GLYPHS

    for key, _title in TABS:
        assert TAB_GLYPHS.get(key), f"Falta glifo para {key}"


def test_main_window_layout():
    """La ventana crea barra lateral (6 filas + config), contenido y pie con versión."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication, QLabel, QTabWidget

    from ui.main_window import APP_VERSION, MainWindow

    app = QApplication.instance() or QApplication([])
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


def test_find_siril_does_not_crash():
    """Detección de SirIL funciona aunque no esté instalado (None o ruta)."""
    from stacks.siril_finder import find_siril

    result = find_siril()
    assert result is None or isinstance(result, str)
