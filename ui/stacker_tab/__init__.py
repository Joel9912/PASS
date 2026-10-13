"""Pestaña Apilador: asistente de un paso que orquesta todo el flujo de SirIL.

Flujo fijo (decisión del usuario): **Sesiones → Calibrar → Auditar → Apilar →
Final**, con barra de pasos, progreso + log en vivo, «Siguiente» que ejecuta la
fase actual (o la salta si ya está hecha) y «Hacer todo» que encadena todo el
recorrido. Cada fase corre en un ``QThread`` (``worker.SirilWorker``): la
ventana nunca se congela y «Cancelar» mata la corrida de SirIL en curso.
"""
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from db.settings import PROJECT_ROOT_KEY, get_setting, set_setting
from stacks.calibrator import (
    CALIBRATED_DIR,
    SETTING_GLOBAL_DIR,
    calibrate_session,
    delete_calibrated,
    limpiar_calibraciones_ajenas,
    list_calibrated,
    output_dir_for,
    save_calibration,
)
from stacks.frame_metrics import FrameMetrics, extract_metrics
from stacks.global_pool import GlobalPool, pool_desde_calibradas
from stacks.registration import (
    REGISTRADOS_DIR,
    Registro,
    audit_pool,
    auditoria_guardada,
    register_pool,
)
from stacks.session_parser import (
    FichaFITS,
    Session,
    exposure_de,
    ficha_de_luz,
    parse_sessions,
)
from stacks.siril_finder import SETTINGS_KEY, find_siril, siril_version
from stacks.siril_runner import (
    WORKING_FOLDER,
    SirilError,
    binario_de_tarea,
    eliminar_salidas_trabajo,
)
from stacks.stacker import APILADOS_DIR, apilar_pool, exportar_apilados
from ui.style import PALETTE

from .paneles import PanelApilar, PanelAuditar, PanelCalibrar, PanelFinal, PanelSesiones
from .pasos_common import clave_sesion, configurar_pyqtgraph
from .worker import CANCELADO, SirilWorker, arrancar_en_hilo

#: Nombres de los cinco pasos; el orden ES el flujo del asistente.
PASOS = ("Sesiones", "Calibrar", "Auditar", "Apilar", "Final")


def _siril_del_usuario() -> str | None:
    """SirIL resuelto con la ruta guardada del usuario (A-03).

    ``settings`` se lee aquí, en el hilo de UI, y el valor viaja por
    parámetro: los módulos de ``stacks/`` no tocan la BD.
    """
    return find_siril(get_setting(SETTINGS_KEY) or None)


def nombre_por_integracion(frames: list) -> str:
    """Nombra el resultado con la exposición real de los frames aceptados."""
    duraciones = [ref.exposicion_s for ref in frames]
    if not duraciones or any(t is None or t <= 0 for t in duraciones):
        raise ValueError("Falta la exposición de alguna toma: escribe un nombre al apilado.")
    segundos = sum(duraciones)
    tiempo = f"{segundos:.3f}".rstrip("0").rstrip(".")
    return f"result_{tiempo}s"


def _chip_style(estado: str) -> str:
    """Hoja inline de un chip de paso (pendiente | hecho | actual).

    Va inline y no en ``ui/style.py`` porque cambia en cada repintado con
    propiedades que Qt no repolisha solo; el resto de la pestaña usa el
    QSS global como todo el programa.
    """
    marco = "border-radius: 6px; padding: 4px 10px;"
    if estado == "actual":
        return (
            f"color: {PALETTE['text']}; background-color: {PALETTE['surface']}; "
            f"border: 1px solid {PALETTE['accentLight']}; font-weight: bold; {marco}"
        )
    if estado == "hecho":
        return (
            f"color: {PALETTE['accentLight']}; background-color: {PALETTE['panel']}; "
            f"border: 1px solid {PALETTE['accent']}; {marco}"
        )
    return (
        f"color: {PALETTE['textDim']}; background-color: {PALETTE['panel']}; "
        f"border: 1px solid {PALETTE['border']}; {marco}"
    )


