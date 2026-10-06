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
        "ui/planner_tab/busqueda",
        "ui/planner_tab/catalogo_personal",
        "ui/planner_tab/planificacion",
        "ui/planner_tab/sesiones",
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


def test_main_window_layout():
    """La ventana crea barra lateral (6 filas + config), contenido y pie con versión."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication, QLabel, QTabWidget

    from ui.main_window import APP_VERSION, MainWindow

    _app = QApplication.instance() or QApplication([])
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


def test_equipment_page_construye_con_sus_dos_subpestanas():
    """Paso 2: EquipmentPage monta Equipos y Ubicaciones y reemite señales.

    El cableado de la página en la ventana (fila de navegación → página real,
    no placeholder) se comprueba en el paso 3; aquí solo la página en sí.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication, QTabWidget

    from ui.equipment_tab import EquipmentPage

    _app = QApplication.instance() or QApplication([])
    pagina = EquipmentPage()

    tabs = pagina.findChild(QTabWidget)
    assert tabs is not None and tabs.count() == 2
    assert [tabs.tabText(i) for i in range(2)] == ["Equipos", "Ubicaciones"]

    # Las dos señales del contrato existen y reemiten lo de las subpestañas
    recibidas: list[str] = []
    pagina.setups_changed.connect(lambda: recibidas.append("setups"))
    pagina.locations_changed.connect(lambda: recibidas.append("locations"))
    pagina.equipos.setups_changed.emit()
    pagina.ubicaciones.locations_changed.emit()
    assert recibidas == ["setups", "locations"]

    pagina.deleteLater()


def test_ubicaciones_fila_geografia_primero_y_vista_previa_mapa(tmp_path):
    """Paso 2b: fila Geografía|Cielo y vista previa del mapa de CL.

    Regresiones de la revisión: la fila superior va **Geografía primero**
    (no al revés) y la imagen cargada aparece en el cuadro de la derecha
    para modelar con la referencia a la vista — vacío sin mapa y aviso si
    la ruta no se puede cargar.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QImage
    from PyQt6.QtWidgets import QApplication, QLabel, QTabWidget

    from ui.equipment_tab import EquipmentPage

    _app = QApplication.instance() or QApplication([])
    pagina = EquipmentPage()
    tab = pagina.ubicaciones

    # La fila superior: el primer hueco es la caja de Geografía (contiene
    # el Nombre) y el segundo la de Cielo.
    fila = tab._fila_superior.layout()
    primera = fila.itemAt(0).widget()
    assert primera is not None and primera.isAncestorOf(tab._nombre)

    # Vista previa: sin mapa → vacía; con imagen → cargada a tamaño real.
    vista = tab._sitio._vista
    tab._sitio.set_valores({}, {}, None, True)
    assert vista._original.isNull()
    assert tab._sitio._boton_anadir.text() == "Añadir"

    ruta = tmp_path / "mapa.png"
    imagen = QImage(8, 6, QImage.Format.Format_RGB32)
    imagen.fill(0)
    assert imagen.save(str(ruta))
    tab._sitio.set_valores({}, {}, str(ruta), True)
    assert not vista._original.isNull()
    assert vista._original.width() == 8
    assert tab._sitio._boton_anadir.text() == "Cambiar"

    # Ruta inexistente → sin imagen y aviso en el propio rótulo.
    tab._sitio.set_valores({}, {}, str(tmp_path / "no_existe.png"), True)
    assert vista._original.isNull()
    assert "No se pudo" in vista.text()

    # Revisión 2 del layout: títulos, las 2 casillas en la fila superior
    # del esquemático y discos/esquemático con HFW (ancho completo, sin
    # hueco).
    sitio = tab._sitio
    textos = [rotulo.text() for rotulo in sitio.findChildren(QLabel)]
    assert "Mapa de Contaminación Lumínica" in textos
    assert "Referencia: el programa no la analiza." not in textos
    assert sitio._considerar.text() == "Usar CL y Obstáculos al Planificar"
    # Las dos casillas juntas en la fila superior, antes de la gráfica
    # (si el interruptor va debajo, roba alto al disco): misma fila, y
    # «Mostrar obstáculos» es solo pantalla — mueve el flag sin tocar
    # lo guardado.
    assert sitio._considerar.parentWidget() is sitio._salida.parentWidget()
    caja = sitio._salida.parentWidget().layout()
    assert caja.indexOf(sitio._considerar) < caja.indexOf(sitio._salida)
    assert caja.indexOf(sitio._mostrar_obst) == caja.indexOf(sitio._considerar)
    assert sitio._mostrar_obst.isChecked()
    antes = sitio.valores()
    sitio._mostrar_obst.setChecked(False)
    assert not sitio._salida._mostrar_obstaculos
    assert sitio.valores() == antes
    sitio._mostrar_obst.setChecked(True)
    for disco in (sitio._rosa, sitio._obstrucciones, sitio._lumen):
        assert disco.hasHeightForWidth()
        assert disco.heightForWidth(300) == 300
    assert sitio._salida.hasHeightForWidth()
    assert sitio._salida.heightForWidth(500) == 440

    # Los dos discos arrancan a la misma cota: la fila de las casillas
    # mide lo mismo que la de nombre/botones del mapa (comparables).
    # La pestaña debe estar visible: si no, la página no se maqueta y
    # todas las cotas serían 0 (la aserción no probaría nada).
    pagina.findChild(QTabWidget).setCurrentIndex(1)  # pestaña Ubicaciones
    pagina.resize(1400, 900)
    pagina.show()
    _app.processEvents()
    cota_esquematico = sitio._salida.mapTo(sitio, QPoint(0, 0)).y()
    cota_mapa = sitio._vista.mapTo(sitio, QPoint(0, 0)).y()
    assert cota_esquematico == cota_mapa
    # Las casillas tienen altura fija y valen lo que mide la fila del mapa.
    fila_mapa = max(
        sitio._mapa_lbl.sizeHint().height(),
        sitio._boton_anadir.sizeHint().height(),
        sitio._boton_quitar.sizeHint().height(),
        sitio._considerar.sizeHint().height(),
        sitio._mostrar_obst.sizeHint().height(),
    )
    assert sitio._considerar.minimumHeight() == fila_mapa
    assert sitio._considerar.maximumHeight() == fila_mapa
    assert sitio._mostrar_obst.minimumHeight() == fila_mapa
    assert sitio._mostrar_obst.maximumHeight() == fila_mapa

    pagina.deleteLater()
    _app.processEvents()


def test_ubicaciones_seccion_lista_arriba_sin_splitter(memory_db):
    """La lista «Ubicaciones guardados» es una sección de la fila superior, sin splitter.

    Regresión de la reestructuración (simétrica a la de Equipos): la
    barra lateral (QSplitter) desaparece; la sección de la lista va a
    280 px en la fila superior **a la misma altura** que la ficha de la
    derecha (barra «Ubicación» + fila Geografía|Cielo), que ahora queda
    **fuera del scroll**; debajo, el `SitioPanel` corre a todo el ancho.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import (
        QApplication,
        QFrame,
        QLabel,
        QListWidget,
        QPushButton,
        QScrollArea,
        QSplitter,
    )

    from ui.equipment_tab.ubicaciones import UbicacionesTab

    _app = QApplication.instance() or QApplication([])
    tab = UbicacionesTab()
    tab.resize(1000, 600)
    tab.show()
    _app.processEvents()

    assert tab.findChildren(QSplitter) == [], "no debe quedar ningún QSplitter"

    # La sección: marco de ancho fijo con su título PanelTitle.
    secciones = [
        frame
        for frame in tab.findChildren(QFrame)
        if frame.objectName() == "GroupFrame" and frame.minimumWidth() == 280
    ]
    assert len(secciones) == 1, "debe haber exactamente una sección de lista a 280 px"
    seccion = secciones[0]
    titulos = [
        etiqueta
        for etiqueta in seccion.findChildren(QLabel)
        if etiqueta.objectName() == "PanelTitle" and etiqueta.text() == "Ubicaciones guardados"
    ]
    assert len(titulos) == 1, "la sección debe titularse «Ubicaciones guardados»"

    # La lista limita su alto: si creciera (sizeHint de 192 px) la fila
    # superior se hincharía y empujaría el scroll de abajo.
    listas = seccion.findChildren(QListWidget)
    assert len(listas) == 1 and 40 <= listas[0].maximumHeight() <= 100

    # Los botones van en fila (misma altura) y «🗑» lleva «Eliminar» en tooltip.
    bots = seccion.findChildren(QPushButton)
    assert {boton.text() for boton in bots} == {"➕ Nueva…", "🗑"}
    assert abs(bots[0].y() - bots[1].y()) <= 2, "los botones deben compartir fila"
    assert "Eliminar" in (bots[1].toolTip() or "")

    # Fila superior: la sección ocupa la misma banda que la columna
    # derecha (barra «Ubicación» + Geografía|Cielo): mismo pie abajo y
    # misma cota arriba que la barra. Y el sizeHint de la sección no
    # manda: si lo superara, la fila se hincharía y empujaría el scroll.
    assert abs(
        (seccion.y() + seccion.height())
        - (tab._fila_superior.y() + tab._fila_superior.height())
    ) <= 2, "la sección y la ficha de la derecha deben acabar a la par"
    assert seccion.sizeHint().height() <= seccion.height(), (
        "el sizeHint de la sección no debe ser el que dispare la fila superior"
    )

    # Geografía|Cielo queda FUERA del scroll; dentro solo va el sitio.
    areas = tab.findChildren(QScrollArea)
    assert len(areas) == 1
    area = areas[0]
    assert not area.isAncestorOf(tab._fila_superior), (
        "Geografía|Cielo no debe vivir dentro del scroll"
    )
    assert area.isAncestorOf(tab._sitio), "el SitioPanel sí va en el scroll"
    assert area.y() >= seccion.y() + seccion.height(), "el scroll debe ir bajo la fila superior"
    assert area.width() >= tab.width() - 30, (
        f"scroll a {area.width()} px de {tab.width()} (debe ir a todo el ancho)"
    )

    tab.deleteLater()
    _app.processEvents()


