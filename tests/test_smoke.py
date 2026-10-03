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


def test_ephemeris_panel_fills_its_cell():
    """El cuadro de Efemérides llena su celda y no pellizca a los otros.

    Regresión del hueco que quedaba sobre Ubicación: el container de
    Efemérides llevaba un ``addStretch(1)`` después del panel, que se
    tragaba el sobrante (medido: 177 px en 1919×1026). Se sustituyó por
    ``addWidget(panel, 1)``, que estira el marco sin subir su sizeHint;
    así la rejilla reparte igual y **Filtros y Ubicación no cambian de
    alto** (antes y después: 406 y 135 px en ese tamaño).

    El aire del interior (rango 1:3:3) va a la Luna y a los dos rótulos de
    abajo; la barra día/noche **no** se lo lleva: es de altura fija de
    44 px, por petición del usuario.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication, QGridLayout, QLabel, QTabWidget

    from ui.main_window import MainWindow
    from ui.planner_tab.widgets import DAY_NIGHT_BAR_HEIGHT, DayNightBar, EphemerisPanel

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    window.content.setCurrentIndex(4)      # página del Planificador visible
    window.resize(1919, 1026)              # tamaño holgado, como el real
    for _ in range(3):
        app.processEvents()

    page = window.content.widget(4).findChild(QTabWidget).widget(0)

    def find_grid(layout):
        for index in range(layout.count()):
            child = layout.itemAt(index).layout()
            if isinstance(child, QGridLayout):
                return child
            if child is not None:
                found = find_grid(child)
                if found is not None:
                    return found
        return None

    grid = find_grid(page.layout())
    assert grid is not None
    page.layout().activate()
    app.processEvents()

    filtros = grid.itemAtPosition(0, 0).widget()
    efem = grid.itemAtPosition(1, 0).widget()
    ubic = grid.itemAtPosition(2, 0).widget()
    efem.layout().activate()
    panel = efem.findChild(EphemerisPanel)

    # Sin hueco: el marco llega hasta la fila siguiente.
    assert panel is not None and efem.height() == panel.height()

    # Y las otras dos filas no se quedan cortas (no hay que robarles alto).
    assert filtros.height() >= filtros.sizeHint().height()
    assert ubic.height() >= ubic.sizeHint().height()

    # La barra día/noche es de altura fija en el layout real: no crece
    # con el sobrante del cuadro.
    bar = panel.findChild(DayNightBar)
    assert bar is not None and bar.height() == DAY_NIGHT_BAR_HEIGHT

    # El aire va a la Luna y a los dos rótulos de abajo (1:3:3), no a la
    # barra (0).
    layout = panel.layout()
    assert layout.stretch(layout.indexOf(panel._bar)) == 0
    assert layout.stretch(layout.indexOf(panel._sunset_label)) == 3
    assert layout.stretch(layout.indexOf(panel._night_label)) == 3

    # Rótulo de la sección renombrado.
    titles = [
        label.text()
        for label in panel.findChildren(QLabel)
        if label.objectName() == "MetricTitle"
    ]
    assert "PUESTA DE SOL Y NOCHE ASTRONÓMICA" in titles
    assert "LUZ DEL DÍA Y NOCHE ASTRONÓMICA" not in titles

    window.close()


def test_day_night_bar_dynamic_axis():
    """La barra día/noche va de 1 h antes de la puesta a 1 h después de la salida.

    Eje dinámico, al estilo de la Curva de Tránsito (petición del usuario):
    los «00h 06h 12h 18h» fijos no decían nada del rango real de esa noche.
    Las etiquetas son ``HH:MM`` cada 2 h dentro del rango (subiendo a 3/4/6 h
    si no caben) y sin repetirse. Sin puesta/salida se pinta el día completo.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from ui.planner_tab.widgets import (
        DAY_NIGHT_BAR_HEIGHT,
        DayNightBar,
        fmt_hhmm,
    )

    app = QApplication.instance() or QApplication([])
    bar = DayNightBar()

    # Altura fija: no crece (ni por política ni por mínimos) con el aire.
    assert bar.minimumHeight() == bar.maximumHeight() == DAY_NIGHT_BAR_HEIGHT

    # Puesta 17:30 y salida 05:30 → rango 16:30 … 06:30 desenvuelto.
    bar.set_marks(17.5, 18.7, 4.3, 5.5)
    start, end = bar.hour_range()
    assert (start, end) == (16.5, 30.5)

    # Horas redondas dentro del rango, cada 2 h, sin repetir etiquetas.
    ticks = bar.tick_hours(400)
    assert ticks == [18.0, 20.0, 22.0, 24.0, 26.0, 28.0, 30.0]
    assert all(start <= tick <= end for tick in ticks)
    assert [fmt_hhmm(tick % 24) for tick in ticks] == [
        "18:00", "20:00", "22:00", "00:00", "02:00", "04:00", "06:00",
    ]

    # Sin puesta/salida: día completo de 00 h a 24 h.
    bar.set_marks(None, None, None, None)
    assert bar.hour_range() == (0.0, 24.0)
    labels = [fmt_hhmm(tick % 24) for tick in bar.tick_hours(400)]
    assert len(labels) == len(set(labels))     # el 00:00 no sale dos veces

    # Si2 h por etiqueta no caben, el paso sube solo (2 h → 3 h → 4 h → 6 h).
    assert bar.tick_hours(200) == [0.0, 6.0, 12.0, 18.0]

    app.processEvents()


def test_curve_windows_line_is_reserved():
    """La curva no cambia su mínimo al llegar los datos (sin reflow).

    El rótulo «★ Captura Ideal / ⚠ Captura Posible» estaba **oculto** sin
    datos: al seleccionar un objeto aparecía y el mínimo del panel crecía
    **+21 px** (235 → 256 medidos), la rejilla de Búsqueda reequilibraba
    las filas y el cuadro de Efemérides se hinchaba — los dos rótulos de
    abajo cambiaban de tamaño con los datos (panel 272 → 294 px y rótulos
    22 → 33 px). Ahora la línea se reserva con **texto en blanco** desde
    el arranque (petición del usuario: los tamaños tienen que estar
    puestos antes), así que el mínimo es el mismo con y sin datos.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from ui.planner_tab.widgets import TransitCurve

    app = QApplication.instance() or QApplication([])
    curve = TransitCurve()
    curve.clear()                       # estado sin selección

    label = curve._windows_label
    assert not label.isHidden()         # la línea sigue reservada
    assert label.text().strip() == ""   # ...con texto en blanco

    # El mínimo no se mueve cuando llega el texto de datos.
    before = curve.minimumSizeHint().height()
    label.setText(
        "★ Captura Ideal: 00:08 – 01:54 (1h 46min) · "
        "⚠ Captura Posible: 00:08 – 02:19 (2h 11min)"
    )
    assert curve.minimumSizeHint().height() == before

    app.processEvents()


def test_find_siril_does_not_crash():
    """Detección de SirIL funciona aunque no esté instalado (None o ruta)."""
    from stacks.siril_finder import find_siril

    result = find_siril()
    assert result is None or isinstance(result, str)
