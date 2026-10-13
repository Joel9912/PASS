"""Registro local persistente de acciones y errores, separado para el Apilador."""

import logging
import re
import sys
import threading
from contextvars import ContextVar
from pathlib import Path

from db import connection

MAX_LOG_LINES = 2000
LOG_PERSISTED: ContextVar[bool] = ContextVar("pass_log_persisted", default=False)
_handlers: list[logging.Handler] = []
_directory: Path | None = None
_lock = threading.RLock()


def _redact(text: str) -> str:
    """Oculta credenciales etiquetadas y tokens de autorización antes de escribir."""
    text = re.sub(
        r'''(?i)(api[_-]?key|password|contraseña|token|secret)(["']?\s*[=:]\s*)("[^"]*"|'[^']*'|[^\s,;&]+)''',
        r"\1\2[oculto]", text,
    )
    return re.sub(r"(?i)(Bearer\s+)\S+", r"\1[oculto]", text)


class _Formatter(logging.Formatter):
    """Redacta también tracebacks sin modificar el LogRecord compartido."""

    def format(self, record):
        """Añade fecha, nivel y origen a cada evento persistente."""
        return _redact(super().format(record))


class _SectionFilter(logging.Filter):
    """Envía los módulos del Apilador a su archivo y los demás al general."""

    def __init__(self, stacker: bool):
        """Fija la sección que admite este handler."""
        super().__init__()
        self.stacker = stacker

    def filter(self, record):
        """Evita duplicar los mensajes de SirIL en el archivo general."""
        stacker = record.name.startswith(("stacks.", "ui.stacker_tab", "pass.apilador"))
        return stacker == self.stacker


def configure_logging() -> Path:
    """Abre ambos archivos en append; permite reconfigurar el destino del sandbox."""
    global _directory
    directory = connection.DATA_DIR / "logs"
    with _lock:
        if _directory == directory and _handlers:
            return directory
        close_logging()
        directory.mkdir(parents=True, exist_ok=True)
        try:
            for name, stacker in (("pass.log", False), ("apilador.log", True)):
                handler = logging.FileHandler(directory / name, encoding="utf-8")
                handler.setFormatter(_Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
                handler.addFilter(_SectionFilter(stacker))
                logging.getLogger().addHandler(handler)
                _handlers.append(handler)
        except OSError:
            close_logging()
            raise
        _directory = directory
    return directory


def close_logging() -> None:
    """Libera únicamente handlers de PASS, sin alterar los de otros consumidores."""
    global _directory
    with _lock:
        for handler in _handlers:
            logging.getLogger().removeHandler(handler)
            handler.close()
        _handlers.clear()
        _directory = None


def record_action(section: str, message: str, *, level: int = logging.INFO) -> None:
    """Persiste un evento incluso desde workers y sin depender de una UI abierta."""
    configure_logging()
    logger = logging.getLogger("pass.apilador" if section == "apilador" else "pass.general")
    logger.setLevel(logging.INFO)
    logger.log(level, "[%s] %s", section, message)


def install_exception_hooks() -> None:
    """Conserva tracebacks no manejados de Python/Qt y workers, además de stderr."""
    previous = sys.excepthook
    previous_thread = threading.excepthook

    def exception_hook(kind, value, traceback):
        """Registra el error sin suprimir el comportamiento previo de Python."""
        logging.getLogger(_exception_logger(traceback)).error("Excepción no manejada", exc_info=(kind, value, traceback))
        previous(kind, value, traceback)

    def thread_hook(args):
        """Incluye el traceback de un hilo que termina inesperadamente."""
        logging.getLogger(_exception_logger(args.exc_traceback)).error(
            "Excepción en hilo %s", args.thread.name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        previous_thread(args)

    sys.excepthook = exception_hook
    threading.excepthook = thread_hook


def _exception_logger(traceback) -> str:
    """Enruta al Apilador las excepciones cuyo traceback pasa por su código."""
    while traceback is not None:
        module = traceback.tb_frame.f_globals.get("__name__", "")
        if module.startswith(("stacks.", "ui.stacker_tab")):
            return "pass.apilador"
        traceback = traceback.tb_next
    return "pass.general"
