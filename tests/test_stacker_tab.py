"""Pestaña Apilador: asistente de un paso, worker en hilo y cadena completa.

SirIL está mockeado (como en el resto de tests de ``stacks``): aquí se prueba
la ORQUESTACIÓN de la UI — pasos, señales, hilo y callbacks — no SirIL.
"""
import time
from pathlib import Path

import pytest

from stacks.calibrator import CalibrationResult
from stacks.frame_metrics import FrameMetrics
from stacks.global_pool import GlobalPool, LightRef
from stacks.registration import Registro
from stacks.session_parser import Session


def _app():
    """QApplication de la sesión de pruebas (la crea el fixture ``app_font``)."""
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def qapp():
    """Mantiene la QApplication viva durante el test.

    La que crea el fixture ``app_font`` de ``conftest`` muere al cerrar su
    fixture (PyQt posee el objeto): aquí se crea otra y se sostiene mientras
    corre el test, como hace el resto de tests de Qt del proyecto.
    """
    return _app()


def _esperar(condicion, *, tiempo=8.0):
    """Procesa eventos Qt hasta que se cumpla ``condicion`` (o se acabe el tiempo)."""
    app = _app()
    limite = time.monotonic() + tiempo
    while time.monotonic() < limite:
        app.processEvents()
        if condicion():
            return True
        time.sleep(0.005)
    return False


def _sesion(nombre: str, n_lights: int, base: Path) -> Session:
    """Sesión falsa con ``n_lights`` ficheros de nombre único."""
    carpeta = base / nombre
    (carpeta / "lights").mkdir(parents=True, exist_ok=True)
    ficheros = [
        carpeta / "lights" / f"L{i:03d}.fits" for i in range(n_lights)
    ]
    return Session(path=carpeta, frames={"lights": ficheros})


# --------------------------------------------------------------- construcción

def test_pagina_construye_el_asistente():
    """La pestaña monta los 5 pasos con barra, navegación y log inicial."""
    from ui.stacker_tab import PASOS, StackerPage

    pagina = StackerPage()

    assert PASOS == ("Sesiones", "Calibrar", "Auditar", "Apilar", "Final")
    assert pagina._paneles.count() == 5
    assert len(pagina._chips) == 5
    assert pagina._paso == 0
    assert not pagina._atras.isEnabled()
    assert pagina._siguiente.isEnabled()
    assert pagina._todo.isEnabled()
    assert pagina._terminal.isReadOnly()
    assert pagina._barra.isHidden()  # sin corrida no hay barra de progreso
    assert not pagina._cancelar.isVisibleTo(pagina)


def test_boton_apilar_comparte_fila_con_titulo():
    """El botón se sitúa junto al título en vez de consumir otra fila inferior."""
    from PyQt6.QtWidgets import QHBoxLayout

    from ui.stacker_tab.pasos import PanelApilar

    panel = PanelApilar()
    contenido = panel._scroll.widget().layout()
    cabecera = contenido.itemAt(0).layout()
    assert isinstance(cabecera, QHBoxLayout)
    assert cabecera.itemAt(0).widget().text() == "Apilado"
    assert cabecera.itemAt(2).widget() is panel._boton


def test_final_muestra_preview_rgb_y_fallo_legible(tmp_path):
    """La vista Final estira el FITS RGB y avisa si no se puede leer."""
    import numpy as np
    from astropy.io import fits

    from ui.stacker_tab.pasos import PanelFinal

    ruta = tmp_path / "pila.fit"
    datos = np.arange(3 * 24 * 32, dtype=np.float32).reshape(3, 24, 32)
    fits.writeto(ruta, datos)
    panel = PanelFinal()
    panel.resize(900, 650)
    panel.show()
    _app().processEvents()
    panel.mostrar(nombre="pila", sesiones=1, registrados=2, descartados=0, salidas=[ruta])
    assert panel._imagen is not None
    assert panel._imagen.width() == 32
    assert not panel._preview_label.pixmap().isNull()
    panel.mostrar(nombre="pila", sesiones=1, registrados=2, descartados=0,
                  salidas=[tmp_path / "falta.fit"])
    assert panel._imagen is None
    assert "Vista previa no disponible" in panel._preview_label.text()
    panel.close()


def test_final_abre_fits_seleccionado_en_siril_grafico(tmp_path, monkeypatch):
    """El botón lanza el GUI con la ruta elegida, no el CLI de procesado."""
    from ui.stacker_tab import pasos

    gui = tmp_path / "siril.exe"
    gui.touch()
    imagen = tmp_path / "final.fit"
    imagen.touch()
    monkeypatch.setattr(pasos, "find_siril", lambda: str(tmp_path / "siril-cli.exe"))
    llamadas = []
    monkeypatch.setattr(pasos.subprocess, "Popen", lambda args: llamadas.append(args))
    panel = pasos.PanelFinal()
    panel.mostrar(nombre="final", sesiones=1, registrados=2, descartados=0,
                  salidas=[imagen])
    panel._siril_boton.click()
    assert llamadas == [[str(gui), str(imagen)]]


def test_autoestirado_resalta_senal_tenue_sin_tocar_datos():
    """El asinh levanta nebulosidad débil y conserva la matriz de entrada."""
    import numpy as np

    from ui.stacker_tab.pasos import _estirar

    imagen = np.full((80, 80), 0.002, dtype=np.float32)
    imagen[20:60, 20:60] = 0.0024
    imagen[30:35, 30:35] = 0.03
    copia = imagen.copy()
    salida = _estirar([imagen])[0]
    assert salida[25, 25] >= 12 > salida[0, 0]
    assert salida[32, 32] >= 254
    np.testing.assert_array_equal(imagen, copia)


def test_autoestirado_moderado_conserva_contraste_de_nubes_y_cables():
    """Levanta el fondo sin esconder zonas claras u oscuras defectuosas."""
    import numpy as np

    from ui.stacker_tab.pasos import _estirar

    rng = np.random.default_rng(23)
    imagen = rng.normal(0.002, 0.00012, (128, 128)).astype(np.float32)
    imagen[0:32, :] += 0.0008  # nube más clara
    imagen[64:80, :] -= 0.0007  # sombra de un cable
    imagen[20, 20] = 0.03  # estrella
    vista = _estirar([imagen])[0]
    assert np.median(vista[0:32, :]) > np.median(vista[40:60, :])
    assert np.median(vista[40:60, :]) > np.median(vista[64:80, :])
    assert np.median(vista[40:60, :]) > 175
    assert vista[20, 20] >= 254


def test_nombre_vacio_admite_generacion_automatica():
    """El formulario no impide usar la exposición de los frames aceptados."""
    from ui.stacker_tab.pasos import PanelApilar

    assert PanelApilar().nombre() == ""


def test_nombre_automatico_suma_solo_tomas_aceptadas():
    """Sin nombre explícito, la duración procede de los frames elegidos."""
    from types import SimpleNamespace

    from ui.stacker_tab import nombre_por_integracion

    assert nombre_por_integracion([
        SimpleNamespace(exposicion_s=45), SimpleNamespace(exposicion_s=60.5),
    ]) == "result_105.5s"
    with pytest.raises(ValueError, match="exposición"):
        nombre_por_integracion([SimpleNamespace(exposicion_s=None)])


def test_calibrada_de_otra_raiz_no_entra_en_el_pool(tmp_path, memory_db):
    """Dos sesiones homónimas en proyectos distintos no comparten calibrado."""
    from ui.stacker_tab import StackerPage

    ajena = _sesion("noche1", 1, tmp_path / "otro_proyecto")
    actual = _sesion("noche1", 1, tmp_path / "proyecto_actual")
    salida = tmp_path / "working" / "calibrados" / "noche1"
    salida.mkdir(parents=True)
    memory_db.execute(
        "INSERT INTO calibrated_sessions(session_dir, calibrated_dir, n_frames)"
        " VALUES (?, ?, ?)", (str(ajena.path), str(salida), 1),
    )
    pagina = StackerPage()
    pagina.sesiones = [actual]
    pagina._refrescar_calibradas()

    assert pagina._calibradas == set()
    assert pagina._filas_calibradas_actuales() == []


