"""Regresiones de UI del Planificador: Búsqueda/Efemérides y cableados (M-04/M-05/M-15/M-19).

La ``QApplication`` viene del fixture ``qt_app`` de ``conftest.py``.
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_ajustes_guardados_refrescan_clima_por_tipo(qt_app, monkeypatch):
    """M-15: tras guardar API keys, Búsqueda se busca por tipo, no por índice.

    Con una página más delante del Planificador, `widget(4)` ya no lo es
    y el clima de Búsqueda no se refrescaba (y con `widget(4)` en None,
    crasheaba).
    """

    from PyQt6.QtWidgets import QLabel

    from ui.main_window import MainWindow
    from ui.planner_tab.busqueda import BusquedaTab

    window = MainWindow()
    busq = window.content.findChild(BusquedaTab)
    assert busq is not None

    llamadas: list[int] = []
    monkeypatch.setattr(busq, "refresh_weather", lambda: llamadas.append(1))

    # Página nueva delante del Planificador: el índice 4 ya no es él
    window.content.insertWidget(4, QLabel("pestaña extra"))
    window._on_settings_saved()

    assert llamadas == [1]
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


def test_planner_search_tab_corrections(qt_app):
    """Búsqueda: título «Catálogo», valores centrados y ◀/▶ en Lat/Lon.

    Correcciones rápidas del usuario:

    - el panel de resultados se llama «Catálogo», no «Objetos por filtro»;
    - todas las celdas centradas como sus cabeceras (antes Mag/Tránsito/
      Horas iban a la derecha);
    - los spinboxes de lat/lon van sin flechitas nativas (eran minúsculas
      y el clic a veces no acertaba) con ◀/▶ de 34 px como los de
      Efemérides, moviendo 1° por clic.
    """

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QAbstractSpinBox,
        QDoubleSpinBox,
        QLabel,
        QPushButton,
        QTableWidget,
        QTabWidget,
    )

    from ui.main_window import MainWindow
    from ui.planner_tab.busqueda import COLUMNS
    from ui.planner_tab.widgets import LocationBar

    _app = qt_app
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

def test_ephemeris_panel_fills_its_cell(qt_app):
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

    from PyQt6.QtWidgets import QGridLayout, QLabel, QTabWidget

    from ui.main_window import MainWindow
    from ui.planner_tab.widgets import DAY_NIGHT_BAR_HEIGHT, DayNightBar, EphemerisPanel

    app = qt_app
    window = MainWindow()
    window.show()
    window.content.setCurrentIndex(4)      # página del Planificador visible
    window.resize(1919, 1026)              # tamaño holgado, como el real
    for _ in range(3):
        app.processEvents()

    page = window.content.widget(4).findChild(QTabWidget).widget(0)

    def find_grid(layout):
        """Busca el primer QGridLayout anidado (los paneles envuelven sus widgets)."""
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

def test_day_night_bar_dynamic_axis(qt_app):
    """La barra día/noche va de 1 h antes de la puesta a 1 h después de la salida.

    Eje dinámico, al estilo de la Curva de Tránsito (petición del usuario):
    los «00h 06h 12h 18h» fijos no decían nada del rango real de esa noche.
    Las etiquetas son ``HH:MM`` cada 2 h dentro del rango (subiendo a 3/4/6 h
    si no caben) y sin repetirse. Sin puesta/salida se pinta el día completo.
    """

    from ui.planner_tab.widgets import (
        DAY_NIGHT_BAR_HEIGHT,
        DayNightBar,
        fmt_hhmm,
    )

    app = qt_app
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

def test_curve_windows_line_is_reserved(qt_app):
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

    from ui.planner_tab.widgets import TransitCurve

    app = qt_app
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



def test_hoy_emite_una_sola_vez(qt_app):
    """M-03: «Hoy» emite `date_changed` una vez (no dos, como antes).

    Regresión: `setDate` ya dispara `dateChanged`→`_emit_date` y además
    se emitía a mano, con lo que Búsqueda refrescaba dos veces.
    """
    from ui.planner_tab.widgets import EphemerisPanel

    panel = EphemerisPanel()
    panel.set_date("2026-10-01")
    emitidas: list[str] = []
    panel.date_changed.connect(emitidas.append)

    panel._go_today()

    assert emitidas == [panel.current_date_iso()]
    panel._go_today()  # ya en hoy: nada cambió, nada se emite
    assert len(emitidas) == 1
    panel.deleteLater()


def test_location_bar_reload_reselecciona_por_id(qt_app, monkeypatch):
    """C-4: `reload()` reselecciona por id y aplica los valores (re)leídos.

    Antes buscaba el dict entero con `findData`: tras editar una
    ubicación el dict ya no coincidía, el combo caía a «(Manual)» y los
    campos conservaban la lat/long vieja como si fueran manuales.
    """
    import equipment.localizations as localiz
    from ui.planner_tab.widgets import LocationBar

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO locations (name, latitude, longitude, utc_offset_hours)"
        " VALUES (?, ?, ?, ?)",
        ("Casa", 40.4, -3.7, 2.0),
    )
    conn.commit()
    monkeypatch.setattr(localiz, "get_connection", lambda: conn)

    bar = LocationBar()
    assert bar.has_saved_location()      # selecciona la primera guardada
    assert bar.latitude() == 40.4

    # Editar la ubicación: nombre y latitud cambian (el dict ya no coincide)
    conn.execute("UPDATE locations SET name = 'Casa nueva', latitude = 41.5 WHERE id = 1")
    conn.commit()

    bar.reload()

    assert bar.has_saved_location()      # sigue en la ubicación, no en Manual
    assert bar._combo.currentText() == "Casa nueva"
    assert bar.latitude() == 41.5        # con los valores ya editados

    # Modo manual: reload() no toca lo escrito a mano
    bar._combo.setCurrentIndex(0)
    bar._latitude.setValue(12.345)
    bar.reload()
    assert not bar.has_saved_location()
    assert bar.latitude() == 12.345

    conn.close()
    bar.deleteLater()


def test_reload_targets_actualiza_una_vez(qt_app, monkeypatch):
    """M-04: repoblar el combo de targets dispara `_on_target_changed` una vez.

    Antes `setCurrentIndex` emitía **y** se llamaba a mano: curva y
    encuadre se recalculaban dos veces por recarga (y `target_changed`
    se emitía dos veces).
    """
    from ui.planner_tab.planificacion import tab as plan_tab

    llamadas: list[int] = []
    original = plan_tab.PlanificacionTab._on_target_changed

    def contando(self, *args, **kwargs):
        """Sustituto de `_on_target_changed` que cuenta sus llamadas."""
        llamadas.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(plan_tab.PlanificacionTab, "_on_target_changed", contando)
    filas = [
        {"object_id": "M42", "catalog": "messier"},
        {"object_id": "M31", "catalog": "messier"},
    ]
    monkeypatch.setattr(plan_tab.personal_catalog, "list_objects", lambda: filas)

    page = plan_tab.PlanificacionTab()
    page._target.setCurrentIndex(1)   # selecciona el segundo
    llamadas.clear()

    page.reload_targets()             # keep_current: debe volver al índice 1

    assert len(llamadas) == 1
    page.deleteLater()


def test_reload_setups_mantiene_la_seleccion(qt_app, monkeypatch):
    """M-19: repoblar el combo de equipos reselecciona por id, no al primero."""
    from ui.planner_tab.planificacion import tab as plan_tab

    setups = [
        {"id": 1, "name": "Cámara nocturna", "category": "espacio_profundo"},
        {"id": 2, "name": "Setup planetario", "category": "planetario"},
    ]
    monkeypatch.setattr(plan_tab, "list_setups", lambda: setups)
    monkeypatch.setattr(plan_tab.personal_catalog, "list_objects", list)

    page = plan_tab.PlanificacionTab()
    page._setup.setCurrentIndex(1)    # el segundo (id 2)

    page.reload_setups()

    assert page._setup.currentData()["id"] == 2
    page.deleteLater()


def test_refresh_no_repite_lo_que_no_cambio(qt_app, monkeypatch):
    """M-01: aplicar filtros/Enter no vuelve a calcular astropy.

    Antes cada `refresh()` (clic «Aplicar filtros», Enter, reordenar,
    «Hoy») recalculaba las 4 partes aunque solo los filtros hubieran
    cambiado: ~1,1 s de efemérides+curva por clic. Ahora la búsqueda
    corre siempre (los filtros pueden haber cambiado) y las partes
    caras se saltan si su clave (objeto/noche/ubicación/huso) no cambió.
    """
    from ui.planner_tab.busqueda import tab as busq_tab

    page = busq_tab.BusquedaTab()

    busquedas: list[int] = []
    efemerides: list[int] = []
    clima: list[int] = []
    limpiezas: list[int] = []
    monkeypatch.setattr(page, "_run_search", lambda *a, **k: busquedas.append(1))
    monkeypatch.setattr(
        page._ephemeris, "refresh", lambda *a, **k: efemerides.append(1)
    )
    monkeypatch.setattr(page._weather, "refresh", lambda *a, **k: clima.append(1))
    monkeypatch.setattr(page._curve, "clear", lambda *a, **k: limpiezas.append(1))

    page.set_location(40.4, -3.7, 2.0)      # primera vez: todo corre
    assert len(efemerides) == 1 and len(clima) == 1

    page.refresh()                          # «Aplicar filtros» sin más cambios
    assert len(busquedas) == 2              # la búsqueda sí corre siempre…
    assert len(efemerides) == 1             # …pero efemérides no…
    assert len(clima) == 1                  # …ni clima…
    assert len(limpiezas) == 0              # …ni la curva (sin selección)

    page.set_location(41.0, -3.7, 2.0)      # cambia la latitud → sí recalcula
    assert len(efemerides) == 2 and len(clima) == 2
    page.deleteLater()


def test_calcular_plan_bloquea_la_reentrada(qt_app, monkeypatch):
    """M-08: «Calcular plan» desactiva el botón mientras calcula.

    `processEvents()` dejaba entregar un segundo clic dentro del mismo
    método: dos `best_dates` en reentrada (y las 30 noches calculadas
    dos veces, ~2 s perdidos).
    """
    from ui.planner_tab.planificacion import tab as plan_tab

    filas = [
        {
            "object_id": "M42", "catalog": "messier",
            "ra_hours": 5.588139, "dec_deg": -5.391111,
        },
    ]
    monkeypatch.setattr(plan_tab.personal_catalog, "list_objects", lambda: filas)

    page = plan_tab.PlanificacionTab()
    page.set_location(40.4, -3.7, 2.0)

    estados: list[bool] = []

    def best_dates_falso(*args, **kwargs):
        """Sustituto de `best_dates`: anota si el botón sigue activo y devuelve []."""
        estados.append(page._plan_button.isEnabled())
        return []

    monkeypatch.setattr(plan_tab, "best_dates", best_dates_falso)

    page._calculate_plan()

    assert estados == [False]           # botón desactivado mientras calcula
    assert page._plan_button.isEnabled()  # y reactivado al terminar
    page.deleteLater()


def test_catalog_labels_fuente_unica(monkeypatch):
    """M-12: una sola `CATALOG_LABELS` (en `widgets.py`) para las dos pestañas.

    Estaba duplicada con valores ya divergidos: el mismo catálogo se
    llamaba «LDN (nebulosas oscuras)»/«LDN» o «Otros»/«Otro» según
    dónde se mirara.
    """
    from ui.planner_tab.busqueda import tab as busq_tab
    from ui.planner_tab.catalogo_personal import tab as cat_tab
    from ui.planner_tab.widgets import CATALOG_LABELS

    assert busq_tab.CATALOG_LABELS is CATALOG_LABELS
    assert cat_tab.CATALOG_LABELS is CATALOG_LABELS
    assert CATALOG_LABELS["ldn"] == "LDN"
    assert CATALOG_LABELS["other"] == "Otros"
    assert CATALOG_LABELS["region"] == "Región"


def test_quitar_objeto_emite_catalog_changed(qt_app, monkeypatch):
    """M-05: quitar del catálogo personal avisa a Planificación (señal nueva).

    Sin la señal, Planificación seguía ofreciendo el target borrado y
    podía guardar una sesión de un objeto ya fuera del catálogo.
    """
    from planners import personal_catalog
    from ui.planner_tab.catalogo_personal import tab as cat_tab

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    monkeypatch.setattr(personal_catalog, "get_connection", lambda: conn)
    personal_catalog.add("M42", "messier")

    # Respuesta Sí al «¿Quitar…?» sin abrir QMessageBox.
    class _Caja:
        """QMessageBox falso: el «¿Quitar…?» responde Sí sin abrir ventana."""
        StandardButton = cat_tab.QMessageBox.StandardButton
        question = staticmethod(lambda *args, **kwargs: _Caja.StandardButton.Yes)

    monkeypatch.setattr(cat_tab, "QMessageBox", _Caja)

    page = cat_tab.CatalogoPersonalTab()
    assert page._table.rowCount() == 1
    page._table.selectRow(0)
    recibidas: list[int] = []
    page.catalog_changed.connect(lambda: recibidas.append(1))

    page._on_remove()

    assert recibidas == [1]
    assert conn.execute("SELECT COUNT(*) FROM personal_catalog").fetchone()[0] == 0
    conn.close()
    page.deleteLater()


def test_clima_worker_en_pool_sin_bd(qt_app, memory_settings):
    """Regresión A-32: `WeatherCards.refresh` no toca la BD desde el pool.

    Antes el runnable leía `settings` en un hilo de `QThreadPool` con la
    conexión creada en el hilo principal → `sqlite3.ProgrammingError`, la
    señal `listo` nunca llegaba y la app se caía (crashe de la revisión
    de v0.2). Las keys las lee ahora `refresh` en su hilo y viajan por
    parámetro: el resultado sí debe llegar con la nota «guardada».
    """
    import time

    from planners.weather.base import save_api_key
    from ui.planner_tab.widgets import WeatherCards

    save_api_key("clear_outside_api_key", "co-demo")
    save_api_key("meteoblue_api_key", "mb-demo")

    cards = WeatherCards()
    recibido: list[tuple] = []
    cards._senal.listo.connect(lambda *args: recibido.append(args))
    cards.refresh(10.0, -84.0, "2026-10-02")

    limite = time.monotonic() + 5.0
    while not recibido and time.monotonic() < limite:
        qt_app.processEvents()
        time.sleep(0.01)

    assert recibido, "el worker del clima no emitió (¿excepción en el pool?)"
    _peticion, clear, meteo = recibido[0]
    # Si la key no viajara por parámetro, la nota sería «Falta la API key».
    assert "guardada" in clear.note
    assert "guardada" in meteo.note
    cards.close()


def test_catalogo_personal_reaparece_tras_reabrir(qt_app, tmp_path, monkeypatch):
    """Los objetos añadidos desde Búsqueda vuelven al abrir con una conexión nueva.

    Usa una BD temporal y no la de ``data/``: tanto el INSERT como la
    lectura inicial de la nueva pestaña deben pasar por la misma ruta.
    """
    from db import connection as db_connection
    from ui.planner_tab.catalogo_personal.tab import CatalogoPersonalTab

    ruta = tmp_path / "pass.db"
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO catalog (object_id, catalog, messier_num) VALUES (?, ?, ?)",
        ("M33", "messier", 33),
    )
    conn.commit()
    monkeypatch.setattr(db_connection, "_connection", conn)

    primera = CatalogoPersonalTab()
    primera.add_object("M33", "messier")
    assert primera._table.rowCount() == 1
    primera.close()
    conn.close()

    nueva = sqlite3.connect(ruta)
    nueva.row_factory = sqlite3.Row
    monkeypatch.setattr(db_connection, "_connection", nueva)
    segunda = CatalogoPersonalTab()
    assert segunda._table.rowCount() == 1
    assert segunda._table.item(0, 1).text() == "M33"
    segunda.close()
    nueva.close()


def test_tarjetas_clima_muestran_pronostico_numerico(qt_app):
    """Una respuesta con datos no provoca KeyError al formatear las tarjetas."""
    from planners.weather.base import WeatherForecast
    from ui.planner_tab.widgets import WeatherCards

    cards = WeatherCards()
    cards._peticion = 1
    cards._rellenar(
        1,
        WeatherForecast("clear_outside", "2026-10-11", cloud_cover_pct=[20.0]),
        WeatherForecast("meteoblue", "2026-10-11", seeing_arcsec=[1.5]),
    )
    assert "20 %" in cards._cards["cloud"]._value.text()
    assert '1.5"' in cards._cards["seeing"]._value.text()
    cards.close()
def test_bandas_de_captura_coinciden_con_resumen_redondeado(qt_app, monkeypatch):
    """Las bandas pintan los mismos cortes y restos que las horas del resumen."""
    from types import SimpleNamespace

    from ui.planner_tab import widgets

    curva = widgets.TransitCurve()
    horas = [20 + 2 / 60, 21 + 8 / 60, 22.0]
    datos = SimpleNamespace(
        hours_local=horas, altitudes=[60, 35, 0], moon_altitudes=[-5, -5, -5],
        moon_separations=[90, 90, 90], astro_night=[True, True, False],
        moon_illumination=0.5, transit_index=0,
    )
    bandas = {}
    monkeypatch.setattr(curva._ideal_band, "set_spans", lambda spans: bandas.update(ideal=spans))
    monkeypatch.setattr(curva._possible_band, "set_spans", lambda spans: bandas.update(possible=spans))
    resumen = curva.show_curve(datos)
    assert bandas["ideal"] == [h for tramo in resumen["ideal"]["ranges"] for h in tramo]
    assert bandas["possible"] == [h for tramo in resumen["possible"]["ranges"] for h in tramo]
    curva.deleteLater()


def test_curva_corta_posible_en_cruce_lunar_cinco_grados(qt_app):
    """La UI utiliza el resumen refinado, no el minuto completo antes del cruce."""
    from types import SimpleNamespace

    import pytest

    from ui.planner_tab import widgets

    curva = widgets.TransitCurve()
    datos = SimpleNamespace(
        hours_local=[22.0, 22 + 1 / 60], altitudes=[60, 60], moon_altitudes=[4.8, 5.2],
        moon_separations=[10, 10], astro_night=[True, True],
        moon_illumination=0.5, transit_index=0,
    )
    resumen = curva.show_curve(datos)
    assert resumen["possible"]["hours"] == pytest.approx(0.5 / 60)
    assert resumen["possible"]["ranges"][0][1] == pytest.approx(22 + 0.5 / 60)
    curva.deleteLater()


def test_curva_aplica_margen_nocturno_y_corte_del_amanecer(qt_app, monkeypatch):
    """La gráfica consume alturas solares para cortar la noche y limitar Ideal."""
    from types import SimpleNamespace

    import pytest

    from ui.planner_tab import widgets

    curva = widgets.TransitCurve()
    bandas = []
    monkeypatch.setattr(curva._night_band, "set_spans", lambda spans: bandas.extend(spans))
    datos = SimpleNamespace(
        hours_local=[20, 20 + 10 / 60, 20 + 20 / 60], altitudes=[60] * 3,
        moon_altitudes=[-5] * 3, moon_separations=[100] * 3, astro_night=[False, True, False],
        sun_altitudes=[-17, -19, -17], moon_illumination=0.5, transit_index=1,
    )
    resumen = curva.show_curve(datos)
    assert resumen.get("ideal", {}).get("hours", 0) == 0
    assert resumen["possible"]["ranges"][0] == pytest.approx((20 + 5 / 60, 20 + 15 / 60))
    assert bandas == pytest.approx([20 + 5 / 60, 20 + 15 / 60])
    curva.deleteLater()
