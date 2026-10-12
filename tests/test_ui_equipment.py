"""Regresiones de UI de la pestaña Equipo: Equipos, Ubicaciones y «Cálculos».

La ``QApplication`` viene del fixture ``qt_app`` de ``conftest.py``.
"""


def test_guardado_fallido_avisa_y_conserva_formulario(qt_app, memory_db, monkeypatch):
    """Errores de copia o SQLite no se escapan ni anuncian un guardado exitoso."""
    import sqlite3

    from ui.equipment_tab import equipos

    pagina = equipos.EquiposTab()
    pagina._nombre.setText("Sin guardar")
    avisos = []
    emisiones = []
    monkeypatch.setattr(equipos.QMessageBox, "warning", lambda *args: avisos.append(args[2]))
    pagina.setups_changed.connect(lambda: emisiones.append(True))
    for error in (OSError("copia fallida"), sqlite3.IntegrityError("BD fallida")):
        def fallar(setup, error=error):
            """Simula un fallo de persistencia del backend."""
            raise error
        monkeypatch.setattr(equipos.manager, "create", fallar)
        pagina._guardar()
    assert avisos == ["copia fallida", "BD fallida"]
    assert emisiones == []
    assert pagina._nombre.text() == "Sin guardar"
    assert pagina._setup_id is None
    pagina.deleteLater()


def test_equipment_page_construye_con_sus_dos_subpestanas(qt_app):
    """Paso 2: EquipmentPage monta Equipos y Ubicaciones y reemite señales.

    El cableado de la página en la ventana (fila de navegación → página real,
    no placeholder) se comprueba en el paso 3; aquí solo la página en sí.
    """

    from PyQt6.QtWidgets import QTabWidget

    from ui.equipment_tab import EquipmentPage

    _app = qt_app
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

def test_ubicaciones_seccion_unica_y_vista_previa_mapa(qt_app, tmp_path):
    """Sección «Ubicación» única en 2 filas + vista previa del mapa de CL.

    Regresiones de la fusión (pedido del usuario): la ficha es **un solo
    marco** —título con «Guardar ubicación» y dos filas de campos— con
    el orden que fijó él: Nombre · Altitud · Latitud · Longitud y
    Bortle · SQM · Seeing · ☑ Huso automático · Desfase; ya no quedan
    los rótulos «Geografía»/«Cielo». Y la imagen cargada aparece en el
    cuadro de la derecha para modelar con la referencia a la vista —
    vacío sin mapa y aviso si la ruta no se puede cargar.
    """

    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QImage
    from PyQt6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QLabel,
        QLineEdit,
        QPushButton,
        QTabWidget,
    )

    from ui.equipment_tab import EquipmentPage

    _app = qt_app
    pagina = EquipmentPage()
    tab = pagina.ubicaciones

    # Un solo marco: título + fila 1 + fila 2.
    assert tab._ficha.objectName() == "GroupFrame"
    lay = tab._ficha.layout()
    assert lay.count() == 3, "la ficha debe ser título y dos filas de campos"
    cabecera = lay.itemAt(0).layout()
    assert cabecera.itemAt(0).widget().text() == "Ubicación"
    botones = [
        cabecera.itemAt(i).widget()
        for i in range(cabecera.count())
        if isinstance(cabecera.itemAt(i).widget(), QPushButton)
    ]
    assert [b.text() for b in botones] == ["Guardar ubicación"]

    # Fila 1: parejas etiqueta|campo en el orden pedido.
    fila1 = lay.itemAt(1).layout()
    widgets1 = [fila1.itemAt(i).widget() for i in range(fila1.count())]
    assert [w.text() for w in widgets1 if isinstance(w, QLabel)] == [
        "Nombre",
        "Altitud",
        "Latitud",
        "Longitud",
    ]
    assert [w for w in widgets1 if not isinstance(w, QLabel)] == [
        tab._nombre,
        tab._altitud,
        tab._latitud,
        tab._longitud,
    ]
    assert isinstance(tab._nombre, QLineEdit)

    # Fila 2: Bortle, SQM, Seeing, el check y Desfase, en ese orden.
    fila2 = lay.itemAt(2).layout()
    widgets2 = [fila2.itemAt(i).widget() for i in range(fila2.count())]
    assert [type(w).__name__ for w in widgets2] == [
        "QLabel",
        "QComboBox",
        "QLabel",
        "QDoubleSpinBox",
        "QLabel",
        "QDoubleSpinBox",
        "QCheckBox",
        "QLabel",
        "QDoubleSpinBox",
    ]
    assert [w.text() for w in widgets2 if isinstance(w, QLabel)] == [
        "Bortle",
        "SQM",
        "Seeing",
        "Desfase",
    ]
    assert isinstance(tab._bortle, QComboBox)
    assert isinstance(tab._sqm, QDoubleSpinBox)
    assert isinstance(tab._seeing, QDoubleSpinBox)
    assert isinstance(tab._auto, QCheckBox)
    assert tab._auto.text() == "Huso automático"
    assert tab._auto.isChecked()

    # Los rótulos de las dos cajas antiguas ya no existen.
    textos = [r.text() for r in tab.findChildren(QLabel)]
    assert "Geografía" not in textos
    assert "Cielo" not in textos

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