def test_auditoria_no_recorta_la_cabecera_frame():
    """La casilla es corta y Frame conserva un mínimo sin scroll lateral."""
    from ui.stacker_tab import StackerPage

    pagina = StackerPage()
    tabla = pagina.panel_auditar._tabla
    cabecera = tabla.horizontalHeader()
    assert tabla.columnWidth(0) <= 50
    assert cabecera.minimumSectionSize() >= 42
    assert tabla.minimumWidth() >= sum(
        tabla.columnWidth(c) for c in range(tabla.columnCount())
    )


def test_log_colapsable_en_todos_los_pasos(memory_db):
    """El terminal conserva el estado elegido al navegar por las cinco fases."""
    from ui.stacker_tab import StackerPage

    pagina = StackerPage()
    for paso in range(5):
        pagina._mostrar_paso(paso)
        assert pagina._ver_log.isVisible() == pagina.isVisible()
        assert pagina._terminal.isHidden()
    pagina._alternar_log()
    for paso in range(5):
        pagina._mostrar_paso(paso)
        assert not pagina._terminal.isHidden()
    pagina._alternar_log()
    assert pagina._terminal.isHidden()


def test_ventana_real_instala_la_pagina_del_apilador():
    """MainWindow construye la pestaña Apilador (ya no es placeholder)."""
    from PyQt6.QtWidgets import QPlainTextEdit

    from ui.main_window import TABS, MainWindow
    from ui.stacker_tab import StackerPage

    ventana = MainWindow()
    indice = [clave for clave, _titulo in TABS].index("stacker_tab")
    pagina = ventana.content.widget(indice)

    assert isinstance(pagina, StackerPage)
    assert pagina.findChild(QPlainTextEdit) is not None


# ------------------------------------------------------------------- worker

def test_worker_emite_fin_log_y_progreso():
    """La tarea correcta llega por ``fin``; log y progreso cruzan por señales."""
    from ui.stacker_tab.worker import SirilWorker

    def tarea(progress_cb, log_cb):
        progress_cb(0.5)
        log_cb("hola")
        return 7

    fin, fallos, logs, progreso = [], [], [], []
    worker = SirilWorker(tarea)
    worker.fin.connect(fin.append)
    worker.fallo.connect(fallos.append)
    worker.log.connect(logs.append)
    worker.progreso.connect(progreso.append)

    worker.run()  # misma entrega directa: sin evento ni hilo que espere

    assert fin == [7]
    assert fallos == []
    assert logs == ["hola"]
    assert progreso == [50]


def test_worker_convierte_la_excepcion_en_fallo():
    """Un error de la tarea sale por ``fallo`` con su texto, nunca propaga."""
    from ui.stacker_tab.worker import SirilWorker

    def tarea_rota(progress_cb, log_cb):
        raise ValueError("va mal")

    fallos = []
    worker = SirilWorker(tarea_rota)
    worker.fallo.connect(fallos.append)

    worker.run()

    assert fallos == ["va mal"]


def test_worker_cancelado_descarta_resultado_y_cancela_siril(monkeypatch):
    """Cancelar antes o durante mata SirIL y emite ``fallo`` cancelado."""
    from ui.stacker_tab import worker as modulo_worker
    from ui.stacker_tab.worker import CANCELADO, SirilWorker

    matados = []
    monkeypatch.setattr(modulo_worker, "cancelar_siril", lambda: matados.append(1))

    fin, fallos = [], []
    worker = SirilWorker(lambda progress_cb, log_cb: "resultado viejo")
    worker.fin.connect(fin.append)
    worker.fallo.connect(fallos.append)
    worker.cancelar()
    worker.run()

    assert matados == [1]
    assert fallos == [CANCELADO]
    assert fin == []


# ------------------------------------------------------------------ escaneo

def test_escaneo_en_hilo_rellena_y_el_siguiente_avanza(tmp_path, monkeypatch):
    """Escanear corre en su hilo, rellena la tabla y «Siguiente» salta al paso 2."""
    from ui import stacker_tab
    from ui.stacker_tab import StackerPage

    sesion = _sesion("noche1", 3, tmp_path)
    monkeypatch.setattr(stacker_tab, "parse_sessions", lambda raiz: [sesion])
    monkeypatch.setattr(stacker_tab, "find_siril", lambda: "/usr/bin/siril")
    monkeypatch.setattr(stacker_tab, "list_calibrated", list)

    pagina = StackerPage()
    pagina.panel_sesiones.poner_raiz(str(tmp_path))
    pagina.escanear(ir_a=1)

    assert _esperar(lambda: pagina._paso == 1)
    tabla = pagina.panel_sesiones._tabla
    assert tabla.rowCount() == 1
    assert tabla.item(0, 0).text() == "noche1"
    assert tabla.item(0, 1).text() == "3"  # 3 tomas detectadas
    assert "Pendiente" in tabla.item(0, 0).toolTip()
    assert "Sesiones: 1" in pagina.panel_sesiones._resumen.text()
    assert "Frames: 3" in pagina.panel_sesiones._resumen.text()
    # el material y los másters viven en el paso Calibrar (no en Sesiones)
    calibrar = pagina.panel_calibrar._tabla
    assert [calibrar.horizontalHeaderItem(c).text() for c in range(5)] == [
        "Sesión", "Material", "Másters", "Estado", "Avisos",
    ]
    assert calibrar.item(0, 0).text() == "noche1"
    assert pagina._barra.isHidden()  # acabó la corrida: sin progreso


def test_tabla_sesiones_duracion_total_y_colores():
    """Columnas en su orden, exposición en segundos, tiempo legible y colores."""
    from ui.stacker_tab import StackerPage

    pagina = StackerPage()
    panel = pagina.panel_sesiones
    sesion = Session(path=Path("/x/noche1"))
    sesion.kind = "osc"
    sesion.frames["lights"] = [Path("a.fits")] * 28  # 28 × 60 s
    panel.mostrar([sesion], set(), {"noche1": [60.0] * 28})

    tabla = panel._tabla
    assert [tabla.horizontalHeaderItem(c).text() for c in range(4)] == [
        "ID", "Tomas", "Exposición", "Tiempo",
    ]
    assert tabla.item(0, 2).text() == "60 s"     # exposición por frame
    assert tabla.item(0, 3).text() == "28 min"   # acumulado legible
    assert "osc · Pendiente" in tabla.item(0, 0).toolTip()
    assert tabla.item(0, 3).foreground().color().name() == "#7ee787"
    # la línea de resumen recuenta lo mismo (un solo banner, sin pastillas)
    resumen = panel._resumen.text()
    assert "Sesiones: 1" in resumen
    assert "Frames: 28" in resumen
    assert "Integración: 28 min" in resumen

    # sin dato de exposición → «—» en ambas columnas
    panel.mostrar([sesion], set(), {})
    assert tabla.item(0, 2).text() == "—"
    assert tabla.item(0, 3).text() == "—"

    # hora y pico: 79 frames × 60 s = 4740 s → «1 h 19 min»
    sesion.frames["lights"] = [Path("a.fits")] * 79
    panel.mostrar([sesion], {"noche1"}, {"noche1": [60.0] * 79})
    assert tabla.item(0, 3).text() == "1 h 19 min"
    assert "Calibrada ✓" in tabla.item(0, 0).toolTip()

    # los segundos de integración no se pierden al combinar sesiones
    sesion.frames["lights"] = [Path("a.fits")] * 14
    panel.mostrar([sesion], set(), {"noche1": [45.0] * 14})
    assert tabla.item(0, 3).text() == "10 min 30 s"
    assert "Integración: 10 min 30 s" in panel._resumen.text()

    # sin sesiones (reinicio) el banner avisa y la ficha vuelve a su texto inicial
    panel.mostrar([], set(), {})
    assert "No se detectaron carpetas" in panel._resumen.text()
    assert panel._detalle_optico.text() == "Sin escanear todavía."


