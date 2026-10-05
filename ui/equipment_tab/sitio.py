"""Bloques «Sitio» de la ficha de ubicación: horizonte y contaminación lumínica.

Ambos pintan las mismas 8 direcciones en una malla 3×3 (la casilla central
es el título) y su verdad en memoria es un dict de las 8 claves de
``DIRECTIONS``: ``HorizonWidget`` maneja los tipos de obstáculo por
dirección y ``LightPollutionWidget`` el nivel de CL 0-3 por dirección más
Bortle, SQM, el mapa de referencia y la casilla ``consider_lp``.

Regla UX global: nada se persiste hasta «Guardar ubicación»; estos widgets
solo mantienen el estado en memoria (D-5: cancelar no toca BD ni ficheros).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from equipment.models import DIRECTIONS, LP_LEVELS, OBSTACLE_TYPES

#: Posición de cada dirección en la malla 3×3 (fila, columna); el centro
#: (1, 1) lo ocupa el título.
_CELDAS: dict[str, tuple[int, int]] = {
    "NO": (0, 0), "N": (0, 1), "NE": (0, 2),
    "O": (1, 0),              "E": (1, 2),
    "SO": (2, 0), "S": (2, 1), "SE": (2, 2),
}

#: Ficheros de imagen admitidos para el mapa de CL.
_FILTRO_IMAGENES = "Imágenes (*.png *.jpg *.jpeg *.bmp);;Todos los archivos (*)"


def _titulo(texto: str) -> QLabel:
    """Etiqueta-título de malla (``PanelTitle`` de ``ui/style.py``)."""
    etiqueta = QLabel(texto)
    etiqueta.setObjectName("PanelTitle")
    etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return etiqueta


class _MenuCasillas(QMenu):
    """Menú que no se cierra al marcar, para elegir varios tipos de una vez.

    Qt cierra el menú al pulsar cualquier acción; como un mismo obstáculo
    puede convivir con otros («Árboles» + «Edificios»), el clic en una
    casilla aquí solo la alterna y el menú se cierra al hacer clic fuera
    o con Esc.
    """

    def mouseReleaseEvent(self, event) -> None:
        """Al pulsar una casilla la alterna sin cerrar; el resto, al resto."""
        accion = self.actionAt(event.position().toPoint())
        if accion is not None and accion.isCheckable():
            accion.toggle()
            return
        super().mouseReleaseEvent(event)


class HorizonWidget(QFrame):
    """Malla 3×3 del horizonte: un botón por dirección con sus obstáculos.

    El texto del botón resume el estado («N ✓2» = dos tipos marcados en N);
    el clic abre un menú con casillas por cada tipo de ``OBSTACLE_TYPES``.
    Entran por ``set_obstacles`` y salen por ``obstacles`` (siempre las 8
    direcciones, con copia para que nadie muten el estado interno).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta la malla con las 8 direcciones vacías y el título central."""
        super().__init__(parent)
        self.setObjectName("GroupFrame")
        self._obstacles: dict[str, list[str]] = {d: [] for d in DIRECTIONS}
        self._botones: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 10)
        layout.setSpacing(8)
        rejilla = QGridLayout()
        rejilla.setSpacing(6)
        for direccion, (fila, columna) in _CELDAS.items():
            boton = QPushButton(direccion)
            boton.clicked.connect(lambda _=False, d=direccion: self._abrir_menu(d))
            self._botones[direccion] = boton
            rejilla.addWidget(boton, fila, columna)
        rejilla.addWidget(_titulo("Horizonte"), 1, 1)
        layout.addLayout(rejilla)

    # -- estado -----------------------------------------------------------

    def obstacles(self) -> dict[str, list[str]]:
        """Copia del horizonte con las 8 direcciones."""
        return {d: list(tipos) for d, tipos in self._obstacles.items()}

    def set_obstacles(self, obstacles: dict[str, list[str]]) -> None:
        """Carga el horizonte; las direcciones ausentes quedan vacías."""
        for direccion in DIRECTIONS:
            self._obstacles[direccion] = list(obstacles.get(direccion, []))
            self._pintar(direccion)

    # -- interacción ------------------------------------------------------

    def _abrir_menu(self, direccion: str) -> None:
        """Despliega los tipos de obstáculo de ``direccion`` (casillas multi)."""
        menu = _MenuCasillas(self)
        for clave, etiqueta in OBSTACLE_TYPES.items():
            accion = menu.addAction(etiqueta)
            accion.setCheckable(True)
            accion.setChecked(clave in self._obstacles[direccion])
            accion.toggled.connect(
                lambda marcado, d=direccion, k=clave: self._fijar(d, k, marcado)
            )
        boton = self._botones[direccion]
        menu.exec(boton.mapToGlobal(boton.rect().bottomLeft()))

    def _fijar(self, direccion: str, tipo: str, marcado: bool) -> None:
        """Añade o quita ``tipo`` en ``direccion`` y refresca su botón."""
        tipos = self._obstacles[direccion]
        if marcado and tipo not in tipos:
            tipos.append(tipo)
        elif not marcado and tipo in tipos:
            tipos.remove(tipo)
        self._pintar(direccion)

    def _pintar(self, direccion: str) -> None:
        """Texto del botón: «N», o «N ✓2» con el número de tipos marcados."""
        n = len(self._obstacles[direccion])
        self._botones[direccion].setText(f"{direccion} ✓{n}" if n else direccion)


class LightPollutionWidget(QFrame):
    """Malla 3×3 de CL por dirección + Bortle, SQM, mapa y ``consider_lp``.

    La casilla central es el título «CL»; cada celda es un combo con las
    etiquetas de ``LP_LEVELS`` (0-3). La imagen de referencia es **una
    sola**: «Añadir mapa…» sustituye a la anterior y «Quitar» la deja sin
    mapa; la copia a ``data/`` ocurre al «Guardar ubicación» (D-5), aquí
    solo se guarda la ruta en memoria.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta la malla de CL y el bloque de valores (Bortle/SQM/mapa)."""
        super().__init__(parent)
        self.setObjectName("GroupFrame")
        self._lp: dict[str, int] = {d: 0 for d in DIRECTIONS}
        self._combos: dict[str, QComboBox] = {}
        self._lp_map: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 10)
        layout.setSpacing(8)

        rejilla = QGridLayout()
        rejilla.setSpacing(6)
        for direccion, (fila, columna) in _CELDAS.items():
            combo = QComboBox()
            for nivel, etiqueta in LP_LEVELS.items():
                combo.addItem(etiqueta, nivel)
            combo.currentIndexChanged.connect(
                lambda i, d=direccion, c=combo: self._lp.__setitem__(d, c.itemData(i))
            )
            self._combos[direccion] = combo
            rejilla.addWidget(combo, fila, columna)
        rejilla.addWidget(_titulo("CL"), 1, 1)
        layout.addLayout(rejilla)

        # Bortle obligatorio (la validación lo exige 1-9).
        bortle = QHBoxLayout()
        bortle.addWidget(QLabel("Bortle"))
        self._bortle = QComboBox()
        self._bortle.addItem("Elige un nivel…", None)
        for nivel in range(1, 10):
            self._bortle.addItem(str(nivel), nivel)
        bortle.addWidget(self._bortle, 1)
        layout.addLayout(bortle)
        pista = QLabel("Obligatorio: la CL alimenta las decisiones de captura.")
        pista.setObjectName("HintLabel")
        pista.setWordWrap(True)
        layout.addWidget(pista)

        # SQM cenital opcional (0-30 mag/arcsec²; «—» = no informado).
        sqm = QHBoxLayout()
        sqm.addWidget(QLabel("SQM cenital"))
        self._sqm = QDoubleSpinBox()
        self._sqm.setRange(0.0, 30.0)
        self._sqm.setDecimals(2)
        self._sqm.setSpecialValueText("—")
        self._sqm.setSuffix(" mag/arcsec²")
        self._sqm.setToolTip("Magnitud por segundo de arco cuadrado en el cenit (opcional).")
        sqm.addWidget(self._sqm, 1)
        layout.addLayout(sqm)

        # Mapa de referencia: único, con copia a data/ al guardar.
        mapa = QHBoxLayout()
        mapa.addWidget(QLabel("Mapa de CL"))
        self._mapa = QLabel("Sin mapa")
        self._mapa.setToolTip("")
        mapa.addWidget(self._mapa, 1)
        boton_anadir = QPushButton("➕ Añadir mapa…")
        boton_anadir.clicked.connect(self._anadir_mapa)
        mapa.addWidget(boton_anadir)
        self._boton_quitar = QPushButton("Quitar")
        self._boton_quitar.setEnabled(False)
        self._boton_quitar.clicked.connect(self._quitar_mapa)
        mapa.addWidget(self._boton_quitar)
        layout.addLayout(mapa)
        referencia = QLabel("Referencia: el programa no la analiza.")
        referencia.setObjectName("HintLabel")
        layout.addWidget(referencia)

        self._considerar = QCheckBox("Tener en cuenta la CL en las capturas de esta ubicación")
        self._considerar.setChecked(True)
        layout.addWidget(self._considerar)

    # -- estado -----------------------------------------------------------

    def values(
        self,
    ) -> tuple[dict[str, int], int | None, float | None, str | None, bool]:
        """Valores del bloque: (CL por dirección, Bortle, SQM, mapa, considera)."""
        sqm = self._sqm.value() if self._sqm.value() > 0.0 else None
        return (
            dict(self._lp),
            self._bortle.currentData(),
            sqm,
            self._lp_map,
            self._considerar.isChecked(),
        )

    def set_values(
        self,
        lp: dict[str, int],
        bortle: int | None,
        sqm: float | None,
        lp_map: str | None,
        consider_lp: bool,
    ) -> None:
        """Carga el bloque completo (ausentes → valores de fábrica vacíos)."""
        for direccion in DIRECTIONS:
            nivel = lp.get(direccion, 0)
            combo = self._combos[direccion]
            indice = combo.findData(nivel)
            combo.setCurrentIndex(max(0, indice))
        self._bortle.setCurrentIndex(max(0, self._bortle.findData(bortle)))
        self._sqm.setValue(float(sqm) if sqm else 0.0)
        self._lp_map = lp_map
        self._actualizar_mapa()
        self._considerar.setChecked(bool(consider_lp))

    # -- mapa -------------------------------------------------------------

    def _anadir_mapa(self) -> None:
        """Elige una imagen (cualquier nueva sustituye a la anterior)."""
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar el mapa de CL", "", _FILTRO_IMAGENES
        )
        if ruta:
            self._lp_map = ruta
            self._actualizar_mapa()

    def _quitar_mapa(self) -> None:
        """Deja el campo sin mapa (se confirma al «Guardar ubicación»)."""
        self._lp_map = None
        self._actualizar_mapa()

    def _actualizar_mapa(self) -> None:
        """Pinta el nombre del archivo y habilita «Quitar» si hay mapa."""
        if self._lp_map:
            self._mapa.setText(Path(self._lp_map).name)
            self._mapa.setToolTip(self._lp_map)
        else:
            self._mapa.setText("Sin mapa")
            self._mapa.setToolTip("")
        self._boton_quitar.setEnabled(bool(self._lp_map))