def test_ubicaciones_todo_en_un_scroll_sin_splitter(qt_app, memory_db):
    """La lista, la ficha y el sitio viven en UN solo scroll, sin splitter.

    Regresión de la reestructuración (simétrica a la de Equipos): la
    barra lateral (QSplitter) desaparece y la pestaña no deja nada
    fijo —su único hijo directo es el `QScrollArea`—, así que la
    sección de la lista, la ficha «Ubicación» y el `SitioPanel` (a
    todo el ancho) se ven todos con la misma barra. La sección va
    **sin rótulo** y con el ancho que le deja la ficha (`_ancho_lista`,
    calculado sobre el viewport real del scroll: la ficha manda para
    que «Ubicación» quepa en 2 filas).
    """

    from PyQt6.QtWidgets import (
        QLabel,
        QListWidget,
        QPushButton,
        QScrollArea,
        QSplitter,
    )

    from ui.equipment_tab.ubicaciones import UbicacionesTab

    _app = qt_app
    tab = UbicacionesTab()
    tab.resize(1000, 600)
    tab.show()
    _app.processEvents()

    assert tab.findChildren(QSplitter) == [], "no debe quedar ningún QSplitter"

    # Un solo hijo directo de la pestaña: el scroll. Nada queda fijo
    # fuera de él (ése era el objetivo: las gráficas sin cabecera que
    # les robara altura).
    assert tab.layout().count() == 1, "la pestaña solo debe contener el scroll"
    area = tab.layout().itemAt(0).widget()
    assert isinstance(area, QScrollArea), "el hijo directo debe ser el scroll"
    assert tab.findChildren(QScrollArea) == [area], "debe haber exactamente un scroll"

    # Dentro del scroll: primero la fila [lista | ficha] y debajo el
    # sitio, a todo el ancho.
    flay = area.widget().layout()
    fila_sup = flay.itemAt(0).layout()
    seccion = fila_sup.itemAt(0).widget()
    assert seccion is not None and seccion.objectName() == "GroupFrame"
    assert flay.itemAt(1).widget() is tab._sitio, "el sitio va debajo de la fila, en el scroll"

    # El ancho de la lista sale del viewport real del scroll (hueco
    # tras el mínimo de la ficha, con suelo 200 y techo 450).
    hueco = area.viewport().width()
    esperado = max(200, min(450, hueco - 10 - tab._ficha.minimumSizeHint().width()))
    assert seccion.minimumWidth() == esperado, (
        "el ancho de la lista sale de la regla: viewport − mínimo de la ficha, con suelo y techo"
    )
    # Con el scroll suficientemente ancho, la sección llega a su techo
    # (y al pasar por ahí se comprueba que `resizeEvent` la recalcula).
    tab.resize(3000, 600)
    _app.processEvents()
    assert seccion.minimumWidth() == 450, "con scroll ancho la sección va a su techo"
    tab.resize(1000, 600)
    _app.processEvents()
    titulos = [
        etiqueta
        for etiqueta in seccion.findChildren(QLabel)
        if etiqueta.objectName() == "PanelTitle"
    ]
    assert titulos == [], "el rótulo «Ubicaciones guardados» se quitó: la pestaña ya se llama así"

    # La lista no infla la fila superior: sizeHint pequeño, **sin tope
    # de alto** y llenando la sección (el tope de 100 px la recortaba).
    listas = seccion.findChildren(QListWidget)
    assert len(listas) == 1
    lista = listas[0]
    assert lista.sizeHint().height() <= 60, "el sizeHint de la lista no debe mandar"
    assert lista.maximumHeight() > 1000, "la lista no debe llevar tope de alto"
    assert lista.height() >= seccion.height() // 2, (
        f"la lista ({lista.height()} px) debe llenar la sección ({seccion.height()} px)"
    )

    # Los botones van en fila (misma altura) y «🗑» lleva «Eliminar» en tooltip.
    bots = seccion.findChildren(QPushButton)
    assert {boton.text() for boton in bots} == {"➕ Nueva…", "🗑"}
    assert abs(bots[0].y() - bots[1].y()) <= 2, "los botones deben compartir fila"
    assert "Eliminar" in (bots[1].toolTip() or "")

    # La sección y la ficha derecha ocupan la misma banda (mismo pie
    # abajo) y el sizeHint de la sección no manda: si lo superara, la
    # fila se hincharía a costa del sitio.
    assert abs(
        (seccion.y() + seccion.height())
        - (tab._ficha.y() + tab._ficha.height())
    ) <= 2, "la sección y la ficha de la derecha deben acabar a la par"
    assert seccion.sizeHint().height() <= seccion.height(), (
        "el sizeHint de la sección no debe ser el que dispare la fila superior"
    )

    # Todo vive dentro del scroll: lista, ficha y sitio.
    assert area.isAncestorOf(seccion), "la sección de la lista debe ir en el scroll"
    assert area.isAncestorOf(tab._ficha), "la ficha «Ubicación» debe ir en el scroll"
    assert area.isAncestorOf(tab._sitio), "el SitioPanel sí va en el scroll"
    assert area.width() >= tab.width() - 30, (
        f"scroll a {area.width()} px de {tab.width()} (debe ir a todo el ancho)"
    )

    tab.deleteLater()
    _app.processEvents()

