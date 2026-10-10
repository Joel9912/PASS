"""PASS — Planning & Astronomical Stacking Suite.

Entry point: ventana principal con las 6 pestañas del programa.
"""
import sys

from PyQt6.QtWidgets import QApplication

from planners.catalog_loader import ensure_catalog
from ui.main_window import MainWindow
from ui.style import apply_style


def main() -> None:
    """Precarga el catálogo, monta la ventana principal y ejecuta el bucle de Qt.

    No retorna: termina con ``sys.exit`` cuando el usuario cierra la ventana.
    """
    # Primera ejecución: descarga y carga OpenNGC + estrellas HYG (~18 MB).
    # Si no hay red, se imprime un aviso y el programa sigue funcionando.
    ensure_catalog()

    app = QApplication(sys.argv)
    apply_style(app)
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
