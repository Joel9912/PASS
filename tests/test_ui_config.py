"""Regresiones de UI del diálogo de Configuración (sonda SirIL, clima y guardado).

La ``QApplication`` viene del fixture ``qt_app`` de ``conftest.py``.
"""

import pytest

pytestmark = pytest.mark.usefixtures("qt_app")


def _config_dialog(monkeypatch, find_path, *, real_probe=False):
    """Crea un ``ConfigDialog`` de prueba: sin BD y con SirIL simulado.

    Devuelve ``(módulo, diálogo, probed)``; ``probed`` registra las rutas
    mandadas a comprobar. Con ``real_probe`` no se intercepta la sonda y
    el hilo de trabajo va de verdad (para probar la señal de vuelta).
    """

    from ui.config_tab import config_dialog as cd

    probed: list[str] = []
    monkeypatch.setattr(cd, "find_siril", lambda _ruta_guardada=None: find_path)
    monkeypatch.setattr(cd, "get_setting", lambda _key: "")
    monkeypatch.setattr(cd, "load_api_key", lambda _key: "")
    if not real_probe:
        monkeypatch.setattr(cd._BRIDGE, "probe", lambda path: probed.append(path))
    return cd, cd.ConfigDialog(), probed

def test_config_dialog_check_is_async(tmp_path, monkeypatch):
    """Configuración abre sin esperar a SirIL (estado «Comprobando…»).

    Regresión del «lagaso» de ~1,5 s al pulsar ⚙: el constructor
    ejecutaba ``siril-cli --version`` en el hilo de la interfaz (el
    antivirus puede costar ~1 s el primer día en examinar el proceso)
    y el diálogo tardaba en aparecer. Ahora la comprobación va por
    ``_BRIDGE.probe`` (hilo de trabajo) y la UI se pinta con el estado
    provisorio.
    """
    fake = tmp_path / "siril-cli.exe"
    fake.write_text("", encoding="utf-8")

    cd, dialog, probed = _config_dialog(monkeypatch, str(fake))

    assert probed == [str(fake)]                         # la comprobación va al hilo
    assert "Comprobando" in dialog._siril_status.text()  # ...y no ha vuelto aún
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)


def test_config_ruta_editada_invalida_estado(qt_app, tmp_path, monkeypatch):
    """C-0003: editar la ruta retira el éxito previo y comprueba al terminar."""
    fake = tmp_path / "siril-cli.exe"
    fake.write_text("", encoding="utf-8")
    cd, dialog, probed = _config_dialog(monkeypatch, str(fake))
    dialog._on_siril_result(str(fake), "siril 1.4.4")
    dialog._siril_path.setText(str(tmp_path / "ausente.exe"))
    assert "✓" not in dialog._siril_status.text()
    dialog._siril_path.editingFinished.emit()
    assert "no existe" in dialog._siril_status.text()
    dialog._siril_path.setText(str(fake))
    dialog._siril_path.editingFinished.emit()
    assert probed == [str(fake), str(fake)]
    assert "Comprobando" in dialog._siril_status.text()
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)
    dialog.deleteLater()


def test_config_limites_invertidos_no_guardan(qt_app, memory_db, monkeypatch):
    """C-0001: límites invertidos avisan sin persistir ni emitir éxito."""
    from db.settings import get_setting, set_setting

    set_setting("project_root", "anterior")
    cd, dialog, _ = _config_dialog(monkeypatch, None)
    dialog._project_root.setText("nuevo")
    dialog._sampling_over.setValue(2.0)
    dialog._sampling_under.setValue(1.0)
    avisos, exitos = [], []
    monkeypatch.setattr(cd.QMessageBox, "warning", lambda *args: avisos.append(args))
    monkeypatch.setattr(cd.QMessageBox, "information", lambda *args: exitos.append(args))
    dialog.saved.connect(lambda: exitos.append(True))
    dialog._save()
    assert avisos
    assert not exitos
    assert get_setting("project_root") == "anterior"
    assert dialog._sampling_over.value() == 2.0
    dialog._sampling_over.setValue(1.0)
    dialog._save()
    assert get_setting("project_root") == "nuevo"
    assert exitos
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)
    dialog.deleteLater()


def test_config_fallo_intermedio_revierte_todo(qt_app, memory_db, monkeypatch):
    """C-0002: un fallo SQLite conserva todas las claves y no anuncia éxito."""
    from db.settings import get_setting, set_setting

    set_setting("project_root", "anterior")
    set_setting("siril_path", "ruta anterior")
    memory_db.execute("""CREATE TRIGGER rechazar_clima BEFORE INSERT ON settings
        WHEN NEW.key = 'meteoblue_api_key'
        BEGIN SELECT RAISE(ABORT, 'fallo simulado'); END""")
    memory_db.commit()
    cd, dialog, _ = _config_dialog(monkeypatch, None)
    dialog._project_root.setText("nuevo")
    avisos, exitos = [], []
    monkeypatch.setattr(cd.QMessageBox, "warning", lambda *args: avisos.append(args))
    monkeypatch.setattr(cd.QMessageBox, "information", lambda *args: exitos.append(args))
    dialog.saved.connect(lambda: exitos.append(True))
    dialog._save()
    assert avisos
    assert not exitos
    assert get_setting("project_root") == "anterior"
    assert get_setting("siril_path") == "ruta anterior"
    assert get_setting("clear_outside_api_key") is None
    assert dialog._project_root.text() == "nuevo"
    assert not memory_db.in_transaction
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)
    dialog.deleteLater()


