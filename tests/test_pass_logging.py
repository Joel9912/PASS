"""Verifica persistencia, separación y protección del registro local de PASS."""

import logging
import sys
import threading
from types import SimpleNamespace

from db import connection
from pass_logging import close_logging, configure_logging, record_action


def test_logs_separados_append_y_redaccion(tmp_path, monkeypatch):
    """Reabrir no trunca el historial y los mensajes no mezclan secciones."""
    monkeypatch.setattr(connection, "DATA_DIR", tmp_path)
    try:
        directory = configure_logging()
        record_action("equipo", "Guardar equipo api_key=privado")
        record_action("clima", '{"token": "secreto con espacios"}; Bearer credencial')
        record_action("apilador", "SirIL: primer frame")
        logging.getLogger("stacks.calibrator").warning("Aviso de calibración")
        close_logging()
        record_action("apilador", "SirIL: segundo frame")
        general = (directory / "pass.log").read_text(encoding="utf-8")
        stacker = (directory / "apilador.log").read_text(encoding="utf-8")
        assert "Guardar equipo" in general and "privado" not in general
        assert "secreto" not in general and "credencial" not in general
        assert "SirIL" not in general
        assert "primer frame" in stacker and "segundo frame" in stacker
        assert "Aviso de calibración" in stacker
        assert "Guardar equipo" not in stacker
    finally:
        close_logging()


def test_acciones_y_avisos_ui(qt_app, tmp_path, monkeypatch):
    """Observa clicks por teclado/ratón y avisos sin leer campos del formulario."""
    from PyQt6.QtWidgets import QMessageBox, QPushButton, QWidget

    from ui.action_logging import ActionLogger

    monkeypatch.setattr(connection, "DATA_DIR", tmp_path)
    observer = ActionLogger(qt_app)
    widget = QWidget()
    button = QPushButton("Guardar", widget)
    widget.show()
    qt_app.processEvents()
    button.click()
    message = QMessageBox(QMessageBox.Icon.Warning, "Error", "Guardado fallido", parent=widget)
    message.show()
    qt_app.processEvents()
    try:
        text = (tmp_path / "logs" / "pass.log").read_text(encoding="utf-8")
        assert "Acción: Guardar" in text
        assert "Guardado fallido" in text
    finally:
        message.close()
        widget.close()
        qt_app.removeEventFilter(observer)
        observer.deleteLater()
        close_logging()


def test_terminal_apilador_acotado(qt_app):
    """S-0018: el documento visible descarta bloques viejos sin crecer indefinidamente."""
    from pass_logging import MAX_LOG_LINES
    from ui.stacker_tab import StackerPage

    page = StackerPage()
    try:
        for index in range(MAX_LOG_LINES + 50):
            page._log(f"mensaje {index}")
        assert page._terminal.document().blockCount() == MAX_LOG_LINES
        assert "mensaje 0\n" not in page._terminal.toPlainText()
        assert f"mensaje {MAX_LOG_LINES + 49}" in page._terminal.toPlainText()
    finally:
        page.deleteLater()


def test_excepciones_con_traceback_y_hooks_previos(tmp_path, monkeypatch):
    """Los errores no manejados se pueden trazar sin suprimir los hooks originales."""
    from pass_logging import install_exception_hooks

    monkeypatch.setattr(connection, "DATA_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: calls.append("main"))
    monkeypatch.setattr(threading, "excepthook", lambda args: calls.append("thread"))
    configure_logging()
    install_exception_hooks()
    try:
        try:
            raise ValueError("token=privado")
        except ValueError:
            kind, value, traceback = sys.exc_info()
            sys.excepthook(kind, value, traceback)
            threading.excepthook(SimpleNamespace(
                exc_type=kind, exc_value=value, exc_traceback=traceback,
                thread=SimpleNamespace(name="worker-controlado"),
            ))
        text = (tmp_path / "logs" / "pass.log").read_text(encoding="utf-8")
        assert "Traceback" in text and "ValueError" in text and "worker-controlado" in text
        assert "privado" not in text
        assert calls == ["main", "thread"]
    finally:
        close_logging()