def test_ubicacion_altitud_desfase_y_sqm(qt_app, memory_db):
    """Revisión 2: la altitud sobrevive al guardar, desfase, SQM «—» y seeing.

    Regresiones de los tres defectos reportados: ``list_locations`` trae la
    columna ``altitude`` (la ficha leía ``altitude_m`` y se quedaba en 0 al
    recargar); con «Huso automático» el Desfase muestra ``round(lon/15)``
    —la misma regla que el planificador— y queda fijo, y sin el check se
    edita; y el SQM vuelve a vacío («-» al salir del campo → «—», en vez
    de revertir al valor anterior). El Seeing guarda y recarga, y la
    pista antigua de Bortle/SQM ya no existe: su texto vive en los
    tooltips de los campos.
    """

    from PyQt6.QtCore import QEvent
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QLabel

    from ui.equipment_tab.ubicaciones import UbicacionesTab

    _app = qt_app
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

def test_rosaceas_construyen_pintan_y_hacen_roundtrip(qt_app):
    """Paso 2: los discos de la rosácea construyen, pintan y roundtrip.

    Cubre `rosaceas.py` sin motor de nada más: la rosa y los dos discos
    de entrada pintan su círculo (``grab()`` dispara ``paintEvent``) y el
    estado de obstrucciones/CL sobrevive a set→get con las 8 direcciones;
    el esquemático acepta datos y repinta.
    """

    from equipment.models import DIRECTIONS
    from ui.equipment_tab.rosaceas import (
        DiscoEsquematico,
        DiscoLumen,
        DiscoObstrucciones,
        RosaDirecciones,
    )

    _app = qt_app
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

def test_cabecera_suma_precio_peso_y_lo_persiste(qt_app, memory_db):
    """Cabecera: precio/peso son la suma en vivo (solo lectura) y se guarda.

    Regresiones del rediseño: los dos campos de la cabecera ya no se
    teclean (son calculados); los 5 formularios y cada filtro marcado
    suman precio, cada telescopio con la casilla «Aplanador/Reductor/Coma»
    añade 0,5 kg de peso y sin datos se pinta «—» (0). Al «Guardar equipo» la
    suma queda en ``price_eur``/``weight_kg`` del setup (D-3) — sustituye
    al valor manual— y sobrevive a la recarga.
    """

    import pytest
    from PyQt6.QtWidgets import QCheckBox

    from equipment import components, manager
    from equipment.models import Filter
    from ui.equipment_tab.componentes import _FiltroDialog
    from ui.equipment_tab.equipos import EquiposTab

    _app = qt_app
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
    qt_app,
    memory_db,
):
    """Subtipo: combo solo seleccionable con la taxonomía de su tipo.

    Regresiones: el combo ya no admite texto libre; al elegir Tipo aparecen
    solo las opciones de esa óptica (Refractor = las 5 de la taxonomía);
    un subtipo guardado que no está en la lista (otra BD o el texto libre
    antiguo) se conserva al cargar, y al cambiar de Tipo el combo
    selecciona el primer subtipo del nuevo tipo (no arrastra el anterior).
    """

    from ui.equipment_tab.componentes import TelescopeForm

    _app = qt_app
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

