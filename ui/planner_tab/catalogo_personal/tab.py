"""Subpestaña **Catálogo Personal**: objetos guardados y regiones de interés.

Muestra lo que hay en ``personal_catalog`` en una sola tabla:

- **Objetos** (``kind='catalog'``): los que se añaden desde Búsqueda con el
  botón "Añadir a Mi Lista". Sus datos (tipo, mag, tamaño) vienen del JOIN
  con la tabla ``catalog``.
- **Regiones** (``kind='region'``): encuadres libres o mosaicos que el
  usuario define a mano (nombre, centro RA/Dec, FOV, teselas). Las regiones
  **no se pintan en el planetario** (decisión del usuario): solo se usan en
  planificación, para no ensuciar la vista estelar.

Señales: ``target_selected(object_id, catalog)`` al marcar una fila y
``region_added(name)`` cuando se crea una región.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from planners import personal_catalog

from ..widgets import (
    CATALOG_LABELS,
    _type_label,
    crear_tabla_filas,
    fila_seleccionada,
    format_dec,
    format_ra,
    format_size,
)

#: Columnas de la tabla (mockup del usuario).
COLUMNS: tuple[str, ...] = (
    "#", "Nombre", "Tipo", "Catálogo", "Mag", "RA", "Dec", "Tamaño", "Notas",
)

#: Catálogos → etiqueta: compartida desde `../widgets.py` (M-12; antes
#: estaba duplicada aquí con valores divergentes de los de Búsqueda).


class RegionDialog(QDialog):
    """Diálogo para crear una región de interés (centro + encuadre + teselas)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Formulario: nombre, centro RA/Dec, FOV, teselas y notas (Aceptar/Cancelar)."""
        super().__init__(parent)
        self.setWindowTitle("Añadir región de interés")
        self.setMinimumWidth(420)

        form = QFormLayout(self)
        form.setSpacing(10)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Mosaico de Orión")
        form.addRow("Nombre", self._name)

        self._ra = QDoubleSpinBox()
        self._ra.setRange(0.0, 24.0)
        self._ra.setDecimals(4)
        self._ra.setSingleStep(0.1)
        self._ra.setSuffix(" h")
        form.addRow("Centro RA (J2000)", self._ra)

        self._dec = QDoubleSpinBox()
        self._dec.setRange(-90.0, 90.0)
        self._dec.setDecimals(4)
        self._dec.setSingleStep(0.5)
        self._dec.setSuffix("°")
        form.addRow("Centro Dec (J2000)", self._dec)

        self._fov_major = QDoubleSpinBox()
        self._fov_major.setRange(0.0, 1800.0)
        self._fov_major.setDecimals(1)
        self._fov_major.setSuffix("′")
        self._fov_major.setSpecialValueText("Sin encuadre")
        form.addRow("FOV mayor", self._fov_major)

        self._fov_minor = QDoubleSpinBox()
        self._fov_minor.setRange(0.0, 1800.0)
        self._fov_minor.setDecimals(1)
        self._fov_minor.setSuffix("′")
        self._fov_minor.setSpecialValueText("Sin encuadre")
        form.addRow("FOV menor", self._fov_minor)

        self._tiles_x = QSpinBox()
        self._tiles_x.setRange(1, 20)
        self._tiles_x.setSuffix(" teselas")
        self._tiles_y = QSpinBox()
        self._tiles_y.setRange(1, 20)
        self._tiles_y.setSuffix(" teselas")
        form.addRow("Teselas horizontales", self._tiles_x)
        form.addRow("Teselas verticales", self._tiles_y)

        self._notes = QLineEdit()
        self._notes.setPlaceholderText("Notas opcionales")
        form.addRow("Notas", self._notes)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _validate(self) -> None:
        """Acepta solo con nombre; si falta, avisa y el diálogo sigue abierto."""
        if not self._name.text().strip():
            QMessageBox.warning(self, "Falta el nombre", "Dale nombre a la región.")
            return
        self.accept()

    def values(self) -> dict:
        """Datos de la región en la forma que espera ``add_region``.

        FOV a 0 («Sin encuadre») se guarda como ``None`` y las teselas
        solo se guardan si hay FOV mayor; sin él, la región es centro puro.
        """
        major = self._fov_major.value() or None
        minor = self._fov_minor.value() or None
        return {
            "name": self._name.text().strip(),
            "ra_hours": self._ra.value(),
            "dec_deg": self._dec.value(),
            "fov_major_arcmin": major,
            "fov_minor_arcmin": minor,
            "tiles_x": self._tiles_x.value() if major else None,
            "tiles_y": self._tiles_y.value() if major else None,
            "notes": self._notes.text().strip(),
        }


class CatalogoPersonalTab(QWidget):
    """Tabla de elementos guardados + acciones (quitar, notas, región)."""

    target_selected = pyqtSignal(str, str)   # object_id, catalog
    region_added = pyqtSignal(str)           # nombre de la región creada
    #: La lista cambió (quitar un objeto): Planificación debe recargarla.
    catalog_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta tabla, acciones y aviso; arranca leyendo la base (``refresh``)."""
        super().__init__(parent)
        self._rows: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel("Objetos guardados y regiones")
        title.setObjectName("PanelTitle")
        title_row.addWidget(title)
        self._count = QLabel("0 elementos")
        self._count.setObjectName("HintLabel")
        title_row.addWidget(self._count)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        self._table = crear_tabla_filas(list(COLUMNS), altura_min=260, word_wrap=False)
        self._table.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self._table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self._remove = QPushButton("Quitar seleccionado")
        self._remove.clicked.connect(self._on_remove)
        self._remove.setEnabled(False)
        actions.addWidget(self._remove)

        self._notes = QPushButton("Editar notas")
        self._notes.clicked.connect(self._on_edit_notes)
        self._notes.setEnabled(False)
        actions.addWidget(self._notes)

        self._add_region = QPushButton("＋ Añadir región")
        self._add_region.setObjectName("PrimaryButton")
        self._add_region.clicked.connect(self._on_add_region)
        actions.addWidget(self._add_region)

        actions.addStretch(1)
        layout.addLayout(actions)

        hint = QLabel(
            "Las regiones no se dibujan en el planetario: se usan en "
            "Planificación como encuadre de referencia."
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.refresh()

    # -- API pública ---------------------------------------------------------
    def refresh(self) -> None:
        """Vuelve a leer la base y repuebla la tabla."""
        self._rows = personal_catalog.list_objects()
        self._fill()
        self._count.setText(f"{len(self._rows)} elementos")

    def add_object(self, object_id: str, catalog: str) -> None:
        """Añade un objeto del catálogo global al personal (desde Búsqueda)."""
        already = any(
            row["object_id"] == object_id and row["catalog"] == catalog
            for row in self._rows
        )
        if already:
            QMessageBox.information(
                self,
                "Ya estaba guardado",
                f"{object_id} ya estaba en tu catálogo personal.",
            )
            return
        personal_catalog.add(object_id, catalog)
        self.refresh()

    # -- Relleno de la tabla -------------------------------------------------
    def _fill(self) -> None:
        """Vuelca ``self._rows`` a la tabla (objetos y regiones en la misma)."""
        self._table.setRowCount(len(self._rows))
        for index, row in enumerate(self._rows):
            is_region = row.get("kind") == "region"
            values = (
                str(index + 1),
                str(row.get("object_id") or "--"),
                "Región de interés" if is_region else _type_label(row.get("type")),
                CATALOG_LABELS.get(str(row.get("catalog")), str(row.get("catalog"))),
                "--" if is_region else (f"{row['magnitude']:.2f}"
                                         if row.get("magnitude") is not None else "--"),
                format_ra(row.get("ra_hours")),
                format_dec(row.get("dec_deg")),
                self._size_text(row, is_region),
                row.get("notes") or "",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self._table.setItem(index, column, item)
        self._table.resizeRowsToContents()

    @staticmethod
    def _size_text(row: dict, is_region: bool) -> str:
        """Texto de la celda: FOV(+teselas) en regiones, tamaño angular en objetos."""
        if is_region:
            major = row.get("fov_major_arcmin")
            minor = row.get("fov_minor_arcmin")
            tiles_x, tiles_y = row.get("tiles_x"), row.get("tiles_y")
            if not major:
                return "--"
            text = format_size(major, minor)
            if tiles_x and tiles_y and (tiles_x > 1 or tiles_y > 1):
                text += f" ({tiles_x}×{tiles_y})"
            return text
        return format_size(row.get("size_major_arcmin"), row.get("size_minor_arcmin"))

    # -- Selección -----------------------------------------------------------
    def _selected(self) -> dict | None:
        """Dict de la fila seleccionada (``None`` si no hay)."""
        return fila_seleccionada(self._table, self._rows)

    def _on_selection(self) -> None:
        """Activa los botones y emite ``target_selected`` al marcar una fila."""
        row = self._selected()
        has_row = row is not None
        self._remove.setEnabled(has_row)
        self._notes.setEnabled(has_row)
        if has_row:
            self.target_selected.emit(
                str(row["object_id"]), str(row["catalog"])
            )

    # -- Acciones ------------------------------------------------------------
    def _on_remove(self) -> None:
        """Quita la fila seleccionada tras confirmar y avisa con ``catalog_changed``."""
        row = self._selected()
        if row is None:
            return
        name = row.get("object_id") or ""
        answer = QMessageBox.question(
            self,
            "Quitar del catálogo",
            f'¿Quitar "{name}" de tu catálogo personal?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            personal_catalog.remove(str(row["object_id"]), str(row["catalog"]))
            self.refresh()
            # Planificación sigue ofreciendo el target quitado sin esta
            # señal (podía guardar una sesión de un objeto ya fuera).
            self.catalog_changed.emit()

    def _on_edit_notes(self) -> None:
        """Abre el diálogo multilinea de notas y guarda si el usuario acepta."""
        row = self._selected()
        if row is None:
            return
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "Editar notas",
            f'Notas de {row["object_id"]}:',
            row.get("notes") or "",
        )
        if accepted:
            personal_catalog.update_notes(
                str(row["object_id"]), str(row["catalog"]), text
            )
            self.refresh()

    def _on_add_region(self) -> None:
        """Abre ``RegionDialog`` y, si se acepta, crea la región y refresca."""
        dialog = RegionDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.values()
            personal_catalog.add_region(**values)
            self.region_added.emit(values["name"])
            self.refresh()
        # El diálogo se construye con padre: sin borrarlo se acumula como
        # hijo oculto en cada clic (fuga medida en la auditoría, M-14).
        dialog.deleteLater()