def test_ubicacion_altitud_desfase_y_sqm(memory_db):
    """Revisión 2: la altitud sobrevive al guardar, desfase, SQM «—» y seeing.

    Regresiones de los tres defectos reportados: ``list_locations`` trae la
    columna ``altitude`` (la ficha leía ``altitude_m`` y se quedaba en 0 al
    recargar); con «Huso automático» el Desfase muestra ``round(lon/15)``
    —la misma regla que el planificador— y queda fijo, y sin el check se
    edita; y el SQM vuelve a vacío («-» al salir del campo → «—», en vez
    de revertir al valor anterior). El Seeing típico del bloque Cielo
    guarda y recarga, y la pista antigua de Bortle/SQM ya no existe: su
    texto vive en los tooltips de los dos campos.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtCore import QEvent
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QLabel

    from ui.equipment_tab.ubicaciones import UbicacionesTab

    _app = QApplication.instance() or QApplication([])
    tab = UbicacionesTab()
    tab._nombre.setText("Cacao")
    tab._latitud.setValue(10.019)
    tab._longitud.setValue(-84.282)
    tab._altitud.setValue(822.0)
    tab._bortle.setCurrentIndex(5)
    tab._seeing.setValue(2.5)

    # Huso automático: el Desfase indica round(-84,282 / 15) = -6 y fijo.
    assert tab._huso.value() == -6.0
    assert not tab._huso.isEnabled()

    tab._guardar()
    # Regresión: la altitud no se borra al guardar (clave «altitude»).
    assert tab._altitud.value() == 822.0
    # El seeing típico sobrevive a guardar (create + recarga desde la BD).
    assert tab._seeing.value() == 2.5
    # La pista de Bortle/SQM desapareció: el seeing ocupa su fila.
    assert [
        etiqueta.text()
        for etiqueta in tab.findChildren(QLabel)
        if "Bortle obligatorio" in etiqueta.text()
    ] == []
    # La longitud sigue mandando y el desfase sigue automático al recargar.
    assert tab._huso.value() == -6.0
    assert not tab._huso.isEnabled()

    # Sin el check, el desfase se indica a mano y se persiste.
    tab._auto.setChecked(False)
    assert tab._huso.isEnabled()
    tab._huso.setValue(-5.0)
    tab._guardar()
    assert tab._auto.isChecked() is False
    assert tab._huso.value() == -5.0

    # SQM: con valor, «-» al salir del campo → «—» (0), no el valor viejo.
    tab._sqm.setValue(19.98)
    tab._sqm.setFocus()
    tab._sqm.lineEdit().selectAll()
    QTest.keyClicks(tab._sqm, "-")
    QApplication.sendEvent(tab._sqm, QEvent(QEvent.Type.FocusOut))
    assert tab._sqm.value() == 0.0
    assert tab._sqm.text() == "—"
    assert tab._sqm_actual() is None

    tab.deleteLater()


def test_rosaceas_construyen_pintan_y_hacen_roundtrip():
    """Paso 2: los discos de la rosácea construyen, pintan y roundtrip.

    Cubre `rosaceas.py` sin motor de nada más: la rosa y los dos discos
    de entrada pintan su círculo (``grab()`` dispara ``paintEvent``) y el
    estado de obstrucciones/CL sobrevive a set→get con las 8 direcciones;
    el esquemático acepta datos y repinta.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from equipment.models import DIRECTIONS
    from ui.equipment_tab.rosaceas import (
        DiscoEsquematico,
        DiscoLumen,
        DiscoObstrucciones,
        RosaDirecciones,
    )

    _app = QApplication.instance() or QApplication([])
    rosa = RosaDirecciones()
    obstaculos = DiscoObstrucciones()
    lumen = DiscoLumen()
    salida = DiscoEsquematico()

    # Construyen y pintan sin lanzar (grab fuerza el repintado).
    salida.resize(420, 340)
    for widget in (rosa, obstaculos, lumen, salida):
        if widget is not salida:
            widget.resize(200, 200)
        foto = widget.grab()
        assert not foto.isNull(), f"{type(widget).__name__} no pinta"

    # Roundtrip de los discos de entrada con valores guardados.
    grados = {d: 0 for d in DIRECTIONS}
    grados["N"] = 45
    grados["NO"] = 15
    obstaculos.set_obstacles(grados)
    assert obstaculos.obstacles() == grados

    fuentes = {d: {"fuente": None, "km": 0.0} for d in DIRECTIONS}
    fuentes["SE"] = {"fuente": "ciudad", "km": 12.5}
    fuentes["E"] = {"fuente": "gran_ciudad", "km": 40.0}
    lumen.set_lp(fuentes)
    assert lumen.lp() == fuentes

    # Salida: con datos pinta el campo y las obstrucciones sin error.
    salida.set_datos(4, 21.4, grados, fuentes)
    assert not salida.grab().isNull()

    # Regresión: el campo de color debe llegar al centro del disco. Con el
    # brush negro heredado del disco, cada anillo de la rejilla se rellenaba
    # como un círculo negro y tapaba el campo entero (centro siempre negro).
    pixmap = salida.grab()
    imagen = pixmap.toImage()
    dpr = pixmap.devicePixelRatio()
    cx = 420 / 2 - 92 / 2  # centro del disco: hay barra (base informada)
    centro = imagen.pixelColor(round(cx * dpr), round(340 / 2 * dpr))
    assert (centro.red(), centro.green(), centro.blue()) != (0, 0, 0)

    # «Mostrar obstáculos» es solo pintado: apagado, la cuña de N (45°)
    # desaparece del borde superior (r = 142, mismos cálculos que
    # paintEvent: hay barra y cx = 164) pero el dato no se toca.
    x_cuña, y_cuña = round(cx * dpr), round((340 / 2 - 142 + 12) * dpr)
    con = imagen.pixelColor(x_cuña, y_cuña)
    salida.set_mostrar_obstaculos(False)
    sin = salida.grab().toImage().pixelColor(x_cuña, y_cuña)
    assert (con.red(), con.green(), con.blue()) != (
        sin.red(),
        sin.green(),
        sin.blue(),
    )
    assert salida._obstacles["N"] == 45
    salida.set_mostrar_obstaculos(True)
    vuelta = salida.grab().toImage().pixelColor(x_cuña, y_cuña)
    assert (vuelta.red(), vuelta.green(), vuelta.blue()) == (
        con.red(),
        con.green(),
        con.blue(),
    )

    # y sin datos vuelve al disco negro de fábrica (sin campo cacheado).
    salida.set_datos(None, None, {}, {})
    assert not salida.grab().isNull()

    for widget in (rosa, obstaculos, lumen, salida):
        widget.deleteLater()


