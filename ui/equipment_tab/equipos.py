"""Subpestaña **Equipos**: la lista de guardados, cabecera y ficha.

Layout: dos filas — la superior es `[sección de la lista (hasta 450 px,
**sin rótulo**: la pestaña ya se llama «Equipos» y el rótulo robaba
44 px de altura que ahora son filas) | cabecera Equipo]`, con la lista y
sus botones «Nuevo…»/«Eliminar» **a la altura** de la cabecera (no a
toda la altura de la pestaña); en la fila inferior, un scroll **a todo
el ancho** con las sub-subpestañas Telescopio / Cámara / Montura /
Filtros y el bloque «Cálculos». La cabecera (nombre, categoría,
ubicación, precio/peso — **suma en vivo, solo lectura** — y notas — a
dos columnas — y «Guardar equipo») vive fuera del scroll para que su
Guardar esté siempre visible.

Las filas de la lista dicen `nombre · categoría · ubicación` a 10 pt en
una sola línea (450 px de sección = 424 útiles; a 13 pt ese texto pide
544); si no cabe, se elige al medio con «…» (el texto completo va en el
tooltip) y la barra horizontal, además de fea, se comía 12 px de alto.
Cuando la ventana es estrecha la sección baja de 450 (`_ancho_seccion`)
para no quedar debajo de la cabecera.

Regla UX global (§9): **nada se persiste hasta «Guardar equipo»**: lo que
toca las piezas globales lo decide su propio botón «Guardar componente»
(``componentes.py``). Cambiar de fila en la lista sin guardar descarta lo
tecleado (es el «cancelar» de D-5). El bloque «Cálculos» sí se recalcula en
vivo: es estado en memoria de lo que hay en pantalla, no una lectura de la
base.
"""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QResizeEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from db.settings import get_float
from equipment import localizations, manager
from equipment.images import list_images
from equipment.metrics import calculos
from equipment.models import CATEGORIES, EquipmentSetup

from .componentes import (
    CameraForm,
    FiltersPanel,
    MountForm,
    PartEditor,
    TelescopeForm,
    spin_peso,
    spin_precio,
)


def _formato(valor: float | None, unidad: str = "") -> str:
    """Pinta una métrica: «—» si falta el dato, 2 decimales con unidad si no."""
    return "—" if valor is None else f"{valor:.2f}{unidad}"


#: Ancho máximo de la sección de la lista: es lo que necesita la fila
#: «nombre · categoría · ubicación» a 10 pt para caber en una línea.
_ANCHO_SECCION_MAX = 450


