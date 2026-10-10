"""Visor interactivo del cielo capturado por una sesión, sin catálogo externo.

Muestra el primer light FITS sin modificarlo. RA/Dec y campo angular vienen
exclusivamente de su cabecera: el desplazamiento y el zoom son visuales,
no se atribuyen coordenadas inventadas a píxeles sin solución WCS.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from weakref import ref

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPen, QWheelEvent
from PyQt6.QtWidgets import QWidget

from stacks.session_parser import FichaFITS, campo_vision
from ui.planner_tab.planificacion.planetario_visual import (
    PlanetarioVisual,
    gnomonic,
    marker_color,
)
from ui.style import PALETTE

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fits-sesiones")

#: Catálogos de la leyenda (etiqueta tal y como la pinta la referencia).
_LEYENDA = (
    ("messier", "• Messier (Dorado)"),
    ("ngc", "• NGC (Celeste)"),
    ("ic", "• IC (Verde)"),
    ("ldn", "• LDN (Oscuras)"),
)


class CieloCapturado(PlanetarioVisual):
    """Carta de catálogos compartidos, limitada al encuadre del FITS seleccionado.

    Hereda proyección, estrellas, objetos y navegación del Planificador,
    pero no emite acciones de selección ni crea regiones de planificación.
    El contorno del encuadre va en azul (con su cruz de centro) y las capas
    de texto reproducen la referencia: FOV, rotación, leyenda y centro.
    """

    #: Contorno del encuadre: azul en vez del ámbar del Planificador.
    _color_marco = "#58a6ff"
    #: Relleno del encuadre: casi transparente, solo para marcar la zona.
    _color_relleno_marco = QColor(88, 166, 255, 6)

    def __init__(self, parent=None) -> None:
        """Carga el mismo catálogo del Planificador, sin duplicar consultas SQL."""
        super().__init__(parent)
        self._captura: tuple[float, float, float, float] | None = None
        self._rotacion = 0.0
        self._valido = False
        self._centro_ficha: tuple[float, float] | None = None
        self._objeto_ficha = ""
        self._crota_fits: float | None = None

    def mostrar(self, ficha: FichaFITS | None) -> None:
        """Centra la carta en la captura; sin coordenadas no dibuja FOV falso."""
        campo = campo_vision(ficha) if ficha else None
        self._crota_fits = ficha.rotacion_deg if ficha else None
        self._objeto_ficha = (ficha.objeto or "") if ficha else ""
        if ficha and ficha.ra_deg is not None and ficha.dec_deg is not None:
            self._valido = True
            self._centro_ficha = (ficha.ra_deg / 15.0, ficha.dec_deg)
            self.set_center(ficha.ra_deg / 15, ficha.dec_deg, ficha.objeto or "Captura")
            if campo:
                self._captura = (ficha.ra_deg / 15, ficha.dec_deg, *campo)
                self.set_framing(*self._captura)
                self.set_fov_deg(min(180, max(1, max(campo) * 1.6)))
            else:
                self._captura = None
                self.clear_framing()
                self.set_fov_deg(6.0)
        else:
            self._valido = False
            self._centro_ficha = None
            self._captura = None
            self.clear_framing()
            self.set_center_label("FITS sin coordenadas: encuadre desconocido")
        self.update()

    def tiene_encuadre(self) -> bool:
        """True si ahora mismo hay un contorno FOV dibujado (hay sensor activo)."""
        return self.framing is not None

    def actualizar_campo(self, campo: tuple[float, float] | None) -> None:
        """Reancla el contorno FOV al centro del FITS con el campo indicado.

        Se usa cuando cambia la escala (cabecera o óptica editada a mano): el
        rectángulo vuelve a su sitio aunque el usuario haya arrastrado la
        vista. Sin campo, o sin coordenadas, se retira en vez de apuntar a
        una zona que ya no sabemos.
        """
        if not self._valido or self._centro_ficha is None:
            return
        if campo is None:
            if self.framing is not None:
                self.clear_framing()
            self.update()
            return
        habia = self.framing is not None
        ra, dec = self._centro_ficha
        self.set_framing(ra, dec, campo[0], campo[1])
        if not habia:
            self.set_fov_deg(min(180, max(1, max(campo) * 1.6)))
        self.update()

    def set_rotation(self, grados: float) -> None:
        """Rota solo el contorno FOV; el catálogo conserva norte arriba."""
        self._rotacion = grados
        self.update()

    def _draw_framing(self, painter: QPainter, ppr: float) -> None:
        """Pinta el marco con la rotación disponible y su cruz de centro."""
        if not self.framing:
            return
        painter.save()
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self._rotacion)
        painter.translate(-self.width() / 2, -self.height() / 2)
        super()._draw_framing(painter, ppr)
        self._draw_cruz_centro(painter, ppr)
        painter.restore()

    def _draw_cruz_centro(self, painter: QPainter, ppr: float) -> None:
        """Cruz punteada (±12 px) sobre el centro exacto del encuadre."""
        marco = self.framing
        if not marco:
            return
        ra, dec = marco[0], marco[1]
        ra0, dec0 = self.center_deg
        xi, eta, ok = gnomonic([ra], [dec], ra0, dec0)
        if not bool(ok[0]):
            return
        x, y = self._to_screen(xi, eta, ppr)
        cx, cy = float(x[0]), float(y[0])
        painter.setPen(QPen(QColor("#79c0ff"), 1, Qt.PenStyle.DotLine))
        painter.drawLine(QPointF(cx - 12.0, cy), QPointF(cx + 12.0, cy))
        painter.drawLine(QPointF(cx, cy - 12.0), QPointF(cx, cy + 12.0))

    def _draw_label(self, painter: QPainter) -> None:
        """La etiqueta del centro la pinta la capa de la referencia (``_pintar_capas``)."""

    def paintEvent(self, event) -> None:
        """Sin RA/Dec no dibuja otra zona del cielo como si fuera la captura."""
        if not self._valido:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor("#05070d"))
            painter.setPen(QColor(PALETTE["textDim"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "La cabecera FITS no contiene coordenadas del centro.")
            painter.end()
            return
        super().paintEvent(event)
        self._pintar_capas()

    # ------------------------------------------------------------ capas de texto
    def _pintar_capas(self) -> None:
        """Rotulos de la referencia: FOV/rotación, leyenda, centro y coordenadas."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ancho, alto = self.width(), self.height()

        fuente = QFont(self.font())
        fuente.setPointSize(9)
        painter.setFont(fuente)
        painter.setPen(QColor("#c9d1d9"))
        marco = self.framing
        if marco:
            painter.drawText(
                12, 22,
                f"FOV: {marco[2]:.2f}° × {marco[3]:.2f}°",
            )
            crota = (
                f" (CROTA2 {self._crota_fits:.1f}°)"
                if self._crota_fits is not None else ""
            )
            painter.drawText(
                12, 38,
                f"Rotación Sensor: {round(self._rotacion)}°{crota}",
            )

        # Leyenda de catálogos, a la derecha y por debajo del botón flotante.
        fuente_leyenda = QFont(self.font())
        fuente_leyenda.setPointSize(8)
        painter.setFont(fuente_leyenda)
        for indice, (catalogo, texto) in enumerate(_LEYENDA):
            painter.setPen(marker_color(catalogo))
            painter.drawText(ancho - 150, 60 + 14 * indice, texto)

        objeto = self._objeto_ficha
        if objeto and objeto.lower() not in ("unknown", "desconocido"):
            fuente_centro = QFont(self.font())
            fuente_centro.setPointSize(9)
            fuente_centro.setBold(True)
            painter.setFont(fuente_centro)
            painter.setPen(QColor("#f1fa8c"))
            painter.drawText(75, alto - 24, f"Centro: {objeto}")

        painter.setFont(fuente_leyenda)
        painter.setPen(QColor("#8b949e"))
        painter.drawText(75, alto - 10, self._coordenadas_vista())
        painter.end()

    def _coordenadas_vista(self) -> str:
        """«RA 00h47m | Dec +41,3°» del centro mirado ahora (coma decimal)."""
        ra_deg, dec_deg = self.center_deg
        ra_h = (ra_deg / 15.0) % 24.0
        horas = int(ra_h)
        minutos = int(round((ra_h - horas) * 60.0))
        if minutos == 60:
            horas, minutos = (horas + 1) % 24, 0
        dec = f"{dec_deg:+.1f}".replace(".", ",")
        return f"RA {horas:02d}h{minutos:02d}m | Dec {dec}°"

    def reset_view(self) -> None:
        """Restaura centro y campo de la captura, no el origen genérico (0°,0°)."""
        if self._captura:
            ra, dec, ancho, alto = self._captura
            self.set_center(ra, dec, self.center_label)
            self.set_fov_deg(min(180, max(1, max(ancho, alto) * 1.6)))
            self.update()

    def _handle_click(self, _pos) -> None:
        """No convierte clics del Apilador en acciones del Planificador."""