def test_cabecera_suma_precio_peso_y_lo_persiste(memory_db):
    """Cabecera: precio/peso son la suma en vivo (solo lectura) y se guarda.

    Regresiones del rediseño: los dos campos de la cabecera ya no se
    teclean (son calculados); los 5 formularios y cada filtro marcado
    suman precio, cada telescopio con la casilla «Aplanador» añade
    0,5 kg de peso y sin datos se pinta «—» (0). Al «Guardar equipo» la
    suma queda en ``price_eur``/``weight_kg`` del setup (D-3) — sustituye
    al valor manual— y sobrevive a la recarga.
    """
    import os

    import pytest

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication, QCheckBox

    from equipment import components, manager
    from equipment.models import Filter
    from ui.equipment_tab.componentes import _FiltroDialog
    from ui.equipment_tab.equipos import EquiposTab

    _app = QApplication.instance() or QApplication([])
    tab = EquiposTab()

    # Sin datos: «—» (0) en los dos campos y no admiten teclear.
    assert tab._precio.value() == 0.0 and tab._peso.value() == 0.0
    assert tab._precio.isReadOnly() and tab._peso.isReadOnly()

    # Lo tecleado en los formularios suma al momento (changed en vivo).
    tel = tab._tel_principal.form
    tel._nombre.setText("ED80")
    tel._precio.setValue(650)
    tel._peso.setValue(2.7)
    tel._reductor.setChecked(True)  # +0,5 kg por el aplanador
    cam = tab._cam_principal.form
    cam._nombre.setText("ASI2600")
    cam._precio.setValue(1550)
    cam._peso.setValue(0.7)
    montura = tab._montura.form
    montura._nombre.setText("AM5")
    montura._precio.setValue(2100)
    montura._peso.setValue(5.5)
    assert tab._precio.value() == pytest.approx(4300.0)
    assert tab._peso.value() == pytest.approx(9.4)

    # «Guardar componente» persiste precio/peso de cada pieza.
    for editor in (tab._tel_principal, tab._cam_principal, tab._montura):
        editor._guardar()
    guardado = components.get_telescope(tab._tel_principal.selected_id())
    assert guardado["price_eur"] == pytest.approx(650)
    assert guardado["weight_kg"] == pytest.approx(2.7)

    # Un filtro marcado suma precio (sin peso) al alternar su casilla.
    components.create_filter(Filter(name="UHC", filter_type="uhc", price_eur=45))
    tab._filtros.reload()
    assert tab._filtros._tabla.horizontalHeaderItem(2).text() == "Precio"
    casilla = tab._filtros._tabla.cellWidget(0, 3).findChild(QCheckBox)
    casilla.click()
    assert tab._precio.value() == pytest.approx(4345.0)
    assert tab._peso.value() == pytest.approx(9.4)

    # El diálogo del filtro recoge y devuelve su precio.
    dialogo = _FiltroDialog(tab._filtros, {"name": "UHC", "price_eur": 45})
    assert dialogo.filtro().price_eur == pytest.approx(45)
    dialogo.deleteLater()

    # «Guardar equipo» persiste la suma (D-3) y al recargar sigue en pie.
    tab._nombre.setText("Prueba suma")
    tab._guardar()
    fila = manager.get(tab._setup_id)
    assert fila["price_eur"] == pytest.approx(4345.0)
    assert fila["weight_kg"] == pytest.approx(9.4)
    assert fila["telescope_id"] == tab._tel_principal.selected_id()
    assert tab._precio.value() == pytest.approx(4345.0)
    assert tab._peso.value() == pytest.approx(9.4)

    tab.deleteLater()


