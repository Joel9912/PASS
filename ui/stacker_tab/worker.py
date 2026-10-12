"""Hilo de trabajo para las corridas largas de SirIL (Worker + QThread).

La ventana no se congela: cada tarea corre en un ``QThread`` propio y se
comunica con la UI por señales Qt (conexiones en cola al hilo principal).
La cancelación mata el proceso SirIL en curso (``siril_runner.cancelar_siril``);
si la tarea terminó con la cancelación ya pedida se emite ``fallo`` con el
motivo de cancelación, nunca ``fin``: el resultado ya no es fiable.
"""
from collections.abc import Callable

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot

from stacks.siril_runner import cancelar_siril

#: Motivo de fallo cuando la parada la pidió el usuario (no un error real).
CANCELADO = "Corrida cancelada por el usuario."


class SirilWorker(QObject):
    """Tarea única ejecutada en su hilo; informa a la UI por señales.

    La tarea es un callable que recibe ``progress_cb(fraccion)`` (0..1) y
    ``log_cb(linea)`` y devuelve cualquier objeto, que se emite por ``fin``.
    """

    log = pyqtSignal(str)      # línea del log de SirIL (o del propio flujo)
    progreso = pyqtSignal(int)  # 0..100, para QProgressBar
    fin = pyqtSignal(object)    # resultado de la tarea
    fallo = pyqtSignal(str)     # motivo (error real o cancelación)

    def __init__(
        self, tarea: Callable[..., object], parent: QObject | None = None
    ) -> None:
        """Guarda la tarea y arranca en estado no cancelado."""
        super().__init__(parent)
        self._tarea = tarea
        self._cancelado = False

    def cancelar(self) -> None:
        """Pide parar: mata SirIL si corre y descarta el resultado final."""
        self._cancelado = True
        cancelar_siril()

    @pyqtSlot()
    def run(self) -> None:
        """Ejecuta la tarea; nunca lanza: los errores salen por ``fallo``."""
        if self._cancelado:
            self.fallo.emit(CANCELADO)
            return
        try:
            resultado = self._tarea(
                progress_cb=lambda f: self.progreso.emit(
                    min(max(int(round(f * 100)), 0), 100)
                ),
                log_cb=self.log.emit,
            )
        except Exception as exc:
            # El error viaja como texto: la UI lo pinta en el log/estado.
            motivo = (
                CANCELADO
                if self._cancelado
                else (str(exc) or type(exc).__name__)
            )
            self.fallo.emit(motivo)
        else:
            if self._cancelado:
                self.fallo.emit(CANCELADO)
            else:
                self.fin.emit(resultado)


def arrancar_en_hilo(
    tarea: Callable[..., object],
    *,
    al_log: Callable[[str], None],
    al_progreso: Callable[[int], None],
    al_fin: Callable[[object], None],
    al_fallo: Callable[[str], None],
    contenedor: QObject,
    al_liberar: Callable[[QThread], None] | None = None,
) -> tuple[QThread, SirilWorker]:
    """Crea el hilo + worker, conecta sus señales a ``contenedor`` y lo arranca.

    Devuelve (hilo, worker): el llamador los guarda para poder cancelar
    (``worker.cancelar()``) y para limpiar al terminar. Las conexiones
    ``fin``/``fallo`` también cierran el hilo (``quit``) y programan el
    borrado de ambos objetos (``deleteLater``).

    ``al_liberar(hilo)`` se ejecuta cuando Qt emite ``finished``: la referencia
    se suelta ahí, no al recibir el resultado, porque entre medias el hilo
    sigue corriendo y un ``wait()`` posterior lo necesitaría vivo.
    """
    hilo = QThread(contenedor)
    worker = SirilWorker(tarea)
    worker.moveToThread(hilo)
    hilo.started.connect(worker.run)
    worker.log.connect(al_log)
    worker.progreso.connect(al_progreso)
    worker.fin.connect(hilo.quit)
    worker.fallo.connect(hilo.quit)
    worker.fin.connect(al_fin)
    worker.fallo.connect(al_fallo)
    if al_liberar is not None:
        # Encolada al hilo principal y antes de deleteLater: la referencia se
        # suelta en la UI y una tarea instantánea no debe perder la señal.
        hilo.finished.connect(
            lambda h=hilo: al_liberar(h), Qt.ConnectionType.QueuedConnection
        )
    hilo.finished.connect(worker.deleteLater)
    hilo.finished.connect(hilo.deleteLater)
    hilo.start()
    return hilo, worker