def test_tabla_sesiones_region_y_ficha_fits():
    """La región sale de las coordenadas FITS y la ficha junta óptica/sitio."""
    from stacks.session_parser import FichaFITS
    from ui.stacker_tab import StackerPage
    from ui.stacker_tab.pasos import _formato_ficha, _formato_region

    assert _formato_region(None) == "—"
    assert _formato_region(FichaFITS()) == "—"
    ficha = FichaFITS(ra_deg=11.77643, dec_deg=41.26189)
    assert _formato_region(ficha) == "0h47m, +41,3°"
    # en el borde de la hora el redondeo no puede dar «2h60m»
    assert _formato_region(FichaFITS(ra_deg=29.9999, dec_deg=-1.0)) == "2h00m, -1,0°"

    pagina = StackerPage()
    panel = pagina.panel_sesiones
    sesion = Session(path=Path("/x/noche1"))
    sesion.frames["lights"] = [Path("a.fits")]
    panel.mostrar([sesion], set(), {"noche1": [45.0]}, {"noche1": ficha})
    tabla = panel._tabla
    assert "0h47m, +41,3°" in tabla.item(0, 0).toolTip()
    assert "0h47m, +41,3°" in panel._detalle_sitio.text()

    completa = FichaFITS(
        camara="GPhoto CCD", montura="iOptron SkyGuider Pro",
        focal_mm=420.0, diametro_mm=70.0, escala_as_px=1.915643,
        px_x=6000, px_y=4000, pix_um=3.9, binning=1,
        lat=10.01917, lon=-84.28153,
    )
    texto = _formato_ficha({"a": completa})
    assert "Óptica:</b> 420 mm · f/6 · 1,916 ″/px" in texto
    assert "Sensor:</b> 6000×4000 px · 3,9 µm · 23,4×15,6 mm · bin 1×1" in texto
    assert "Equipo:</b> GPhoto CCD · iOptron SkyGuider Pro" in texto
    assert "Sitio:</b> +10,019°, -84,282°" in texto

    # dos sesiones con cámaras distintas: se ven las dos sin repetir etiquetas
    otra = FichaFITS(camara="ASI294MC")
    dos = _formato_ficha({"a": completa, "b": otra})
    assert "iOptron SkyGuider Pro / ASI294MC" in dos
    assert "&lt;b&gt;" in _formato_ficha({"a": FichaFITS(camara="<b>")})
    # sin cabeceras en ninguna sesión: se avisa
    assert "Sin cabeceras" in _formato_ficha({"a": FichaFITS()})


def test_visor_sesiones_usa_fits_y_seleccion_sin_modificar_originales(tmp_path):
    """La fila elegida controla miniatura y fichas; no se reescribe el FITS."""
    import numpy as np
    from astropy.io import fits

    from ui.stacker_tab.pasos import PanelSesiones

    sesiones = []
    originales = {}
    fichas = {}
    for nombre, centro in (("noche1", 11.0), ("noche2", 22.0)):
        ruta = tmp_path / nombre / "lights" / "luz.fits"
        ruta.parent.mkdir(parents=True)
        fits.writeto(ruta, np.arange(64, dtype=np.uint16).reshape(8, 8),
                     header=fits.Header({"RA": centro, "DEC": 5.0, "SCALE": 2.0}))
        originales[ruta] = ruta.read_bytes()
        sesion = Session(path=ruta.parent.parent)
        sesion.frames["lights"] = [ruta]
        if nombre == "noche1":
            sesion.frames["lights"].insert(0, ruta.with_suffix(".cr2"))
        sesiones.append(sesion)
        from stacks.session_parser import ficha_de_luz
        fichas[nombre] = ficha_de_luz(ruta)

    panel = PanelSesiones()
    panel.mostrar(sesiones, set(), {}, fichas)
    assert _esperar(lambda: panel._visor._imagen is not None)
    assert panel._visor._ficha.ra_deg == 11.0
    panel._tabla.selectRow(1)
    assert _esperar(lambda: panel._visor._imagen is not None
                   and panel._visor._ficha.ra_deg == 22.0)
    assert "1h28m" in panel._detalle_sitio.text()
    panel._visor._zoom = 2
    panel._visor.reiniciar_vista()
    assert panel._visor._zoom == 1
    assert all(ruta.read_bytes() == contenido for ruta, contenido in originales.items())


def test_visor_ignora_lectura_tardia_y_datos_ausentes():
    """Una lectura anterior no reemplaza la sesión recién seleccionada."""
    from PyQt6.QtGui import QImage

    from stacks.session_parser import FichaFITS
    from ui.stacker_tab.visor_sesiones import VisorSesiones

    visor = VisorSesiones(lambda _ruta: None)
    visor.mostrar(None, FichaFITS())
    vieja = visor._revision
    visor.mostrar(None, FichaFITS(ra_deg=2, dec_deg=3))
    visor._recibir(vieja, QImage(2, 2, QImage.Format.Format_RGB888))
    assert visor._imagen is None
    assert visor._ficha.ra_deg == 2


def test_cielo_capturado_reutiliza_catalogo_y_no_activa_telescopius(memory_db):
    """Carta centrada en FITS: usa objetos reales, marco y botón aún inerte."""
    from stacks.session_parser import FichaFITS
    from ui.stacker_tab.pasos import PanelSesiones

    memory_db.execute(
        "INSERT INTO catalog(object_id, catalog, ra_hours, dec_deg)"
        " VALUES ('M31', 'messier', ?, ?)", (11.7764 / 15, 41.2619),
    )
    panel = PanelSesiones()
    ficha = FichaFITS(ra_deg=11.7764, dec_deg=41.2619,
                      px_x=6000, px_y=4000, escala_as_px=1.92,
                      rotacion_deg=3.0, altitud_m=822)
    panel._cielo.mostrar(ficha)
    panel._rellenar_campos(ficha)
    assert "M31" in panel._cielo._objects["ids"]
    assert panel._cielo._framing[2:4] == (3.2, 2.1333333333333333)
    assert not panel._telescopius.isEnabled()
    assert panel._sitio_campos_2.text() == "--"
    panel._cielo._fov_deg = 30
    panel._cielo.reset_view()
    assert panel._cielo.view[0] == pytest.approx(11.7764 / 15)
    assert panel._cielo.view[2] < 30
    panel._cielo.mostrar(None)
    assert panel._cielo._framing is None and not panel._cielo._valido