def _ancho_seccion(ancho_tab: int) -> int:
    """Ancho de la sección de la lista: 450 px si cabe, si no, la mitad de su hueco.

    La fila superior reparte **a medias** el ancho disponible cuando los
    mínimos de sus dos hijos no caben (la cabecera pide ~1085 px sola),
    así que una sección más ancha que la mitad acabaría debajo de la
    cabecera —solape de hasta 61 px en la ventana mínima (1024)—. Con la
    mitad del hueco como techo, la sección se queda en su ancho completo
    cuando la ventana es ancha y encoge (sin solapar) cuando es estrecha.

    Args:
        ancho_tab: ancho de la pestaña en píxeles.

    Returns:
        Ancho fijo que hay que darle a la sección.
    """
    hueco = max(0, ancho_tab - 22)  # márgenes (6+6) + spacing (10)
    return min(_ANCHO_SECCION_MAX, hueco // 2)


class _ListaEquipos(QListWidget):
    """Lista de equipos guardados cuyo *sizeHint* no manda sobre la sección.

    `QListWidget` pide de por sí ~192 px de alto; si ese sizeHint
    llegara a la sección, la fila superior crecería por encima de la
    cabecera y empujaría el scroll de la ficha, que a 1000×600 solo
    tiene 12 px de holgura (lo comprueba
    `test_ficha_sin_hint_de_solo_visuales_y_cabe_sin_scroll`). Aquí el
    alto preferido es fijo y pequeño, pero **puede crecer**: la sección
    le da stretch, así que la lista llena los ~112 px que quedan y caben
    ~7 filas en vez de 2.

    Va a 10 pt y con el texto elegido al medio: el contenido completo
    `nombre · categoría · ubicación` mide 416 px y hay 424 útiles; lo
    que no quepa se corta por el centro con «…» (el texto completo va
    en el tooltip) y la barra horizontal —que se comía otros 12 px—
    queda desactivada.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setMinimumHeight(40)
        fuente = self.font()
        fuente.setPointSizeF(10)
        self.setFont(fuente)

    def sizeHint(self) -> QSize:
        """Alto preferido de 60 px: manda la sección, no la lista."""
        return QSize(400, 60)


#: Los 5 niveles de muestreo y sus colores (etiqueta y barra), decididos
#: por el usuario como un arcoíris: de la escala fina a la gruesa —
#: violeta, azul, verde, amarillo, naranja. Legibles sobre el tema oscuro.
_VEREDICTO_COLOR = {
    "Submuestreado": "#F39C12",           # naranja
    "Submuestreado Ligero": "#F4D03F",    # amarillo
    "Muestreo Correcto": "#2ECC71",       # verde
    "Sobremuestreado Ligero": "#5DADE2",  # azul
    "Sobremuestreado": "#A78BFA",         # violeta
}

#: Orden del arcoíris en la barra (de más fina a más gruesa).
_ARCOIRIS = (
    "Sobremuestreado",
    "Sobremuestreado Ligero",
    "Muestreo Correcto",
    "Submuestreado Ligero",
    "Submuestreado",
)


def _posicion_marcador(
    escala: float | None, limites: tuple[float, float, float, float] | None
) -> float | None:
    """Posición del marcador en la barra, de 0.0 a 1.0 (None sin dato).

    La barra es una escala **fija** de 5 quintos equidistantes —violeta,
    azul, verde centrado, amarillo, naranja— y el marcador se coloca
    dentro del quinto de su veredicto, con las mismas ramas que
    `equipment.metrics.veredicto_muestreo`: así el color que hay debajo
    del marcador siempre es el color del nivel y, al crecer la escala,
    el marcador solo se mueve de izquierda a derecha. Los límites salen
    de `limites_muestreo` (factor ≥ 1 → bandas ordenadas y sin
    divisiones por cero; rango de un solo punto → centro del verde).
    """
    if escala is None or escala <= 0 or limites is None:
        return None
    bajo_lig, bajo, alto, alto_lig = limites
    if escala > alto_lig:
        # Naranja: asintótico hasta 1,0 (nunca se queda pegado al borde).
        return 0.8 + 0.2 * (1.0 - alto_lig / escala)
    if escala > alto:
        return 0.6 + 0.2 * (escala - alto) / (alto_lig - alto)
    if escala < bajo_lig:
        return 0.2 * (escala / bajo_lig)
    if escala < bajo:
        return 0.2 + 0.2 * (escala - bajo_lig) / (bajo - bajo_lig)
    if alto <= bajo:
        return 0.5  # rango de un solo punto: centro del verde
    return 0.4 + 0.2 * (escala - bajo) / (alto - bajo)


class BarraMuestreo(QWidget):
    """Mini barra arcoíris: 5 zonas fijas y el marcador del nivel movible.

    El fondo es una escala **fija** de 5 quintos equidistantes con
    fundidos entre vecinos (violeta sobremuestreado · azul ligero ·
    verde correcto **centrado** · amarillo ligero · naranja
    submuestreado): no se reposiciona con el rango, así el color del
    centro es siempre el verde. Lo único que se mueve es el marcador
    ( `_posicion_marcador`, dentro del quinto de su veredicto). Sin
    límites (no hay apertura) se pinta la barra gris de «sin datos».
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Barra apilable de alto fijo; los datos llegan con `pintar`."""
        super().__init__(parent)
        self._escala: float | None = None
        self._limites: tuple[float, float, float, float] | None = None
        self._posicion: float | None = None
        self.setFixedHeight(16)
        self.setMinimumWidth(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(
            "Arcoíris de los 5 niveles (fijo): violeta sobremuestreado · azul "
            "sobremuestreado ligero · verde correcto · amarillo "
            "submuestreado ligero · naranja submuestreado (la línea "
            "marca el nivel actual)."
        )

    def pintar(
        self,
        escala: float | None,
        limites: tuple[float, float, float, float] | None,
    ) -> None:
        """Actualiza escala y límites (con ellos la posición) y repinta."""
        self._escala = escala if escala and escala > 0 else None
        self._limites = limites
        self._posicion = _posicion_marcador(self._escala, limites)
        self.update()

    def paintEvent(self, evento) -> None:
        """Pinta el arcoíris fijo de 5 zonas y el marcador del nivel."""
        del evento  # el repintado es completo: no hace falta usar el rect
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ancho, alto = self.width(), self.height()
        if ancho <= 0 or alto <= 0:
            return
        ruta = QPainterPath()
        ruta.addRoundedRect(0.0, 0.0, float(ancho), float(alto), 4.0, 4.0)
        pintor.setClipPath(ruta)

        if self._limites is None:
            pintor.fillRect(0, 0, ancho, alto, QColor("#4A5058"))
            return

        # Quintos fijos: color sólido en el núcleo y fundido de 4 % a
        # cada lado de cada borde (los offsets van de 0 a 1, en orden).
        degradado = QLinearGradient(0, 0, ancho, 0)
        transicion = 0.04
        paradas: list[tuple[float, QColor]] = []
        for i, clave in enumerate(_ARCOIRIS):
            color = QColor(_VEREDICTO_COLOR[clave])
            borde = i * 0.2
            if i:
                paradas.append(
                    (borde - transicion, QColor(_VEREDICTO_COLOR[_ARCOIRIS[i - 1]]))
                )
            paradas.append((borde + (transicion if i else 0.0), color))
        paradas.append((1.0, QColor(_VEREDICTO_COLOR[_ARCOIRIS[-1]])))
        degradado.setStops(paradas)
        pintor.fillRect(0, 0, ancho, alto, degradado)

        # Marcador: línea oscura con el núcleo claro encima.
        if self._posicion is not None:
            x = max(2, min(ancho - 2, int(self._posicion * ancho)))
            pintor.fillRect(x - 2, 0, 5, alto, QColor("#0d1117"))
            pintor.fillRect(x - 1, 0, 3, alto, QColor("#e6edf3"))


class EquiposTab(QWidget):
    """Gestión de equipos: lista + ficha con sub-subpestañas y Cálculos.

    Señales: ``setups_changed`` tras alta/baja/guardado de un equipo **o de
    una pieza/filtro** (los componentes cambian lo que pinta Planificación);
    la ventana principal es quien decide a dónde reenviarla.
    """

    setups_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta las dos filas (lista + cabecera / scroll) y carga el primer equipo si hay."""
        super().__init__(parent)
        self._setup_id: int | None = None
        self._imagenes_setup: list[str] = []
        self._cargando = False
        self._editores: list[PartEditor] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        # Fila superior: la sección de la lista a la izquierda (hasta
        # 450 px, a la misma altura que la cabecera) y la cabecera a la
        # derecha. El alto lo manda la cabecera; la lista se estira.
        fila_sup = QHBoxLayout()
        fila_sup.setSpacing(10)
        self._marco_lista = self._seccion_lista()
        fila_sup.addWidget(self._marco_lista)
        fila_sup.addWidget(self._cabecera(), 1)
        layout.addLayout(fila_sup)

        # Fila inferior: sub-subpestañas y cálculos en un panel con
        # scroll vertical, **a todo el ancho** (ya no hay barra lateral).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contenido = QWidget()
        interior = QVBoxLayout(contenido)
        interior.setContentsMargins(0, 0, 0, 0)
        interior.setSpacing(8)
        interior.addWidget(self._subpestanas())
        interior.addWidget(self._bloque_calculos())
        interior.addStretch(1)
        scroll.setWidget(contenido)
        layout.addWidget(scroll, 1)

        # Cableado interno: los cálculos viven de cualquier cambio en
        # pantalla; las piezas guardadas refrescan combos y avisan fuera.
        for editor in self._editores:
            editor.changed.connect(self._recalcular)
            editor.saved.connect(self._tras_pieza_guardada)
        self._filtros.saved.connect(self.setups_changed.emit)
        self._filtros.changed.connect(self._recalcular)  # casilla → suma en vivo
        # Cambiar de ubicación cambia el seeing que recorta el rango.
        self._ubicacion.currentIndexChanged.connect(lambda _i: self._recalcular())
        self._recargar_lista(select_id=None)

    def resizeEvent(self, ev: QResizeEvent) -> None:
        """Recalcula el ancho de la sección de la lista al redimensionar.

        Sin esto, en la ventana mínima (1024 px → 780 de pestaña) la
        sección de 450 se metía 61 px debajo de la cabecera: ver
        `_ancho_seccion`.
        """
        super().resizeEvent(ev)
        marco = getattr(self, "_marco_lista", None)
        if marco is None:
            return
        ancho = _ancho_seccion(self.width())
        if marco.width() != ancho:
            marco.setFixedWidth(ancho)

    # -- construcción ------------------------------------------------------

    def _seccion_lista(self) -> QFrame:
        """Sección de la lista: equipos guardados, sin rótulo, y sus botones.

        El ancho lo da `_ancho_seccion` (hasta 450 px, y en ventana
        estrecha la mitad de su hueco para no solapar la cabecera) para
        que la fila de la lista quepa a la izquierda de ella **a la
        misma altura**. Sin rótulo: «Equipos guardados» a `PanelTitle`
        (13 pt) ocupaba dos líneas —44 px— de los 153 de la sección, y
        ese alto es de las filas que faltaban para ver 3 equipos
        seguidos; la pestaña ya se llama «Equipos» y la zona no necesita
        etiqueta.

        - la lista va con stretch para llenar lo que sobre
          (`_ListaEquipos.sizeHint()` es pequeño a propósito: su
          sizeHint natural de 192 px hincharía la fila superior y
          empujaría el scroll de la ficha);
        - los botones van en fila («➕ Nuevo…» + «🗑 Eliminar» no caben
          en 426 → «🗑» con tooltip), que ahorra 31 px sobre apilarlos.
        """
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        marco.setFixedWidth(_ancho_seccion(self.width()))
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(12, 4, 12, 6)
        lay.setSpacing(6)

        self._lista = _ListaEquipos()
        self._lista.currentRowChanged.connect(self._al_elegir_fila)
        lay.addWidget(self._lista, 1)

        acciones = QHBoxLayout()
        acciones.setSpacing(6)
        boton_nuevo = QPushButton("➕ Nuevo…")
        boton_nuevo.clicked.connect(self._nuevo)
        acciones.addWidget(boton_nuevo, 1)
        self._boton_eliminar = QPushButton("🗑")
        self._boton_eliminar.setToolTip("Eliminar el equipo seleccionado")
        self._boton_eliminar.clicked.connect(self._eliminar)
        self._boton_eliminar.setEnabled(False)
        acciones.addWidget(self._boton_eliminar)
        lay.addLayout(acciones)
        return marco

    def _cabecera(self) -> QFrame:
        """Cabecera del equipo a dos columnas: identidad, la suma precio/peso, notas y su «Guardar»."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(12, 6, 12, 10)
        lay.setSpacing(8)

        fila_titulo = QHBoxLayout()
        titulo = QLabel("Equipo")
        titulo.setObjectName("PanelTitle")
        fila_titulo.addWidget(titulo)
        fila_titulo.addStretch(1)
        self._boton_guardar = QPushButton("Guardar equipo")
        self._boton_guardar.setObjectName("PrimaryButton")
        self._boton_guardar.clicked.connect(self._guardar)
        fila_titulo.addWidget(self._boton_guardar)
        lay.addLayout(fila_titulo)

        # Tres filas de dos campos (el usuario pidió las parejas): la
        # rejilla alinea las columnas y la cabecera baja de 6 filas a 3.
        self._nombre = QLineEdit()
        self._nombre.setPlaceholderText("Equipo de viaje, montura fija…")
        self._categoria = QComboBox()
        for clave, etiqueta in CATEGORIES.items():
            self._categoria.addItem(etiqueta, clave)
        self._ubicacion = QComboBox()
        # Precio/peso SOLO LECTURA: la cabecera pinta la suma en vivo de
        # las piezas en pantalla y «Guardar equipo» persiste ese total.
        self._precio = spin_precio()
        self._precio.setReadOnly(True)
        self._precio.setToolTip(
            "Suma del precio de las piezas y los filtros marcados "
            "(se guarda con «Guardar equipo»)."
        )
        self._peso = spin_peso()
        self._peso.setReadOnly(True)
        self._peso.setToolTip(
            "Suma del peso de las piezas en pantalla: +0,5 kg por cada "
            "telescopio con la casilla «Aplanador» (aplanador, reductor "
            "o coma corrector)."
        )
        self._notas = QLineEdit()
        self._notas.setPlaceholderText("Notas (opcional)")
        parejas = (
            ("Nombre", self._nombre, "Categoría", self._categoria),
            ("Ubicación", self._ubicacion, "Precio", self._precio),
            ("Peso", self._peso, "Notas", self._notas),
        )
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        for fila, (etiqueta_a, campo_a, etiqueta_b, campo_b) in enumerate(parejas):
            form.addWidget(QLabel(etiqueta_a), fila, 0)
            form.addWidget(campo_a, fila, 1)
            form.addWidget(QLabel(etiqueta_b), fila, 2)
            form.addWidget(campo_b, fila, 3)
        # Afine A: aviso inline «Falta: nombre» bajo el campo (sin cuadro de
        # diálogo); solo se enseña al guardar vacío y se quita al teclear.
        self._falta_nombre = QLabel("Falta: nombre")
        self._falta_nombre.setStyleSheet("color: #F85149; font-size: 12px;")
        self._falta_nombre.hide()
        self._nombre.textChanged.connect(lambda _texto: self._falta_nombre.hide())
        form.addWidget(self._falta_nombre, len(parejas), 0, 1, 2)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        lay.addLayout(form)
        self.reload_locations()
        return marco

    def _subpestanas(self) -> QTabWidget:
        """Telescopio y Cámara en dos columnas (Principal/Guía), Montura y Filtros."""
        tabs = QTabWidget()
        tabs.addTab(self._columna_doble("telescope", TelescopeForm), "Telescopio")
        tabs.addTab(self._columna_doble("camera", CameraForm), "Cámara")
        tabs.addTab(self._columna_montura(), "Montura")
        tabs.addTab(self._columna_filtros(), "Filtros")
        return tabs

    def _columna_doble(self, kind: str, formularios: type) -> QWidget:
        """Dos ``PartEditor`` del mismo tipo: pieza principal y pieza de guía."""
        contenedor = QWidget()
        fila = QHBoxLayout(contenedor)
        # Márgenes/espaciado propios: el default del contenedor sumaba ~70 px
        # al ancho mínimo de la página y forzaba scroll horizontal.
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(6)
        principal = PartEditor(kind, formularios(), "Principal")
        guia = PartEditor(kind, formularios(), "Guía")
        fila.addWidget(principal)
        fila.addWidget(guia)
        self._editores += [principal, guia]
        if kind == "telescope":
            self._tel_principal, self._tel_guia = principal, guia
        else:
            self._cam_principal, self._cam_guia = principal, guia
        return contenedor

    def _columna_montura(self) -> QWidget:
        """Un único editor de montura (no hay montura de guía)."""
        contenedor = QWidget()
        fila = QHBoxLayout(contenedor)
        montura = PartEditor("mount", MountForm(), "Montura")
        self._montura = montura
        self._editores.append(montura)
        fila.addWidget(montura)
        fila.addStretch(1)
        return contenedor

    def _columna_filtros(self) -> QWidget:
        """Tabla de filtros: casilla de asignación + CRUD de los globales."""
        contenedor = QWidget()
        fila = QHBoxLayout(contenedor)
        self._filtros = FiltersPanel()
        fila.addWidget(self._filtros)
        fila.addStretch(1)
        return contenedor

    def _bloque_calculos(self) -> QFrame:
        """«Cálculos» como barra de una línea: relación focal, focal efectiva, escala, Dawes y muestreo.

        Barra (y no cuadrícula) para que el bloque pese ~60 px menos de
        alto: el formulario entero cabe sin scroll vertical a altura
        maximizada. Aquí viven también las lecturas del telescopio
        (relación focal y focal efectiva) para no duplicarlas en su
        formulario. El orden de las lecturas lo decidió el usuario y los
        rótulos van con dos puntos.
        """
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(12, 4, 12, 6)  # apretados: la ficha cabe sin scroll
        lay.setSpacing(6)
        fila = QHBoxLayout()
        fila.setSpacing(8)
        titulo = QLabel("Cálculos")
        titulo.setObjectName("PanelTitle")
        fila.addWidget(titulo)
        self._escala = QLabel("—")
        self._dawes = QLabel("—")
        self._relacion = QLabel("—")
        self._efectiva = QLabel("—")
        self._muestreo = QLabel("—")
        valores = (
            ("Relación Focal:", self._relacion),
            ("Distancia Focal Efectiva:", self._efectiva),
            ("Escala:", self._escala),
            ("Límite Dawes:", self._dawes),
            ("Muestreo:", self._muestreo),
        )
        for etiqueta, valor in valores:
            fila.addWidget(QLabel(etiqueta))
            fila.addWidget(valor)
        fila.addStretch(1)
        lay.addLayout(fila)
        self._pista_calculos = QLabel(
            "Sobre el telescopio y la cámara principales en pantalla."
        )
        self._pista_calculos.setObjectName("HintLabel")
        self._pista_calculos.setWordWrap(True)
        # Barra de zonas a la izquierda de la pista: el usuario aprobó
        # «Rango adecuado: …» junto a los «Falta:…» y su barra con marcador.
        self._barra = BarraMuestreo()
        fila_pista = QHBoxLayout()
        fila_pista.setSpacing(8)
        fila_pista.addWidget(self._barra)
        fila_pista.addWidget(self._pista_calculos, 1)
        lay.addLayout(fila_pista)
        return marco

    # -- lista y carga -----------------------------------------------------

    def reload_locations(self) -> None:
        """Repuebla el combo de ubicaciones (lo llama ``EquipmentPage``)."""
        actual = self._ubicacion.currentData()
        self._ubicacion.blockSignals(True)
        self._ubicacion.clear()
        self._ubicacion.addItem("(sin ubicación)", None)
        for lugar in localizations.list_locations():
            self._ubicacion.addItem(str(lugar["name"]), lugar["id"])
        self._ubicacion.setCurrentIndex(max(0, self._ubicacion.findData(actual)))
        self._ubicacion.blockSignals(False)
        # El seeing de la ubicación recorta el rango: si cambió (p. ej. al
        # volver de Ubicaciones), recalcular. El primer relleno pasa durante
        # la construcción de la cabecera, cuando los editores aún no existen.
        if self._editores:
            self._recalcular()

    def _seeing_ubicacion(self) -> float | None:
        """Seeing FWHM de la ubicación elegida en la cabecera (None si no hay).

        Se lee de la BD en cada recálculo: la tabla es corta y así un
        cambio en la pestaña Ubicaciones se refleja al instante (sin
        caché que desincronice). «—» o ubicación sin dato → ``None``.
        """
        ubicacion_id = self._ubicacion.currentData()
        if ubicacion_id is None:
            return None
        for lugar in localizations.list_locations():
            if lugar["id"] == ubicacion_id:
                return lugar.get("seeing_arcsec")
        return None

    def _recargar_lista(self, select_id: int | None) -> None:
        """Repuebla la lista y carga ``select_id`` (si no, la primera fila).

        Con la lista vacía se pinta una fila de ayuda no seleccionable
        (afine A): la lista explica qué hacer en vez de dejar un hueco.
        """
        self._cargando = True
        self._lista.clear()
        ids: list[int] = []
        for equipo in manager.list_setups():
            crudo = str(equipo.get("category") or "")
            etiqueta = CATEGORIES.get(crudo, crudo.replace("_", " "))
            # «nombre · categoría · ubicación» (la ubicación, si la hay:
            # location_name viene del LEFT JOIN de list_setups, M-17).
            piezas = [str(equipo["name"]), etiqueta, equipo.get("location_name")]
            texto = " · ".join(pieza for pieza in piezas if pieza)
            item = QListWidgetItem(texto)
            item.setToolTip(texto)
            item.setData(Qt.ItemDataRole.UserRole, equipo["id"])
            self._lista.addItem(item)
            ids.append(equipo["id"])
        if not ids:
            vacio = QListWidgetItem("(sin equipos — pulsa «Nuevo…»)")
            vacio.setFlags(vacio.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._lista.addItem(vacio)
        objetivo = select_id if select_id in ids else (ids[0] if ids else None)
        if objetivo is not None:
            self._lista.setCurrentRow(ids.index(objetivo))
        self._cargando = False
        self._cargar(objetivo)

    def _al_elegir_fila(self, fila: int) -> None:
        """Selección del usuario: carga ese equipo (o la ficha en blanco)."""
        if self._cargando:
            return
        item = self._lista.item(fila)
        self._cargar(item.data(Qt.ItemDataRole.UserRole) if item else None)

    def _cargar(self, setup_id: int | None) -> None:
        """Vierte un equipo de la base en todo el panel (None = en blanco)."""
        self._cargando = True
        try:
            fila = manager.get(setup_id) if setup_id is not None else None
            if fila is None:
                self._setup_id = None
                self._imagenes_setup = []
                self._nombre.clear()
                self._categoria.setCurrentIndex(
                    max(0, self._categoria.findData("general"))
                )
                self._ubicacion.setCurrentIndex(0)
                self._notas.clear()
                for editor in self._editores:
                    editor.cargar(None)
                self._filtros.set_filter_ids([])
            else:
                self._setup_id = fila["id"]
                self._imagenes_setup = [
                    imagen["path"] for imagen in list_images("setup", fila["id"])
                ]
                self._nombre.setText(str(fila.get("name") or ""))
                self._asegurar_categoria(str(fila.get("category") or "general"))
                self._ubicacion.setCurrentIndex(
                    max(0, self._ubicacion.findData(fila.get("location_id")))
                )
                self._notas.setText(str(fila.get("notes") or ""))
                self._tel_principal.cargar(fila.get("telescope_id"))
                self._tel_guia.cargar(fila.get("guide_telescope_id"))
                self._cam_principal.cargar(fila.get("camera_id"))
                self._cam_guia.cargar(fila.get("guide_camera_id"))
                self._montura.cargar(fila.get("mount_id"))
                self._filtros.set_filter_ids(list(fila.get("filter_ids") or []))
        finally:
            self._cargando = False
        self._boton_eliminar.setEnabled(self._setup_id is not None)
        self._recalcular()

    def _asegurar_categoria(self, categoria: str) -> None:
        """Selecciona la categoría en el combo (y la añade si venía de otra BD)."""
        if self._categoria.findData(categoria) == -1:
            self._categoria.addItem(categoria.replace("_", " ").capitalize(), categoria)
        self._categoria.setCurrentIndex(max(0, self._categoria.findData(categoria)))

    # -- acciones ----------------------------------------------------------

    def _nuevo(self) -> None:
        """Alta en memoria: deja la ficha en blanco con el cursor en Nombre.

        Sin diálogo de nombre (afine A): el texto se teclea en la propia
        ficha y nada se persiste hasta «Guardar equipo» (§9).
        """
        self._cargando = True
        self._lista.setCurrentRow(-1)  # ninguna fila seleccionada
        self._cargando = False
        self._setup_id = None
        self._imagenes_setup = []
        self._nombre.clear()
        self._categoria.setCurrentIndex(max(0, self._categoria.findData("general")))
        self._ubicacion.setCurrentIndex(0)
        self._notas.clear()
        for editor in self._editores:
            editor.cargar(None)
        self._filtros.set_filter_ids([])
        self._boton_eliminar.setEnabled(False)
        self._recalcular()
        self._nombre.setFocus()

    def _guardar(self) -> None:
        """Persiste el equipo: create si es nuevo, update si venía de la base.

        Afine A: sin nombre no se persiste nada y la cabecera enseña el
        hint «Falta: nombre» (sin cuadro de diálogo; se quita al teclear).
        El resto de errores de guardado siguen con su aviso modal.
        """
        if not self._nombre.text().strip():
            self._falta_nombre.show()
            self._nombre.setFocus()
            return
        setup = EquipmentSetup(
            id=self._setup_id,
            name=self._nombre.text().strip(),
            category=self._categoria.currentData() or "general",
            location_id=self._ubicacion.currentData(),
            telescope_id=self._tel_principal.selected_id(),
            guide_telescope_id=self._tel_guia.selected_id(),
            camera_id=self._cam_principal.selected_id(),
            guide_camera_id=self._cam_guia.selected_id(),
            mount_id=self._montura.selected_id(),
            filter_ids=self._filtros.filter_ids(),
            price_eur=(self._precio.value() or None),
            weight_kg=(self._peso.value() or None),
            notes=self._notas.text().strip(),
            images=list(self._imagenes_setup),  # D-5: la lista es la verdad
        )
        try:
            if setup.id is None:
                manager.create(setup)
            else:
                manager.update(setup)
        except ValueError as exc:
            QMessageBox.warning(self, "No se pudo guardar", str(exc))
            return
        self._recargar_lista(select_id=setup.id)
        self.setups_changed.emit()

    def _eliminar(self) -> None:
        """Borra el equipo (no sus componentes) tras avisar de sesiones e imágenes."""
        if self._setup_id is None:
            return
        nombre = self._nombre.text().strip() or "este equipo"
        sesiones = manager.count_sessions(self._setup_id)
        imagenes = len(list_images("setup", self._setup_id))
        mensaje = f"¿Eliminar el equipo «{nombre}»?"
        if sesiones:
            mensaje += f"\n\n• {sesiones} sesiones planificadas quedarán desvinculadas."
        if imagenes:
            mensaje += f"\n• Se borrarán {imagenes} imágenes adjuntas."
        mensaje += "\n\nLos componentes no se borran: solo este equipo."
        boton = QMessageBox.StandardButton
        if (
            QMessageBox.question(
                self, "Eliminar equipo", mensaje, boton.Yes | boton.No, boton.No
            )
            != boton.Yes
        ):
            return
        manager.delete(self._setup_id)
        self._recargar_lista(select_id=None)
        self.setups_changed.emit()

    # -- cálculos ----------------------------------------------------------

    def _recalcular(self) -> None:
        """Repinta «Cálculos» con la pareja principal en pantalla (en vivo).

        El seeing de la ubicación elegida en la cabecera recorta el rango
        adecuado y Configuración aporta los dos umbrales y el margen
        «Ligero» de los 5 niveles; sin ubicación o sin dato manda solo
        Dawes.
        """
        telescopio = self._tel_principal.form.a_modelo()
        camara = self._cam_principal.form.a_modelo()
        filas = calculos(
            telescopio,
            camara,
            get_float("sampling_under_ratio", 1.0),
            get_float("sampling_over_ratio", 0.5),
            self._seeing_ubicacion(),
            get_float("sampling_light_factor", 1.4),
        )
        self._escala.setText(_formato(filas["escala"], " ″/px"))
        self._dawes.setText(_formato(filas["dawes"], " ″"))
        self._relacion.setText(
            f"F/{filas['relacion_focal']:.1f}" if filas["relacion_focal"] else "—"
        )
        self._efectiva.setText(_formato(filas["focal_efectiva"], " mm"))
        veredicto = filas["muestreo"]
        self._muestreo.setText(veredicto or "—")
        color = _VEREDICTO_COLOR.get(veredicto) if veredicto else None
        self._muestreo.setStyleSheet(f"color: {color};" if color else "")
        faltan = []
        if telescopio.focal_mm is None:
            faltan.append("focal")
        if camara.pixel_size_um is None:
            faltan.append("píxel de la cámara")
        if telescopio.aperture_mm is None:
            faltan.append("apertura")
        limites = filas["muestreo_limites"]
        piezas = ["Sobre el telescopio y la cámara principales en pantalla."]
        if limites:
            piezas.append(f"Rango adecuado: {limites[1]:.2f}–{limites[2]:.2f} ″/px.")
        if faltan:
            piezas.append(f"Falta: {' · '.join(faltan)}.")
        self._pista_calculos.setText(" ".join(piezas))
        self._barra.pintar(filas["escala"], limites)
        self._repinta_totales()

    def _repinta_totales(self) -> None:
        """Cabecera: precio/peso = suma en vivo de las piezas en pantalla.

        Precio: los 5 formularios + el de cada filtro marcado. Peso: los 5
        formularios + 0,5 kg por cada telescopio con «Aplanador» (su
        tooltip recuerda que cubre aplanador, reductor o coma corrector:
        el accesorio pesa aunque la óptica no informe su peso); los
        filtros no pesan. 0 = nada informado → el spin pinta «—».
        «Guardar equipo» persiste estos totales (D-3).
        """
        modelos = [
            self._tel_principal.form.a_modelo(),
            self._tel_guia.form.a_modelo(),
            self._cam_principal.form.a_modelo(),
            self._cam_guia.form.a_modelo(),
            self._montura.form.a_modelo(),
        ]
        precio = sum(modelo.price_eur or 0.0 for modelo in modelos)
        peso = sum(modelo.weight_kg or 0.0 for modelo in modelos)
        for telescopio in modelos[:2]:
            if telescopio.reducer:
                peso += 0.5
        precio += sum(self._filtros.precios_marcados())
        self._precio.setValue(precio)
        self._peso.setValue(peso)

    def _tras_pieza_guardada(self) -> None:
        """Una pieza cambió en la base: repuebla combos y avisa a la ventana."""
        for editor in self._editores:
            editor.reload()  # conserva su selección y recalcula
        self.setups_changed.emit()
