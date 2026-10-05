"""Bloques de la ficha de Ubicación: rosácea de entrada y salida.

Arriba, la rosácea con los 3 discos de `rosaceas.py` (orientación,
obstrucciones y CL por dirección) a ancho completo; abajo, dos cuadros a
mitades: la representación esquemática del sitio (``DiscoEsquematico``,
con la casilla ``consider_lp`` «Usar Contaminación Lumínica al
Planificar» dentro) y el mapa de CL adjunto con su vista previa
(``_VistaMapa``). Se sustituye a la antigua malla 3×3
(``HorizonWidget``/``LightPollutionWidget``).

Regla UX global (§9): **nada se persiste hasta «Guardar ubicación»** —
los discos mantienen el estado en memoria y la copia a ``data/`` del mapa
ocurre al guardar (D-5).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
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


class _VistaMapa(QLabel):
    """Vista previa del mapa de CL, escalada al cuadro disponible.

    La imagen original se conserva intacta y se reescala al cambiar de
    tamaño; el ``sizePolicy`` en Ignored evita que el tamaño del pixmap
    alimente al layout (bucle de redimensionado).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Rótulo centrado, con un mínimo por si el cuadro queda estrecho."""
        super().__init__(parent)
        self._original = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(160, 120)

    def set_ruta(self, ruta: str | None) -> None:
        """Carga la imagen de ``ruta`` (o la vacía) y la escala al cuadro."""
        self._original = QPixmap(ruta) if ruta else QPixmap()
        if self._original.isNull():
            self.setText("No se pudo cargar la imagen" if ruta else "")
            return
        self.setText("")
        self._escalar()

    def resizeEvent(self, event) -> None:
        """Reescala al redimensionar para aprovechar todo el cuadro."""
        super().resizeEvent(event)
        self._escalar()

    def _escalar(self) -> None:
        """Pone el pixmap manteniendo la proporción del original."""
        if self._original.isNull():
            return
        self.setPixmap(
            self._original.scaled(
                max(1, self.width() - 4),
                max(1, self.height() - 4),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class SitioPanel(QWidget):
    """Rosácea de los 3 discos + esquemático + mapa de CL + ``consider_lp``.

    Los discos de entrada ceden sus cambios a la salida
    (``DiscoEsquematico``) sin tocar la base; el Bortle/SQM del formulario
    (arriba, en la ficha) llega por ``set_cielo``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta la rosácea y los dos cuadros grandes (casilla incluida)."""
        super().__init__(parent)
        self._bortle: int | None = None
        self._sqm: float | None = None
        self._lp_map: str | None = None

        # La casilla vive dentro del cuadro del esquemático.
        self._considerar = QCheckBox("Usar Contaminación Lumínica al Planificar")
        self._considerar.setChecked(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._rosacea())

        # Mitades iguales: el esquemático llena su celda (HFW) y el mapa
        # aprovecha el mismo ancho para la vista previa.
        abajo = QHBoxLayout()
        abajo.setSpacing(8)
        abajo.addWidget(self._esquematico(), 1)
        abajo.addWidget(self._mapa(), 1)
        layout.addLayout(abajo)

        self._obstrucciones.changed.connect(self._repintar_salida)
        self._lumen.changed.connect(self._repintar_salida)
        self._repintar_salida()

    # -- construcción ------------------------------------------------------

    def _rosacea(self) -> QFrame:
        """Los 3 discos de entrada en fila: tercios iguales, sin laterales."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        caja = QVBoxLayout(marco)
        caja.setContentsMargins(12, 6, 12, 10)
        caja.setSpacing(6)
        fila = QHBoxLayout()
        fila.setSpacing(16)

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
            # Sin AlignHCenter: el disco crece hasta el ancho de su celda
            # y su altura lo sigue (HFW) — cuadrados a ancho completo.
            columna.addWidget(disco)
            fila.addLayout(columna, 1)
        caja.addLayout(fila)
        return marco

    def _esquematico(self) -> QFrame:
        """Cuadro de la representación del sitio, con la casilla de CL."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        caja = QVBoxLayout(marco)
        caja.setContentsMargins(12, 6, 12, 10)
        caja.setSpacing(6)
        titulo = QLabel("Representación esquemática")
        titulo.setObjectName("PanelTitle")
        caja.addWidget(titulo)
        self._salida = DiscoEsquematico()
        caja.addWidget(self._salida, 1)
        # La casilla de CL la «asume» el esquemático (lo pidió el usuario).
        caja.addWidget(self._considerar)
        return marco

    def _mapa(self) -> QFrame:
        """Cuadro del mapa de CL con su vista previa a ancho de celda."""
        marco = QFrame()
        marco.setObjectName("GroupFrame")
        caja = QVBoxLayout(marco)
        caja.setContentsMargins(12, 6, 12, 10)
        caja.setSpacing(6)
        titulo = QLabel("Mapa de Contaminación Lumínica")
        titulo.setObjectName("PanelTitle")
        caja.addWidget(titulo)

        fila = QHBoxLayout()
        self._mapa_lbl = QLabel("Sin mapa")
        self._mapa_lbl.setToolTip("")
        fila.addWidget(self._mapa_lbl, 1)
        # El rótulo cambia con el estado: «Añadir» sin mapa, «Cambiar» con él.
        self._boton_anadir = QPushButton("Añadir")
        self._boton_anadir.clicked.connect(self._anadir_mapa)
        fila.addWidget(self._boton_anadir)
        self._boton_quitar = QPushButton("Quitar")
        self._boton_quitar.setEnabled(False)
        self._boton_quitar.clicked.connect(self._quitar_mapa)
        fila.addWidget(self._boton_quitar)
        caja.addLayout(fila)

        # Vista previa: el usuario modela discos y obstrucciones con la
        # referencia a la vista (ocupa todo el resto del cuadro).
        self._vista = _VistaMapa()
        caja.addWidget(self._vista, 1)
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
        """Pinta nombre, botón contextual, vista previa y «Quitar»."""
        if self._lp_map:
            self._mapa_lbl.setText(Path(self._lp_map).name)
            self._mapa_lbl.setToolTip(self._lp_map)
        else:
            self._mapa_lbl.setText("Sin mapa")
            self._mapa_lbl.setToolTip("")
        self._boton_anadir.setText("Añadir" if not self._lp_map else "Cambiar")
        self._boton_quitar.setEnabled(bool(self._lp_map))
        self._vista.set_ruta(self._lp_map)