def test_sesiones_diseno_referencia_grupos_fichas_y_escala():
    """La subpaso «Sesiones» reproduce la maqueta de referencia de la imagen.

    Dos grupos fijos de 115 px con rejilla 2×2, sin dato escrito como «--» o
    «Pendiente FITS» (nunca un valor inventado), panel de rotación flotante
    oculto hasta que haya encuadre, y escala/Región tomadas del FITS.
    """
    from stacks.session_parser import FichaFITS
    from ui.stacker_tab.pasos import PanelSesiones

    panel = PanelSesiones()

    # Arranque (sin escanear): altura fija y ausencia de datos a la vista.
    assert panel._grupo_opt.height() == 115
    assert panel._grupo_sitio.height() == 115
    assert panel._optica_campos_0.text() == "--"
    assert panel._sitio_campos_0.text() == "--"
    assert panel._sitio_campos_2.text() == "--"
    assert panel._optica_campos_2.text() == "Pendiente FITS"
    assert panel._sitio_campos_3.text() == "Pendiente FITS"
    assert panel._panel_rot.isHidden()  # no hay contorno que rotar todavía

    # Todos los valores FITS son informativos, sin flechas ni edición.
    assert panel._optica_campos_0.isReadOnly()
    assert panel._optica_campos_1.isReadOnly()
    assert panel._optica_campos_0.buttonSymbols() == panel._optica_campos_0.ButtonSymbols.NoButtons
    assert panel._sitio_campos_0.isReadOnly()
    assert panel._sitio_campos_2.buttonSymbols() == panel._sitio_campos_2.ButtonSymbols.NoButtons
    assert panel._sitio_campos_3.isReadOnly()
    assert "border: none" in panel._grupo_opt.styleSheet()
    assert "border: none" in panel._sitio_campos_3.styleSheet()
    assert "font-size: 12pt" in panel._optica_campos_2.styleSheet()
    assert "font-size: 12pt" in panel._sitio_campos_3.styleSheet()

    ficha = FichaFITS(
        ra_deg=11.7764, dec_deg=41.2619, objeto="M31",
        px_x=6000, px_y=4000, escala_as_px=1.92, focal_mm=420.0,
        pix_um=3.9, rotacion_deg=3.0, altitud_m=822, lat=46.2, lon=6.1,
    )
    panel._cielo.mostrar(ficha)
    panel._rellenar_campos(ficha)

    assert panel._optica_campos_0.value() == pytest.approx(420.0)
    assert panel._sitio_campos_0.value() == pytest.approx(46.2)
    assert panel._sitio_campos_2.text() == "--"  # elevación del sitio no es altura del objeto
    assert panel._optica_campos_2.text() == "1,92 arcsec/px"  # manda SCALE
    assert panel._optica_campos_3.text() == "3°"
    assert "CROTA2" in panel._optica_campos_3.toolTip()
    assert panel._sitio_campos_3.text() == "M31 | 0h47m, +41,3°"
    ficha.altura_obj_deg = 47.73039
    panel._rellenar_campos(ficha)
    assert panel._sitio_campos_2.value() == pytest.approx(47.7)
    assert panel._sitio_campos_3.text() == "M31 | 0h47m, +41,3°"
    panel._actualizar_detalles(ficha)
    assert "822 m" in panel._grupo_sitio.toolTip()
    assert panel._rotacion.value() == 3
    assert not panel._panel_rot.isHidden()  # ya hay encuadre que rotar
    # …aunque el panel todavía no se ve: su padre no está a la vista.
    assert not panel._panel_rot.isVisible()

    # Sin SCALE ni datos ópticos suficientes no se inventa una escala.
    panel._rellenar_campos(FichaFITS())
    assert panel._optica_campos_2.text() == "Pendiente FITS"

    # «Ver FITS» solo existe cuando hay imagen; sin sesión se oculta y no
    # queda un botón muerto sobre la carta vacía.
    assert not panel._alternar_vista.isHidden()
    panel.mostrar([], set(), {})
    assert panel._alternar_vista.isHidden()


def test_sesiones_objctalt_visible_sin_elevacion_del_observatorio(tmp_path):
    """OBJCTALT se muestra en grados; no se confunde con SITEELEV ausente."""
    import numpy as np
    from astropy.io import fits

    from stacks.session_parser import ficha_de_luz
    from ui.stacker_tab.pasos import PanelSesiones

    ruta = tmp_path / "light.fit"
    fits.writeto(ruta, np.zeros((2, 2)), header=fits.Header({
        "OBJCTALT": 58.57722, "SITELAT": 10.01917,
        "SITELONG": -84.28153, "RA": 17.95289, "DEC": 41.26607,
        "OBJECT": "Unknown",
    }))
    ficha = ficha_de_luz(ruta)
    panel = PanelSesiones()
    panel._rellenar_campos(ficha)
    panel._actualizar_detalles(ficha)
    assert panel._sitio_campos_2.value() == pytest.approx(58.6)
    assert panel._sitio_campos_3.text() != "Pendiente FITS"
    assert "Alt." not in panel._sitio_campos_3.text()
    assert "No consta en FITS" in panel._grupo_sitio.toolTip()


def test_limpieza_working_explicita_con_ruta_y_confirmacion(
    tmp_path, monkeypatch, memory_db,
):
    """Conservar no borra; eliminar todo requiere confirmar la ruta exacta."""
    from PyQt6.QtWidgets import QMessageBox

    from stacks import siril_runner
    from ui import stacker_tab

    raiz = tmp_path / "working"
    raiz.mkdir()
    salida = raiz / "apilado.fit"
    salida.write_bytes(b"resultado")
    original = tmp_path / "light.fit"
    original.write_bytes(b"original")
    monkeypatch.setattr(stacker_tab, "WORKING_FOLDER", raiz)
    monkeypatch.setattr(siril_runner, "WORKING_FOLDER", raiz)
    visto = []
    elegir = ["Conservar"]

    def abrir(dialogo):
        """Simula el clic sin mostrar un modal durante pytest."""
        visto.append(dialogo.informativeText())
        return 0

    def pulsado(dialogo):
        """Devuelve el botón que escogería el usuario."""
        return next(b for b in dialogo.buttons() if b.text() == elegir[0])

    monkeypatch.setattr(QMessageBox, "exec", abrir)
    monkeypatch.setattr(QMessageBox, "clickedButton", pulsado)
    pagina = stacker_tab.StackerPage()
    pagina._preguntar_trabajo()
    assert salida.exists() and str(raiz) in visto[0]

    elegir[0] = "Eliminar TODO working"
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.No,
    )
    pagina._preguntar_trabajo()
    assert salida.exists()  # segunda confirmación rechazada
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    pagina._preguntar_trabajo()
    assert not salida.exists() and original.read_bytes() == b"original"


def test_limpieza_selectiva_conserva_otras_salidas(tmp_path, monkeypatch, memory_db):
    """Borrar calibrados de la sesión actual no afecta otras noches ni apilados."""
    from PyQt6.QtWidgets import QMessageBox

    from stacks import siril_runner
    from ui import stacker_tab

    raiz = tmp_path / "working"
    actual = raiz / "calibrados" / "noche1"
    otra = raiz / "calibrados" / "noche2"
    actual.mkdir(parents=True)
    otra.mkdir()
    (actual / "pp_light.fit").write_bytes(b"salida")
    (otra / "pp_light.fit").write_bytes(b"ajena")
    apilado = raiz / "apilado.fit"
    apilado.write_bytes(b"apilado")
    monkeypatch.setattr(stacker_tab, "WORKING_FOLDER", raiz)
    monkeypatch.setattr(siril_runner, "WORKING_FOLDER", raiz)
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: 0)
    monkeypatch.setattr(
        QMessageBox, "clickedButton",
        lambda dlg: next(
            b for b in dlg.buttons() if b.text() == "Eliminar estos calibrados"
        ),
    )
    pagina = stacker_tab.StackerPage()
    pagina.sesiones = [Session(path=tmp_path / "noche1")]
    pagina._preguntar_trabajo()
    assert not actual.exists()
    assert (otra / "pp_light.fit").read_bytes() == b"ajena"
    assert apilado.read_bytes() == b"apilado"


