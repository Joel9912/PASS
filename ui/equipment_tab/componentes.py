"""Formularios de las piezas globales y el selector de componente.

Aquí viven los formularios del equipo (`TelescopeForm`, `CameraForm`,
`MountForm`, `FiltersPanel`) y el selector (`PartPicker`/`PartEditor`) que
combina el combo de piezas globales con sus botones.

Regla de los **dos niveles de guardado** (§9 del plan): las piezas globales
se persisten con «Guardar componente» (create si el formulario venía vacío,
update si venía de la base) y las asignaciones al equipo con «Guardar
equipo» de la cabecera. Cambiar de pieza en el combo sin guardar descarta
lo tecleado: es el «cancelar» de la regla D-5 (nada llega a la BD ni a
`data/` hasta que se pulsa su botón).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from equipment import components, manager
from equipment.images import list_images
from equipment.models import (
    BIT_DEPTHS,
    FILTER_TYPES,
    MOUNT_TYPES,
    OPTICAL_TYPES,
    SUBTYPE_SUGGESTIONS,
    Camera,
    Filter,
    Mount,
    Telescope,
)

#: Ficheros de imagen admitidos para charts/ganancia (solo visuales).
_FILTRO_IMAGENES = "Imágenes (*.png *.jpg *.jpeg *.bmp);;Todos los archivos (*)"

#: Ruta de cada tipo de pieza hacia su CRUD en ``equipment.components`` y su
#: modelo. El mapa vive aquí porque solo lo necesita el cableado del
#: formulario; las funciones del backend son el contrato único.
_PIEZAS: dict[str, dict] = {
    "telescope": {
        "vacio": "(sin telescopio)",
        "nombre": "telescopio",
        "listar": components.list_telescopes,
        "obtener": components.get_telescope,
        "crear": components.create_telescope,
        "actualizar": components.update_telescope,
        "borrar": components.delete_telescope,
        "modelo": Telescope,
    },
    "camera": {
        "vacio": "(sin cámara)",
        "nombre": "cámara",
        "listar": components.list_cameras,
        "obtener": components.get_camera,
        "crear": components.create_camera,
        "actualizar": components.update_camera,
        "borrar": components.delete_camera,
        "modelo": Camera,
    },
    "mount": {
        "vacio": "(sin montura)",
        "nombre": "montura",
        "listar": components.list_mounts,
        "obtener": components.get_mount,
        "crear": components.create_mount,
        "actualizar": components.update_mount,
        "borrar": components.delete_mount,
        "modelo": Mount,
    },
}


class ListaGuardados(QListWidget):
    """Lista de guardados (equipos o ubicaciones) cuyo *sizeHint* no manda.

    `QListWidget` pide de por sí ~192 px de alto; si ese sizeHint
    llegara a la sección de la lista, la fila superior se hincharía y
    empujaría lo que haya debajo (en Equipos, el scroll de la ficha,
    que a 1000×600 solo tiene 12 px de holgura —lo comprueba
    `test_ficha_sin_hint_de_solo_visuales_y_cabe_sin_scroll`—; en
    Ubicaciones, el scroll del sitio). Aquí el alto preferido es fijo y
    pequeño, pero **puede crecer**: la sección le da stretch, así que
    la lista llena lo que sobre y caben ~7 filas en vez de 2.

    Va a 10 pt y con el texto elegido al medio: lo que no quepa se
    corta por el centro con «…» —el texto completo va en el tooltip de
    cada fila— y la barra horizontal, que se comía 12 px, queda
    desactivada. Compartida por `EquiposTab` y `UbicacionesTab`.
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


def _opt_f(spin: QDoubleSpinBox) -> float | None:
    """Valor de un spin con «—» como especial: 0 = no informado → ``None``.

    Ninguna magnitud física de estos formularios admite 0 de verdad
    (apertura, focal, píxel…), así que 0 significa «el usuario no lo sabe»
    y se guarda como NULL, no como un cero inventado.
    """
    valor = spin.value()
    return float(valor) if valor > 0.0 else None


def _opt_i(spin: QSpinBox) -> int | None:
    """Igual que ``_opt_f`` pero para spins de enteros (bits, píxeles)."""
    valor = spin.value()
    return int(valor) if valor > 0 else None


def sin_botones(spin: QAbstractSpinBox) -> None:
    """Quita las flechas de un spin: el usuario teclea el valor tal cual.

    Los valores de estos formularios se copian de la página del producto
    (apertura, focal, precio…): avanzar a pasos de 0,1 es lento y las
    flechas ensanchan el campo, empujando las filas pareadas a forzar
    scroll horizontal. Se aplica a todos los spins de Equipos y
    Ubicaciones.
    """
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)


def spin_precio() -> QDoubleSpinBox:
    """Spin de precio en € (sin flechas; 0 = «—» = no informado).

    Lo usan los formularios de pieza, el diálogo de filtro y la cabecera
    del equipo (ahí, en solo lectura, pintando la suma en vivo).
    """
    spin = QDoubleSpinBox()
    spin.setRange(0.0, 1_000_000.0)
    spin.setDecimals(0)
    spin.setSuffix(" €")
    spin.setSpecialValueText("—")
    sin_botones(spin)
    return spin


def spin_peso() -> QDoubleSpinBox:
    """Spin de peso en kg (sin flechas; 0 = «—» = no informado)."""
    spin = QDoubleSpinBox()
    spin.setRange(0.0, 1000.0)
    spin.setDecimals(1)
    spin.setSuffix(" kg")
    spin.setSpecialValueText("—")
    sin_botones(spin)
    return spin


def _etiqueta_archivo(ruta: str) -> tuple[str, str]:
    """(nombre para la lista, ruta completa para el dato): imagen adjunta."""
    return Path(ruta).name, ruta


def _combo_opciones(combo: QComboBox, opciones: dict[str, str]) -> None:
    """Rellena un combo con «(sin …)» + las opciones del catálogo."""
    combo.addItem("(sin dato)", None)
    for clave, etiqueta in opciones.items():
        combo.addItem(etiqueta, clave)