def test_telescopio_rejilla_de_cuatro_columnas(qt_app):
    """Telescopio: rejilla de 4 columnas, cajas alineadas y sin tope de ancho.

    Regresión del rediseño —antes, filas sueltas de `QHBoxLayout`, cada
    una repartiendo por su cuenta—: todo el formulario vive en **una
    `QGridLayout` como la cabecera de Equipo**, con las etiquetas en las
    columnas 0 y 2 y los campos en la 1 y la 3 (ambas con stretch). Al
    montarla a 628 px —el ancho de la columna Principal/Guía en ventana
    1000×600—, `Precio`, `Apertura` y `Tipo` arrancan en la misma `x` y
    miden lo mismo que `Peso`, `Focal` y `Subtipo`, que era justo lo que
    faltaba: los `setMaximumWidth` (80/85/95/104/60 px) recortaban cada
    caja por su lado. La casilla ocupa las columnas 0-1 para que su texto
    largo no ensanche la fila y «Factor ×» va en la 2, delante de su
    caja. Se conservan los rangos que fijó el usuario: apertura 0-5000,
    focal 0-20000, factor 0,01-10,00 con inicial 1,00.
    """

    from PyQt6.QtWidgets import (
        QGridLayout,
        QLabel,
        QLineEdit,
        QVBoxLayout,
        QWidget,
    )

    from ui.equipment_tab.componentes import TelescopeForm

    _app = qt_app

    # Con ancho fijo real, no el del sizeHint: así se mide el reparto.
    contenedor = QWidget()
    caja = QVBoxLayout(contenedor)
    caja.setContentsMargins(0, 0, 0, 0)
    form = TelescopeForm()
    caja.addWidget(form)
    contenedor.setFixedWidth(628)
    contenedor.show()
    _app.processEvents()

    # Una sola rejilla con todo dentro (más el stretch de cierre).
    assert form.layout().count() == 2
    rejilla = form.layout().itemAt(0).layout()
    assert isinstance(rejilla, QGridLayout), "los datos van en una única rejilla"
    assert rejilla.columnCount() == 4

    def celda(widget) -> tuple[int, int]:
        """(fila, columna) que ocupa `widget`; falla si no está en la rejilla."""
        indice = rejilla.indexOf(widget)
        assert indice >= 0, widget
        fila, columna, _, _ = rejilla.getItemPosition(indice)
        return fila, columna

    def celda_ancha(widget) -> tuple[int, int, int, int]:
        """(fila, columna, filas, columnas) de `widget`, para las que abarcan."""
        indice = rejilla.indexOf(widget)
        assert indice >= 0, widget
        fila, columna, filas, columnas = rejilla.getItemPosition(indice)
        return fila, columna, filas, columnas

    # Campos de dos en dos en las columnas 1 y 3…
    assert celda(form._nombre) == (0, 1)
    assert celda(form._precio) == (1, 1)
    assert celda(form._peso) == (1, 3)
    assert celda(form._apertura) == (2, 1)
    assert celda(form._focal) == (2, 3)
    assert celda(form._tipo) == (4, 1)
    assert celda(form._subtipo) == (4, 3)
    # …la casilla abarca la 0-1, Notas toda la fila y los botones de
    # imágenes la 2-3 (la lista, la columna de campos 1).
    assert celda_ancha(form._reductor) == (3, 0, 1, 2)
    assert celda(form._factor) == (3, 3)
    assert celda_ancha(form._notas) == (5, 0, 1, 4)
    assert celda(form._imagenes) == (6, 1)

    def rotulo(fila: int, columna: int) -> str:
        """Texto de la etiqueta que hay en la celda (fila, columna)."""
        item = rejilla.itemAtPosition(fila, columna)
        assert item is not None, (fila, columna)
        assert isinstance(item.widget(), QLabel), (fila, columna)
        return item.widget().text()

    assert [rotulo(*c) for c in ((0, 0), (1, 0), (1, 2), (2, 0), (2, 2), (3, 2), (4, 0), (4, 2), (6, 0))] == [
        "Nombre",
        "Precio",
        "Peso",
        "Apertura",
        "Focal",
        "Factor ×",
        "Tipo",
        "Subtipo",
        "Imágenes",
    ]

    # Solo las dos columnas de campos están estiradas.
    assert [rejilla.columnStretch(c) for c in range(4)] == [0, 1, 0, 1]

    # Prueba visual: misma `x` y mismo ancho entre las cajas de una misma
    # columna (antes se descolocaban), y columnas 1 y 3 con el mismo
    # reparto (tolerancia por el mínimo que impone la casilla).
    assert form._precio.x() == form._apertura.x() == form._tipo.x()
    assert form._peso.x() == form._focal.x() == form._subtipo.x()
    assert form._precio.width() == form._apertura.width() == form._tipo.width()
    assert form._peso.width() == form._focal.width() == form._subtipo.width()
    assert abs(form._precio.width() - form._peso.width()) <= 12

    # Ningún spin con ancho máximo (era lo que recortaba las cajas).
    ancho_libre = QLineEdit().maximumWidth()  # máximo por defecto de una caja
    for spin in (form._precio, form._peso, form._apertura, form._focal, form._factor):
        assert spin.maximumWidth() == ancho_libre, spin

    # Rangos del usuario intactos y factor arrancando en 1,00.
    assert (form._apertura.minimum(), form._apertura.maximum()) == (0.0, 5000.0)
    assert (form._focal.minimum(), form._focal.maximum()) == (0.0, 20000.0)
    assert (form._factor.minimum(), form._factor.maximum(), form._factor.value()) == (0.01, 10.0, 1.0)

    # Al vaciarlo («Nuevo…» o carga vacía) el factor vuelve a 1,00 como
    # al arrancar: `limpiar()` seguía poniendo 0,80 y el 1,00 del
    # usuario no se llegaba a ver nunca en pantalla.
    form.limpiar()
    assert form._factor.value() == 1.0

    # La casilla conserva su texto largo, con el detalle en el tooltip.
    assert form._reductor.text() == "Aplanador/Reductor/Coma"
    assert "aplanador, reductor o coma corrector" in form._reductor.toolTip()

    form.deleteLater()
    contenedor.deleteLater()