def test_subtipo_es_solo_seleccionable_conserva_al_cargar_y_cambia_con_el_tipo(
    memory_db,
):
    """Subtipo: combo solo seleccionable con la taxonomía de su tipo.

    Regresiones: el combo ya no admite texto libre; al elegir Tipo aparecen
    solo las opciones de esa óptica (Refractor = las 5 de la taxonomía);
    un subtipo guardado que no está en la lista (otra BD o el texto libre
    antiguo) se conserva al cargar, y al cambiar de Tipo el combo
    selecciona el primer subtipo del nuevo tipo (no arrastra el anterior).
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from ui.equipment_tab.componentes import TelescopeForm

    _app = QApplication.instance() or QApplication([])
    form = TelescopeForm()

    # Solo selección: sin edición libre.
    assert not form._subtipo.isEditable()
    form._tipo.setCurrentIndex(form._tipo.findData("refractor"))
    assert [form._subtipo.itemText(i) for i in range(form._subtipo.count())] == [
        "Acromático",
        "Doblete (ED)",
        "Triplete Apocromático",
        "Quad (FF)",
        "Petzval",
    ]

    # Un subtipo guardado ajeno a la lista no se pierde al cargar...
    form.cargar(
        {"id": 1, "name": "Raro", "optical_type": "refractor", "subtype": "Sextuplete"}
    )
    assert form._subtipo.currentText() == "Sextuplete"
    assert form.a_modelo().subtype == "Sextuplete"

    # ...pero al cambiar de tipo se selecciona el primero del nuevo tipo
    # (regresión: «Sextuplete» se quedaba pegado y hasta se añadía a la
    # lista de Reflector).
    form._tipo.setCurrentIndex(form._tipo.findData("reflector"))
    assert [form._subtipo.itemText(i) for i in range(form._subtipo.count())] == [
        "Newtoniano",
        "Ritchey-Chrétien (RC)",
    ]
    assert form._subtipo.currentText() == "Newtoniano"

    form.deleteLater()


def test_telescopio_filas_de_tres_campos():
    """Telescopio: dos filas de tres campos, casilla corta y spins estrechos.

    Regresiones del reagrupado —antes eran 3 filas: `Precio|Peso`,
    `Apertura|Focal` y `casilla|Factor`—: la fila 1 es
    `Precio·Peso·Apertura` y la 2 `Focal·Aplanador·Factor` (la fila que
    se gana se cede al bloque «Cálculos»); la casilla, cuyo texto mandaba
    el ancho mínimo de la columna, pasa de «Con aplanador/reductor» a
    «Aplanador» con el detalle en el tooltip; y cada spin lleva ancho
    máximo (80/85/95/104/60 px, medidos con la fuente real) porque con
    el `sizeHint` la fila 1 pedía ~560 px y forzaba scroll horizontal en
    la columna Principal/Guía.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from ui.equipment_tab.componentes import TelescopeForm

    _app = QApplication.instance() or QApplication([])
    form = TelescopeForm()

    def fila_de(widget) -> int:
        """Índice de la fila del layout vertical que contiene `widget`."""
        vertical = form.layout()
        for i in range(vertical.count()):
            fila = vertical.itemAt(i).layout()
            if fila is None:
                continue
            for j in range(fila.count()):
                if fila.itemAt(j).widget() is widget:
                    return i
        return -1

    def widgets_de(indice: int):
        fila = form.layout().itemAt(indice).layout()
        return [fila.itemAt(j).widget() for j in range(fila.count()) if fila.itemAt(j).widget()]

    fila_precio = fila_de(form._precio)
    fila_focal = fila_de(form._focal)

    # Una fila para Precio·Peso·Apertura, otra para Focal·Aplanador·Factor.
    assert (fila_de(form._peso), fila_de(form._apertura)) == (fila_precio, fila_precio)
    assert (fila_de(form._reductor), fila_de(form._factor)) == (fila_focal, fila_focal)
    assert fila_precio != fila_focal, "los 6 campos deben ir en dos filas, no en una"

    # Y en ese orden (rótulo delante de su campo).
    primera = widgets_de(fila_precio)
    assert [primera.index(w) for w in (form._precio, form._peso, form._apertura)] == [1, 3, 5]
    assert [etiqueta.text() for etiqueta in (primera[0], primera[2], primera[4])] == [
        "Precio",
        "Peso",
        "Apertura",
    ]
    segunda = widgets_de(fila_focal)
    assert [segunda.index(w) for w in (form._focal, form._reductor, form._factor)] == [1, 2, 4]
    assert segunda[0].text() == "Focal" and segunda[3].text() == "Factor ×"

    # Casilla corta (su texto es lo que más pesa en el ancho mínimo).
    assert form._reductor.text() == "Aplanador"
    assert "aplanador, reductor o coma corrector" in form._reductor.toolTip()

    # Ancho máximo de cada spin = su texto más largo.
    assert {
        "precio": form._precio.maximumWidth(),
        "peso": form._peso.maximumWidth(),
        "apertura": form._apertura.maximumWidth(),
        "focal": form._focal.maximumWidth(),
        "factor": form._factor.maximumWidth(),
    } == {"precio": 80, "peso": 85, "apertura": 95, "focal": 104, "factor": 60}

    form.deleteLater()