def test_conservar_no_sobrescribe_calibrados_parciales(
    tmp_path, monkeypatch, memory_db,
):
    """Una salida parcial sin registro en BD tampoco se limpia al calibrar."""
    from ui import stacker_tab

    raiz = tmp_path / "working"
    salida = raiz / "calibrados" / "noche1" / "light" / "pp_light.fit"
    salida.parent.mkdir(parents=True)
    salida.write_bytes(b"parcial")
    monkeypatch.setattr(stacker_tab, "WORKING_FOLDER", raiz)
    pagina = stacker_tab.StackerPage()
    pagina.sesiones = [Session(path=tmp_path / "noche1")]
    monkeypatch.setattr(pagina, "_asegurar_siril", lambda: True)
    monkeypatch.setattr(
        pagina, "_lanzar", lambda *a, **k: pytest.fail("No debe lanzar SirIL"),
    )
    pagina.calibrar()
    assert salida.read_bytes() == b"parcial"
    assert not pagina._calibrado


def test_entrar_en_calibrar_avisa_solo_una_vez_si_hay_datos(
    tmp_path, monkeypatch, memory_db,
):
    """El paso Calibrar ofrece limpiar los datos previos sin hacerlo solo."""
    from ui import stacker_tab

    raiz = tmp_path / "working"
    salida = raiz / "calibrados" / "noche1"
    salida.mkdir(parents=True)
    monkeypatch.setattr(stacker_tab, "WORKING_FOLDER", raiz)
    pagina = stacker_tab.StackerPage()
    pagina.sesiones = [Session(path=tmp_path / "noche1")]
    avisos = []
    monkeypatch.setattr(pagina, "_preguntar_trabajo", lambda: avisos.append(True))
    pagina._mostrar_paso(1)
    pagina._mostrar_paso(0)
    pagina._mostrar_paso(1)
    assert avisos == [True]
    assert salida.is_dir()


def test_repertir_anchos_reparte_el_ancho_de_la_cabecera():
    """El ID ocupa el 44 % y el resto no baja de los mínimos de las otras.

    Se prueban anchos dados porque el ancho real del panel depende de la
    fuente de la plataforma (offscreen en CI, Windows en escritorio): el
    reparto es el mismo para el mismo ancho de cabecera.
    """
    from ui.stacker_tab.pasos import PanelSesiones

    panel = PanelSesiones()
    tabla = panel._tabla

    # Panel ancho: el ID manda y las tres numéricas comparten el resto.
    panel._repertir_anchos(1200)
    assert [tabla.columnWidth(c) for c in range(4)] == [528, 203, 237, 232]
    assert sum(tabla.columnWidth(c) for c in range(4)) == 1200

    # Estrecho: el 44 % choca con los mínimos de las tres numéricas.
    panel._repertir_anchos(445)
    assert [tabla.columnWidth(c) for c in range(4)] == [155, 75, 110, 105]

    # Muy estrecho: se conservan los mínimos y Qt ofrece desplazamiento.
    panel._repertir_anchos(317)
    assert [tabla.columnWidth(c) for c in range(4)] == [145, 75, 110, 105]


def test_tabla_sesiones_anchos_sigue_al_widget():
    """Los anchos se recalculan cuando la tabla cambia de tamaño (event filter).

    El reparto concreto se prueba aparte contra un ancho dado: aquí lo que
    importa es que el filtro corre con la cabecera ya medida y llena el
    hueco sin dejar los 100 px por columna de fábrica.
    """
    from ui.stacker_tab.pasos import PanelSesiones

    panel = PanelSesiones()  # sin padre: su resize manda sobre sus hijos
    sesion = Session(path=Path("/x/noche1"))
    sesion.frames["lights"] = [Path("a.fits")]
    panel.mostrar([sesion], set(), {"noche1": [60.0]})
    tabla = panel._tabla

    panel.resize(1200, 500)
    panel.show()

    def lleno() -> bool:
        """True cuando el filtro ya repartió el ancho real de la cabecera."""
        ancho = tabla.horizontalHeader().width()
        suma = sum(tabla.columnWidth(c) for c in range(tabla.columnCount()))
        return ancho > 400 and abs(suma - ancho) <= tabla.columnCount()

    assert _esperar(lleno)
    ancho = tabla.horizontalHeader().width()
    suma = sum(tabla.columnWidth(c) for c in range(tabla.columnCount()))
    # las cuatro columnas llenan la cabecera, sin descuadre de píxel
    assert abs(suma - ancho) <= tabla.columnCount()
    assert tabla.columnWidth(2) >= 110  # «Exposición» completa
    assert tabla.columnWidth(3) >= 105  # «Tiempo» completo


def test_escaneo_sin_carpeta_no_lanza_nada():
    """Raíz vacía o inexistente: avisa en la línea de estado y no arranca hilo."""
    from ui.stacker_tab import StackerPage

    pagina = StackerPage()
    pagina.panel_sesiones._raiz.clear()  # sin raíz (la de Configuración no vale)
    pagina.escanear()

    assert pagina._worker is None
    assert "carpeta raíz" in pagina._estado.text()

    pagina.panel_sesiones.poner_raiz("/esta/carpeta/no/existe")
    pagina.escanear()

    assert pagina._worker is None
    assert "no existe" in pagina._estado.text()


# ------------------------------------------------------- cadena «Hacer todo»

def test_hacer_todo_encadena_las_cuatro_fases(tmp_path, monkeypatch, memory_db):
    """«Hacer todo» encadena escaneo → calibración → auditoría → apilado.

    Usa la BD real (``memory_db``): la sesión calibrada se persiste desde el
    hilo principal vía la señal ``dato``. Si la escritura volviera al hilo
    de trabajo, SQLite abortaría («can only be used in that same thread»)
    y la cadena se cortaría en la calibración.
    """
    from db.settings import set_setting
    from stacks.calibrator import SETTING_GLOBAL_DIR, _material_global, list_calibrated
    from stacks.siril_runner import _binario_tarea
    from ui import stacker_tab
    from ui.stacker_tab import StackerPage

    sesion = _sesion("noche1", 2, tmp_path)
    llamadas: list[str] = []
    set_setting(SETTING_GLOBAL_DIR, str(tmp_path / "global_inexistente"))

    def calibrar_falso(sesion_cal, **kwargs):
        # La conexión SQLite del fixture pertenece al hilo principal.
        assert _binario_tarea.get() == "/usr/bin/siril"
        assert kwargs["global_dir"] == str(tmp_path / "global_inexistente")
        assert _material_global(kwargs["global_dir"]) == ({}, {})
        llamadas.append("calibrar")
        destino = tmp_path / "cal" / sesion_cal.path.name
        destino.mkdir(parents=True, exist_ok=True)
        return CalibrationResult(
            session=sesion_cal, dir=destino, n_lights=2, exposure_s=30.0
        )

    def pool_falso(filas):
        llamadas.append("pool")
        pool = GlobalPool()
        pool.entries = [
            LightRef(
                ruta=Path("/tmp/working") / f"pp_light_{i:05d}.fit",
                sesion="noche1",
                filtro=None,
                exposicion_s=30.0,
            )
            for i in (1, 2)
        ]
        return pool

    def audit_falso(pool, **_kwargs):
        llamadas.append("auditar")
        return Registro(
            dir=tmp_path / "reg",
            seq="registro_",
            frames=list(pool.entries),
            transformadas=False,
        )

    def metricas_falso(registro, pesos=None):
        llamadas.append("metricas")
        return [
            FrameMetrics(
                path=str(ref.ruta),
                session=ref.sesion,
                fwhm=2.0,
                roundness=1.0,
                transparency=1.0,
                background=100.0,
                weighted=90.0 - 10 * i,
            )
            for i, ref in enumerate(registro.frames)
        ]

    def registrar_falso(pool, nombre, *, aceptados=None, debayer=False,
                        drizzle=False, **_kwargs):
        llamadas.append(
            f"registrar:{len(aceptados or pool.entries)}"
            f":debayer={debayer}:drizzle={drizzle}"
        )
        return Registro(
            dir=tmp_path / "reg_final",
            seq="registro_",
            frames=list(aceptados or pool.entries),
        )

    def apilar_falso(registro, nombre, *, opciones, progress_cb=None, log_cb=None):
        llamadas.append("apilar")
        carpeta = tmp_path / "apilados" / nombre
        return [carpeta / f"{nombre}.fit"]

    monkeypatch.setattr(stacker_tab, "parse_sessions", lambda raiz: [sesion])
    monkeypatch.setattr(stacker_tab, "find_siril", lambda: "/usr/bin/siril")
    monkeypatch.setattr(stacker_tab, "calibrate_session", calibrar_falso)
    monkeypatch.setattr(stacker_tab, "pool_desde_calibradas", pool_falso)
    monkeypatch.setattr(stacker_tab, "audit_pool", audit_falso)
    monkeypatch.setattr(stacker_tab, "register_pool", registrar_falso)
    monkeypatch.setattr(stacker_tab, "extract_metrics", metricas_falso)
    monkeypatch.setattr(stacker_tab, "apilar_pool", apilar_falso)
    monkeypatch.setattr(stacker_tab, "exportar_apilados", lambda salidas, _madre: salidas)

    pagina = StackerPage()
    pagina.panel_sesiones.poner_raiz(str(tmp_path))
    pagina.panel_apilar._nombre.setText("mi_pila")

    pagina.hacer_todo()
    assert _esperar(lambda: pagina._paso == 4)

    # orden exacto de las fases: auditoría rápida y luego registro final
    # (sin drizzle → debayer de los CFA) + apilado.
    assert llamadas == [
        "calibrar", "pool", "auditar", "metricas",
        "registrar:2:debayer=True:drizzle=False", "apilar",
    ]
    assert pagina._calibrado and pagina._auditado and pagina._apilado
    assert pagina.panel_auditar._tabla.rowCount() == 2
    assert pagina.panel_auditar.aceptados() == [1, 2]
    assert pagina.panel_final._salidas.count() == 1
    assert "mi_pila" in pagina.panel_final._resumen.text()
    assert pagina._barra.isHidden()
    assert not pagina._siguiente.isEnabled()  # último paso
    # la BD real quedó al día con la calibración (guardada en el hilo principal)
    assert [Path(f["calibrated_dir"]).name for f in list_calibrated()] == [
        "noche1"
    ]