class _FiltroDialog(QDialog):
    """Alta/edición de un filtro global (nombre, tipo, precio, notas).

    Solo valida en backend al aceptar el llamante: aquí se recogen los
    campos y el ``ValueError`` de `validar_filtro` se enseña en un aviso.
    """

    def __init__(self, parent: QWidget, fila: dict | None = None) -> None:
        """Con vacío para alta, o precargado con ``fila`` para editar."""
        super().__init__(parent)
        self.setWindowTitle("Filtro")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._nombre = QLineEdit(str((fila or {}).get("name") or ""))
        self._nombre.setPlaceholderText("UHC, CLS, Baader…")
        form.addRow("Nombre", self._nombre)
        self._tipo = QComboBox()
        _combo_opciones(self._tipo, FILTER_TYPES)
        tipo = (fila or {}).get("filter_type")
        if tipo:
            self._tipo.setCurrentIndex(max(0, self._tipo.findData(tipo)))
        form.addRow("Tipo", self._tipo)
        self._precio = spin_precio()
        self._precio.setValue(float((fila or {}).get("price_eur") or 0.0))
        form.addRow("Precio", self._precio)
        self._notas = QLineEdit(str((fila or {}).get("notes") or ""))
        form.addRow("Notas", self._notas)
        layout.addLayout(form)
        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

    def filtro(self, filter_id: int | None = None) -> Filter:
        """Modelo del diálogo (el id solo lo pone quien ya tiene filtro)."""
        return Filter(
            id=filter_id,
            name=self._nombre.text().strip(),
            filter_type=self._tipo.currentData(),
            price_eur=_opt_f(self._precio),
            notes=self._notas.text().strip(),
        )


