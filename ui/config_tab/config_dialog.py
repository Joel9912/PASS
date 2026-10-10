"""Diálogo «Configuración General de la Aplicación».

Se abre con el botón ⚙ de la barra lateral. Tres secciones en el nav:
«General» (motor SirIL y carpeta base de proyectos), «Clima» (API keys
de Clear Outside y Meteoblue) y «Equipo» (umbrales y margen «Ligero»
del muestreo del bloque Cálculos). «Guardar» escribe todo de una vez en
la tabla ``settings`` (nunca en código ni en el repositorio); «Cerrar» o
✕ descarta los cambios.

La comprobación de SirIL corre en un hilo aparte: el diálogo abre al
instante aunque arrancar ``siril-cli`` tarde (el antivirus puede
tardar ~1 s el primer día en examinar el proceso).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from db.settings import get_float, get_setting, set_setting
from planners.weather.base import load_api_key, save_api_key
from stacks.siril_finder import SETTINGS_KEY, find_siril, siril_version

#: Clave de ``settings`` para la carpeta base de proyectos.
PROJECT_ROOT_KEY = "project_root"

#: Colores de estado (mismos tonos que las tarjetas de clima).
_OK = "#22c55e"      # verde: detectado y operativo
_WARN = "#f59e0b"    # ámbar: falta algo o no responde
_ERROR = "#f85149"   # rojo: la ruta no existe
_BUSY = "#94a3b8"    # gris: comprobación en marcha

#: Un solo hilo de trabajo para comprobar SirIL. Ejecutar ``siril-cli
#: --version`` puede costar ~1 s el primer día (el antivirus examina el
#: proceso): eso **no** puede congelar el diálogo, así que corre aquí.
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="config-siril")


class _SirilBridge(QObject):
    """Devuelve la comprobación de SirIL al hilo de la interfaz.

    ``probe()`` se lanza desde el hilo de trabajo y emite ``checked``
    desde allí: como el diálogo vive en el hilo principal, Qt la encola
    (conexión automática) y el slot pinta el estado donde toca. Si el
    diálogo se cierra antes, Qt desconecta el slot solo.
    """

    checked = pyqtSignal(str, str)  # (ruta comprobada, versión o "")

    def probe(self, path: str) -> None:
        """Ejecuta ``siril_version(path)`` fuera del hilo de la interfaz."""
        future = _EXECUTOR.submit(siril_version, path)
        future.add_done_callback(lambda fut: self._emit(path, fut))

    def _emit(self, path: str, future) -> None:
        """Entrega (ruta, versión) a la señal; cualquier fallo crudo queda como «sin versión»."""
        try:
            version = future.result()
        except Exception:  # el hilo de trabajo jamás debe tumbar la UI
            version = None
        self.checked.emit(path, version or "")


#: Puente compartido: el diálogo solo se conecta, sin crear hilos por apertura.
_BRIDGE = _SirilBridge()


class ConfigDialog(QDialog):
    """Configuración general: SirIL, carpeta base y API keys del clima.

    Emite ``saved`` tras «Guardar» para que la ventana principal pueda
    refrescar el clima de Búsqueda si cambiaron las API keys.
    """

    saved = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta nav + páginas + pie y conecta la comprobación de SirIL."""
        super().__init__(parent)
        self.setWindowTitle("Configuración General de la Aplicación")
        self.setMinimumSize(860, 520)
        # La regla base `QWidget { background-color }` deja las etiquetas
        # con fondo negro sobre las tarjetas; aquí se transparentan (como
        # en el mockup). Global: decisión a proponer aparte.
        self.setStyleSheet(
            "QLabel { background: transparent; }"
            "QCheckBox { background: transparent; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(12)

        # Nav lateral (según el mockup: General, Clima y Equipo).
        self._nav = QListWidget()
        self._nav.setObjectName("ConfigNav")
        self._nav.setFixedWidth(170)
        self._nav.addItems(
            ["\U0001f527  General", "\U0001f324  Clima", "\U0001f52d  Equipo"]
        )
        body.addWidget(self._nav)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_general_page())
        self._stack.addWidget(self._build_clima_page())
        self._stack.addWidget(self._build_equipo_page())
        body.addWidget(self._stack, 1)
        root.addLayout(body, 1)

        # Pie: Guardar / Cerrar (abajo a la derecha, como el mockup).
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        save = QPushButton("Guardar")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self._save)
        footer.addWidget(save)
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.reject)
        footer.addWidget(close_button)
        root.addLayout(footer)

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

        # El estado de SirIL llega del hilo de trabajo por esta señal.
        _BRIDGE.checked.connect(self._on_siril_result)
        self.reload()

    # ------------------------------------------------------------ construcción
    @staticmethod
    def _group(title: str) -> tuple[QFrame, QVBoxLayout]:
        """Marco de sección con su título azul (estilo GroupFrame)."""
        frame = QFrame()
        frame.setObjectName("GroupFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 6, 12, 10)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("PanelTitle")
        layout.addWidget(title_label)
        return frame, layout

    @staticmethod
    def _field_row(field: QLineEdit, browse_slot) -> QWidget:
        """Campo de texto + botón «Examinar...» en una fila compacta."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(field, 1)
        browse = QPushButton("\U0001f4c1 Examinar...")
        browse.clicked.connect(browse_slot)
        row.addWidget(browse)
        wrapper = QWidget()
        wrapper.setLayout(row)
        return wrapper

    def _build_general_page(self) -> QWidget:
        """Página «General»: motor SirIL (ruta + estado) y carpeta base de proyectos."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # --- Motor de procesamiento (SirIL)
        siril_frame, siril_layout = self._group("Motor de Procesamiento (Siril)")
        form = QFormLayout()
        form.setSpacing(6)
        self._siril_path = QLineEdit()
        self._siril_path.setPlaceholderText(r"C:\Program Files\Siril\bin\siril-cli.exe")
        form.addRow("Ruta al ejecutable:", self._field_row(self._siril_path, self._browse_siril))
        self._siril_status = QLabel("")
        self._siril_status.setWordWrap(True)
        form.addRow("", self._siril_status)
        siril_layout.addLayout(form)
        layout.addWidget(siril_frame)

        # --- Carpeta base de proyectos
        project_frame, project_layout = self._group("Carpeta Base de Proyectos")
        project_form = QFormLayout()
        project_form.setSpacing(6)
        self._project_root = QLineEdit()
        self._project_root.setPlaceholderText(r"D:\Astrofotografía")
        project_form.addRow(
            "Directorio raíz:",
            self._field_row(self._project_root, self._browse_project_root),
        )
        project_layout.addLayout(project_form)
        hint = QLabel("Esta carpeta servirá de inicio al examinar y organizar "
                      "tus sesiones nocturnas.")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        project_layout.addWidget(hint)
        layout.addWidget(project_frame)

        layout.addStretch(1)
        return page

    def _build_clima_page(self) -> QWidget:
        """Página «Clima»: API keys ocultas con la opción de mostrarlas."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        weather_frame, weather_layout = self._group("API keys del clima")
        form = QFormLayout()
        form.setSpacing(6)

        self._clear_outside_key = QLineEdit()
        self._clear_outside_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._clear_outside_key.setPlaceholderText("Sin API key")
        form.addRow("Clear Outside:", self._clear_outside_key)

        self._meteoblue_key = QLineEdit()
        self._meteoblue_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._meteoblue_key.setPlaceholderText("Sin API key")
        form.addRow("Meteoblue:", self._meteoblue_key)

        self._show_keys = QCheckBox("Mostrar las claves")
        self._show_keys.toggled.connect(self._toggle_keys)
        form.addRow("", self._show_keys)
        weather_layout.addLayout(form)

        hint = QLabel(
            "Se guardan en la base local (tabla settings), nunca en el código "
            "ni en el repositorio. Sin clave, el clima muestra «Sin datos»."
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        weather_layout.addWidget(hint)
        layout.addWidget(weather_frame)

        layout.addStretch(1)
        return page

    def _build_equipo_page(self) -> QWidget:
        """Página «Equipo»: los umbrales y el margen «Ligero» del muestreo.

        Las métricas las define el usuario (decisión suya): estos números
        deciden las 5 etiquetas del bloque «Cálculos» — de «Submuestreado»
        a «Sobremuestreado» pasando por los dos «Ligero»
        (``equipment.metrics.veredicto_muestreo``). Se guardan con el
        mismo «Guardar» del diálogo y el bloque «Cálculos» los relee en
        cada recálculo, así que no hay que cablear la señal ``saved``.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        frame, frame_layout = self._group("Muestreo")
        form = QFormLayout()
        form.setSpacing(6)

        self._sampling_under = QDoubleSpinBox()
        self._sampling_under.setRange(0.01, 10.0)
        self._sampling_under.setDecimals(2)
        self._sampling_under.setSingleStep(0.05)
        self._sampling_under.setSuffix(" ×")
        self._sampling_under.setToolTip(
            "Marca el alto del rango adecuado (× la resolución de Dawes): "
            "por encima empieza «Submuestreado Ligero» y más allá del "
            "margen «Ligero», «Submuestreado»."
        )
        form.addRow("Umbral de submuestreo (× Dawes):", self._sampling_under)

        self._sampling_over = QDoubleSpinBox()
        self._sampling_over.setRange(0.01, 10.0)
        self._sampling_over.setDecimals(2)
        self._sampling_over.setSingleStep(0.05)
        self._sampling_over.setSuffix(" ×")
        self._sampling_over.setToolTip(
            "Marca el bajo del rango adecuado (× Dawes): por debajo "
            "empieza «Sobremuestreado Ligero» y más allá del margen "
            "«Ligero», «Sobremuestreado»."
        )
        form.addRow("Umbral de sobremuestreo (× Dawes):", self._sampling_over)

        self._sampling_light = QDoubleSpinBox()
        self._sampling_light.setRange(1.0, 5.0)
        self._sampling_light.setDecimals(2)
        self._sampling_light.setSingleStep(0.05)
        self._sampling_light.setSuffix(" ×")
        self._sampling_light.setToolTip(
            "Margen «Ligero»: hasta este múltiplo del borde del rango "
            "adecuado la etiqueta lleva «Ligero»; más allá, el nivel "
            "completo. 1,0 = sin niveles intermedios."
        )
        form.addRow("Margen «Ligero» (× el borde del rango):", self._sampling_light)

        frame_layout.addLayout(form)
        hint = QLabel(
            "Los decide el usuario: la escala ″/px se compara con estos "
            "múltiplos de la resolución de Dawes y con el margen «Ligero» "
            "sobre el borde del rango. El bloque «Cálculos» de la pestaña "
            "Equipo los relee en cada cálculo."
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        frame_layout.addWidget(hint)
        layout.addWidget(frame)

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ valores
    def reload(self) -> None:
        """Rellena los campos con ``settings`` y comprueba SirIL sin bloquear.

        Lo llama ``MainWindow._show_settings`` al reabrir: el diálogo se
        crea una sola vez y se reutiliza en vez de montarse otra vez.
        """
        path = find_siril(get_setting(SETTINGS_KEY) or None) or ""
        self._siril_path.setText(path)
        self._project_root.setText(get_setting(PROJECT_ROOT_KEY) or "")
        self._clear_outside_key.setText(load_api_key("clear_outside_api_key") or "")
        self._meteoblue_key.setText(load_api_key("meteoblue_api_key") or "")
        self._sampling_under.setValue(get_float("sampling_under_ratio", 1.0))
        self._sampling_over.setValue(get_float("sampling_over_ratio", 0.5))
        self._sampling_light.setValue(get_float("sampling_light_factor", 1.4))
        self._check_siril(path)

    def _check_siril(self, path: str) -> None:
        """«✓ detectado y operativo» con la versión real, **sin congelar la UI**.

        Los avisos malos salen ya mismo (no hay que arrancar nada) y lo
        único que puede tardar — ``siril-cli --version`` — corre en el
        hilo de trabajo; el resultado vuelve por ``_on_siril_result``.
        """
        if not path:
            self._set_siril_status(
                "⚠ No se encontró SirIL. Usa «Examinar...» para indicar la ruta del cliente.",
                _WARN,
            )
            return
        if not Path(path).is_file():
            self._set_siril_status("⚠ La ruta no existe: usa «Examinar...».", _ERROR)
            return
        self._set_siril_status("⏳ Comprobando SirIL…", _BUSY)
        _BRIDGE.probe(path)

    def _on_siril_result(self, path: str, version: str) -> None:
        """Pinta lo que dijo ``siril_version`` (señal encolada desde el hilo).

        Solo si sigue mandando la ruta del campo: una sonda lenta de una
        ruta vieja no debe pintar sobre la actual (M-23 de la auditoría).
        """
        if path != self._siril_path.text().strip():
            return
        if version:
            self._set_siril_status(f"✓ {version} detectado y operativo.", _OK)
        else:
            self._set_siril_status(
                f"⚠ Encontrado en {path}, pero no responde a --version.", _WARN
            )

    def _set_siril_status(self, text: str, color: str) -> None:
        """Pinta el mensaje de SirIL teñido con su color de estado."""
        self._siril_status.setText(text)
        self._siril_status.setStyleSheet(f"color: {color};")

    # ------------------------------------------------------------------ acciones
    def _browse_siril(self) -> None:
        """Selector de fichero para la ruta de SirIL; al elegirla se comprueba ya."""
        start = self._siril_path.text().strip() or None
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar el ejecutable de SirIL",
            start or "",
            "Ejecutables (*.exe);;Todos los archivos (*.*)",
        )
        if path:
            self._siril_path.setText(path)
            self._check_siril(path)

    def _browse_project_root(self) -> None:
        """Selector de carpeta para la raíz de proyectos (solo escribe la ruta)."""
        start = self._project_root.text().strip() or None
        path = QFileDialog.getExistingDirectory(
            self, "Seleccionar la carpeta base de proyectos", start or ""
        )
        if path:
            self._project_root.setText(path)

    def _toggle_keys(self, checked: bool) -> None:
        """«Mostrar las claves»: alterna las dos contraseñas entre visible y oculta."""
        mode = (
            QLineEdit.EchoMode.Normal
            if checked
            else QLineEdit.EchoMode.Password
        )
        self._clear_outside_key.setEchoMode(mode)
        self._meteoblue_key.setEchoMode(mode)

    def _save(self) -> None:
        """Escribe todo de una vez en ``settings`` y avisa a la ventana."""
        set_setting(SETTINGS_KEY, self._siril_path.text().strip())
        set_setting(PROJECT_ROOT_KEY, self._project_root.text().strip())
        save_api_key("clear_outside_api_key", self._clear_outside_key.text().strip())
        save_api_key("meteoblue_api_key", self._meteoblue_key.text().strip())
        set_setting("sampling_under_ratio", str(self._sampling_under.value()))
        set_setting("sampling_over_ratio", str(self._sampling_over.value()))
        set_setting("sampling_light_factor", str(self._sampling_light.value()))
        self._check_siril(self._siril_path.text().strip())
        QMessageBox.information(self, "Configuración", "Configuración guardada.")
        self.saved.emit()