def test_apilar_pide_debayer_o_drizzle_segun_la_casilla(tmp_path, monkeypatch):
    """Sin drizzle → registro final con debayer; con drizzle → solo drizzle.

    Los dos nunca van juntos: SirIL 1.4.4 rebayeriza él solo al drizzlezar
    CFA, y la decisión la toma el usuario con la casilla del paso Apilar.
    """
    from ui import stacker_tab
    from ui.stacker_tab import StackerPage

    ref = LightRef(
        ruta=tmp_path / "pp_light_00001.fit",
        sesion="noche1",
        filtro=None,
        exposicion_s=30.0,
    )
    pool = GlobalPool()
    pool.entries = [ref]
    auditoria = Registro(
        dir=tmp_path / "reg", seq="registro_", frames=[ref], transformadas=False
    )
    metrica = FrameMetrics(
        path=str(ref.ruta), session="noche1", fwhm=2.0, roundness=1.0,
        transparency=1.0, background=100.0, weighted=90.0,
    )
    llamadas: list[dict] = []

    def registrar_falso(pool_falso, nombre, *, aceptados=None, debayer=False,
                        drizzle=False, **_kwargs):
        llamadas.append({"debayer": debayer, "drizzle": drizzle})
        return Registro(
            dir=tmp_path / "reg_final", seq="registro_",
            frames=list(aceptados or pool_falso.entries),
        )

    monkeypatch.setattr(stacker_tab, "find_siril", lambda: "/usr/bin/siril")
    monkeypatch.setattr(stacker_tab, "register_pool", registrar_falso)
    monkeypatch.setattr(
        stacker_tab, "apilar_pool",
        lambda registro, nombre, **_k: [tmp_path / "x.fit"],
    )

    pagina = StackerPage()
    pagina.sesiones = [_sesion("noche1", 1, tmp_path)]
    pagina.registro = auditoria
    pagina.metricas = [metrica]
    pagina._pool = pool
    pagina.panel_auditar.mostrar(auditoria, [metrica])
    pagina.panel_apilar._nombre.setText("pila")

    pagina.apilar()
    assert _esperar(
        lambda: pagina._worker is None and len(llamadas) == 1
    )
    assert llamadas[0] == {"debayer": True, "drizzle": False}

    pagina.panel_apilar._drizzle.setChecked(True)
    pagina.apilar()
    assert _esperar(
        lambda: pagina._worker is None and len(llamadas) == 2
    )
    assert llamadas[1] == {"debayer": False, "drizzle": True}


def test_siguiente_salta_las_fases_ya_hechas(tmp_path):
    """El «Siguiente» no repite fases hechas: va directo a la siguiente."""
    from ui.stacker_tab import StackerPage

    pagina = StackerPage()
    pagina.sesiones = [_sesion("noche1", 1, tmp_path)]

    pagina._ir_siguiente()
    assert pagina._paso == 1

    pagina._calibrado = True
    pagina._ir_siguiente()
    assert pagina._paso == 2

    pagina._auditado = True
    pagina._ir_siguiente()
    assert pagina._paso == 3

    pagina._apilado = True
    pagina._ir_siguiente()
    assert pagina._paso == 4
    assert not pagina._siguiente.isEnabled()


# ------------------------------------------------- opciones y descarte manual

def test_opciones_de_apilado_rechazan_lo_que_siril_no_acepta():
    """Combinaciones que SirIL no admite revientan ya en el formulario."""
    from ui.stacker_tab.pasos import PanelApilar

    panel = PanelApilar()
    panel._integracion.setCurrentIndex(panel._integracion.findData("med"))
    panel._ponderacion.setCurrentIndex(panel._ponderacion.findData("noise"))

    with pytest.raises(ValueError, match="mean"):
        panel.opciones()

    panel._ponderacion.setCurrentIndex(0)  # sin ponderación: válido otra vez
    panel._integracion.setCurrentIndex(panel._integracion.findData("med"))
    assert panel.opciones().integration == "med"


def test_pesos_todos_a_cero_no_se_aceptan():
    """La puntuación sin pesos no existe: avisa en vez de puntuar a ciegas."""
    from ui.stacker_tab.pasos import PanelAuditar

    panel = PanelAuditar()
    for spin in panel._pesos.values():
        spin.setValue(0)

    with pytest.raises(ValueError, match="cero"):
        panel.pesos()


def test_descartar_recomendados_desmarca_con_motivo_y_respeta_a_siril(tmp_path):
    """Los recomendados desmarcan su fila con su motivo; SirIL sigue intocable."""
    from ui.stacker_tab import StackerPage

    pagina = StackerPage()
    refs = [
        LightRef(
            ruta=tmp_path / f"pp_light_{i:05d}.fit",
            sesion="noche1",
            filtro=None,
            exposicion_s=30.0,
        )
        for i in (1, 2, 3, 4, 5)
    ]
    registro = Registro(dir=tmp_path, seq="registro_", frames=refs)
    fondos = [100.0, 100.0, 100.0, 400.0]  # el 4º es el peor de todo
    metricas = [
        FrameMetrics(
            path=str(refs[i].ruta),
            session="noche1",
            fwhm=[2.0, 2.0, 2.0, 12.0][i],
            roundness=1.0,
            transparency=100.0 / fondos[i],
            background=fondos[i],
            weighted=0.0,
        )
        for i in range(4)
        # el 5º frame no tiene métricas: SirIL lo descartó al registrar
    ]
    pagina.registro = registro
    pagina.metricas = metricas
    pagina.panel_auditar.mostrar(registro, metricas)

    tabla = pagina.panel_auditar._tabla
    assert tabla.rowCount() == 5
    # La columna «Descartada» dice el motivo (Puntuación por debajo del
    # mínimo; SirIL, sin métricas); los tres buenos, «No».
    assert tabla.item(0, 8).text() == "No"
    assert tabla.item(3, 8).text() == "Sí · Puntuación"
    assert tabla.item(4, 8).text() == "SirIL"

    pagina.descartar_recomendados()

    assert pagina.panel_auditar.aceptados() == [1, 2, 3]
    assert "casillas" in pagina._estado.text()