class FiltersPanel(QFrame):
    """Filtros globales: tabla con la casilla «lo lleva este equipo» + CRUD.

    La casilla es una **asignación en memoria** del equipo que se está
    editando (la persiste «Guardar equipo»); «Nuevo filtro…», «Editar» y
    «Eliminar» tocan los filtros **globales** al momento (su propio nivel de
    guardado) y al eliminar, ``count_setups_using('filter', id)`` avisa de
    los equipos afectados antes de confirmar.
    """

    changed = pyqtSignal()  # cambió una casilla → asignación pendiente
    saved = pyqtSignal()    # filtro global persistido → refrescar combos/listas

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta la tabla de filtros y sus botones de CRUD."""
        super().__init__(parent)
        self.setObjectName("GroupFrame")
        self._marcados: set[int] = set()
        self._cargando = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 10)
        layout.setSpacing(8)
        titulo = QLabel("Filtros")
        titulo.setObjectName("PanelTitle")
        layout.addWidget(titulo)

        self._tabla = QTableWidget(0, 4)
        self._tabla.setHorizontalHeaderLabels(
            ["Filtro", "Tipo", "Precio", "Lo lleva este equipo"]
        )
        self._tabla.verticalHeader().setVisible(False)
        self._tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tabla.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._tabla)

        botones = QHBoxLayout()
        boton_nuevo = QPushButton("➕ Nuevo filtro…")
        boton_nuevo.clicked.connect(self._nuevo)
        botones.addWidget(boton_nuevo)
        boton_editar = QPushButton("Editar")
        boton_editar.clicked.connect(self._editar)
        botones.addWidget(boton_editar)
        boton_eliminar = QPushButton("Eliminar")
        boton_eliminar.clicked.connect(self._eliminar)
        botones.addWidget(boton_eliminar)
        botones.addStretch(1)
        layout.addLayout(botones)

        ayuda = QLabel(
            "La casilla asigna el filtro a este equipo (se guarda con el equipo); "
            "los botones de abajo guardan el filtro global al momento."
        )
        ayuda.setObjectName("HintLabel")
        ayuda.setWordWrap(True)
        layout.addWidget(ayuda)
        self.reload()

    # -- asignación en memoria (equipo en edición) ------------------------

    def filter_ids(self) -> list[int]:
        """Ids de los filtros marcados (los pinta «Guardar equipo»)."""
        return sorted(self._marcados)

    def precios_marcados(self) -> list[float]:
        """Precio de cada filtro marcado (lo suma la cabecera del equipo)."""
        return [
            float(filtro["price_eur"])
            for filtro in components.list_filters()
            if filtro["id"] in self._marcados and filtro.get("price_eur")
        ]

    def set_filter_ids(self, ids: list[int]) -> None:
        """Marca los filtros de ``ids`` sin emitir (carga de un equipo)."""
        self._marcados = set(ids)
        self._pintar_casillas()

    # -- CRUD global -------------------------------------------------------

    def reload(self) -> None:
        """Vuelve a leer los filtros de la base preservando las casillas."""
        filas = components.list_filters()
        self._cargando = True
        self._tabla.setRowCount(len(filas))
        for fila_id, filtro in enumerate(filas):
            self._tabla.setItem(
                fila_id, 0, QTableWidgetItem(str(filtro["name"]))
            )
            tipo = FILTER_TYPES.get(str(filtro.get("filter_type") or ""), "—")
            self._tabla.setItem(fila_id, 1, QTableWidgetItem(tipo))
            precio = filtro.get("price_eur")
            self._tabla.setItem(
                fila_id, 2,
                QTableWidgetItem(f"{float(precio):.0f} €" if precio else "—"),
            )
            # Casilla real (cellWidget): con NoEditTriggers un item no
            # alterna, y aquí sí tiene que alternar.
            casilla = QCheckBox()
            casilla.setChecked(filtro["id"] in self._marcados)
            casilla.toggled.connect(
                lambda marcado, fid=filtro["id"]: self._casilla(fid, marcado)
            )
            # Marcar una casilla también pone la fila al frente: si no,
            # «Eliminar»/«Editar» actuarían sobre la fila que estaba antes.
            casilla.clicked.connect(
                lambda _c=False, r=fila_id: self._tabla.setCurrentCell(r, 0)
            )
            contenedor = QWidget()
            fila_casilla = QHBoxLayout(contenedor)
            fila_casilla.setContentsMargins(8, 0, 0, 0)
            fila_casilla.addWidget(casilla)
            fila_casilla.addStretch(1)
            self._tabla.setCellWidget(fila_id, 3, contenedor)
            marcador = QTableWidgetItem()
            marcador.setData(Qt.ItemDataRole.UserRole, filtro["id"])
            self._tabla.setItem(fila_id, 3, marcador)
        self._cargando = False

    def _pintar_casillas(self) -> None:
        """Refresca las casillas de la columna «Lo lleva este equipo»."""
        self._cargando = True
        for fila in range(self._tabla.rowCount()):
            contenedor = self._tabla.cellWidget(fila, 3)
            item = self._tabla.item(fila, 3)
            if contenedor is None or item is None:
                continue
            casilla = contenedor.findChild(QCheckBox)
            if casilla is not None:
                casilla.setChecked(item.data(Qt.ItemDataRole.UserRole) in self._marcados)
        self._cargando = False

    def _casilla(self, filtro_id: int, marcado: bool) -> None:
        """Guarda o descarta el filtro en memoria al alternar su casilla."""
        if self._cargando:
            return
        if marcado:
            self._marcados.add(filtro_id)
        else:
            self._marcados.discard(filtro_id)
        self.changed.emit()

    def _id_seleccionado(self) -> int | None:
        """Id del filtro de la fila seleccionada (None si no hay fila)."""
        fila = self._tabla.currentRow()
        if fila < 0 or self._tabla.item(fila, 3) is None:
            return None
        return self._tabla.item(fila, 3).data(Qt.ItemDataRole.UserRole)

    def _nuevo(self) -> None:
        """Alta inmediata del filtro global (su propio «Guardar»)."""
        dialogo = _FiltroDialog(self)
        if not dialogo.exec():
            return
        try:
            components.create_filter(dialogo.filtro())
        except ValueError as exc:
            QMessageBox.warning(self, "No se pudo guardar", str(exc))
            return
        self.reload()
        self.saved.emit()

    def _editar(self) -> None:
        """Edita la fila seleccionada y guarda el filtro global al instante."""
        filtro_id = self._id_seleccionado()
        if filtro_id is None:
            return
        fila = components.get_filter(filtro_id)
        if fila is None:
            return
        dialogo = _FiltroDialog(self, fila)
        if not dialogo.exec():
            return
        try:
            components.update_filter(dialogo.filtro(filtro_id))
        except ValueError as exc:
            QMessageBox.warning(self, "No se pudo guardar", str(exc))
            return
        self.reload()
        self.saved.emit()

    def _eliminar(self) -> None:
        """Borra el filtro global tras avisar con ``count_setups_using``."""
        filtro_id = self._id_seleccionado()
        if filtro_id is None:
            return
        nombre = self._tabla.item(self._tabla.currentRow(), 0).text()
        afectados = manager.count_setups_using("filter", filtro_id)
        mensaje = f"¿Eliminar el filtro «{nombre}»?"
        if afectados:
            mensaje += f"\n\nLo usan {afectados} equipos: quedarán sin ese filtro."
        boton = QMessageBox.StandardButton
        if (
            QMessageBox.question(
                self, "Eliminar filtro", mensaje, boton.Yes | boton.No, boton.No
            )
            != boton.Yes
        ):
            return
        components.delete_filter(filtro_id)
        self._marcados.discard(filtro_id)
        self.reload()
        self.saved.emit()


class PartPicker(QFrame):
    """Combo de una pieza global + sus botones: «Nuevo…», «Guardar componente», «Eliminar».

    Solo gestiona la selección y el ciclo de vida de la pieza elegida; el
    formulario lo apila debajo el ``PartEditor``. «Nuevo» deja el formulario
    en blanco: la pieza recién existe en la base tras «Guardar componente».
    """

    nuevo_solicitado = pyqtSignal()
    guardar_solicitado = pyqtSignal()
    eliminar_solicitado = pyqtSignal()
    seleccion_cambiada = pyqtSignal()  # cambio hecho por el usuario

    def __init__(
        self, kind: str, titulo: str | None = None, parent: QWidget | None = None
    ) -> None:
        """``kind`` es la clave de ``_PIEZAS``; ``titulo`` etiqueta la columna."""
        super().__init__(parent)
        self._pieza = _PIEZAS[kind]

        # Dos filas (combo arriba, botones abajo): en una sola el ancho
        # mínimo de los 3 botones + combo forzaba scroll horizontal con las
        # columnas Principal/Guía lado a lado.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._combo = QComboBox()
        self._combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self._combo.currentIndexChanged.connect(self._tras_cambio)
        # El título de la columna va en la fila del combo (antes fila
        # propia): ahorra 35 px de alto por editor sin perderlo.
        fila_combo = QHBoxLayout()
        fila_combo.setSpacing(6)
        if titulo:
            etiqueta = QLabel(titulo)
            etiqueta.setObjectName("PanelTitle")
            fila_combo.addWidget(etiqueta)
        fila_combo.addWidget(self._combo, 1)
        layout.addLayout(fila_combo)

        botones = QHBoxLayout()
        botones.setSpacing(6)
        boton_nuevo = QPushButton("Nuevo…")
        boton_nuevo.clicked.connect(self.nuevo_solicitado)
        botones.addWidget(boton_nuevo)
        boton_guardar = QPushButton("Guardar componente")
        boton_guardar.clicked.connect(self.guardar_solicitado)
        botones.addWidget(boton_guardar)
        self._boton_eliminar = QPushButton("Eliminar")
        self._boton_eliminar.clicked.connect(self.eliminar_solicitado)
        botones.addWidget(self._boton_eliminar)
        botones.addStretch(1)
        layout.addLayout(botones)
        self.reload()

    def selected_id(self) -> int | None:
        """Id de la pieza seleccionada (None = «(sin …)» o lista vacía)."""
        return self._combo.currentData()

    def _tras_cambio(self, _indice: int) -> None:
        """Tras un cambio (del usuario o de recarga): «Eliminar» y aviso."""
        self._boton_eliminar.setEnabled(self._combo.currentData() is not None)
        self.seleccion_cambiada.emit()

    def selected_name(self) -> str:
        """Texto visible de la selección (para los mensajes de borrado)."""
        return self._combo.currentText()

    def reload(self, select_id: int | None = None) -> None:
        """Repuebla el combo desde la base y selecciona ``select_id``.

        Se hacen señales bloqueadas: la recarga es programática (quien la
        pide ya sabe qué formulario debe quedar en pantalla).
        """
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItem(self._pieza["vacio"], None)
        for fila in self._pieza["listar"]():
            self._combo.addItem(str(fila["name"]), fila["id"])
        self._combo.setCurrentIndex(max(0, self._combo.findData(select_id)))
        self._combo.blockSignals(False)
        self._boton_eliminar.setEnabled(self._combo.currentData() is not None)


class PartEditor(QWidget):
    """Columna «selector + formulario» de una pieza global (principal o guía).

    Los dos botones de ``PartPicker`` dejan su alcance a la vista (§9):
    «Guardar componente» persiste lo del formulario (create/update) y
    «Eliminar» borra la pieza tras avisar con ``count_setups_using``; las
    asignaciones al equipo las decide «Guardar equipo» en la cabecera.
    Recargar el combo con una pieza distinta descarta lo no guardado en el
    formulario: cancelar nunca toca la base (D-5).
    """

    changed = pyqtSignal()  # formulario/selección cambiaron → bloque Cálculos
    saved = pyqtSignal()    # pieza persistida → setups_changed y combos

    def __init__(
        self, kind: str, form: QWidget, titulo: str, parent: QWidget | None = None
    ) -> None:
        """Apila el picker de ``kind`` (con su ``titulo`` de columna) y su formulario."""
        super().__init__(parent)
        self.setObjectName("GroupFrame")
        self._kind = kind
        self._pieza = _PIEZAS[kind]
        self.form = form

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 10)
        layout.setSpacing(8)
        self.picker = PartPicker(kind, titulo)
        layout.addWidget(self.picker)
        layout.addWidget(form)

        self.picker.seleccion_cambiada.connect(self._cargar_formulario)
        self.picker.nuevo_solicitado.connect(self._nuevo)
        self.picker.guardar_solicitado.connect(self._guardar)
        self.picker.eliminar_solicitado.connect(self._eliminar)
        self.form.changed.connect(self.changed)

    # -- API para EquiposTab ----------------------------------------------

    def selected_id(self) -> int | None:
        """Pieza seleccionada = asignación que «Guardar equipo» escribirá."""
        return self.picker.selected_id()

    def cargar(self, pieza_id: int | None) -> None:
        """Selección programática (al cargar un equipo): combo + formulario."""
        self.picker.reload(select_id=pieza_id)
        self._cargar_formulario()

    def reload(self) -> None:
        """Repuebla el combo preservando la selección (tras crear en otro editor)."""
        self.picker.reload(select_id=self.picker.selected_id())
        self.changed.emit()

    # -- cableado interno --------------------------------------------------

    def _cargar_formulario(self) -> None:
        """Vierte la pieza seleccionada (o el vacío) en el formulario."""
        pieza_id = self.picker.selected_id()
        fila = self._pieza["obtener"](pieza_id) if pieza_id is not None else None
        self.form.cargar(fila)

    def _nuevo(self) -> None:
        """Formulario en blanco para crear una pieza nueva (sin id)."""
        self.picker.reload(select_id=None)
        self.form.limpiar()
        self.changed.emit()

    def _guardar(self) -> None:
        """Persiste el formulario: create si no venía de la base, update si sí."""
        try:
            modelo = self.form.a_modelo()
            if modelo.id is None:
                nuevo_id = self._pieza["crear"](modelo)
            else:
                self._pieza["actualizar"](modelo)
                nuevo_id = modelo.id
        except ValueError as exc:
            QMessageBox.warning(self, "No se pudo guardar", str(exc))
            return
        self.cargar(nuevo_id)  # releer de la base: ids y valores canónicos
        self.saved.emit()
        self.changed.emit()

    def _eliminar(self) -> None:
        """Borra la pieza global tras avisar del número de equipos afectados."""
        pieza_id = self.picker.selected_id()
        if pieza_id is None:
            return
        nombre = self.picker.selected_name()
        afectados = manager.count_setups_using(self._kind, pieza_id)
        mensaje = f"¿Eliminar el {self._pieza['nombre']} «{nombre}»?"
        if afectados:
            mensaje += (
                f"\n\nLo usan {afectados} equipos: quedarán sin esta pieza"
                " (los equipos no se borran)."
            )
        boton = QMessageBox.StandardButton
        if (
            QMessageBox.question(
                self, "Eliminar componente", mensaje, boton.Yes | boton.No, boton.No
            )
            != boton.Yes
        ):
            return
        self._pieza["borrar"](pieza_id)
        self.picker.reload()
        self.form.limpiar()
        self.saved.emit()
        self.changed.emit()


class _ImagenesMixin:
    """Fila «Imágenes» y sus 4 métodos, idénticos en TelescopeForm y CameraForm (A-09).

    La clase anfitriona crea ``self._imagenes`` con ``_montar_fila_imagenes``
    y expone la señal ``changed`` (de su propia clase); el mixin solo añade
    y quita filas en memoria — la persistencia sigue siendo del formulario.
    """

    #: Título del diálogo «Adjuntar…» (lo fija cada formulario).
    _TITULO_ADJUNTAR = "Seleccionar imágenes"

    def _montar_fila_imagenes(self, rejilla: QGridLayout, fila: int) -> None:
        """Coloca la fila «Imágenes» en ``rejilla`` y crea ``self._imagenes``.

        La lista va en la columna de campos 1 y los dos botones en paralelo
        en la 2-3 (apilados sumaban 56 px de fila).
        """
        self._imagenes = QListWidget()
        self._imagenes.setMaximumHeight(44)  # 1,5 filas: el alto sobra menos que el ancho
        rejilla.addWidget(QLabel("Imágenes"), fila, 0)
        rejilla.addWidget(self._imagenes, fila, 1)
        botones = QHBoxLayout()
        botones.setSpacing(6)
        boton_anadir = QPushButton("➕ Adjuntar…")
        boton_anadir.clicked.connect(self._anadir_imagenes)
        botones.addWidget(boton_anadir)
        boton_quitar = QPushButton("Quitar")
        boton_quitar.clicked.connect(self._quitar_imagenes)
        botones.addWidget(boton_quitar)
        rejilla.addLayout(botones, fila, 2, 1, 2)

    def _anadir_imagenes(self) -> None:
        """Adjunta imágenes nuevas a la lista en memoria (sin tocar la base)."""
        rutas, _ = QFileDialog.getOpenFileNames(
            self, self._TITULO_ADJUNTAR, "", _FILTRO_IMAGENES
        )
        for ruta in rutas:
            self._anadir_fila(ruta)
        if rutas:
            self.changed.emit()

    def _quitar_imagenes(self) -> None:
        """Quita de la lista lo seleccionado (la base se toca al guardar)."""
        for item in self._imagenes.selectedItems():
            self._imagenes.takeItem(self._imagenes.row(item))
        self.changed.emit()

    def _anadir_fila(self, ruta: str) -> None:
        """Añade la ruta si no estaba ya (nombre visible, ruta en el dato)."""
        if ruta in self._rutas():
            return
        nombre, ruta = _etiqueta_archivo(ruta)
        item = QListWidgetItem(nombre)
        item.setData(Qt.ItemDataRole.UserRole, ruta)
        item.setToolTip(ruta)
        self._imagenes.addItem(item)

    def _rutas(self) -> list[str]:
        """Rutas completas de las imágenes listadas (su verdad en memoria)."""
        return [
            self._imagenes.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._imagenes.count())
        ]


class TelescopeForm(_ImagenesMixin, QFrame):
    """Formulario de una óptica: rejilla de 4 columnas, reductor e imágenes.

    Los datos van en **una sola `QGridLayout` como la cabecera de Equipo**
    —etiquetas en las columnas 0 y 2, campos en la 1 y la 3, ambas con
    stretch—: así todas las cajas arrancan en la misma `x` y miden lo
    mismo, que era lo que faltaba con las filas sueltas (cada `QHBoxLayout`
    calculaba su propio ancho y las etiquetas de distinto tamaño
    descolocaban las cajas). Van de dos en dos (Precio·Peso,
    Apertura·Focal, casilla·Factor, Tipo·Subtipo), una fila más que antes:
    para no ganar alto la rejilla va a 4 px de espaciado vertical y la
    lista de Imágenes baja de 56 a 44 px (la ficha ha de seguir cabiendo
    sin scroll vertical a 1000×600).
    """

    changed = pyqtSignal()

    #: Título del diálogo «Adjuntar…»: aquí se adjuntan charts.
    _TITULO_ADJUNTAR = "Seleccionar charts"

    def __init__(self, parent: QWidget | None = None) -> None:
        """Campos del telescopio + lecturas vivas y la lista de charts."""
        super().__init__(parent)
        self._id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Rejilla de 4 columnas como la cabecera de Equipo: etiquetas en
        # la 0 y la 2, campos en la 1 y la 3 con stretch. Sin ancho
        # máximo en ningún spin: las columnas reparten el sobrante y
        # todas las cajas del mismo campo miden y empiezan igual.
        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(12)  # como Equipo
        rejilla.setVerticalSpacing(4)  # 6 no cabe: la rejilla gana una fila

        self._nombre = QLineEdit()
        self._nombre.setPlaceholderText("ED80, Newton 200…")
        rejilla.addWidget(QLabel("Nombre"), 0, 0)
        rejilla.addWidget(self._nombre, 0, 1, 1, 3)

        # Precio y peso en pareja, sin flechas: la cabecera del equipo
        # los suma en vivo.
        self._precio = spin_precio()
        self._peso = spin_peso()
        rejilla.addWidget(QLabel("Precio"), 1, 0)
        rejilla.addWidget(self._precio, 1, 1)
        rejilla.addWidget(QLabel("Peso"), 1, 2)
        rejilla.addWidget(self._peso, 1, 3)

        # Apertura y focal en pareja y sin flechas: el usuario teclea el
        # valor de la ficha técnica (rangos los que fijó él: 5000 y
        # 20000 mm). Relación focal y focal efectiva no se duplican aquí:
        # viven en la barra «Cálculos», siempre visible bajo las pestañas.
        self._apertura = QDoubleSpinBox()
        self._apertura.setRange(0.0, 5000.0)
        self._apertura.setDecimals(1)
        self._apertura.setSuffix(" mm")
        self._apertura.setSpecialValueText("—")
        sin_botones(self._apertura)
        self._focal = QDoubleSpinBox()
        self._focal.setRange(0.0, 20000.0)
        self._focal.setDecimals(1)
        self._focal.setSuffix(" mm")
        self._focal.setSpecialValueText("—")
        sin_botones(self._focal)
        rejilla.addWidget(QLabel("Apertura"), 2, 0)
        rejilla.addWidget(self._apertura, 2, 1)
        rejilla.addWidget(QLabel("Focal"), 2, 2)
        rejilla.addWidget(self._focal, 2, 3)

        # La casilla ocupa las columnas 0 y 1 (comparte la de los
        # campos, así su texto largo no ensancha ninguna fila) y
        # «Factor ×» va en la 2, delante de su caja como el resto de
        # etiquetas. El detalle —aplanador, reductor o coma corrector—
        # está en el tooltip.
        self._reductor = QCheckBox("Aplanador/Reductor/Coma")
        self._reductor.setToolTip(
            "Focal efectiva = focal × factor: vale para aplanador, "
            "reductor o coma corrector."
        )
        self._factor = QDoubleSpinBox()
        self._factor.setRange(0.01, 10.00)
        self._factor.setDecimals(2)
        self._factor.setSingleStep(0.05)
        self._factor.setValue(1.0)
        self._factor.setEnabled(False)
        sin_botones(self._factor)
        rejilla.addWidget(self._reductor, 3, 0, 1, 2)
        rejilla.addWidget(QLabel("Factor ×"), 3, 2)
        rejilla.addWidget(self._factor, 3, 3)

        self._tipo = QComboBox()
        _combo_opciones(self._tipo, OPTICAL_TYPES)
        self._subtipo = QComboBox()  # solo seleccionable (taxonomía por tipo)
        self._subtipo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        rejilla.addWidget(QLabel("Tipo"), 4, 0)
        rejilla.addWidget(self._tipo, 4, 1)
        rejilla.addWidget(QLabel("Subtipo"), 4, 2)
        rejilla.addWidget(self._subtipo, 4, 3)

        self._notas = QLineEdit()
        self._notas.setPlaceholderText("Notas (opcional)")
        rejilla.addWidget(self._notas, 5, 0, 1, 4)

        # Imágenes: la lista en la columna de campos 1 y los dos botones
        # en paralelo en la 2-3 (patrón del mixin, A-09).
        self._montar_fila_imagenes(rejilla, 6)

        rejilla.setColumnStretch(1, 1)
        rejilla.setColumnStretch(3, 1)
        layout.addLayout(rejilla)
        layout.addStretch(1)

        self._tipo.currentIndexChanged.connect(self._subtipos)
        self._subtipos()
        self._conectar_cambios()

    # -- protocolo de formulario (PartEditor) ------------------------------

    def limpiar(self) -> None:
        """Vacía el formulario para una óptica nueva (id = None)."""
        self._id = None
        self._nombre.clear()
        self._apertura.setValue(0.0)
        self._focal.setValue(0.0)
        self._precio.setValue(0.0)
        self._peso.setValue(0.0)
        self._reductor.setChecked(False)
        # 1,00 igual que el arranque: es el valor neutro (focal efectiva
        # = focal). Con 0,80 «Nuevo…» enseñaba un factor que nadie había
        # pedido y tu 1,00 no se veía nunca en pantalla.
        self._factor.setValue(1.0)
        self._tipo.setCurrentIndex(0)
        self._subtipo.setCurrentIndex(-1)
        self._notas.clear()
        self._imagenes.clear()

    def cargar(self, fila: dict | None) -> None:
        """Vierte una fila de la base (o ``None`` = vacío) en el formulario."""
        self.limpiar()
        if fila is None:
            return
        self._id = fila.get("id")
        self._nombre.setText(str(fila.get("name") or ""))
        self._apertura.setValue(float(fila.get("aperture_mm") or 0.0))
        self._focal.setValue(float(fila.get("focal_mm") or 0.0))
        self._precio.setValue(float(fila.get("price_eur") or 0.0))
        self._peso.setValue(float(fila.get("weight_kg") or 0.0))
        self._reductor.setChecked(bool(fila.get("reducer")))
        factor = fila.get("reducer_factor")
        if factor:
            self._factor.setValue(float(factor))
        indice = self._tipo.findData(fila.get("optical_type"))
        self._tipo.setCurrentIndex(max(0, indice) if fila.get("optical_type") else 0)
        self._subtipos()
        if fila.get("subtype"):
            self._asegurar_subtipo(str(fila["subtype"]))
        self._notas.setText(str(fila.get("notes") or ""))
        for imagen in list_images("telescope", int(fila["id"])):
            self._anadir_fila(imagen["path"])

    def a_modelo(self) -> Telescope:
        """Modelo con lo que hay en pantalla (el id marca create vs update)."""
        return Telescope(
            id=self._id,
            name=self._nombre.text().strip(),
            aperture_mm=_opt_f(self._apertura),
            focal_mm=_opt_f(self._focal),
            optical_type=self._tipo.currentData(),
            subtype=self._subtipo.currentText().strip() or None,
            reducer=self._reductor.isChecked(),
            reducer_factor=_opt_f(self._factor) if self._reductor.isChecked() else None,
            price_eur=_opt_f(self._precio),
            weight_kg=_opt_f(self._peso),
            notes=self._notas.text().strip(),
            images=self._rutas(),
        )

    # -- lecturas vivas ----------------------------------------------------

    def _subtipos(self) -> None:
        """Repuebla el combo con los subtipos del tipo elegido (solo selección).

        Al cambiar de Tipo se selecciona el **primer subtipo** del nuevo
        tipo: el combo no arrastra el valor del tipo anterior (aunque fuera
        ajeno a la lista). Conservar un subtipo guardado que no está en la
        taxonomía es cosa de `cargar`, que lo restaura **después** de
        repueblar.
        """
        claves = self._tipo.currentData() or "otro"
        self._subtipo.clear()
        self._subtipo.addItems(SUBTYPE_SUGGESTIONS.get(claves, ()))
        if self._subtipo.count():
            self._subtipo.setCurrentIndex(0)

    def _asegurar_subtipo(self, subtipo: str) -> None:
        """Selecciona ``subtipo`` en el combo (y lo añade si venía de otra BD)."""
        if self._subtipo.findText(subtipo) == -1:
            self._subtipo.addItem(subtipo)
        self._subtipo.setCurrentText(subtipo)

    def _conectar_cambios(self) -> None:
        """Cualquier toque al formulario emite ``changed`` (para «Cálculos»)."""
        def toque() -> None:
            self.changed.emit()

        for widget in (self._nombre, self._apertura, self._focal, self._notas):
            widget.textChanged.connect(lambda _t: toque())
        for widget in (self._apertura, self._focal, self._precio, self._peso,
                       self._factor):
            widget.valueChanged.connect(lambda _v: toque())
        self._reductor.toggled.connect(lambda _c: toque())
        self._tipo.currentIndexChanged.connect(lambda _i: toque())
        self._subtipo.currentTextChanged.connect(lambda _t: toque())
        self._factor.setEnabled(self._reductor.isChecked())
        self._reductor.toggled.connect(self._factor.setEnabled)


class CameraForm(_ImagenesMixin, QFrame):
    """Formulario de una cámara: rejilla de 4 columnas, sensor e imágenes.

    Misma rejilla que `TelescopeForm` y que la cabecera de Equipo —etiquetas
    en las columnas 0 y 2, campos en la 1 y la 3, ambas con stretch— para
    que todas las cajas arrancen en la misma `x` y midan lo mismo (~218 px
    en columna de 628, como las ~235 de las filas sueltas que había antes).

    «Resolución» va en **su propia fila** justo debajo de Ancho·Alto: meter
    las tres parejas del sensor en una sola fila obligaría a la rejilla a
    tener 6 columnas (Ancho·Alto·Resolución), las columnas de más le
    roban ancho a todas las filas y las cajas bajaban a 161 px. El
    espaciado vertical va a 4 px y la lista de Imágenes baja de 56 a 44 px
    como en Telescopio (el alto sobra menos que el ancho).
    """

    changed = pyqtSignal()

    #: Título del diálogo «Adjuntar…»: aquí se adjuntan curvas de ganancia.
    _TITULO_ADJUNTAR = "Seleccionar curvas de ganancia"

    def __init__(self, parent: QWidget | None = None) -> None:
        """Campos de la cámara + la lectura derivada de resolución."""
        super().__init__(parent)
        self._id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(12)  # como la cabecera de Equipo
        rejilla.setVerticalSpacing(4)

        self._nombre = QLineEdit()
        self._nombre.setPlaceholderText("ASI2600MC…")
        rejilla.addWidget(QLabel("Nombre"), 0, 0)
        rejilla.addWidget(self._nombre, 0, 1, 1, 3)

        # Precio y peso de la pieza en pareja, tras el Nombre (mismo patrón
        # que el telescopio): la cabecera del equipo los suma en vivo.
        self._precio = spin_precio()
        self._peso = spin_peso()
        rejilla.addWidget(QLabel("Precio"), 1, 0)
        rejilla.addWidget(self._precio, 1, 1)
        rejilla.addWidget(QLabel("Peso"), 1, 2)
        rejilla.addWidget(self._peso, 1, 3)

        # Píxel y profundidad en pareja: el usuario pidió «Tam. Píxel (µm)»
        # y «Bits» en la misma fila (los nombres largos no caben a dos
        # columnas con la fuente de 13pt); la profundidad se elige del
        # catálogo BIT_DEPTHS (10/12/14/16): no hay nada que teclear.
        self._pixel = QDoubleSpinBox()
        self._pixel.setRange(0.0, 100.0)
        self._pixel.setDecimals(3)
        self._pixel.setSpecialValueText("—")
        self._pixel.setToolTip("Tamaño de píxel del sensor, en micras.")
        sin_botones(self._pixel)
        self._bits = QComboBox()
        self._bits.addItem("—", None)
        for bits in BIT_DEPTHS:
            self._bits.addItem(str(bits), bits)
        self._bits.setToolTip("Profundidad en bits: solo existen 10, 12, 14 y 16.")
        rejilla.addWidget(QLabel("Tam. Píxel (µm)"), 2, 0)
        rejilla.addWidget(self._pixel, 2, 1)
        rejilla.addWidget(QLabel("Bits"), 2, 2)
        rejilla.addWidget(self._bits, 2, 3)

        # Ancho y alto sin flechas, en pareja…
        self._ancho = QSpinBox()
        self._ancho.setRange(0, 30000)
        self._ancho.setSpecialValueText("—")
        sin_botones(self._ancho)
        self._alto = QSpinBox()
        self._alto.setRange(0, 30000)
        self._alto.setSpecialValueText("—")
        sin_botones(self._alto)
        rejilla.addWidget(QLabel("Ancho"), 3, 0)
        rejilla.addWidget(self._ancho, 3, 1)
        rejilla.addWidget(QLabel("Alto"), 3, 2)
        rejilla.addWidget(self._alto, 3, 3)

        # …y la resolución derivada de los dos, en la fila de abajo
        # (regresión: en pareja con ellos forzaba 6 columnas y estrechaba
        # todas las cajas de la rejilla).
        rejilla.addWidget(QLabel("Resolución"), 4, 0)
        self._resolucion = QLabel("—")
        rejilla.addWidget(self._resolucion, 4, 1)

        # Casillas en fila propia (abarcando las 4 columnas): juntas con
        # la resolución sumaban 835 px de mínimo y forzaban scroll
        # horizontal.
        casillas = QHBoxLayout()
        casillas.setSpacing(12)
        self._refrigerada = QCheckBox("Refrigerada")
        casillas.addWidget(self._refrigerada)
        self._mono = QCheckBox("Monocromática")
        casillas.addWidget(self._mono)
        self._ampglow = QCheckBox("Amp glow")
        casillas.addWidget(self._ampglow)
        casillas.addStretch(1)
        rejilla.addLayout(casillas, 5, 0, 1, 4)

        self._notas = QLineEdit()
        self._notas.setPlaceholderText("Notas (opcional)")
        rejilla.addWidget(self._notas, 6, 0, 1, 4)

        # Imágenes: la lista en la columna de campos 1 y los dos botones
        # en paralelo en la 2-3 (patrón del mixin, A-09).
        self._montar_fila_imagenes(rejilla, 7)

        rejilla.setColumnStretch(1, 1)
        rejilla.setColumnStretch(3, 1)
        layout.addLayout(rejilla)
        layout.addStretch(1)

        self._conectar_cambios()

    # -- protocolo de formulario ------------------------------------------

    def limpiar(self) -> None:
        """Vacía el formulario para una cámara nueva (id = None)."""
        self._id = None
        self._nombre.clear()
        self._pixel.setValue(0.0)
        self._precio.setValue(0.0)
        self._peso.setValue(0.0)
        self._bits.setCurrentIndex(0)
        self._ancho.setValue(0)
        self._alto.setValue(0)
        self._refrigerada.setChecked(False)
        self._mono.setChecked(False)
        self._ampglow.setChecked(False)
        self._notas.clear()
        self._imagenes.clear()
        self._recalcular()

    def cargar(self, fila: dict | None) -> None:
        """Vierte una fila de la base (o ``None`` = vacío) en el formulario."""
        self.limpiar()
        if fila is None:
            return
        self._id = fila.get("id")
        self._nombre.setText(str(fila.get("name") or ""))
        self._pixel.setValue(float(fila.get("pixel_size_um") or 0.0))
        self._precio.setValue(float(fila.get("price_eur") or 0.0))
        self._peso.setValue(float(fila.get("weight_kg") or 0.0))
        bits = fila.get("bit_depth")
        indice = self._bits.findData(int(bits)) if bits else -1
        self._bits.setCurrentIndex(max(0, indice))
        self._ancho.setValue(int(fila.get("width_px") or 0))
        self._alto.setValue(int(fila.get("height_px") or 0))
        self._refrigerada.setChecked(bool(fila.get("cooled")))
        self._mono.setChecked(bool(fila.get("mono")))
        self._ampglow.setChecked(bool(fila.get("ampglow")))
        self._notas.setText(str(fila.get("notes") or ""))
        for imagen in list_images("camera", int(fila["id"])):
            self._anadir_fila(imagen["path"])

    def a_modelo(self) -> Camera:
        """Modelo con lo que hay en pantalla (el id marca create vs update)."""
        return Camera(
            id=self._id,
            name=self._nombre.text().strip(),
            cooled=self._refrigerada.isChecked(),
            bit_depth=self._bits.currentData(),
            pixel_size_um=_opt_f(self._pixel),
            width_px=_opt_i(self._ancho),
            height_px=_opt_i(self._alto),
            mono=self._mono.isChecked(),
            ampglow=self._ampglow.isChecked(),
            price_eur=_opt_f(self._precio),
            weight_kg=_opt_f(self._peso),
            notes=self._notas.text().strip(),
            images=self._rutas(),
        )

    # -- lecturas vivas ----------------------------------------------------

    def _recalcular(self) -> None:
        """Repinta la resolución derivada (ancho × alto; sin datos, «—»)."""
        ancho, alto = _opt_i(self._ancho), _opt_i(self._alto)
        self._resolucion.setText(f"{ancho}×{alto}" if ancho and alto else "—")

    def _conectar_cambios(self) -> None:
        """Cualquier toque al formulario emite ``changed`` y recalcula."""
        def toque() -> None:
            self._recalcular()
            self.changed.emit()

        for widget in (self._nombre, self._notas):
            widget.textChanged.connect(lambda _t: toque())
        for widget in (self._pixel, self._precio, self._peso, self._ancho,
                       self._alto):
            widget.valueChanged.connect(lambda _v: toque())
        self._bits.currentIndexChanged.connect(lambda _i: toque())
        for widget in (self._refrigerada, self._mono, self._ampglow):
            widget.toggled.connect(lambda _c: toque())
        self._recalcular()


class MountForm(QFrame):
    """Formulario de una montura: rejilla de 4 columnas (tipo y capacidad).

    Misma rejilla que `TelescopeForm` y que la cabecera de Equipo —etiquetas
    en las columnas 0 y 2, campos en la 1 y la 3 con stretch—: Precio·Peso
    y Tipo·Capacidad de carga van de dos en dos, así las cajas arrancan en
    la misma `x` y miden lo mismo. «Capacidad de carga» es la etiqueta más
    larga de la 2, así que ahí manda su ancho (como «Notas» en la cabecera).
    """

    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Campos de la montura (el más corto de los tres)."""
        super().__init__(parent)
        self._id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(12)  # como la cabecera de Equipo
        rejilla.setVerticalSpacing(4)

        self._nombre = QLineEdit()
        self._nombre.setPlaceholderText("AM5, EQ6-R…")
        rejilla.addWidget(QLabel("Nombre"), 0, 0)
        rejilla.addWidget(self._nombre, 0, 1, 1, 3)

        # Precio y peso de la pieza en pareja, tras el Nombre (mismo patrón
        # que el telescopio): la cabecera del equipo los suma en vivo.
        self._precio = spin_precio()
        self._peso = spin_peso()
        rejilla.addWidget(QLabel("Precio"), 1, 0)
        rejilla.addWidget(self._precio, 1, 1)
        rejilla.addWidget(QLabel("Peso"), 1, 2)
        rejilla.addWidget(self._peso, 1, 3)

        self._tipo = QComboBox()
        _combo_opciones(self._tipo, MOUNT_TYPES)
        self._capacidad = QDoubleSpinBox()
        self._capacidad.setRange(0.0, 200.0)
        self._capacidad.setDecimals(1)
        self._capacidad.setSuffix(" kg")
        self._capacidad.setSpecialValueText("—")
        self._capacidad.setToolTip("Carga útil máxima que admite la montura.")
        sin_botones(self._capacidad)
        rejilla.addWidget(QLabel("Tipo"), 2, 0)
        rejilla.addWidget(self._tipo, 2, 1)
        rejilla.addWidget(QLabel("Capacidad de carga"), 2, 2)
        rejilla.addWidget(self._capacidad, 2, 3)

        self._notas = QLineEdit()
        self._notas.setPlaceholderText("Notas (opcional)")
        rejilla.addWidget(self._notas, 3, 0, 1, 4)

        rejilla.setColumnStretch(1, 1)
        rejilla.setColumnStretch(3, 1)
        layout.addLayout(rejilla)
        layout.addStretch(1)

        self._nombre.textChanged.connect(lambda _t: self.changed.emit())
        self._tipo.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self._capacidad.valueChanged.connect(lambda _v: self.changed.emit())
        self._precio.valueChanged.connect(lambda _v: self.changed.emit())
        self._peso.valueChanged.connect(lambda _v: self.changed.emit())
        self._notas.textChanged.connect(lambda _t: self.changed.emit())

    # -- protocolo de formulario ------------------------------------------

    def limpiar(self) -> None:
        """Vacía el formulario para una montura nueva (id = None)."""
        self._id = None
        self._nombre.clear()
        self._tipo.setCurrentIndex(0)
        self._capacidad.setValue(0.0)
        self._precio.setValue(0.0)
        self._peso.setValue(0.0)
        self._notas.clear()

    def cargar(self, fila: dict | None) -> None:
        """Vierte una fila de la base (o ``None`` = vacío) en el formulario."""
        self.limpiar()
        if fila is None:
            return
        self._id = fila.get("id")
        self._nombre.setText(str(fila.get("name") or ""))
        indice = self._tipo.findData(fila.get("mount_type"))
        self._tipo.setCurrentIndex(max(0, indice) if fila.get("mount_type") else 0)
        self._capacidad.setValue(float(fila.get("payload_kg") or 0.0))
        self._precio.setValue(float(fila.get("price_eur") or 0.0))
        self._peso.setValue(float(fila.get("weight_kg") or 0.0))
        self._notas.setText(str(fila.get("notes") or ""))

    def a_modelo(self) -> Mount:
        """Modelo con lo que hay en pantalla (el id marca create vs update)."""
        return Mount(
            id=self._id,
            name=self._nombre.text().strip(),
            mount_type=self._tipo.currentData(),
            payload_kg=_opt_f(self._capacidad),
            price_eur=_opt_f(self._precio),
            weight_kg=_opt_f(self._peso),
            notes=self._notas.text().strip(),
        )