def test_config_dialog_no_siril_warns_instantly(monkeypatch):
    """Sin SirIL el aviso sale ya mismo: ni hilo ni subproceso."""
    cd, dialog, probed = _config_dialog(monkeypatch, None)

    assert probed == []
    assert "No se encontró SirIL" in dialog._siril_status.text()
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)


def test_config_dialog_bad_path_errors_instantly(monkeypatch):
    """Ruta inventada: «La ruta no existe» sin intentar arrancar nada."""
    cd, dialog, probed = _config_dialog(
        monkeypatch, r"C:\ruta\fantasma\siril-cli.exe"
    )

    assert probed == []
    assert "La ruta no existe" in dialog._siril_status.text()
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)


def test_config_dialog_result_paints_status(tmp_path, monkeypatch):
    """El resultado del hilo pinta verde con versión y ámbar si falla."""
    fake = tmp_path / "siril-cli.exe"
    fake.write_text("", encoding="utf-8")

    cd, dialog, _probed = _config_dialog(monkeypatch, str(fake))

    dialog._on_siril_result(str(fake), "siril 1.4.4")
    assert dialog._siril_status.text() == "✓ siril 1.4.4 detectado y operativo."

    dialog._on_siril_result(str(fake), "")
    assert "no responde a --version" in dialog._siril_status.text()
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)


def test_config_dialog_result_descarta_ruta_vieja(tmp_path, monkeypatch):
    """M-23: una sonda lenta de una ruta vieja no pinta sobre la actual.

    El usuario cambia de ruta mientras la comprobación anterior sigue en
    el hilo de trabajo: su resultado («Encontrado en <vieja>…» o versión)
    ya no representa el campo y se descarta.
    """
    fake = tmp_path / "siril-cli.exe"
    fake.write_text("", encoding="utf-8")

    cd, dialog, _probed = _config_dialog(monkeypatch, str(fake))

    estado = dialog._siril_status.text()          # «Comprobando…» de la actual
    dialog._on_siril_result(r"C:\vieja\siril-cli.exe", "siril 1.0")
    assert dialog._siril_status.text() == estado  # resultado viejo: descartado

    dialog._on_siril_result(str(fake), "siril 1.4.4")
    assert "siril 1.4.4" in dialog._siril_status.text()   # la actual sí manda
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)


def test_config_dialog_probe_reaches_ui(qt_app, tmp_path, monkeypatch):
    """El hilo de trabajo devuelve la versión y la señal la pinta en la UI."""
    import time

    from ui.config_tab import config_dialog as cd

    fake = tmp_path / "siril-cli.exe"
    fake.write_text("", encoding="utf-8")

    monkeypatch.setattr(cd, "siril_version", lambda _path: "siril 9.9.9")
    cd, dialog, _probed = _config_dialog(monkeypatch, str(fake), real_probe=True)

    app = qt_app
    for _ in range(300):  # hasta ~3 s: el hilo acaba y la señal se encola
        app.processEvents()
        if "siril 9.9.9" in dialog._siril_status.text():
            break
        time.sleep(0.01)
    assert dialog._siril_status.text() == "✓ siril 9.9.9 detectado y operativo."
    cd._BRIDGE.checked.disconnect(dialog._on_siril_result)


def test_show_settings_keeps_one_dialog(qt_app, monkeypatch):
    """⚙ crea el diálogo una sola vez: reabrir solo lo refresca (``reload``)."""

    from ui.config_tab import ConfigDialog
    from ui.config_tab import config_dialog as cd
    from ui.main_window import MainWindow

    _app = qt_app

    monkeypatch.setattr(cd, "find_siril", lambda _ruta_guardada=None: None)
    monkeypatch.setattr(cd, "get_setting", lambda _key: "")
    monkeypatch.setattr(cd, "load_api_key", lambda _key: "")

    created: list[object] = []
    original_init = ConfigDialog.__init__

    def counting_init(self, parent=None):
        """Sustituto de `ConfigDialog.__init__` que cuenta cuántas veces se construye."""
        created.append(self)
        original_init(self, parent)

    reloaded: list[object] = []
    original_reload = ConfigDialog.reload

    def counting_reload(self):
        """Sustituto de `ConfigDialog.reload` que cuenta cuántas veces se recarga."""
        reloaded.append(self)
        original_reload(self)

    monkeypatch.setattr(ConfigDialog, "__init__", counting_init)
    monkeypatch.setattr(ConfigDialog, "reload", counting_reload)
    monkeypatch.setattr(ConfigDialog, "exec", lambda self: None)  # sin modal

    window = MainWindow()
    window._show_settings()
    window._show_settings()

    assert len(created) == 1     # una sola construcción…
    assert len(reloaded) == 2    # ...pero los valores se recargan al reabrir
    window.close()
