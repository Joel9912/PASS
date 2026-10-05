"""Bloques de la ficha de Ubicación: rosácea de entrada y salida.

Arriba, la rosácea con los 3 discos de `rosaceas.py` (orientación,
obstrucciones y CL por dirección); abajo, los dos cuadros grandes: la
representación esquemática del sitio (``DiscoEsquematico``) y el mapa de
CL adjunto, más la casilla ``consider_lp``. Se sustituye a la antigua
malla 3×3 (``HorizonWidget``/``LightPollutionWidget``).

Regla UX global (§9): **nada se persiste hasta «Guardar ubicación»** —
los discos mantienen el estado en memoria y la copia a ``data/`` del mapa
ocurre al guardar (D-5).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .rosaceas import (
    DiscoEsquematico,
    DiscoLumen,
    DiscoObstrucciones,
    RosaDirecciones,
)

#: Ficheros de imagen admitidos para el mapa de CL.
_FILTRO_IMAGENES = "Imágenes (*.png *.jpg *.jpeg *.bmp);;Todos los archivos (*)"


class SitioPanel(QWidget):
    """Rosácea de los 3 discos + esquemático + mapa de CL + ``consider_lp``.

    Los discos de entrada ceden sus cambios a la salida
    (``DiscoEsquematico``) sin tocar la base; el Bortle/SQM del formulario
    (arriba, en la ficha) llega por ``set_cielo``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta la rosácea, los dos cuadros grandes y la casilla de CL."""
        super().__init__(parent)
        self._bortle: int | None = None
        self._sqm: float | None = None
        self._lp_map: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._rosacea())

        abajo = QHBoxLayout()
        abajo.setSpacing(8)
        abajo.addWidget(self._esquematico(), 3)
        abajo.addWidget(self._mapa(), 2)
        layout.addLayout(abajo)

        self._considerar = QCheckBox(
            "Tener en cuenta la CL en las capturas de esta ubicación"
        )
        self._considerar.setChecked(True)
        layout.addWidget(self._considerar)

        self._obstrucciones.changed.connect(self._repintar_salida)
        self._lumen.changed.connect(self._repintar_salida)
        self._repintar_salida()

    # -- construcción ------------------------------------------------------

    def _rosacea(self) -> QFrame:
        """Los 3 discos de entrada en fila, cada uno con su rótulo."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        caja = QVBoxLayout(marco)
        caja.setContentsMargins(12, 6, 12, 10)
        caja.setSpacing(6)
        fila = QHBoxLayout()
        fila.setSpacing(16)
        fila.addStretch(1)

        self._rosa = RosaDirecciones()
        self._obstrucciones = DiscoObstrucciones()
        self._lumen = DiscoLumen()
        discos = (
            ("Orientación", self._rosa),
            ("Obstrucciones", self._obstrucciones),
            ("Contaminación Lumínica", self._lumen),
        )
        for titulo, disco in discos:
            columna = QVBoxLayout()
            columna.setSpacing(4)
            etiqueta = QLabel(titulo)
            etiqueta.setObjectName("PanelTitle")
            etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
            columna.addWidget(etiqueta)
            columna.addWidget(disco, 0, Qt.AlignmentFlag.AlignHCenter)
            fila.addLayout(columna)
        fila.addStretch(1)
        caja.addLayout(fila)
        return marco

    def _esquematico(self) -> QFrame:
        """Cuadro grande de la representación del sitio."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        caja = QVBoxLayout(marco)
        caja.setContentsMargins(12, 6, 12, 10)
        caja.setSpacing(6)
        titulo = QLabel("Representación esquemática")
        titulo.setObjectName("PanelTitle")
        caja.addWidget(titulo)
        self._salida = DiscoEsquematico()
        caja.addWidget(self._salida, 1, Qt.AlignmentFlag.AlignHCenter)
        return marco

    def _mapa(self) -> QFrame:
        """Cuadro grande del mapa de CL adjunto (referencia visual)."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        caja = QVBoxLayout(marco)
        caja.setContentsMargins(12, 6, 12, 10)
        caja.setSpacing(6)
        titulo = QLabel("Mapa de CL")
        titulo.setObjectName("PanelTitle")
        caja.addWidget(titulo)

        fila = QHBoxLayout()
        self._mapa_lbl = QLabel("Sin mapa")
        self._mapa_lbl.setToolTip("")
        fila.addWidget(self._mapa_lbl, 1)
        boton_anadir = QPushButton("➕ Añadir mapa…")
        boton_anadir.clicked.connect(self._anadir_mapa)
        fila.addWidget(boton_anadir)
        self._boton_quitar = QPushButton("Quitar")
        self._boton_quitar.setEnabled(False)
        self._boton_quitar.clicked.connect(self._quitar_mapa)
        fila.addWidget(self._boton_quitar)
        caja.addLayout(fila)

        referencia = QLabel("Referencia: el programa no la analiza.")
        referencia.setObjectName("HintLabel")
        referencia.setWordWrap(True)
        caja.addWidget(referencia)
        caja.addStretch(1)
        return marco

    # -- estado ------------------------------------------------------------

    def set_cielo(self, bortle: int | None, sqm: float | None) -> None:
        """Bortle y SQM cenital del formulario (arriba) para la salida."""
        self._bortle = bortle
        self._sqm = sqm
        self._repintar_salida()

    def set_valores(
        self,
        obstacles: dict,
        lp: dict,
        lp_map: str | None,
        consider_lp: bool,
    ) -> None:
        """Carga discos, mapa y ``consider_lp`` de una ubicación."""
        self._obstrucciones.set_obstacles(obstacles or {})
        self._lumen.set_lp(lp or {})
        self._lp_map = lp_map
        self._actualizar_mapa()
        self._considerar.setChecked(bool(consider_lp))
        # Carga programática: los discos no emiten `changed`, así que el
        # esquemático se repinta aquí (si no, quedaría con la carga vieja).
        self._repintar_salida()

    def valores(self) -> tuple[dict, dict, str | None, bool]:
        """Estado completo: (obstrucciones, CL por dirección, mapa, considera)."""
        return (
            self._obstrucciones.obstacles(),
            self._lumen.lp(),
            self._lp_map,
            self._considerar.isChecked(),
        )

    def _repintar_salida(self) -> None:
        """Vuelca discos + cielo al disco esquemático de abajo."""
        obstaculos, fuentes, _, _ = self.valores()
        self._salida.set_datos(self._bortle, self._sqm, obstaculos, fuentes)

    # -- mapa --------------------------------------------------------------

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
            self._mapa_lbl.setText(Path(self._lp_map).name)
            self._mapa_lbl.setToolTip(self._lp_map)
        else:
            self._mapa_lbl.setText("Sin mapa")
            self._mapa_lbl.setToolTip("")
        self._boton_quitar.setEnabled(bool(self._lp_map))