def test_camara_y_montura_rejilla_de_cuatro_columnas(qt_app):
    """Cámara y Montura: la misma rejilla de 4 columnas que Telescopio.

    Regresión del rediseño (antes, `QFormLayout` + filas sueltas de
    `QHBoxLayout`, cada pareja con su propio reparto): las cajas de una
    misma columna arrancan en la misma `x` y miden lo mismo —Cámara a
    628 px, Precio·Píxel·Ancho en la 1 y Peso·Bits·Alto en la 3— y las
    dos columnas de campos se reparten el sobrante (a 900 px, Tipo y
    Capacidad de carga miden lo mismo en Montura). «Resolución», la
    lectura derivada de Ancho×Alto, va en su propia fila justo debajo
    del sensor: meter las tres parejas del sensor en una fila obligaría
    a la rejilla a tener 6 columnas y esas columnas de más estrechaban
    las cajas de 218 a 161 px. Montura deja además de 5 filas a 4
    (Tipo·Capacidad emparejados) y Cámara gana el espaciado a 4 px y la
    lista de Imágenes a 44 px de Telescopio, así ninguno de los dos
    formularios es más alto que con las filas sueltas.
    """

    from PyQt6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

    from ui.equipment_tab.componentes import CameraForm, MountForm

    _app = qt_app

    def montar(form, ancho: int):
        """Monta `form` en un contenedor de `ancho` px: (form, contenedor, rejilla)."""
        contenedor = QWidget()
        caja = QVBoxLayout(contenedor)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(form)
        contenedor.setFixedWidth(ancho)
        contenedor.show()
        _app.processEvents()
        assert form.layout().count() == 2, "una única rejilla y su stretch"
        rejilla = form.layout().itemAt(0).layout()
        assert isinstance(rejilla, QGridLayout), form
        assert rejilla.columnCount() == 4
        assert [rejilla.columnStretch(c) for c in range(4)] == [0, 1, 0, 1]
        return form, contenedor, rejilla

    def celda(rejilla, widget) -> tuple[int, int, int, int]:
        """(fila, columna, filas, columnas) de `widget` en la rejilla."""
        indice = rejilla.indexOf(widget)
        assert indice >= 0, widget
        return rejilla.getItemPosition(indice)

    def rotulo(rejilla, fila: int, columna: int) -> str:
        """Texto de la etiqueta de la celda (fila, columna)."""
        item = rejilla.itemAtPosition(fila, columna)
        assert item is not None, (fila, columna)
        assert isinstance(item.widget(), QLabel), (fila, columna)
        return item.widget().text()

    def misma_columna(*widgets) -> None:
        """Que todos los widgets midan y arrancen en el mismo sitio."""
        assert len({w.x() for w in widgets}) == 1, [w.x() for w in widgets]
        assert len({w.width() for w in widgets}) == 1, [w.width() for w in widgets]

    # -- Cámara ------------------------------------------------------------
    camara, cont_cam, g_cam = montar(CameraForm(), 628)
    assert celda(g_cam, camara._nombre) == (0, 1, 1, 3)
    assert celda(g_cam, camara._precio) == (1, 1, 1, 1)
    assert celda(g_cam, camara._peso) == (1, 3, 1, 1)
    assert celda(g_cam, camara._pixel) == (2, 1, 1, 1)
    assert celda(g_cam, camara._bits) == (2, 3, 1, 1)
    assert celda(g_cam, camara._ancho) == (3, 1, 1, 1)
    assert celda(g_cam, camara._alto) == (3, 3, 1, 1)
    assert celda(g_cam, camara._resolucion) == (4, 1, 1, 1)
    assert celda(g_cam, camara._notas) == (6, 0, 1, 4)
    assert celda(g_cam, camara._imagenes) == (7, 1, 1, 1)
    assert [rotulo(g_cam, *c) for c in ((0, 0), (1, 0), (1, 2), (2, 0), (2, 2), (3, 0), (3, 2), (4, 0), (7, 0))] == [
        "Nombre",
        "Precio",
        "Peso",
        "Tam. Píxel (µm)",
        "Bits",
        "Ancho",
        "Alto",
        "Resolución",
        "Imágenes",
    ]

    misma_columna(camara._precio, camara._pixel, camara._ancho)
    misma_columna(camara._peso, camara._bits, camara._alto)
    # Las dos columnas de campos se reparten el sobrante por igual.
    assert abs(camara._precio.width() - camara._peso.width()) <= 2

    # La resolución sigue siendo la lectura viva de Ancho × Alto.
    camara._ancho.setValue(6248)
    camara._alto.setValue(4176)
    assert camara._resolucion.text() == "6248×4176"

    # Cámara no es más alta que con las filas sueltas (222 px).
    assert camara.sizeHint().height() < 222

    # -- Montura -----------------------------------------------------------
    montura, cont_mon, g_mon = montar(MountForm(), 900)
    assert celda(g_mon, montura._nombre) == (0, 1, 1, 3)
    assert celda(g_mon, montura._precio) == (1, 1, 1, 1)
    assert celda(g_mon, montura._peso) == (1, 3, 1, 1)
    assert celda(g_mon, montura._tipo) == (2, 1, 1, 1)
    assert celda(g_mon, montura._capacidad) == (2, 3, 1, 1)
    assert celda(g_mon, montura._notas) == (3, 0, 1, 4)
    assert [rotulo(g_mon, *c) for c in ((0, 0), (1, 0), (1, 2), (2, 0), (2, 2))] == [
        "Nombre",
        "Precio",
        "Peso",
        "Tipo",
        "Capacidad de carga",
    ]

    misma_columna(montura._precio, montura._tipo)
    misma_columna(montura._peso, montura._capacidad)
    assert abs(montura._precio.width() - montura._peso.width()) <= 2

    # Montura no es más alto que con las filas sueltas (136 px).
    assert montura.sizeHint().height() < 136

    for contenedor in (cont_cam, cont_mon):
        contenedor.deleteLater()
    _app.processEvents()

