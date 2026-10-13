"""PASS — Planning & Astronomical Stacking Suite.

Punto de entrada: ventana principal con las 6 pestañas del programa.
"""
import sys

from PyQt6.QtWidgets import QApplication

from pass_logging import (
    close_logging,
    configure_logging,
    install_exception_hooks,
    record_action,
)
from ui.action_logging import ActionLogger
from ui.main_window import MainWindow
from ui.style import apply_style


def main() -> None:
    """Abre la ventana sin descargas; los catálogos se gestionan en Configuración.

    No retorna: termina con ``sys.exit`` cuando el usuario cierra la ventana.
    """
    configure_logging()
    install_exception_hooks()
    record_action("inicio", "Inicio de PASS")
    app = QApplication(sys.argv)
    observer = ActionLogger(app)
    app._action_logger = observer
    apply_style(app)
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    code = app.exec()
    record_action("cierre", f"Cierre de PASS (código {code})")
    close_logging()
    sys.exit(code)


if __name__ == "__main__":
    main()
