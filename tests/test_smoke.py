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


def test_capture_ideal_star_is_green():
    """La ★ de «Captura Ideal» va envuelta en span verde.

    Sin el span toma el color del texto (azul de la interfaz) y se
    perdía sobre el panel; el verde es el de la banda Ideal y la ■ de
    la leyenda.
    """
    from planners.moon_distance import WINDOW_IDEAL, WINDOW_POSSIBLE
    from ui.planner_tab.widgets import window_lines

    ideal, posible = window_lines(
        {
            WINDOW_IDEAL: {"ranges": [(16.0, 20.5)]},
            WINDOW_POSSIBLE: {"ranges": []},
        }
    )
    assert '<span style="color:#22c55e">★</span> Captura Ideal' in ideal
    assert "Captura Ideal: 16:00–20:30" in ideal
    assert posible == "⚠ Captura Posible: sin ventana"


def test_planner_search_tab_corrections():
    """Búsqueda: título «Catálogo», valores centrados y ◀/▶ en Lat/Lon.

    Correcciones rápidas del usuario:

    - el panel de resultados se llama «Catálogo», no «Objetos por filtro»;
    - todas las celdas centradas como sus cabeceras (antes Mag/Tránsito/
      Horas iban a la derecha);
    - los spinboxes de lat/lon van sin flechitas nativas (eran minúsculas
      y el clic a veces no acertaba) con ◀/▶ de 34 px como los de
      Efemérides, moviendo 1° por clic.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QAbstractSpinBox,
        QApplication,
        QDoubleSpinBox,
        QLabel,
        QPushButton,
        QTabWidget,
        QTableWidget,
    )

    from ui.main_window import MainWindow
    from ui.planner_tab.busqueda import COLUMNS
    from ui.planner_tab.widgets import LocationBar

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    planner_tabs = window.content.widget(4).findChild(QTabWidget)
    planner_tabs.setCurrentIndex(0)  # Búsqueda
    page = planner_tabs.widget(0)

    # Título del panel de resultados
    titles = [
        label.text()
        for label in page.findChildren(QLabel)
        if label.objectName() == "PanelTitle"
    ]
    assert "Catálogo" in titles
    assert "Objetos por filtro" not in titles

    # Ubicación: ◀/▶ como los de Efemérides y spinbox sin botones nativos
    bar = page.findChild(LocationBar)
    assert bar is not None
    spins = bar.findChildren(QDoubleSpinBox)
    assert len(spins) == 2
    for spin in spins:
        assert spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        assert spin.singleStep() == 1.0
    assert [button.text() for button in bar.findChildren(QPushButton)] == [
        "◀",
        "▶",
        "◀",
        "▶",
    ]

    # Celdas centradas: relleno una fila de mentira y miro la alineación
    table = page.findChild(QTableWidget)
    assert table is not None
    page._fill_table(
        [
            {
                "object_id": "M31",
                "type": "Galaxy",
                "constellation": "And",
                "magnitude": 3.4,
                "ra_hours": 0.712,
                "dec_deg": 41.16,
                "size_major_arcmin": 178.0,
                "size_minor_arcmin": 63.0,
                "transit_local": "21:22",
                "hours_above_30": 3.5,
            }
        ]
    )
    assert table.columnCount() == len(COLUMNS)
    expected = int(Qt.AlignmentFlag.AlignCenter)
    for column in range(table.columnCount()):
        item = table.item(0, column)
        assert item is not None, f"Sin celda en la columna {column}"
        assert int(item.textAlignment()) == expected, (
            f"Columna {column} no centrada ({item.text()!r})"
        )

    window.close()


def test_find_siril_does_not_crash():
    """Detección de SirIL funciona aunque no esté instalado (None o ruta)."""
    from stacks.siril_finder import find_siril

    result = find_siril()
    assert result is None or isinstance(result, str)