def test_calculos_orden_y_rotulos(qt_app, memory_db):
    """Cálculos: las 5 lecturas en el orden decidido y con dos puntos.

    Regresión del reordenado (antes: Escala · Dawes · F/d · Focal
    efectiva · Muestreo y sin dos puntos): la fila es Relación Focal ·
    Distancia Focal Efectiva · Escala · Límite Dawes · Muestreo, cada
    rótulo con su dos puntos y pegado a su valor.
    """

    from ui.equipment_tab.equipos import EquiposTab

    _app = qt_app
    tab = EquiposTab()

    # La fila vive dentro del marco del bloque: título + (rótulo, valor)*5
    # y, al final, el stretch que empuja todo a la izquierda.
    fila = tab._escala.parentWidget().layout().itemAt(0).layout()
    widgetes = [
        item.widget() for j in range(fila.count())
        if (item := fila.itemAt(j)).widget() is not None
    ]
    assert widgetes[0].text() == "Cálculos" and len(widgetes) == 11

    esperado = (
        ("Relación Focal:", tab._relacion),
        ("Distancia Focal Efectiva:", tab._efectiva),
        ("Escala:", tab._escala),
        ("Límite Dawes:", tab._dawes),
        ("Muestreo:", tab._muestreo),
    )
    for i, (rotulo, valor) in enumerate(esperado):
        assert widgetes[1 + 2 * i].text() == rotulo, f"rótulo {i}"
        assert widgetes[2 + 2 * i] is valor, f"valor {i}"

    tab.deleteLater()