def test_calculos_con_seeing_rango_y_barra(memory_db):
    """Cálculos: el seeing recorta el rango, colorea el veredicto y pinta la barra.

    Regresiones: la pista añade «Rango adecuado: X–Y ″/px», la etiqueta
    de Muestreo se tiñe según el veredicto (arcoíris de 5 niveles:
    violeta/azul/verde/amarillo/naranja), la barra pinta, elegir una
    ubicación con seeing cambia rango y veredicto (sin ubicación o sin
    dato manda solo Dawes con los umbrales de Configuración) y los dos
    niveles «Ligero» aparecen en amarillo y azul.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from equipment import localizations
    from equipment.models import DIRECTIONS, Location
    from ui.equipment_tab.equipos import EquiposTab

    _app = QApplication.instance() or QApplication([])
    tab = EquiposTab()

    tel = tab._tel_principal.form
    tel._apertura.setValue(80.0)
    tel._focal.setValue(400.0)
    cam = tab._cam_principal.form
    cam._pixel.setValue(2.4)  # ≈ 1,24 ″/px

    # Sin ubicación: solo Dawes (0,725–1,45) → correcto en verde.
    assert "Rango adecuado:" in tab._pista_calculos.text()
    assert tab._muestreo.text() == "Muestreo Correcto"
    assert "#2ECC71" in tab._muestreo.styleSheet()
    assert not tab._barra.grab().isNull()

    # Niveles «Ligero» sin seeing: banda de Dawes con el margen ×1,4.
    cam._pixel.setValue(3.9)  # ≈ 2,01 ″/px: sobre el rango, dentro del margen
    assert tab._muestreo.text() == "Submuestreado Ligero"
    assert "#F4D03F" in tab._muestreo.styleSheet()
    cam._pixel.setValue(1.2)  # ≈ 0,62 ″/px: bajo el rango, sobre el margen
    assert tab._muestreo.text() == "Sobremuestreado Ligero"
    assert "#5DADE2" in tab._muestreo.styleSheet()
    cam._pixel.setValue(2.4)

    # Ubicación con seeing de 1 ″ → banda (0,25–0,5): la misma escala es
    # submuestreada (naranja) y la pista enseña el rango recortado.
    pk = localizations.create(
        Location(
            name="Cielo fino",
            latitude=40.0,
            longitude=-3.0,
            bortle=4,
            seeing_arcsec=1.0,
            obstacles={d: 0 for d in DIRECTIONS},
            lp={d: {"fuente": None, "km": 0.0} for d in DIRECTIONS},
        )
    )
    tab.reload_locations()
    tab._ubicacion.setCurrentIndex(tab._ubicacion.findData(pk))

    assert "Rango adecuado: 0.25–0.50 ″/px." in tab._pista_calculos.text()
    assert tab._muestreo.text() == "Submuestreado"
    assert "#F39C12" in tab._muestreo.styleSheet()

    tab.deleteLater()


def test_barra_arcoiris_fija_y_marcador_sigue_el_veredicto(memory_db):
    """La barra es una escala fija de 5 quintos y el marcador se mueve solo.

    Regresiones: el verde se queda siempre centrado (0,4–0,6) y los
    colores NO se reposicionan con el rango (mismo color en la misma X
    aunque cambie la apertura); el marcador cae dentro del quinto de su
    veredicto y al crecer la escala solo se mueve a la derecha. Sin
    apertura → barra gris (nada inventado).
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from equipment.metrics import veredicto_muestreo
    from ui.equipment_tab.equipos import (
        _ARCOIRIS,
        _VEREDICTO_COLOR,
        BarraMuestreo,
        _posicion_marcador,
    )

    _app = QApplication.instance() or QApplication([])
    barra = BarraMuestreo()
    barra.resize(160, 16)
    limites = (0.5 / 1.4, 0.5, 1.0, 1.4)  # resolución 1,0 y factor 1,4

    # Al crecer la escala el marcador solo se mueve a la derecha.
    escalas = [0.1, 0.3, 0.35, 0.45, 0.5, 0.99, 1.05, 1.2, 1.41, 1.6, 3.0]
    posiciones = [_posicion_marcador(e, limites) for e in escalas]
    assert all(p is not None for p in posiciones)
    assert posiciones == sorted(posiciones)

    # El marcador cae SIEMPRE en el quinto de su veredicto (mismo mapeo
    # que la barra: índice 0 = violeta … 4 = naranja).
    quintos = {clave: i for i, clave in enumerate(_ARCOIRIS)}
    for escala, posicion in zip(escalas, posiciones):
        veredicto = veredicto_muestreo(escala, 1.0)
        assert veredicto is not None
        assert min(4, int(posicion * 5)) == quintos[veredicto], (
            escala,
            veredicto,
            posicion,
        )

    # Zonas fijas: mismo color en la misma X con rangos distintos
    # (muestreo en el centro de cada quinto; el marcador lejos de ahí).
    muestras = {
        0.1: "Sobremuestreado",
        0.3: "Sobremuestreado Ligero",
        0.5: "Muestreo Correcto",
        0.7: "Submuestreado Ligero",
        0.9: "Submuestreado",
    }

    def pintura() -> dict[float, str]:
        imagen = barra.grab().toImage()
        return {
            frac: imagen.pixelColor(int(imagen.width() * frac), imagen.height() // 2)
            .name()
            .upper()
            for frac in muestras
        }

    barra.pintar(1.1, limites)
    una = pintura()
    barra.pintar(1.1, (0.1 / 1.4, 0.1, 0.2, 0.28))  # rango otra vez
    otra = pintura()
    for frac, clave in muestras.items():
        esperado = _VEREDICTO_COLOR[clave]
        assert una[frac] == esperado, (frac, una[frac])
        assert otra[frac] == esperado, (frac, otra[frac])

    # Sin dato no se inventa nada: sin apertura, barra gris y sin marcador.
    assert _posicion_marcador(1.1, None) is None
    assert _posicion_marcador(None, limites) is None
    assert _posicion_marcador(0.0, limites) is None
    barra.pintar(1.1, None)
    assert barra.grab().toImage().pixelColor(80, 8).name().upper() == "#4A5058"

    barra.deleteLater()


def test_ficha_sin_hint_de_solo_visuales_y_cabe_sin_scroll(memory_db):
    """Sin el hint «Solo visuales» la ficha entera cabe sin scroll.

    «Solo visuales: el programa no analiza los charts / las curvas de
    ganancia» ocupaba una fila con word wrap en cada formulario y
    empujaba la ficha a scrollear: quitado el hint (y apretados los
    márgenes de «Cálculos»), con la ventana a 1000×600 el panel con
    scroll vertical tiene ``maximum == 0``. La aclaración vive en
    `PROGRAM.md` y en la docstring de `equipment.models`, no en la UI.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea

    from ui.equipment_tab.componentes import CameraForm, TelescopeForm
    from ui.equipment_tab.equipos import EquiposTab

    _app = QApplication.instance() or QApplication([])
    for form in (TelescopeForm(), CameraForm()):
        pistas = [
            etiqueta
            for etiqueta in form.findChildren(QLabel)
            if "Solo visuales" in etiqueta.text()
        ]
        assert pistas == [], [p.text() for p in pistas]
        form.deleteLater()

    tab = EquiposTab()
    tab.resize(1000, 600)
    tab.show()
    _app.processEvents()
    areas = tab.findChildren(QScrollArea)
    maximos = [area.verticalScrollBar().maximum() for area in areas]
    assert maximos and all(maximo == 0 for maximo in maximos), (
        f"scroll vertical {maximos} (0 = la ficha cabe sin scroll)"
    )
    tab.deleteLater()
    _app.processEvents()


def test_equipos_seccion_lista_arriba_sin_splitter(memory_db):
    """La lista de guardados es una sección de la fila superior, sin splitter.

    Regresión de la reestructuración: la barra lateral (QSplitter)
    ocupaba toda la pestaña y estrechaba la ficha. Ahora la pestaña
    tiene dos filas — `[sección lista (hasta 450 px, **sin rótulo**)
    | cabecera Equipo]` y, debajo, el panel con scroll **a todo el
    ancho**—, con la sección y la cabecera a la misma altura y sus
    botones en fila bajo la lista.

    El rótulo «Equipos guardados» se quitó a propósito: a `PanelTitle`
    (13 pt) ocupaba dos líneas —44 px— de los 153 de la sección y ese
    alto es de las filas que faltaban para ver 3 equipos seguidos.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import (
        QApplication,
        QFrame,
        QLabel,
        QListWidget,
        QPushButton,
        QScrollArea,
        QSplitter,
    )

    from ui.equipment_tab.equipos import EquiposTab, _ancho_seccion

    _app = QApplication.instance() or QApplication([])
    tab = EquiposTab()
    tab.resize(1000, 600)
    tab.show()
    _app.processEvents()

    assert tab.findChildren(QSplitter) == [], "no debe quedar ningún QSplitter"

    # La sección es el primer elemento de la fila superior (por
    # estructura, no por objectName: «GroupFrame» es selector de estilo).
    fila_sup = tab.layout().itemAt(0).layout()
    seccion = fila_sup.itemAt(0).widget()
    assert seccion is not None and seccion.objectName() == "GroupFrame"
    assert seccion.minimumWidth() == _ancho_seccion(tab.width()), (
        "el ancho de la sección lo calcula _ancho_seccion según la pestaña"
    )
    assert seccion.minimumWidth() == 450, "en pestaña ancha la sección va a su ancho completo"
    titulos = [
        etiqueta
        for etiqueta in seccion.findChildren(QLabel)
        if etiqueta.objectName() == "PanelTitle"
    ]
    assert titulos == [], "el rótulo vertical se quitó: el alto es de la lista"

    # La lista no infla la fila superior: su sizeHint preferido es
    # pequeño (el natural de QListWidget es de 192 px) pero **sí llena**
    # la sección, que es lo que hace visibles a 3+ equipos.
    listas = seccion.findChildren(QListWidget)
    assert len(listas) == 1
    lista = listas[0]
    assert lista.sizeHint().height() <= 60, "el sizeHint de la lista no debe mandar"
    assert lista.maximumHeight() > 1000, "la lista no debe tener tope de alto"
    assert lista.height() >= seccion.height() // 2, (
        f"la lista ({lista.height()} px) debe llenar la sección ({seccion.height()} px)"
    )

    # Fila superior: sección y cabecera comparten altura (la cabecera
    # es la que manda; la sección no la supera ni en sizeHint).
    guardar = [
        boton
        for boton in tab.findChildren(QPushButton)
        if boton.text() == "Guardar equipo"
    ]
    assert len(guardar) == 1
    cabecera = guardar[0].parent()
    while cabecera is not None and not (
        isinstance(cabecera, QFrame) and cabecera.objectName() == "GroupFrame"
    ):
        cabecera = cabecera.parent()
    assert cabecera is not None, "sin cabecera GroupFrame con «Guardar equipo»"
    assert abs(seccion.y() - cabecera.y()) <= 2, "sección y cabecera deben ir a la par"
    assert abs(seccion.height() - cabecera.height()) <= 2, "misma altura en la fila superior"
    assert seccion.sizeHint().height() <= cabecera.sizeHint().height(), (
        "el sizeHint de la sección no debe superar al de la cabecera"
    )
    assert seccion.x() + seccion.width() <= cabecera.x(), (
        "la sección no debe meterse debajo de la cabecera"
    )

    # Los botones de la sección van en fila (misma altura).
    textos = {boton.text() for boton in seccion.findChildren(QPushButton)}
    assert textos == {"➕ Nuevo…", "🗑"}, f"botones de la sección: {sorted(textos)}"
    nuevos = seccion.findChildren(QPushButton)
    assert abs(nuevos[0].y() - nuevos[1].y()) <= 2, "los botones deben compartir fila"

    # El scroll va debajo y a todo el ancho de la pestaña.
    areas = tab.findChildren(QScrollArea)
    assert len(areas) == 1
    area = areas[0]
    assert area.y() >= seccion.y() + seccion.height(), "el scroll debe ir bajo la fila superior"
    assert area.width() >= tab.width() - 30, (
        f"scroll a {area.width()} px de {tab.width()} (debe ir a todo el ancho)"
    )

    tab.deleteLater()
    _app.processEvents()


