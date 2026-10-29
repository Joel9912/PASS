"""Solicitud solar/lunar compartida: datos de valor y señales Qt, sin sincronizar el estado de las vistas."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from PyQt6.QtCore import QObject, pyqtSignal

from planners.sky_state import observe_sky

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sky-context")


class SkyContext(QObject):
    """Ignora resultados tardíos tras cambiar de sitio/instante o cerrar, sin tocar widgets en workers."""

    ready = pyqtSignal(object, str)
    _delivered = pyqtSignal(int, object, str)

    def __init__(self, parent=None):
        """Retiene solo una solicitud pendiente por vista; no crea cálculos al construir."""
        super().__init__(parent)
        self._generation = 0
        self._future = None
        self._delivered.connect(self._receive)
        if parent is not None:
            parent.destroyed.connect(self.stop)

    def request(self, location: dict, moment: datetime | None = None):
        """Envía coordenadas/instante por valor; el backend abre su propia conexión readonly si la necesita."""
        self.stop()
        generation = self._generation
        future = _EXECUTOR.submit(observe_sky, location["latitude"], location["longitude"], moment or datetime.now(UTC))
        self._future = future

        def deliver(done):
            """Entrega una señal; no accede al widget desde el executor."""
            if done.cancelled():
                return
            try:
                result, error = done.result(), ""
            except Exception as exc:
                logging.getLogger(__name__).exception("No se pudo leer el contexto solar/lunar")
                result, error = None, str(exc) or type(exc).__name__
            try:
                self._delivered.emit(generation, result, error)
            except RuntimeError:
                pass

        future.add_done_callback(deliver)

    def stop(self, *_args):
        """Invalida cualquier entrega pendiente sin bloquear el cierre ni interrumpir otros cálculos."""
        self._generation += 1
        if self._future is not None:
            self._future.cancel()
        self._future = None

    def _receive(self, generation, result, error):
        """Solo publica el resultado aún vigente, en el hilo principal."""
        if generation == self._generation:
            self._future = None
            self.ready.emit(result, error)