def test_calculos_con_seeing_rango_y_barra(qt_app, memory_db):
    """Cálculos: el seeing recorta el rango, colorea el veredicto y pinta la barra.

    Regresiones: la pista añade «Rango adecuado (Dawes y Seeing): X–Y
    ″/px», la etiqueta
    de Muestreo se tiñe según el veredicto (arcoíris de 5 niveles:
    violeta/azul/verde/amarillo/naranja), la barra pinta, elegir una
    ubicación con seeing cambia rango y veredicto (sin ubicación o sin
    dato manda solo Dawes con los umbrales de Configuración) y los dos
    niveles «Ligero» aparecen en amarillo y azul.
    """

    from equipment import localizations
    from equipment.models import DIRECTIONS, Location
    from ui.equipment_tab.equipos import EquiposTab

    _app = qt_app
    tab = EquiposTab()

    tel = tab._tel_principal.form
    tel._apertura.setValue(80.0)
    tel._focal.setValue(400.0)
    cam = tab._cam_principal.form
    cam._pixel.setValue(2.4)  # ≈ 1,24 ″/px

    # Sin ubicación: solo Dawes (0,725–1,45) → correcto en verde.
    assert "Muestreo del Equipo: (sin nombre) en (sin ubicación)." in (
        tab._pista_calculos.text()
    )
    assert "Rango adecuado (Dawes y Seeing):" in tab._pista_calculos.text()
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

    assert "Muestreo del Equipo: (sin nombre) en Cielo fino." in (
        tab._pista_calculos.text()
    )
    assert "Rango adecuado (Dawes y Seeing): 0.25–0.50 ″/px." in (
        tab._pista_calculos.text()
    )
    assert tab._muestreo.text() == "Submuestreado"
    assert "#F39C12" in tab._muestreo.styleSheet()

    tab.deleteLater()

def test_pista_calculos_con_equipo_y_barra_mayor(qt_app, memory_db):
    """Cálculos: la pista resume el equipo y la barra gana alto y ancho.

    Regresiones del reparto del espacio que gana el Telescopio al
    agruparse en dos filas: la pista empieza por «Muestreo del Equipo:
    {nombre} en {ubicación}» —nombre vacío → «(sin nombre)», y el combo
    ya trae «(sin ubicación)»— y se repinta al teclear el nombre; el
    bloque abre márgenes y espaciado para llevarse ese alto, y en su
    fila la `BarraMuestreo` comparte stretch con la pista (más larga en
    horizontal) y pasa de 16 a 24 px de alto.
    """

    from ui.equipment_tab.equipos import EquiposTab

    _app = qt_app
    tab = EquiposTab()

    tel = tab._tel_principal.form
    tel._apertura.setValue(80.0)
    tel._focal.setValue(400.0)
    tab._cam_principal.form._pixel.setValue(2.4)

    # Sin nombre y sin ubicación, pero ya con rango (Dawes solo).
    assert tab._pista_calculos.text().startswith(
        "Muestreo del Equipo: (sin nombre) en (sin ubicación)."
    )
    assert "Rango adecuado (Dawes y Seeing):" in tab._pista_calculos.text()

    # El nombre se teclea en la ficha y la pista lo repinta al instante.
    tab._nombre.setText("Noche larga")
    assert tab._pista_calculos.text().startswith(
        "Muestreo del Equipo: Noche larga en (sin ubicación)."
    )

    def fila_de(widget) -> int:
        """Índice de la fila del bloque que contiene `widget` (-1 = no)."""
        vertical = widget.parentWidget().layout()
        for i in range(vertical.count()):
            fila = vertical.itemAt(i).layout()
            if fila is None:
                continue
            for j in range(fila.count()):
                if fila.itemAt(j).widget() is widget:
                    return i
        return -1

    # La barra es de 24 px y su fila la estira igual que la pista.
    assert (tab._barra.minimumHeight(), tab._barra.maximumHeight()) == (24, 24)
    indice = fila_de(tab._barra)
    assert indice >= 0 and fila_de(tab._pista_calculos) == indice, "juntas"
    fila = tab._barra.parentWidget().layout().itemAt(indice).layout()
    assert fila.stretch(fila.indexOf(tab._barra)) == 1
    assert fila.stretch(fila.indexOf(tab._pista_calculos)) == 1

    # El bloque abre márgenes y espaciado: se lleva el alto ganado.
    caja = tab._barra.parentWidget().layout()
    caja_margen = caja.contentsMargins()
    assert caja_margen.top() + caja_margen.bottom() >= 14
    assert caja.spacing() >= 8

    tab.deleteLater()

def test_barra_arcoiris_fija_y_marcador_sigue_el_veredicto(qt_app, memory_db):
    """La barra es una escala fija de 5 quintos y el marcador se mueve solo.

    Regresiones: el verde se queda siempre centrado (0,4–0,6) y los
    colores NO se reposicionan con el rango (mismo color en la misma X
    aunque cambie la apertura); el marcador cae dentro del quinto de su
    veredicto y al crecer la escala solo se mueve a la derecha. Sin
    apertura → barra gris (nada inventado).
    """

    from equipment.metrics import veredicto_muestreo
    from ui.equipment_tab.equipos import (
        _ARCOIRIS,
        _VEREDICTO_COLOR,
        BarraMuestreo,
        _posicion_marcador,
    )

    _app = qt_app
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
    for escala, posicion in zip(escalas, posiciones, strict=True):
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