def test_la_tabla_se_ordena_por_puntuacion_y_aceptados_mapea_indices(tmp_path):
    """La tabla va de mayor a menor; las casillas siguen hablando por índice."""
    from ui.stacker_tab import StackerPage

    pagina = StackerPage()
    refs = [
        LightRef(
            ruta=tmp_path / f"pp_light_{i:05d}.fit",
            sesion="noche1",
            filtro=None,
            exposicion_s=30.0,
        )
        for i in (1, 2, 3)
    ]
    registro = Registro(dir=tmp_path, seq="registro_", frames=refs)
    metricas = [
        FrameMetrics(
            path=str(refs[i].ruta),
            session="noche1",
            fwhm=[8.0, 4.0, 5.0][i],  # el 2º es el mejor, el 1º el peor
            roundness=1.0,
            transparency=1.0,
            background=100.0,
            weighted=0.0,
        )
        for i in range(3)
    ]
    pagina.panel_auditar.mostrar(registro, metricas)

    tabla = pagina.panel_auditar._tabla
    assert [tabla.item(f, 1).text() for f in range(3)] == [
        "pp_light_00002.fit", "pp_light_00003.fit", "pp_light_00001.fit",
    ]
    # El orden de la tabla NO es el de la secuencia: aceptados() devuelve
    # índices de secuencia (1-based), que es lo que consume apilar.
    assert pagina.panel_auditar.aceptados() == [2, 3, 1]
    # …pero la gráfica se dibuja por orden de registro (sin zigzag).
    xs, _ys = pagina.panel_auditar._curva.getData()
    assert list(xs) == [1, 2, 3]


def test_actualizar_repuntua_sin_registrar_y_conserva_las_casillas(tmp_path):
    """«Actualizar» aplica el mínimo nuevo al instante y no pisa elecciones."""
    from PyQt6.QtCore import Qt

    from ui.stacker_tab.pasos import PanelAuditar

    refs = [
        LightRef(
            ruta=tmp_path / f"pp_light_{i:05d}.fit",
            sesion="noche1",
            filtro=None,
            exposicion_s=30.0,
        )
        for i in (1, 2)
    ]
    registro = Registro(dir=tmp_path, seq="registro_", frames=refs)
    metricas = [
        FrameMetrics(
            path=str(refs[i].ruta),
            session="noche1",
            fwhm=[8.0, 4.0][i],
            roundness=1.0,
            transparency=1.0,
            background=100.0,
            weighted=0.0,
        )
        for i in range(2)
    ]
    panel = PanelAuditar()
    panel._umbral.setValue(0.0)  # sin mínimo: nadie recomendado aún
    panel.mostrar(registro, metricas)
    tabla = panel._tabla
    assert tabla.item(1, 8).text() == "No"
    assert panel.aceptados() == [2, 1]  # en orden de tabla (el 2º puntúa más)

    # El usuario descarta al peor a mano y luego sube el mínimo.
    tabla.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    panel._umbral.setValue(80.0)
    panel.actualizar()

    assert tabla.item(1, 8).text() == "Sí · Puntuación"  # el motivo ya sale
    assert panel.aceptados() == [2]  # la casilla del usuario se conserva


def test_aviso_si_el_minimo_se_lleva_todos_los_frames(tmp_path):
    """Si el mínimo deja el pool vacío, el resumen lo dice (puntuación relativa)."""
    from ui.stacker_tab.pasos import PanelAuditar

    refs = [
        LightRef(
            ruta=tmp_path / f"pp_light_{i:05d}.fit",
            sesion="noche1",
            filtro=None,
            exposicion_s=30.0,
        )
        for i in (1, 2, 3)
    ]
    registro = Registro(dir=tmp_path, seq="registro_", frames=refs)
    # Cada frame es el mejor en algo: con la puntuación relativa al pool
    # nadie llega a 100 y el mínimo por defecto (80) se los lleva a los tres.
    metricas = [
        FrameMetrics(
            path=str(refs[i].ruta), session="noche1",
            fwhm=[4.0, 6.0, 5.0][i], roundness=[1.0, 0.9, 0.95][i],
            transparency=[0.7, 0.8, 0.9][i], background=[700.0, 600.0, 500.0][i],
            weighted=0.0,
        )
        for i in range(3)
    ]
    panel = PanelAuditar()
    panel.mostrar(registro, metricas)

    assert "TODOS" in panel._resumen.text()

    panel._umbral.setValue(0.0)
    panel.actualizar()
    assert "TODOS" not in panel._resumen.text()


def test_seleccionar_un_frame_carga_su_miniatura(tmp_path):
    """Al seleccionar una fila se carga la miniatura del FITS del frame."""
    import numpy as np
    from astropy.io import fits

    from ui.stacker_tab.pasos import PanelAuditar

    ruta = tmp_path / "pp_light_00001.fit"
    fits.writeto(ruta, np.full((64, 48), 1000, dtype=np.uint16), overwrite=True)
    refs = [
        LightRef(ruta=ruta, sesion="noche1", filtro=None, exposicion_s=30.0)
    ]
    registro = Registro(dir=tmp_path, seq="registro_", frames=refs)
    metrica = FrameMetrics(
        path=str(ruta), session="noche1", fwhm=2.0, roundness=1.0,
        transparency=1.0, background=100.0, weighted=90.0,
    )
    panel = PanelAuditar()
    panel.mostrar(registro, [metrica])

    panel._tabla.selectRow(0)

    assert panel._preview_img is not None
    assert (panel._preview_img.width(), panel._preview_img.height()) == (48, 64)
    assert "pp_light_00001.fit" in panel._preview_pie.text()
    assert "100.0 puntos" in panel._preview_pie.text()  # único frame: el mejor
    assert panel._tabla.item(0, 5).text() == "100.0"
    assert panel._splitter.minimumHeight() >= 320


def test_preview_de_un_cfa_sale_a_color_y_el_mono_en_gris(tmp_path):
    """La miniatura desempaqueta el mosaico Bayer a RGB; el mono, gris."""
    import numpy as np
    from astropy.io import fits
    from PyQt6.QtGui import QImage

    from ui.stacker_tab.pasos import _preview_fits

    cfa = np.full((64, 64), 500, dtype=np.uint16)
    cfa[::2, ::2] = 2000  # canal R del mosaico RGGB
    ruta_cfa = tmp_path / "cfa.fit"
    fits.writeto(
        ruta_cfa, cfa, header=fits.Header({"BAYERPAT": "RGGB"}), overwrite=True
    )
    ruta_mono = tmp_path / "mono.fit"
    fits.writeto(ruta_mono, cfa, overwrite=True)

    qimg_cfa = _preview_fits(ruta_cfa)
    qimg_mono = _preview_fits(ruta_mono)

    assert qimg_cfa.format() == QImage.Format.Format_RGB888
    assert (qimg_cfa.width(), qimg_cfa.height()) == (32, 32)  # canal a la mitad
    assert qimg_mono.format() == QImage.Format.Format_Grayscale8
    assert (qimg_mono.width(), qimg_mono.height()) == (64, 64)