class StackerPage(QWidget):
    """Pestaña Apilador: asistente + orquestación de las tareas de SirIL."""

    #: Resultado intermedio emitido desde el hilo de trabajo: la BD solo se
    #: toca en el hilo principal (SQLite exige el mismo hilo que la creó).
    dato = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Monta barra de pasos, los 5 paneles, navegación, progreso y log."""
        super().__init__(parent)
        configurar_pyqtgraph()  # antialias + fondo de la gráfica (A-13: nada al importar)

        # --- estado del flujo (la página es la dueña; los paneles solo pintan)
        self.sesiones: list[Session] = []
        self._exposiciones: dict[str, list[float]] = {}  # sesión → exposición por frame
        self._fichas: dict[str, FichaFITS] = {}  # sesión → cabeceras FITS
        self._calibradas: set[str] = set()
        self.registro: Registro | None = None
        self.metricas: list[FrameMetrics] | None = None
        self._pool: GlobalPool | None = None  # pool auditado (lo reutiliza apilar)
        self._calibrado = False
        self._auditado = False
        self._apilado = False
        self._paso = 0
        self._aviso_trabajo = False
        self._hilo: QThread | None = None
        self._worker: SirilWorker | None = None
        self._tarea_ok: Callable[[object], None] | None = None
        self._tarea_no: Callable[[str], None] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        barra_pasos = QHBoxLayout()
        barra_pasos.setSpacing(6)
        self._chips: list[QLabel] = []
        for indice, titulo in enumerate(PASOS):
            chip = QLabel(f"{indice + 1}. {titulo}")
            chip.setStyleSheet(_chip_style("pendiente"))
            self._chips.append(chip)
            barra_pasos.addWidget(chip)
            if indice < len(PASOS) - 1:
                separador = QLabel("→")
                separador.setStyleSheet(f"color: {PALETTE['textDim']};")
                barra_pasos.addWidget(separador)
        barra_pasos.addStretch(1)
        layout.addLayout(barra_pasos)

        self.panel_sesiones = PanelSesiones()
        self.panel_calibrar = PanelCalibrar()
        self.panel_auditar = PanelAuditar()
        self.panel_apilar = PanelApilar()
        self.panel_final = PanelFinal()
        self._paneles_lista = [
            self.panel_sesiones,
            self.panel_calibrar,
            self.panel_auditar,
            self.panel_apilar,
            self.panel_final,
        ]
        self._paneles = QStackedWidget()
        for panel in self._paneles_lista:
            self._paneles.addWidget(panel)
        layout.addWidget(self._paneles, 1)

        nav = QHBoxLayout()
        self._estado = QLabel("Elige la carpeta raíz y pulsa «Escanear».")
        self._estado.setObjectName("HintLabel")
        nav.addWidget(self._estado, 1)
        self._limpiar = QPushButton("Limpiar working…")
        self._limpiar.clicked.connect(self._preguntar_trabajo)
        nav.addWidget(self._limpiar)
        self._ver_log = QPushButton("Ver log")
        self._ver_log.setToolTip("Muestra u oculta el registro sin perder sus mensajes.")
        self._ver_log.clicked.connect(self._alternar_log)
        nav.addWidget(self._ver_log)
        self._barra = QProgressBar()
        self._barra.setRange(0, 100)
        self._barra.setFixedWidth(200)
        self._barra.setVisible(False)
        nav.addWidget(self._barra)
        self._cancelar = QPushButton("Cancelar")
        self._cancelar.clicked.connect(self._cancelar_tarea)
        self._cancelar.setVisible(False)
        nav.addWidget(self._cancelar)
        self._atras = QPushButton("← Atrás")
        self._atras.clicked.connect(self._ir_atras)
        self._siguiente = QPushButton("Siguiente →")
        self._siguiente.setObjectName("PrimaryButton")
        self._siguiente.clicked.connect(self._ir_siguiente)
        self._todo = QPushButton("▶ Hacer todo")
        self._todo.setObjectName("PrimaryButton")
        self._todo.setToolTip("Encadena escaneo → calibración → auditoría → apilado.")
        self._todo.clicked.connect(self.hacer_todo)
        nav.addWidget(self._atras)
        nav.addWidget(self._siguiente)
        nav.addWidget(self._todo)
        layout.addLayout(nav)

        self._terminal = QPlainTextEdit()
        from pass_logging import MAX_LOG_LINES

        self._terminal.setMaximumBlockCount(MAX_LOG_LINES)
        self._terminal.setReadOnly(True)
        self._terminal.setMaximumHeight(150)
        self._terminal.setPlaceholderText(
            "Log de SirIL (y del flujo): lo que pasa durante las corridas…"
        )
        layout.addWidget(self._terminal)
        self._log_abierto = False

        # --- los paneles hablan con la página por señales
        self.panel_sesiones.escanear.connect(lambda: self.escanear())
        self.panel_calibrar.calibrar.connect(lambda: self.calibrar(explicita=True))
        self.panel_auditar.auditar.connect(lambda: self.auditar())
        self.panel_auditar.descartar.connect(self.descartar_recomendados)
        self.panel_apilar.apilar.connect(lambda: self.apilar())
        self.panel_final.reiniciar.connect(self.reiniciar)
        # La tarea emite cada sesión calibrada; aquí se guarda en la BD
        # (siempre en el hilo principal: SQLite no admite otro hilo).
        self.dato.connect(self._guardar_calibracion)

        # --- raíz inicial desde Configuración y estado de SirIL
        self._refrescar_calibradas()
        self.panel_sesiones.poner_raiz(get_setting(PROJECT_ROOT_KEY) or "")
        self.panel_apilar.avisar_siril(_siril_del_usuario() is None)

        # Al salir de la aplicación, ninguna tarea ni SirIL se quedan colgados.
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._parar_todo)

        self._mostrar_paso(0)

    # ------------------------------------------------------------- navegación

    def _mostrar_paso(self, indice: int) -> None:
        """Muestra el paso ``indice`` y repinte de chips + navegación."""
        self._paso = indice
        if indice == 3:
            self.panel_apilar.actualizar_conteo(len(self.panel_auditar.aceptados()))
        self._limpiar.setVisible(indice == 1)
        self._paneles.setCurrentIndex(indice)
        self._terminal.setVisible(self._log_abierto)
        for i, chip in enumerate(self._chips):
            estado = (
                "actual"
                if i == indice
                else ("hecho" if i < indice else "pendiente")
            )
            chip.setStyleSheet(_chip_style(estado))
        ocupado = self._worker is not None
        self._actualizar_navegacion(ocupado, indice)
        if indice == 1 and self.sesiones and not self._aviso_trabajo:
            self._aviso_trabajo = True
            if any(self._carpeta_calibrada(s).exists() for s in self.sesiones):
                self._preguntar_trabajo()

    def _salida_atribuida(self, sesion: Session) -> Path:
        """Salida que corresponde a esta sesión: la registrada o la nueva única.

        La identidad es la **ruta de origen completa**: una homónima de otra
        raíz no hereda la salida ajena, y una sesión sin fila propia apunta a
        su destino nuevo ``<nombre>-<hash>`` (nunca a un legado ambiguo).
        """
        for fila in self._filas_calibradas_actuales():
            if Path(fila["session_dir"]).resolve() == sesion.path.resolve():
                return Path(fila["calibrated_dir"])
        return output_dir_for(sesion.path, root=WORKING_FOLDER / CALIBRATED_DIR)

    def _carpeta_calibrada(self, sesion: Session) -> Path:
        """Carpeta de trabajo existente de esta sesión (para avisar y limpiar).

        Prefiere la salida atribuida; si no existe, ofrece el legado
        ``calibrados/<nombre>`` **salvo** que otra fila lo reclame como suyo:
        ese pertenece a una homónima y no se toca.
        """
        salida = self._salida_atribuida(sesion)
        if salida.exists():
            return salida
        legado = WORKING_FOLDER / CALIBRATED_DIR / sesion.path.name
        reclamado = any(
            Path(fila["session_dir"]).resolve() != sesion.path.resolve()
            for fila in list_calibrated()
            if Path(fila["calibrated_dir"]).resolve() == legado.resolve()
        )
        return legado if legado.exists() and not reclamado else salida

    def _preguntar_trabajo(self) -> None:
        """Ofrece conservar, limpiar estas sesiones o todo working con rutas visibles."""
        if self._worker is not None:
            return
        candidatas = [s for s in self.sesiones if self._carpeta_calibrada(s).is_dir()]
        dialogo = QMessageBox(self)
        dialogo.setWindowTitle("Datos de trabajo existentes")
        dialogo.setText("No se eliminará nada sin tu confirmación.")
        rutas = "\n".join(str(self._carpeta_calibrada(s)) for s in candidatas)
        dialogo.setInformativeText(
            f"Carpeta completa:\n{WORKING_FOLDER.absolute()}\n\n"
            f"Calibrados de estas sesiones:\n{rutas or '(ninguno)'}\n\n"
            "Conservar no modifica ni recalibra los datos existentes."
        )
        conservar = dialogo.addButton("Conservar", QMessageBox.ButtonRole.AcceptRole)
        solo = dialogo.addButton("Eliminar estos calibrados", QMessageBox.ButtonRole.DestructiveRole)
        solo.setEnabled(bool(candidatas))
        todo = dialogo.addButton("Eliminar TODO working", QMessageBox.ButtonRole.DestructiveRole)
        dialogo.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        dialogo.exec()
        eleccion = dialogo.clickedButton()
        if eleccion is conservar or eleccion not in (solo, todo):
            return
        objetivos = (
            [self._carpeta_calibrada(s) for s in candidatas]
            if eleccion is solo else [WORKING_FOLDER]
        )
        if eleccion is todo:
            aviso = QMessageBox.warning(
                self, "Confirmar eliminación total",
                f"Se perderán calibrados, auditorías y apilados en:\n"
                f"{WORKING_FOLDER.absolute()}\n\n"
                "Los originales fuera de esta carpeta no se tocarán.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if aviso != QMessageBox.StandardButton.Yes:
                return
        try:
            for ruta in objetivos:
                eliminar_salidas_trabajo(ruta)
        except (OSError, SirilError) as exc:
            self._decir(f"No se pudo limpiar {ruta}: {exc}")
            return
        if eleccion is todo:
            for fila in list_calibrated():
                if Path(fila["calibrated_dir"]).absolute().is_relative_to(WORKING_FOLDER.absolute()):
                    delete_calibrated(fila["session_dir"])
        else:
            for sesion in candidatas:
                delete_calibrated(str(sesion.path))
        self._invalidar_aguas_abajo()
        self._calibrado = False
        self._refrescar_calibradas()
        self.panel_calibrar.mostrar_pendientes(self.sesiones, self._calibradas)
        self.panel_sesiones.mostrar(
            self.sesiones, self._calibradas, self._exposiciones, self._fichas
        )
        self._decir("Datos de trabajo eliminados; puedes volver a calibrar.")

    def _alternar_log(self) -> None:
        """Alterna el terminal en cualquier paso sin borrar sus mensajes."""
        self._log_abierto = not self._log_abierto
        self._terminal.setVisible(self._log_abierto)
        self._ver_log.setText("Ocultar log" if self._log_abierto else "Ver log")

    def _ir_atras(self) -> None:
        """Paso anterior (deshabilitado en el primero o durante una corrida)."""
        if self._paso > 0 and self._worker is None:
            self._mostrar_paso(self._paso - 1)

    def _ir_siguiente(self) -> None:
        """Ejecuta la fase del paso actual, o la salta si ya está hecha."""
        if self._paso == 0:
            if self.sesiones:
                self._mostrar_paso(1)
            else:
                self.escanear(ir_a=1)
        elif self._paso == 1:
            if self._calibrado:
                self._mostrar_paso(2)
            else:
                self.calibrar(ir_a=2)
        elif self._paso == 2:
            if self._auditado:
                self._mostrar_paso(3)
            else:
                self.auditar(ir_a=3)
        elif self._paso == 3:
            if self._apilado:
                self._mostrar_paso(4)
            else:
                self.apilar(ir_a=4)

    def hacer_todo(self) -> None:
        """Encadena el flujo entero desde el principio (lo hecho se salta)."""
        self._log("── Hacer todo: escaneo → calibración → auditoría → apilado ──")
        self._mostrar_paso(0)
        self._cadena_escaneo()

    def _cadena_escaneo(self) -> None:
        """Fase 1 de la cadena: escanear si todavía no hay sesiones."""
        if self.sesiones:
            self._mostrar_paso(1)
            self._cadena_calibrar()
        else:
            self.escanear(ir_a=1, siguiente=self._cadena_calibrar)

    def _cadena_calibrar(self) -> None:
        """Fase 2 de la cadena: calibrar si aún no está hecho."""
        if self._calibrado:
            self._mostrar_paso(2)
            self._cadena_auditar()
        else:
            self.calibrar(ir_a=2, siguiente=self._cadena_auditar)

    def _cadena_auditar(self) -> None:
        """Fase 3 de la cadena: registrar y medir."""
        if self._auditado:
            self._mostrar_paso(3)
            self._cadena_apilar()
        else:
            self.auditar(ir_a=3, siguiente=self._cadena_apilar)

    def _cadena_apilar(self) -> None:
        """Fase 4 de la cadena: apilar y terminar."""
        if self._apilado:
            self._mostrar_paso(4)
        else:
            self.apilar(ir_a=4)

    def reiniciar(self) -> None:
        """Vuelve al principio (el log se conserva por si hay que depurar)."""
        self.sesiones = []
        self._exposiciones = {}
        self._fichas = {}
        self.registro = None
        self.metricas = None
        self._pool = None
        self._calibrado = False
        self._auditado = False
        self._apilado = False
        self._aviso_trabajo = False
        self._refrescar_calibradas()
        self.panel_sesiones.mostrar([], self._calibradas, {})
        self.panel_calibrar.mostrar_pendientes([], self._calibradas)
        self.panel_auditar.limpiar()
        self.panel_apilar.limpiar()
        self.panel_final.limpiar()
        self._mostrar_paso(0)
        self._decir("Empezamos de nuevo: elige la carpeta raíz.")

    # ------------------------------------------------------- fase 1: escanear

    def escanear(
        self,
        *,
        ir_a: int | None = None,
        siguiente: Callable[[], None] | None = None,
    ) -> None:
        """Escanea la carpeta raíz en el hilo y muestra sus sesiones."""
        raiz = self.panel_sesiones.raiz()
        if not raiz:
            self._decir("Elige primero la carpeta raíz con las sesiones.")
            return
        if not Path(raiz).is_dir():
            self._decir(f"La carpeta {raiz} no existe.")
            return

        def tarea(progress_cb, log_cb):
            base = Path(raiz)
            log_cb(f"Escaneando {base}…")
            encontradas = parse_sessions(base)
            if not encontradas:
                raise ValueError(f"No se detectó ninguna sesión en {base}.")
            exposiciones: dict[str, list[float]] = {}
            fichas: dict[str, FichaFITS] = {}
            for i, sesion in enumerate(encontradas):
                log_cb(
                    f"· {sesion.path.name}: {sesion.n_lights} lights, "
                    f"tipo {sesion.kind}"
                )
                exposiciones[clave_sesion(sesion)] = [
                    exposure_de(f) or 0.0
                    for f in sesion.frames.get("lights", [])
                ]
                # RAW no ofrece una cabecera FITS legible: usar el primer
                # FITS disponible, igual que el visor del paso Sesiones.
                lights = sesion.frames.get("lights", [])
                primer_fits = next(
                    (f for f in lights if f.suffix.lower() in (".fit", ".fits", ".fts")),
                    None,
                )
                fichas[clave_sesion(sesion)] = (
                    ficha_de_luz(primer_fits) if primer_fits else FichaFITS()
                )
                progress_cb((i + 1) / len(encontradas))
            return encontradas, exposiciones, fichas

        def al_terminar(resultado):
            sesiones, exposiciones, fichas = resultado
            self._invalidar_aguas_abajo()
            self._aviso_trabajo = False
            self.sesiones = sesiones
            self._exposiciones = exposiciones
            self._fichas = fichas
            self._refrescar_calibradas()
            claves = {clave_sesion(s) for s in sesiones}
            # Si el escaneo encuentra TODO calibrado, esa fase queda hecha.
            self._calibrado = bool(claves) and claves <= self._calibradas
            self.panel_sesiones.mostrar(
                sesiones, self._calibradas, exposiciones, fichas
            )
            self.panel_calibrar.mostrar_pendientes(sesiones, self._calibradas)
            self._decir(f"{len(sesiones)} sesiones en {raiz}.")
            self._avanzar(ir_a, siguiente)

        if self._lanzar(tarea, al_terminar):
            self._decir(f"Escaneando {raiz}…")

    # ------------------------------------------------------ fase 2: calibrar

    def calibrar(
        self,
        *,
        ir_a: int | None = None,
        siguiente: Callable[[], None] | None = None,
        explicita: bool = False,
    ) -> None:
        """Calibra todas las sesiones escaneadas con SirIL (una tras otra)."""
        if not self.sesiones:
            self._decir("Escanea las sesiones primero (paso 1).")
            return
        if not self._asegurar_siril():
            return
        if self._worker is not None:
            return
        try:
            for origen in limpiar_calibraciones_ajenas(self.sesiones, list_calibrated()):
                delete_calibrated(origen)
        except (ValueError, OSError, SirilError) as exc:
            self._decir(f"No se pudo preparar la calibración: {exc}")
            return
        self._refrescar_calibradas()
        opciones = self.panel_calibrar.opciones()
        sesiones = [
            s for s in self.sesiones if clave_sesion(s) not in self._calibradas
        ]
        if not sesiones:
            self._calibrado = all(
                clave_sesion(s) in self._calibradas for s in self.sesiones
            )
            self._decir(
                "Hay datos anteriores; no se sobrescriben. "
                "Limpia los calibrados para repetir o completar la calibración."
            )
            if self._calibrado:
                self._avanzar(ir_a, siguiente)
            return
        global_dir = get_setting(SETTING_GLOBAL_DIR, "") or ""

        def tarea(progress_cb, log_cb):
            total = len(sesiones)
            resultados = []
            for i, sesion in enumerate(sesiones):
                log_cb(
                    f"━━ Calibrando {sesion.path.name} ({i + 1}/{total}) ━━"
                )
                resultado = calibrate_session(
                    sesion,
                    opt=opciones["opt"],
                    cc=opciones["cc"],
                    progress_cb=lambda f, i=i: progress_cb((i + f) / total),
                    log_cb=log_cb,
                    global_dir=global_dir,
                )
                for aviso in resultado.avisos:
                    log_cb(f"⚠ {sesion.path.name}: {aviso}")
                resultados.append(resultado)
                # Se guarda en el hilo principal vía la señal ``dato``: si la
                # sesión 3 falla, las 1 y 2 ya están en la BD (al día con disco).
                self.dato.emit(resultado)
            return resultados

        def al_terminar(resultados):
            # Recalibrar invalida lo que venga después: el pool, el registro
            # y las métricas ya no corresponden a los lights nuevos.
            self._invalidar_aguas_abajo()
            self._refrescar_calibradas()
            self._calibrado = all(
                clave_sesion(s) in self._calibradas for s in self.sesiones
            )
            avisos = {
                clave_sesion(r.session): r.avisos for r in resultados
            }
            self.panel_calibrar.mostrar_resultados(resultados, avisos)
            self.panel_sesiones.mostrar(
                self.sesiones, self._calibradas, self._exposiciones,
                self._fichas,
            )
            self._decir(f"{len(resultados)} sesiones calibradas.")
            if self._calibrado:
                self._avanzar(ir_a, siguiente)

        if self._lanzar(tarea, al_terminar, siril=True):
            self._decir(f"Calibrando {len(sesiones)} sesiones…")

    # ------------------------------------------------------- fase 3: auditar

    def auditar(
        self,
        *,
        ir_a: int | None = None,
        siguiente: Callable[[], None] | None = None,
    ) -> None:
        """Registra el pool rápido (-2pass) y extrae las métricas de cada frame.

        No aplica nada (ni transformadas, ni debayer, ni drizzle): esto es
        solo para medir y elegir frames. El registro de verdad se hace en
        ``apilar``, sobre los aceptados y con las opciones de allí.
        """
        if not self.sesiones:
            self._decir("Escanea las sesiones primero (paso 1).")
            return
        try:
            pesos = self.panel_auditar.pesos()
        except ValueError as exc:
            self._decir(str(exc))
            return
        # La BD se consulta AQUÍ (hilo principal): el hilo de trabajo no la
        # toca en ninguna fase (SQLite exige el hilo que creó la conexión).
        filas = self._filas_calibradas_actuales()
        if not filas:
            self._decir(
                "Ninguna sesión escaneada está calibrada: calibra primero."
            )
            return
        pool_previo = pool_desde_calibradas(filas)
        previo = auditoria_guardada(pool_previo) if pool_previo.entries else None
        if previo is not None:
            respuesta = QMessageBox.question(
                self, "Auditoría existente",
                "El registro anterior coincide con los lights calibrados actuales. "
                "¿Reutilizarlo sin volver a registrar?\n\n"
                "No: registrar de nuevo con SirIL.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if respuesta == QMessageBox.StandardButton.Yes:
                try:
                    metricas = extract_metrics(previo, pesos)
                except (ValueError, OSError):
                    self._decir("El registro guardado no tiene métricas válidas; se registrará otra vez.")
                else:
                    self.registro, self.metricas, self._pool = previo, metricas, pool_previo
                    self._auditado = True
                    self.panel_auditar.mostrar(previo, metricas)
                    self._decir("Auditoría anterior reutilizada; revisa los descartes.")
                    self._avanzar(ir_a, siguiente)
                    return
        if not self._asegurar_siril():
            return

        def tarea(progress_cb, log_cb):
            pool = pool_previo
            log_cb(f"Pool: {len(pool.entries)} lights de {len(filas)} sesiones.")
            if not pool.entries:
                raise ValueError(
                    "Las sesiones calibradas no tienen lights: revisa la "
                    "calibración."
                )
            log_cb("Registro rápido de auditoría (sin aplicar nada)…")
            registro = audit_pool(
                pool,
                progress_cb=progress_cb,
                log_cb=log_cb,
            )
            metricas = extract_metrics(registro, pesos)
            return registro, metricas, pool

        def al_terminar(resultado):
            self.registro, self.metricas, self._pool = resultado
            self._auditado = True
            self.panel_auditar.mostrar(self.registro, self.metricas)
            descartados = len(self.registro.frames) - len(self.metricas)
            self._decir(
                f"{len(self.metricas)} frames con métricas"
                + (
                    f" · SirIL descartó {descartados}"
                    if descartados
                    else ""
                )
                + "."
            )
            self._avanzar(ir_a, siguiente)

        if self._lanzar(tarea, al_terminar, siril=True):
            self._decir("Registrando y midiendo (auditoría rápida)…")

    def descartar_recomendados(self) -> None:
        """Aplica a las casillas los descartes recomendados (el veto es del usuario)."""
        if not self.metricas:
            self._decir("Audita primero (paso 3).")
            return
        cambiados = self.panel_auditar.descartar_recomendados()
        self._log(f"Descartes recomendados: {cambiados} casillas desmarcadas.")
        self._decir(
            f"{cambiados} casillas desmarcadas según los descartes recomendados: "
            "revísalos; el motivo de cada uno está en la tabla."
        )

    # ------------------------------------------------------- fase 4: apilar

    def apilar(
        self,
        *,
        ir_a: int | None = None,
        siguiente: Callable[[], None] | None = None,
    ) -> None:
        """Registra los frames aceptados (con debayer o drizzle) y los apila.

        Es el registro «como se debe»: solo los marcados en la auditoría,
        y ya con las opciones elegidas aquí — debayer previo si NO hay
        drizzle (solo toca los CFA), o drizzle si lo hay (SirIL rebayeriza
        solo al rezumar). Después, el apilado normal de ``apilar_pool``.
        """
        if self.registro is None or self._pool is None:
            self._decir("Audita primero (paso 3).")
            return
        if not self._asegurar_siril():
            return
        try:
            nombre = self.panel_apilar.nombre()
            opciones = self.panel_apilar.opciones()
            registro_opciones = self.panel_apilar.opciones_registro()
        except ValueError as exc:
            self._decir(str(exc))
            return
        aceptados = self.panel_auditar.aceptados()
        if not aceptados:
            self._decir(
                "No queda ningún frame marcado para apilar: revisa la auditoría."
            )
            return
        auditoria = self.registro
        pool = self._pool
        marcas = [
            auditoria.frames[i - 1]
            for i in aceptados
            if 1 <= i <= len(auditoria.frames)
        ]
        if not marcas:
            self._decir("Los frames marcados ya no existen: vuelve a auditar.")
            return
        if not nombre:
            try:
                nombre = nombre_por_integracion(marcas)
            except ValueError as exc:
                self._decir(str(exc))
                return
        padres = {sesion.path.parent.resolve() for sesion in self.sesiones}
        if len(padres) != 1:
            self._decir("Las sesiones no tienen una misma carpeta madre; no se apilará.")
            return
        madre = padres.pop()
        if madre.is_symlink() or madre.is_junction() or not madre.is_dir():
            self._decir("La carpeta madre de las sesiones no es un directorio seguro.")
            return
        if (madre / f"{nombre}.fit").exists():
            self._decir("Ya existe un stack con ese nombre en la carpeta madre; elige otro.")
            return
        for carpeta in (
            WORKING_FOLDER / REGISTRADOS_DIR / nombre,
            WORKING_FOLDER / APILADOS_DIR / nombre,
        ):
            if carpeta.exists() and (not carpeta.is_dir() or any(carpeta.iterdir())):
                self._decir(f"Ya hay datos en {carpeta}; elige otro nombre para conservarlos.")
                return
        drizzle = registro_opciones["drizzle"]
        # Con drizzle, SirIL rebayeriza él solo al rezumar; sin drizzle los
        # CFA se debayerizan antes (``_debayerizar`` no toca RGB/mono).
        debayer = not drizzle

        def tarea(progress_cb, log_cb):
            log_cb(
                f"Registro final de {len(marcas)} frames aceptados ("
                + (f"drizzle ×{registro_opciones['scale']:g}" if drizzle else "debayer si es CFA")
                + ")…"
            )
            registro = register_pool(
                pool,
                nombre,
                aceptados=marcas,
                debayer=debayer,
                drizzle=drizzle,
                scale=registro_opciones["scale"],
                framing=registro_opciones["framing"],
                pixfrac=registro_opciones["pixfrac"],
                kernel=registro_opciones["kernel"],
                flat=registro_opciones["flat"],
                progress_cb=progress_cb,
                log_cb=log_cb,
            )
            log_cb(f"Apilando «{nombre}»: {len(registro.frames)} frames…")
            salidas = apilar_pool(
                registro,
                nombre,
                opciones=opciones,
                progress_cb=progress_cb,
                log_cb=log_cb,
            )
            exportadas = exportar_apilados(salidas, madre)
            log_cb(f"Apilado copiado a {madre}: {', '.join(p.name for p in exportadas)}")
            return salidas, registro

        def al_terminar(resultado):
            salidas, registro_final = resultado
            self._apilado = True
            self.panel_apilar.mostrar_salidas(salidas)
            self.panel_final.mostrar(
                nombre=nombre,
                sesiones=len(self.sesiones),
                registrados=len(registro_final.frames),
                descartados=len(auditoria.frames) - len(registro_final.frames),
                salidas=salidas,
            )
            self._decir(f"«{nombre}» apilado: {len(salidas)} imagen(es).")
            self._avanzar(ir_a, siguiente)

        if self._lanzar(tarea, al_terminar, siril=True):
            self._decir(f"Apilando «{nombre}»…")

    # -------------------------------------------------- motor de tareas (hilo)

    def _lanzar(
        self,
        tarea: Callable[..., object],
        al_terminar: Callable[[object], None],
        al_fallar: Callable[[str], None] | None = None,
        *,
        siril: bool = False,
    ) -> bool:
        """Arranca ``tarea`` en su hilo; False si ya hay una corrida en curso."""
        if self._worker is not None:
            return False
        if siril:
            binario = _siril_del_usuario()
            if not binario:
                self._decir("SirIL no está disponible.")
                return False

            tarea_original = tarea

            def tarea_con_binario(progress_cb, log_cb):
                """Mantiene el binario resuelto en UI durante toda la tarea."""
                with binario_de_tarea(binario):
                    return tarea_original(progress_cb, log_cb)

            tarea = tarea_con_binario
        self._tarea_ok = al_terminar
        self._tarea_no = al_fallar
        self._ocupar(True)
        self._hilo, self._worker = arrancar_en_hilo(
            tarea,
            al_log=self._log,
            al_progreso=self._barra.setValue,
            al_fin=self._al_terminar,
            al_fallo=self._al_fallar,
            contenedor=self,
            al_liberar=self._hilo_terminado,
        )
        return True

    def _hilo_terminado(self, hilo: QThread) -> None:
        """Suelta la referencia al hilo cuando Qt emite ``finished``.

        No en el callback de resultado: entre medias el hilo sigue vivo y
        ``_parar_todo`` puede necesitar ``wait()``. Si ya corre otro hilo
        nuevo, ése no se toca.
        """
        if self._hilo is hilo:
            self._hilo = None

    def _al_terminar(self, resultado: object) -> None:
        """Fin de tarea: libera el worker y ejecuta el callback de la fase."""
        al_terminar, self._tarea_ok, self._tarea_no = (
            self._tarea_ok,
            None,
            None,
        )
        self._worker = None
        self._ocupar(False)
        if al_terminar is not None:
            al_terminar(resultado)

    def _al_fallar(self, motivo: str) -> None:
        """Fallo o cancelación: libera, lo pinta y corta la cadena."""
        al_fallar, self._tarea_ok, self._tarea_no = (
            self._tarea_no,
            None,
            None,
        )
        self._worker = None
        self._ocupar(False)
        if motivo == CANCELADO:
            self._decir("Cancelado.")
            self._log(f"⏹ {motivo}")
        else:
            self._decir(f"Error: {motivo}")
            self._log(f"✗ {motivo}")
        if al_fallar is not None:
            al_fallar(motivo)

    def _actualizar_navegacion(self, ocupado: bool, indice: int) -> None:
        """Habilita Atrás/Siguiente/Todo/Limpiar según el paso y la corrida (A-21).

        Mismo criterio en los dos caminos que lo necesitan: cambiar de paso
        (``_mostrar_paso``) y arrancar/terminar una tarea (``_ocupar``).
        """
        self._atras.setEnabled(not ocupado and indice > 0)
        self._siguiente.setEnabled(not ocupado and indice < len(PASOS) - 1)
        self._todo.setEnabled(not ocupado and indice < len(PASOS) - 1)
        self._limpiar.setEnabled(not ocupado)

    def _ocupar(self, ocupado: bool) -> None:
        """Estado de «corriendo»: navegación muerta, progreso y Cancelar."""
        self._barra.setVisible(ocupado)
        self._cancelar.setVisible(ocupado)
        if ocupado:
            self._barra.setValue(0)
        self._actualizar_navegacion(ocupado, self._paso)
        for panel in self._paneles_lista:
            panel.bloquear(ocupado)

    def _cancelar_tarea(self) -> None:
        """Pide parar la corrida en curso (mata SirIL y corta la cadena)."""
        if self._worker is not None:
            self._decir("Cancelando…")
            self._worker.cancelar()

    def _parar_todo(self) -> None:
        """Cierre de la aplicación: ninguna tarea ni SirIL se quedan colgados."""
        if self._worker is not None:
            self._worker.cancelar()
        if self._hilo is not None:
            self._hilo.quit()
            self._hilo.wait(3000)

    # ------------------------------------------------------------- utilidades

    def _avanzar(
        self, ir_a: int | None, siguiente: Callable[[], None] | None
    ) -> None:
        """Tras una fase con éxito: pasa de paso y lanza la siguiente si hay."""
        if ir_a is not None:
            self._mostrar_paso(ir_a)
        if siguiente is not None:
            siguiente()

    def _asegurar_siril(self) -> bool:
        """True si SirIL está localizable; si no, pide la ruta y la guarda."""
        if _siril_del_usuario():
            return True
        ruta, _filtro = QFileDialog.getOpenFileName(
            self,
            "Selecciona el ejecutable de SirIL",
            "C:/Program Files/Siril/bin",
            "Ejecutables de SirIL (siril-cli.exe siril.exe);;Todos los archivos (*)",
        )
        if not ruta:
            self._decir("Sin SirIL no puedo continuar.")
            return False
        if not siril_version(ruta):
            self._decir("El ejecutable de SirIL no responde a --version.")
            return False
        set_setting(SETTINGS_KEY, ruta)
        self.panel_apilar.avisar_siril(False)
        self._log(f"SirIL (ruta del usuario): {ruta}")
        self._decir(f"SirIL guardado: {ruta}")
        return True

    def _refrescar_calibradas(self) -> None:
        """Sesiones con salida propia, identificadas por ruta de origen.

        No se usa el nombre: dos raíces distintas pueden tener una carpeta
        homónima y solo una de ellas está calibrada.
        """
        self._calibradas = {
            str(Path(fila["session_dir"]).resolve())
            for fila in self._filas_calibradas_actuales()
        }

    def _filas_calibradas_actuales(self) -> list[dict]:
        """Filtra por ruta de origen completa y salida existente antes del pool."""
        origenes = {s.path.resolve() for s in self.sesiones}
        return [
            fila for fila in list_calibrated()
            if Path(fila["session_dir"]).resolve() in origenes
            and Path(fila["calibrated_dir"]).is_dir()
        ]

    def _guardar_calibracion(self, resultado) -> None:
        """Persiste una sesión calibrada al llegar la señal (hilo principal).

        La emite la tarea desde su hilo; así la BD queda al día incluso si
        una sesión posterior falla y la cadena se corta.
        """
        save_calibration(resultado)
        self._log(
            f"BD: {resultado.session.path.name} guardada "
            f"({resultado.n_lights} lights)."
        )

    def _invalidar_aguas_abajo(self) -> None:
        """Aguas abajo dejan de ser válidos (reescaneo o recalibrado)."""
        self.registro = None
        self.metricas = None
        self._pool = None
        self._calibrado = False
        self._auditado = False
        self._apilado = False

    def _log(self, linea: str) -> None:
        """Añade una línea al log visible (se llama también desde el hilo)."""
        self._terminal.appendPlainText(linea)

    def _decir(self, texto: str) -> None:
        """Actualiza la línea de estado bajo la navegación."""
        self._estado.setText(texto)
        from pass_logging import record_action

        record_action("apilador", texto)