def test_ficha_sin_hint_de_solo_visuales_y_cabe_sin_scroll(qt_app, memory_db):
    """Sin el hint «Solo visuales» la ficha entera cabe sin scroll.

    «Solo visuales: el programa no analiza los charts / las curvas de
    ganancia» ocupaba una fila con word wrap en cada formulario y
    empujaba la ficha a scrollear: quitado el hint (y apretados los
    márgenes de «Cálculos»), con la ventana a 1000×600 el panel con
    scroll vertical tiene ``maximum == 0``. La aclaración vive en
    `PROGRAM.md` y en la docstring de `equipment.models`, no en la UI.
    """

    from PyQt6.QtWidgets import QLabel, QScrollArea

    from ui.equipment_tab.componentes import CameraForm, TelescopeForm
    from ui.equipment_tab.equipos import EquiposTab

    _app = qt_app
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

def test_equipos_seccion_lista_arriba_sin_splitter(qt_app, memory_db):
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

    from PyQt6.QtWidgets import (
        QFrame,
        QLabel,
        QListWidget,
        QPushButton,
        QScrollArea,
        QSplitter,
    )

    from ui.equipment_tab.equipos import EquiposTab, _ancho_seccion

    _app = qt_app
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

def test_equipos_lista_nombre_categoria_y_ubicacion(qt_app, memory_db):
    """Las filas de la lista dicen «nombre · categoría · ubicación».

    Regresión de dos quejas seguidas del usuario: (a) «con 3 equipos
    solo se veían 2» —sin rótulo ni tope la lista llena la sección y
    caben 3+ filas seguidas— y (b) «que también diga la ubicación»
    —``location_name`` del LEFT JOIN de ``list_setups`` (M-17)—. Sin
    ubicación se omite el tercer trozo, como antes.
    """

    from PyQt6.QtWidgets import QListWidget

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

    _app = qt_app
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

def test_equipos_seccion_no_solapa_la_cabecera_en_ventana_estrecha(qt_app, memory_db):
    """La sección encoge en ventana estrecha y nunca queda bajo la cabecera.

    Regresión: con 450 px fijos, la fila superior —que reparte **a
    medias** cuando los mínimos de sus dos hijos no caben, y la
    cabecera sola pide ~1085— metía la sección 61 px debajo de la
    cabecera en la ventana mínima (1024 px → 780 de pestaña).
    `_ancho_seccion` la limita a la mitad de su hueco, así que baja de
    450 solo cuando hace falta.
    """

    from ui.equipment_tab.equipos import _ancho_seccion
    from ui.main_window import TABS, MainWindow

    _app = qt_app
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

def test_equipo_sin_asteriscos_en_los_rotulos(qt_app, memory_db):
    """Ningún rótulo de la pestaña Equipo termina en «*».

    Regresión: «Nombre *», «Latitud *», «Bortle *»… no comunicaban nada
    —la validación real se ve en el «Falta: …» inline y en los tooltips—
    y solo estorbaban; el usuario pidió quitarlos. Cubre las cuatro
    piezas de componentes, la cabecera de Equipos y la sección «Ubicación».
    """

    from PyQt6.QtWidgets import QLabel

    from ui.equipment_tab import EquipmentPage

    _app = qt_app
    pagina = EquipmentPage()
    asteriscos = sorted(
        etiqueta.text() for etiqueta in pagina.findChildren(QLabel)
        if etiqueta.text().endswith("*")
    )
    assert asteriscos == [], f"rótulos con asterisco: {asteriscos}"

    pagina.deleteLater()
    _app.processEvents()

def test_afines_nuevo_sin_dialogo_lista_vacia_y_falta_nombre(qt_app, memory_db, monkeypatch):
    """Afines A de Equipos: «Nuevo…» sin diálogo, ayuda en lista vacía y «Falta: nombre».

    Regresiones: «Nuevo…» no debe abrir ningún QInputDialog (deja la
    ficha en blanco), una lista sin equipos pinta una fila de ayuda no
    seleccionable, y «Guardar equipo» sin nombre enseña el hint inline
    «Falta: nombre» sin aviso modal —que se quita al teclear— sin
    persistir nada.
    """

    import pytest
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QInputDialog, QMessageBox

    from ui.equipment_tab.equipos import EquiposTab

    _app = qt_app
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

def test_equipo_cableado_en_la_ventana(qt_app, monkeypatch):
    """Paso 3: Equipo ya no es placeholder y sus señales llegan al Planificador.

    El cableado vive en ``MainWindow`` (ninguna pestaña importa a otra):
    ``setups_changed`` → recarga de setups de Planificación y de Sesiones;
    ``locations_changed`` → recarga y reenvío de la barra de ubicación.
    """

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

    _app = qt_app
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