class VisorSesiones(QWidget):
    """Lienzo del primer FITS: rueda para zoom y arrastre para inspeccionar."""

    _lista = pyqtSignal(int, object)

    def __init__(self, cargar: Callable[[Path], QImage | None], parent=None) -> None:
        """Recibe un lector de miniaturas: las lecturas largas corren fuera de Qt."""
        super().__init__(parent)
        self._cargar = cargar
        self._imagen: QImage | None = None
        self._ficha: FichaFITS | None = None
        self._zoom = 1.0
        self._desplazamiento = QPoint()
        self._inicio: QPoint | None = None
        self._revision = 0
        self.setMinimumSize(260, 160)
        self.setMouseTracking(True)
        self._lista.connect(self._recibir)

    def mostrar(self, ruta: Path | None, ficha: FichaFITS | None) -> None:
        """Cambia de sesión y descarta previews tardíos de selecciones anteriores."""
        self._revision += 1
        self._ficha = ficha
        self._imagen = None
        self.reiniciar_vista()
        if ruta is not None and ruta.suffix.lower() in {".fit", ".fits", ".fts"}:
            revision = self._revision
            receptor = ref(self)
            futuro = _EXECUTOR.submit(self._cargar, ruta)

            def entregar(terminado):
                """Envía al hilo Qt la imagen leída o un fallo no fatal."""
                try:
                    imagen = terminado.result()
                except (OSError, ValueError):
                    imagen = None
                visor = receptor()
                if visor is not None:
                    try:
                        visor._lista.emit(revision, imagen)
                    except RuntimeError:
                        pass  # el widget Qt pudo cerrarse durante la lectura

            futuro.add_done_callback(entregar)
        self.update()

    def _recibir(self, revision: int, imagen: QImage | None) -> None:
        """Ignora una carga vieja si se eligió otra sesión mientras leía."""
        if revision == self._revision:
            self._imagen = imagen
            self.update()

    def reiniciar_vista(self) -> None:
        """Devuelve el encuadre FITS completo al lienzo."""
        self._zoom = 1.0
        self._desplazamiento = QPoint()
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Acerca o aleja la imagen manteniendo siempre visible el contexto."""
        self._zoom = max(1.0, min(8.0, self._zoom * (1.2 if event.angleDelta().y() > 0 else 1 / 1.2)))
        self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Inicia un desplazamiento visual, sin alterar coordenadas FITS."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._inicio = event.position().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Desplaza la imagen ampliada al arrastrar con el botón izquierdo."""
        if self._inicio is not None and self._zoom > 1:
            actual = event.position().toPoint()
            self._desplazamiento += actual - self._inicio
            self._inicio = actual
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Termina el arrastre al soltar el botón izquierdo."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._inicio = None

    def paintEvent(self, _event) -> None:
        """Pinta el FITS y su contorno, o una pista honesta si faltan datos."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(PALETTE["bg"]))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        imagen = self._imagen
        if imagen is not None and not imagen.isNull():
            escala = min(self.width() / imagen.width(), self.height() / imagen.height()) * self._zoom
            ancho, alto = imagen.width() * escala, imagen.height() * escala
            x = (self.width() - ancho) / 2 + self._desplazamiento.x()
            y = (self.height() - alto) / 2 + self._desplazamiento.y()
            destino = QRectF(x, y, ancho, alto)
            painter.drawImage(destino, imagen)
            painter.setPen(QPen(QColor(PALETTE["accentLight"]), 1))
            painter.drawRect(destino)
        else:
            painter.setPen(QColor(PALETTE["textDim"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Selecciona una sesión con un light FITS legible.")
        painter.setPen(QColor(PALETTE["accentLight"]))
        ficha = self._ficha
        if ficha and ficha.ra_deg is not None and ficha.dec_deg is not None:
            texto = f"Centro FITS: RA {ficha.ra_deg:.4f}° · Dec {ficha.dec_deg:+.4f}°"
        else:
            texto = "Coordenadas no disponibles en el FITS"
        campo = campo_vision(ficha) if ficha else None
        texto += (f"   |   Campo {campo[0]:.2f}° × {campo[1]:.2f}°"
                  if campo else "   |   FOV no disponible")
        painter.fillRect(QRectF(4, 4, self.width() - 8, 30), QColor(13, 17, 23, 215))
        painter.drawText(12, 25, texto)
        painter.end()