def test_equipos_lista_nombre_categoria_y_ubicacion(memory_db):
    """Las filas de la lista dicen «nombre · categoría · ubicación».

    Regresión de dos quejas seguidas del usuario: (a) «con 3 equipos
    solo se veían 2» —sin rótulo ni tope la lista llena la sección y
    caben 3+ filas seguidas— y (b) «que también diga la ubicación»
    —``location_name`` del LEFT JOIN de ``list_setups`` (M-17)—. Sin
    ubicación se omite el tercer trozo, como antes.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication, QListWidget

    from ui.equipment_tab.equipos import EquiposTab

    cur = memory_db.execute(
        "INSERT INTO locations (name, latitude, longitude) VALUES (?, ?, ?)",
        ("Cacao", 28.3, -16.5),
    )
    memory_db.execute(
        "INSERT INTO equipment_setups (name, category, location_id) VALUES (?, ?, ?)",
        ("Orión", "espacio_profundo", cur.lastrowid),
    )
    memory_db.execute(
        "INSERT INTO equipment_setups (name, category) VALUES (?, ?)",
        ("Sin sitio", "paisaje"),
    )
    memory_db.commit()

    _app = QApplication.instance() or QApplication([])
    tab = EquiposTab()
    tab.resize(1000, 600)
    tab.show()
    _app.processEvents()

    seccion = tab.layout().itemAt(0).layout().itemAt(0).widget()
    lista = seccion.findChildren(QListWidget)[0]
    textos = [lista.item(i).text() for i in range(lista.count())]
    assert textos == [
        "Orión · Espacio Profundo · Cacao",
        "Sin sitio · Paisaje",
    ], f"textos de la lista: {textos}"
    assert lista.item(0).toolTip() == textos[0], "el texto completo va en el tooltip"

    # Tres equipos seguidos sin scroll interno: viewport ÷ alto de fila.
    fila = lista.visualItemRect(lista.item(0)).height()
    visibles = lista.viewport().height() // fila
    assert visibles >= 3, f"solo caben {visibles} filas ({fila} px) en {lista.viewport().height()}"


def test_equipos_seccion_no_solapa_la_cabecera_en_ventana_estrecha(memory_db):
    """La sección encoge en ventana estrecha y nunca queda bajo la cabecera.

    Regresión: con 450 px fijos, la fila superior —que reparte **a
    medias** cuando los mínimos de sus dos hijos no caben, y la
    cabecera sola pide ~1085— metía la sección 61 px debajo de la
    cabecera en la ventana mínima (1024 px → 780 de pestaña).
    `_ancho_seccion` la limita a la mitad de su hueco, así que baja de
    450 solo cuando hace falta.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from ui.equipment_tab.equipos import _ancho_seccion
    from ui.main_window import TABS, MainWindow

    _app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1024, 640)
    window.show()
    indice = [key for key, _title in TABS].index("equipment_tab")
    window.sidebar.nav.setCurrentRow(indice)
    _app.processEvents()

    tab = window.content.widget(indice).equipos
    _app.processEvents()

    fila_sup = tab.layout().itemAt(0).layout()
    seccion = fila_sup.itemAt(0).widget()
    cabecera = fila_sup.itemAt(1).widget()

    assert tab.width() < 922, (
        f"la prueba necesita la pestaña estrecha (mide {tab.width()} px)"
    )
    solape = seccion.x() + seccion.width() - cabecera.x()
    assert solape <= 0, f"la sección se mete {solape} px debajo de la cabecera"
    assert seccion.minimumWidth() == _ancho_seccion(tab.width()) < 450, (
        "en ventana estrecha la sección debe bajar de 450"
    )

    window.close()