def test_preview_enlaza_canales_de_fits_normalizado(tmp_path):
    """El fondo de un CFA float32 normalizado no queda rojo o azul."""
    import numpy as np
    from astropy.io import fits

    from ui.stacker_tab.pasos import _preview_fits

    cfa = np.empty((64, 64), dtype=np.float32)
    cfa[::2, ::2] = 0.0018  # R
    cfa[::2, 1::2] = 0.0010  # G
    cfa[1::2, ::2] = 0.0010  # G
    cfa[1::2, 1::2] = 0.0006  # B
    cfa[16:20, 16:20] *= 4  # señal común que hace visible el fondo
    ruta = tmp_path / "normalizado.fit"
    fits.writeto(ruta, cfa, header=fits.Header({"BAYERPAT": "RGGB"}))

    imagen = _preview_fits(ruta)
    pixel = imagen.pixelColor(2, 2)
    assert max(pixel.red(), pixel.green(), pixel.blue()) - min(
        pixel.red(), pixel.green(), pixel.blue()
    ) <= 1


def test_controles_auditoria_comparten_filas_y_ancho():
    """Pesos, criterios y acciones caben juntos; registrar va con la pista."""
    from PyQt6.QtWidgets import QHBoxLayout

    from ui.stacker_tab.pasos import PanelAuditar

    panel = PanelAuditar()
    filas = [
        panel.layout().itemAt(i).layout()
        for i in range(panel.layout().count())
        if isinstance(panel.layout().itemAt(i).layout(), QHBoxLayout)
    ]
    controles = next(f for f in filas if any(
        f.itemAt(i).widget() in panel._pesos.values()
        for i in range(f.count()) if f.itemAt(i).widget() is not None
    ))
    intro = next(f for f in filas if any(
        f.itemAt(i).widget() is panel._boton for i in range(f.count())
    ))
    assert intro is not controles
    assert all(any(controles.itemAt(i).widget() is boton
                   for i in range(controles.count())) for boton in (
                       *panel._pesos.values(), panel._umbral, panel._sigma,
                       panel._boton_actualizar, panel._boton_descartar,
                   ))
    panel.resize(1630, 780)
    panel.show()
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
    assert panel._boton.y() < panel._pesos["fwhm"].y()
    assert panel._boton_descartar.geometry().right() <= panel.width()
    assert panel._tabla.horizontalScrollBar().maximum() == 0
    assert panel._tabla.width() <= 930
    assert panel._tabla.maximumWidth() <= 930
    assert panel._preview_label.width() >= 600
    panel.close()


def test_auditoria_tabla_compacta_centrada_y_visor_ampliado(tmp_path):
    """Frame no absorbe el ancho, Fondo es corto y el FITS gana alto real."""
    import numpy as np
    from astropy.io import fits
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QHeaderView

    from ui.stacker_tab.pasos import PanelAuditar

    panel = PanelAuditar()
    panel.resize(1640, 780)
    panel.show()
    QApplication.processEvents()
    tabla = panel._tabla
    assert tabla.horizontalHeaderItem(5).text() == "Fondo"
    assert tabla.horizontalHeader().sectionResizeMode(1) == QHeaderView.ResizeMode.Fixed
    assert tabla.columnWidth(1) <= 150
    assert tabla.width() <= 875
    assert tabla.horizontalScrollBar().maximum() == 0
    assert panel._plot.maximumHeight() <= 130

    ruta = tmp_path / "pp_light_00001.fit"
    fits.writeto(ruta, np.full((64, 48), 1000, dtype=np.uint16))
    from stacks.frame_metrics import FrameMetrics
    from stacks.global_pool import LightRef
    from stacks.registration import Registro
    ref = LightRef(ruta=ruta, sesion="noche", filtro=None, exposicion_s=30.0)
    panel.mostrar(Registro(dir=tmp_path, seq="registro_", frames=[ref]), [
        FrameMetrics(path=str(ruta), session="noche", fwhm=2.0,
                     roundness=1.0, transparency=1.0, background=100.0,
                     weighted=90.0)
    ])
    QApplication.processEvents()
    assert all(tabla.item(0, col).textAlignment() == Qt.AlignmentFlag.AlignCenter
               for col in range(tabla.columnCount()))
    assert panel._preview_label.height() >= 400
    panel.close()


def test_auditoria_no_reserva_hueco_tras_descartada():
    """Con scrollbar visible, las columnas llegan al borde útil de la tabla."""
    from PyQt6.QtWidgets import QApplication, QTableWidgetItem

    from ui.stacker_tab.pasos import PanelAuditar

    panel = PanelAuditar()
    panel.resize(1309, 735)
    panel.show()
    tabla = panel._tabla
    tabla.blockSignals(True)
    tabla.setRowCount(79)
    for fila in range(79):
        tabla.setItem(fila, 1, QTableWidgetItem(f"pp_light_{fila:05}.fit"))
    tabla.blockSignals(False)
    QApplication.processEvents()
    ultimo_borde = (tabla.horizontalHeader().sectionViewportPosition(8)
                     + tabla.columnWidth(8))
    assert tabla.verticalScrollBar().isVisible()
    assert 0 <= tabla.viewport().width() - ultimo_borde <= 3
    assert tabla.horizontalScrollBar().maximum() == 0
    panel.close()


def test_apilar_bloques_referencia_y_opciones_reales(tmp_path):
    """Los cuatro bloques caben y sus controles alimentan el guion de SirIL."""
    from PyQt6.QtWidgets import QApplication, QGroupBox

    from ui.stacker_tab.pasos import PanelApilar

    panel = PanelApilar()
    panel.resize(1309, 735)
    panel.show()
    QApplication.processEvents()
    titulos = [caja.title() for caja in panel.findChildren(QGroupBox)]
    assert [titulo[0] for titulo in titulos[:4]] == list("1234")
    assert panel._salidas.isHidden()
    panel._integracion.setCurrentIndex(panel._integracion.findData("mean"))
    panel._rechazo.setCurrentIndex(panel._rechazo.findData("linear"))
    panel._ponderacion.setCurrentIndex(panel._ponderacion.findData("noise"))
    panel._norm.setCurrentIndex(panel._norm.findData("addscale"))
    panel._drizzle.setChecked(True)
    panel._scale.setCurrentIndex(1)
    panel._framing.setCurrentIndex(1)
    panel._rejmaps.setChecked(True)
    panel._output_norm.setChecked(True)
    panel._rgb_equal.setChecked(True)
    assert panel.opciones_registro()["drizzle"]
    assert panel.opciones_registro()["scale"] == 1.4
    assert panel.opciones_registro()["framing"] == "min"
    assert panel.opciones().to_siril_args() == [
        "mean", "linear", "3.0", "3.0", "-rejmap", "-norm=addscale",
        "-weight=noise", "-32b", "-output_norm", "-rgb_equal",
    ]
    panel.actualizar_conteo(37)
    assert "37 tomas" in panel._guia.text()
    panel.mostrar_salidas([tmp_path / "pila.fit"])
    QApplication.processEvents()
    assert panel._salidas.isVisible()
    barra = panel._scroll.verticalScrollBar()
    barra.setValue(barra.maximum())
    QApplication.processEvents()
    assert panel._salidas.mapTo(panel._scroll.viewport(),
                                panel._salidas.rect().bottomLeft()).y() <= panel.height()
    panel.close()


def test_apilar_flat_explicito_no_lanza_trabajo_sin_fits(tmp_path):
    """El flat de drizzle solo se pasa al worker tras validarlo."""
    from ui.stacker_tab.pasos import PanelApilar

    panel = PanelApilar()
    panel._drizzle.setChecked(True)
    panel._flat_drizzle.setChecked(True)
    panel._ruta_flat.setText(str(tmp_path / "inexistente.fit"))
    with pytest.raises(ValueError, match="flat de drizzle"):
        panel.opciones_registro()
    flat = tmp_path / "flat.fit"
    flat.touch()
    panel._ruta_flat.setText(str(flat))
    assert panel.opciones_registro()["flat"] == flat
