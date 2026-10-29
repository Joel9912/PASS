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


def test_terminal_oculta_ruido_tecnico_conocido(qt_app):
    """La presentación resume SirIL sin llenar la terminal con detalles por toma."""
    from PyQt6.QtWidgets import QPlainTextEdit

    from ui.stacker_tab import StackerPage

    terminal = QPlainTextEdit()
    page = SimpleNamespace(_terminal=terminal)
    noise = [
        '', '   ', 'T', '1793242876: running command cd',
        'Origen → enlace: original.fits → working/light.fits',
        'Guion SirIL (working): requires 1.4\ncd "working"\nlink light',
        'log: Reading configuration file working/siril.ini',
        'log: Welcome to siril 1.4.4 for windows',
        'log: Supported file types: FITS, RAW',
        "log: Setting CWD (Current Working Directory) to 'working'",
        'log: Parallel processing enabled: using 12 logical processors.',
        'log: Color management active.', 'log: JPEG ICC profiles supported.',
        'log: Running command: calibrate', 'log: OK! This script is compatible with this version of Siril.',
        'log: Link: processing 14 FITS files...',
        'Writing sequence file light_.seq', 'Reading sequence file `light_.seq\'.',
        'Sequence found: light_ 1->14', 'bitpix for the sequence is set as 20',
        'Memory per image: 45 MB. Max memory: 4993 MB',
        'log: Preprocessing: with the current memory and thread limits, up to 12 thread(s) can be used',
        'log: Normalisation value auto evaluated: 0.028',
        'log: Preprocessing...', 'log: Preprocessing: processing...',
        'log: Reading FITS: file light_00001.fit, 1 layer(s), 6000x4000 pixels, 32 bits',
        'log: Saving FITS: file pp_light_00001.fit, 1 layer(s), 6000x4000 pixels, 32 bits',
        'log: Preparing python virtual environment: siril/venv.',
        'log: Checking the python module is up-to-date...', 'log: Python module is up-to-date',
        'progress: Converting files, 0.00%',
        'progress: Preprocessing. Processing image 1 (light_00001.fit), 6.99%',
        'progress: , 100.00%', 'progress: Sequence processing succeeded., 0.00%',
        'closing pipes',
    ]
    try:
        for line in noise:
            StackerPage._log(page, line)
        assert terminal.toPlainText() == ''
    finally:
        terminal.close()


def test_terminal_conserva_avisos_errores_y_mensajes_desconocidos(qt_app):
    """El filtro es conservador: formatos nuevos y fallos no desaparecen por parecer técnicos."""
    from PyQt6.QtWidgets import QPlainTextEdit

    from ui.stacker_tab import StackerPage

    terminal = QPlainTextEdit()
    page = SimpleNamespace(_terminal=terminal)
    lines = [
        '━━ Calibrando sesión (1/3) ━━', 'Máster dark (sesión): master_dark.fit',
        '⚠ El máster de dark ya incluye el bias', 'BD: sesión guardada (14 lights).',
        'log: Total execution time: 7.29 s', 'log: Sequence processing succeeded.',
        'log: Reading FITS: error opening file', 'log: Preprocessing: failed to read image',
        'log: Reading FITS: No such file or directory', 'log: Reading FITS: mensaje desconocido',
        'progress: warning: incomplete conversion, 50.00%', 'log: Running command: error detected',
        'Cancelado.', '✗ No se pudo guardar', 'Traceback (most recent call last):',
        '2026 es un dato útil', 'Temperatura: -10 °C', 't', 'T nueva información',
        'Mensaje nuevo de SirIL',
    ]
    try:
        for line in lines:
            StackerPage._log(page, line)
        assert terminal.toPlainText().splitlines() == lines
    finally:
        terminal.close()


def test_filtro_visual_no_elimina_detalle_del_archivo(qt_app, tmp_path, monkeypatch):
    """El worker persiste el mensaje completo antes de que la UI oculte el ruido."""
    from PyQt6.QtWidgets import QPlainTextEdit

    from ui.stacker_tab import StackerPage
    from ui.stacker_tab.worker import SirilWorker

    monkeypatch.setattr(connection, 'DATA_DIR', tmp_path)
    terminal = QPlainTextEdit()
    page = SimpleNamespace(_terminal=terminal)
    lines = ['Origen → enlace: input.fits → working.fits', 'T', '1793242876: running command cd', '⚠ Aviso importante']

    def task(progress_cb, log_cb):
        """Emite detalle sintético, sin SirIL ni archivos del usuario."""
        for line in lines:
            log_cb(line)
        progress_cb(1.)

    worker = SirilWorker(task)
    worker.log.connect(lambda line: StackerPage._log(page, line))
    try:
        worker.run()
        text = (tmp_path / 'logs/apilador.log').read_text(encoding='utf-8')
        assert all(line in text for line in lines)
        assert terminal.toPlainText() == '⚠ Aviso importante'
    finally:
        terminal.close()
        close_logging()


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
