"""PASS — Planning & Astronomical Stacking Suite.

Punto de entrada: ventana principal con las 6 pestañas del programa.
"""
import sys

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.style import apply_style


def main() -> None:
    """Abre la ventana sin descargas; los catálogos se gestionan en Configuración.

    No retorna: termina con ``sys.exit`` cuando el usuario cierra la ventana.
    """
    app = QApplication(sys.argv)
    apply_style(app)
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