def test_equipo_sin_asteriscos_en_los_rotulos(memory_db):
    """Ningún rótulo de la pestaña Equipo termina en «*».

    Regresión: «Nombre *», «Latitud *», «Bortle *»… no comunicaban nada
    —la validación real se ve en el «Falta: …» inline y en los tooltips—
    y solo estorbaban; el usuario pidió quitarlos. Cubre las cuatro
    piezas de componentes, la cabecera de Equipos y Geografía|Cielo.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication, QLabel

    from ui.equipment_tab import EquipmentPage

    _app = QApplication.instance() or QApplication([])
    pagina = EquipmentPage()
    asteriscos = sorted(
        etiqueta.text() for etiqueta in pagina.findChildren(QLabel)
        if etiqueta.text().endswith("*")
    )
    assert asteriscos == [], f"rótulos con asterisco: {asteriscos}"

    pagina.deleteLater()
    _app.processEvents()


def test_afines_nuevo_sin_dialogo_lista_vacia_y_falta_nombre(memory_db, monkeypatch):
    """Afines A de Equipos: «Nuevo…» sin diálogo, ayuda en lista vacía y «Falta: nombre».

    Regresiones: «Nuevo…» no debe abrir ningún QInputDialog (deja la
    ficha en blanco), una lista sin equipos pinta una fila de ayuda no
    seleccionable, y «Guardar equipo» sin nombre enseña el hint inline
    «Falta: nombre» sin aviso modal —que se quita al teclear— sin
    persistir nada.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    import pytest
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox

    from ui.equipment_tab.equipos import EquiposTab

    _app = QApplication.instance() or QApplication([])
    tab = EquiposTab()

    # Lista vacía → una fila de ayuda, no seleccionable.
    assert tab._lista.count() == 1
    ayuda = tab._lista.item(0)
    assert "sin equipos" in ayuda.text()
    assert not bool(ayuda.flags() & Qt.ItemFlag.ItemIsSelectable)

    # «Nuevo…»: si abriera el diálogo de nombre, el test revienta.
    def _sin_dialogo(*_args, **_kwargs):
        pytest.fail("«Nuevo…» no debe abrir QInputDialog")

    monkeypatch.setattr(QInputDialog, "getText", _sin_dialogo)
    tab._nuevo()
    assert tab._setup_id is None
    assert tab._nombre.text() == ""

    # Guardar sin nombre → hint inline, sin aviso modal y sin persistir.
    def _sin_modal(*_args, **_kwargs):
        pytest.fail("«Falta: nombre» no debe abrir aviso modal")

    monkeypatch.setattr(QMessageBox, "warning", _sin_modal)
    tab._guardar()
    assert tab._setup_id is None
    assert not tab._falta_nombre.isHidden()

    # Al teclear desaparece el hint y el equipo se guarda (fila real).
    tab._nombre.setText("Equipo nuevo")
    assert tab._falta_nombre.isHidden()
    tab._guardar()
    assert tab._setup_id is not None
    assert tab._lista.count() == 1
    assert "Equipo nuevo" in tab._lista.item(0).text()

    tab.deleteLater()


def test_equipo_cableado_en_la_ventana(monkeypatch):
    """Paso 3: Equipo ya no es placeholder y sus señales llegan al Planificador.

    El cableado vive en ``MainWindow`` (ninguna pestaña importa a otra):
    ``setups_changed`` → recarga de setups de Planificación y de Sesiones;
    ``locations_changed`` → recarga y reenvío de la barra de ubicación.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from ui.equipment_tab import EquipmentPage
    from ui.main_window import TABS, MainWindow, PlannerPage
    from ui.planner_tab import PlanificacionTab, SesionesTab
    from ui.planner_tab.widgets import LocationBar

    llamadas: list[str] = []
    monkeypatch.setattr(
        PlanificacionTab,
        "reload_setups",
        lambda self: llamadas.append("reload_setups"),
    )
    monkeypatch.setattr(SesionesTab, "refresh", lambda self: llamadas.append("refresh"))
    monkeypatch.setattr(LocationBar, "reload", lambda self: llamadas.append("reload"))
    monkeypatch.setattr(LocationBar, "reemit", lambda self: llamadas.append("reemit"))

    _app = QApplication.instance() or QApplication([])
    window = MainWindow()
    llamadas.clear()  # descarta la reemisión del propio constructor

    # La fila Equipo ya no es la página provisional
    indice = [key for key, _title in TABS].index("equipment_tab")
    equipo = window.content.widget(indice)
    assert isinstance(equipo, EquipmentPage)
    planificador = window.content.widget(
        [key for key, _title in TABS].index("planner_tab")
    )
    assert isinstance(planificador, PlannerPage)

    equipo.setups_changed.emit()
    assert llamadas == ["reload_setups", "refresh"]

    equipo.locations_changed.emit()
    assert llamadas[-2:] == ["reload", "reemit"]

    window.close()


def test_ajustes_guardados_refrescan_clima_por_tipo(monkeypatch):
    """M-15: tras guardar API keys, Búsqueda se busca por tipo, no por índice.

    Con una página más delante del Planificador, `widget(4)` ya no lo es
    y el clima de Búsqueda no se refrescaba (y con `widget(4)` en None,
    crasheaba).
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QLabel

    from ui.main_window import MainWindow
    from ui.planner_tab.busqueda import BusquedaTab

    _app_ui()
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
        QTableWidget,
        QTabWidget,
    )

    from ui.main_window import MainWindow
    from ui.planner_tab.busqueda import COLUMNS
    from ui.planner_tab.widgets import LocationBar

    _app = QApplication.instance() or QApplication([])
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


# ---------------------------------------------------------------- Configuración
#: QApplication de los tests de Configuración (evita que se recoja entre tests).
_CONFIG_APP = None


def _config_dialog(monkeypatch, find_path, *, real_probe=False):
    """Crea un ``ConfigDialog`` de prueba: sin BD y con SirIL simulado.

    Devuelve ``(módulo, diálogo, probed)``; ``probed`` registra las rutas
    mandadas a comprobar. Con ``real_probe`` no se intercepta la sonda y
    el hilo de trabajo va de verdad (para probar la señal de vuelta).
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from ui.config_tab import config_dialog as cd

    global _CONFIG_APP
    _CONFIG_APP = QApplication.instance() or QApplication([])
    probed: list[str] = []
    monkeypatch.setattr(cd, "find_siril", lambda: find_path)
    monkeypatch.setattr(cd, "get_setting", lambda _key: "")
    monkeypatch.setattr(cd, "load_api_key", lambda _key: "")
    if not real_probe:
        monkeypatch.setattr(cd._BRIDGE, "probe", lambda path: probed.append(path))
    return cd, cd.ConfigDialog(), probed


def test_config_dialog_check_is_async(tmp_path, monkeypatch):
    """Configuración abre sin esperar a SirIL (estado «Comprobando…»).

    Regresión del «lagaso» de ~1,5 s al pulsar ⚙: el constructor
    ejecutaba ``siril-cli --version`` en el hilo de la interfaz (el
    antivirus puede costar ~1 s el primer día en examinar el proceso)
    y el diálogo tardaba en aparecer. Ahora la comprobación va por
    ``_BRIDGE.probe`` (hilo de trabajo) y la UI se pinta con el estado
    provisorio.
    """
    fake = tmp_path / "siril-cli.exe"
    fake.write_text("", encoding="utf-8")

    cd, dialog, probed = _config_dialog(monkeypatch, str(fake))

    assert probed == [str(fake)]                         # la comprobación va al hilo
    assert "Comprobando" in dialog._siril_status.text()  # ...y no ha vuelto aún
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)


def test_config_dialog_no_siril_warns_instantly(monkeypatch):
    """Sin SirIL el aviso sale ya mismo: ni hilo ni subproceso."""
    cd, dialog, probed = _config_dialog(monkeypatch, None)

    assert probed == []
    assert "No se encontró SirIL" in dialog._siril_status.text()
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)


def test_config_dialog_bad_path_errors_instantly(monkeypatch):
    """Ruta inventada: «La ruta no existe» sin intentar arrancar nada."""
    cd, dialog, probed = _config_dialog(
        monkeypatch, r"C:\ruta\fantasma\siril-cli.exe"
    )

    assert probed == []
    assert "La ruta no existe" in dialog._siril_status.text()
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)


def test_config_dialog_result_paints_status(tmp_path, monkeypatch):
    """El resultado del hilo pinta verde con versión y ámbar si falla."""
    fake = tmp_path / "siril-cli.exe"
    fake.write_text("", encoding="utf-8")

    cd, dialog, _probed = _config_dialog(monkeypatch, str(fake))

    dialog._on_siril_result(str(fake), "siril 1.4.4")
    assert dialog._siril_status.text() == "✓ siril 1.4.4 detectado y operativo."

    dialog._on_siril_result(str(fake), "")
    assert "no responde a --version" in dialog._siril_status.text()
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)


def test_config_dialog_result_descarta_ruta_vieja(tmp_path, monkeypatch):
    """M-23: una sonda lenta de una ruta vieja no pinta sobre la actual.

    El usuario cambia de ruta mientras la comprobación anterior sigue en
    el hilo de trabajo: su resultado («Encontrado en <vieja>…» o versión)
    ya no representa el campo y se descarta.
    """
    fake = tmp_path / "siril-cli.exe"
    fake.write_text("", encoding="utf-8")

    cd, dialog, _probed = _config_dialog(monkeypatch, str(fake))

    estado = dialog._siril_status.text()          # «Comprobando…» de la actual
    dialog._on_siril_result(r"C:\vieja\siril-cli.exe", "siril 1.0")
    assert dialog._siril_status.text() == estado  # resultado viejo: descartado

    dialog._on_siril_result(str(fake), "siril 1.4.4")
    assert "siril 1.4.4" in dialog._siril_status.text()   # la actual sí manda
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)


def test_config_dialog_probe_reaches_ui(tmp_path, monkeypatch):
    """El hilo de trabajo devuelve la versión y la señal la pinta en la UI."""
    import time

    from PyQt6.QtWidgets import QApplication

    from ui.config_tab import config_dialog as cd

    fake = tmp_path / "siril-cli.exe"
    fake.write_text("", encoding="utf-8")

    monkeypatch.setattr(cd, "siril_version", lambda _path: "siril 9.9.9")
    cd, dialog, _probed = _config_dialog(monkeypatch, str(fake), real_probe=True)

    app = QApplication.instance()
    for _ in range(300):  # hasta ~3 s: el hilo acaba y la señal se encola
        app.processEvents()
        if "siril 9.9.9" in dialog._siril_status.text():
            break
        time.sleep(0.01)
    assert dialog._siril_status.text() == "✓ siril 9.9.9 detectado y operativo."
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)


def test_show_settings_keeps_one_dialog(monkeypatch):
    """⚙ crea el diálogo una sola vez: reabrir solo lo refresca (``reload``)."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from ui.config_tab import ConfigDialog
    from ui.config_tab import config_dialog as cd
    from ui.main_window import MainWindow

    _app = QApplication.instance() or QApplication([])

    monkeypatch.setattr(cd, "find_siril", lambda: None)
    monkeypatch.setattr(cd, "get_setting", lambda _key: "")
    monkeypatch.setattr(cd, "load_api_key", lambda _key: "")

    created: list[object] = []
    original_init = ConfigDialog.__init__

    def counting_init(self, parent=None):
        """Sustituto de `ConfigDialog.__init__` que cuenta cuántas veces se construye."""
        created.append(self)
        original_init(self, parent)

    reloaded: list[object] = []
    original_reload = ConfigDialog.reload

    def counting_reload(self):
        """Sustituto de `ConfigDialog.reload` que cuenta cuántas veces se recarga."""
        reloaded.append(self)
        original_reload(self)

    monkeypatch.setattr(ConfigDialog, "__init__", counting_init)
    monkeypatch.setattr(ConfigDialog, "reload", counting_reload)
    monkeypatch.setattr(ConfigDialog, "exec", lambda self: None)  # sin modal

    window = MainWindow()
    window._show_settings()
    window._show_settings()

    assert len(created) == 1     # una sola construcción…
    assert len(reloaded) == 2    # ...pero los valores se recargan al reabrir
    window.close()


# --------------------------------------------- Planificación y catálogo (M-04/M-05/M-19)
def _app_ui():
    """QApplication retenida para los tests de cableado (ref. no descartada)."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    global _UI_APP
    _UI_APP = QApplication.instance() or QApplication([])
    return _UI_APP


_UI_APP = None


def test_hoy_emite_una_sola_vez():
    """M-03: «Hoy» emite `date_changed` una vez (no dos, como antes).

    Regresión: `setDate` ya dispara `dateChanged`→`_emit_date` y además
    se emitía a mano, con lo que Búsqueda refrescaba dos veces.
    """
    from ui.planner_tab.widgets import EphemerisPanel

    _app_ui()
    panel = EphemerisPanel()
    panel.set_date("2026-10-01")
    emitidas: list[str] = []
    panel.date_changed.connect(emitidas.append)

    panel._go_today()

    assert emitidas == [panel.current_date_iso()]
    panel._go_today()  # ya en hoy: nada cambió, nada se emite
    assert len(emitidas) == 1
    panel.deleteLater()


def test_location_bar_reload_reselecciona_por_id(monkeypatch):
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

    _app_ui()
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


def test_reload_targets_actualiza_una_vez(monkeypatch):
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

    _app_ui()
    page = plan_tab.PlanificacionTab()
    page._target.setCurrentIndex(1)   # selecciona el segundo
    llamadas.clear()

    page.reload_targets()             # keep_current: debe volver al índice 1

    assert len(llamadas) == 1
    page.deleteLater()


def test_reload_setups_mantiene_la_seleccion(monkeypatch):
    """M-19: repoblar el combo de equipos reselecciona por id, no al primero."""
    from ui.planner_tab.planificacion import tab as plan_tab

    setups = [
        {"id": 1, "name": "Cámara nocturna", "category": "espacio_profundo"},
        {"id": 2, "name": "Setup planetario", "category": "planetario"},
    ]
    monkeypatch.setattr(plan_tab, "list_setups", lambda: setups)
    monkeypatch.setattr(plan_tab.personal_catalog, "list_objects", list)

    _app_ui()
    page = plan_tab.PlanificacionTab()
    page._setup.setCurrentIndex(1)    # el segundo (id 2)

    page.reload_setups()

    assert page._setup.currentData()["id"] == 2
    page.deleteLater()


def test_refresh_no_repite_lo_que_no_cambio(monkeypatch):
    """M-01: aplicar filtros/Enter no vuelve a calcular astropy.

    Antes cada `refresh()` (clic «Aplicar filtros», Enter, reordenar,
    «Hoy») recalculaba las 4 partes aunque solo los filtros hubieran
    cambiado: ~1,1 s de efemérides+curva por clic. Ahora la búsqueda
    corre siempre (los filtros pueden haber cambiado) y las partes
    caras se saltan si su clave (objeto/noche/ubicación/huso) no cambió.
    """
    from ui.planner_tab.busqueda import tab as busq_tab

    _app_ui()
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


def test_calcular_plan_bloquea_la_reentrada(monkeypatch):
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

    _app_ui()
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


def test_quitar_objeto_emite_catalog_changed(monkeypatch):
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

    _app_ui()
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
