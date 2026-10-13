"""calibrator: másters, avisas de faltantes, calibrado y persistencia.

SirIL está mockeado: el doble simula la creación de ficheros que el flujo
real genera (másters, secuencias .seq y pp_light_*), sin depender del binario.
"""
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from stacks import calibrator
from stacks.calibrator import (
    calibrate_session,
    delete_calibrated,
    list_calibrated,
    save_calibration,
)
from stacks.session_parser import parse_session
from stacks.siril_runner import SirilError, SirilResult


def test_enlaza_lights_homonimos_de_filtros_distintos(tmp_path, siril_falso):
    """Dos lights homónimos conservan ambos orígenes, sin sobrescribirlos."""
    fuentes = [_fits(tmp_path / filtro / "luz.fit") for filtro in ("Ha", "OIII")]
    trabajo = tmp_path / "enlaces"
    calibrator._enlazar_frames(fuentes, trabajo, "light")
    enlaces = list(trabajo.glob("*.fit"))
    assert len(enlaces) == 2
    assert {(p.stat().st_dev, p.stat().st_ino) for p in enlaces} == {
        (p.stat().st_dev, p.stat().st_ino) for p in fuentes
    }


@pytest.mark.parametrize("base", ["light", "flat", "dark"])
def test_secuencia_mixta_raw_fits_se_rechaza_antes_de_siril(tmp_path, monkeypatch, base):
    """No se ignoran FITS al elegir convertraw para un conjunto mixto."""
    fit = _fits(tmp_path / "luz.fit")
    raw = tmp_path / "luz.NEF"
    raw.write_bytes(b"raw")
    def prohibido(*args, **kwargs):
        """SirIL nunca debe recibir esta secuencia ambigua."""
        pytest.fail("Se llamó a SirIL con una mezcla RAW/FITS")
    monkeypatch.setattr(calibrator, "ejecutar_script", prohibido)
    trabajo = tmp_path / "trabajo"
    with pytest.raises(SirilError, match="RAW.*FITS"):
        calibrator._enlazar_frames([raw, fit], trabajo, base)
    assert not trabajo.exists()
    assert raw.read_bytes() == b"raw"
    assert fit.is_file()


def _fits(path: Path, *, valor: int = 1, **cabecera) -> Path:
    """Fichero FITS mínimo (2×2) de 16 bits con la cabecera indicada.

    16 bits (no float32) porque así son los frames reales de cámara y lo
    único que ``calibrate`` de SirIL acepta. ``valor`` fija el nivel ADU
    para poder jugar con las medianas (detección de bias en el dark).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    datos = np.full((2, 2), valor, dtype=np.uint16)
    fits.writeto(path, datos, header=fits.Header(cabecera) if cabecera else None, overwrite=True)
    return path


class _SirilFalso:
    """Doble de ``ejecutar_script``: simula link/stack/calibrate creando ficheros.

    Cada comando del guion se interpreta como lo haría SirIL de verdad:
    ``link`` escribe el .seq, ``stack ... -out=X`` crea X, ``calibrate``
    crea ``pp_<seq>_00001.fit``. Así el flujo completo del calibrador se
    ejercita de punta a punta sin el binario.
    """

    def __init__(self):
        self.llamadas: list[dict] = []  # (comandos, cwd) para las aserciones

    def __call__(self, comandos, *, cwd=None, **kwargs):
        self.llamadas.append({"comandos": list(comandos), "cwd": cwd})
        log_cb = kwargs.get("log_cb")
        for comando in comandos:
            if log_cb:
                log_cb(f"simulado: {comando}")
            self._ejecutar(comando, cwd)
        return SirilResult(ok=True, comandos=list(comandos))

    def _ejecutar(self, comando: str, cwd: Path) -> None:
        partes = comando.split()
        orden, resto = partes[0], partes[1:]
        if orden == "link":
            (cwd / f"{resto[0]}_.seq").write_text("{}")
        elif orden == "convertraw":
            _fits(cwd / f"{resto[0]}_00001.fit")
            (cwd / f"{resto[0]}_.seq").write_text("{}")
        elif orden == "stack":
            salida = next(a.split("=", 1)[1] for a in resto if a.startswith("-out="))
            _fits(cwd / salida, EXPOSURE=30.0)
        elif orden == "calibrate":
            # Como SirIL real: la salida es el prefijo pp_ + la secuencia
            # de entrada (light_ → fichero pp_light_00001.fit, seq pp_light_).
            _fits(cwd / f"pp_{resto[0]}00001.fit", EXPOSURE=30.0)
            (cwd / f"pp_{resto[0]}.seq").write_text("{}")


@pytest.fixture(autouse=True)
def carpeta_trabajo(tmp_path_factory, monkeypatch):
    """Desvía la carpeta de trabajo a un tmp: los tests no pisan data/working."""
    destino = tmp_path_factory.mktemp("working")
    monkeypatch.setattr(calibrator, "WORKING_FOLDER", destino)
    return destino


@pytest.fixture()
def siril_falso(monkeypatch):
    """Sustituye la ejecución real de SirIL por el doble."""
    doble = _SirilFalso()
    monkeypatch.setattr(calibrator, "ejecutar_script", doble)
    return doble


@pytest.fixture()
def sesion_completa(tmp_path):
    """Sesión con las cinco carpetas y cabecera EXPOSURE en los lights."""
    for kind, n in (("lights", 5), ("flats", 3), ("darks", 3), ("bias", 4), ("dark_flats", 2)):
        for i in range(1, n + 1):
            extras = {"EXPOSURE": 30.0} if kind == "lights" else {}
            _fits(tmp_path / kind / f"{kind[:-1]}_{i:04d}.fits", **extras)
    return parse_session(tmp_path)


# ---------------------------------------------------------------- flujo feliz
def test_calibrar_conserva_el_origen_vivo_bajo_calibrados(
    tmp_path, siril_falso, monkeypatch,
):
    """Calibrar una sesión dentro de ``working/calibrados`` no la borra.

    Regresión de C-DAT-01: la carpeta de salida era la misma que la de
    origen, así que limpiar el área de trabajo borraba las tomas originales.
    """
    working = tmp_path / "working"
    monkeypatch.setattr(calibrator, "WORKING_FOLDER", working)
    origen = working / "calibrados" / "noche"
    light = _fits(origen / "lights" / "original.fits", EXPOSURE=30.0)
    sesion = parse_session(origen)

    resultado = calibrate_session(sesion)

    assert light.exists()                    # el original sigue intacto
    assert resultado.dir != origen           # destino nuevo y único
    assert resultado.dir.parent == working / "calibrados"
    assert resultado.dir.name.startswith("noche-")


def test_calibrar_rechaza_si_el_destino_coincide_con_el_origen(tmp_path, monkeypatch):
    """Si el destino llegara a ser el origen, se rinde antes de limpiar nada."""
    working = tmp_path / "working"
    monkeypatch.setattr(calibrator, "WORKING_FOLDER", working)
    origen = working / "calibrados" / "noche"
    light = _fits(origen / "lights" / "original.fits")
    sesion = parse_session(origen)
    monkeypatch.setattr(calibrator, "output_dir_for", lambda *_a, **_k: origen)

    with pytest.raises(ValueError, match="solapan"):
        calibrate_session(sesion)
    assert light.exists()


def test_calibrate_session_sesion_completa(siril_falso, sesion_completa):
    """Sesión con todo: másters generados, calibrado y resultado completo.

    El único aviso posible es la nota de que el dark generado (stack de
    darks crudos) ya trae el bias dentro: SirIL restaría los dos, así que
    el bias no se pasa — eso ES calibrar bien, no un problema.
    """
    registro = []
    resultado = calibrate_session(sesion_completa, log_cb=registro.append)
    assert resultado.n_lights == 1
    assert resultado.exposure_s == 30.0
    assert set(resultado.masters) >= {"bias", "dark", "dark_flat", "flat"}
    assert len(resultado.avisos) == 1
    assert "incluye el bias" in resultado.avisos[0]
    assert "medianas FITS" in resultado.avisos[0]
    assert "ADU" not in resultado.avisos[0]
    assert any("Máster dark" in linea and "working" in linea for linea in registro)
    assert any("Origen → enlace:" in linea and "light_" in linea for linea in registro)
    assert sum("ya incluye el bias" in linea for linea in registro) == 0


def test_calibrar_en_hilo_con_directorio_global_capturado(
    siril_falso, sesion_completa,
):
    """La calibración no toca settings/SQLite: la ruta global viaja por parámetro.

    Antes el worker leía `get_setting` desde el hilo de trabajo (SQLite
    prohibe usar la conexión creada en otro hilo, A-03). Ahora la garantía
    es de construcción: ni `calibrator` ni `siril_finder` importan settings,
    y el hilo de prueba lo confirma ejecutando de verdad.
    """
    import inspect
    from concurrent.futures import ThreadPoolExecutor

    import stacks.calibrator as calibrator_mod
    import stacks.siril_finder as finder_mod

    with ThreadPoolExecutor(max_workers=1) as pool:
        resultado = pool.submit(
            calibrate_session, sesion_completa, global_dir=""
        ).result()
    assert resultado.n_lights == 1
    assert "db.settings" not in inspect.getsource(calibrator_mod)
    assert "db.settings" not in inspect.getsource(finder_mod)


def test_lights_calibrados_en_carpeta_de_trabajo(siril_falso, sesion_completa):
    """La salida vive en la carpeta de trabajo, nunca en la sesión original."""
    resultado = calibrate_session(sesion_completa)
    assert list((resultado.dir / "light").glob("pp_*.fit"))
    # La sesión original queda intacta: ni .seq ni pp_ dentro.
    assert not list(sesion_completa.path.rglob("pp_*"))
    assert not list(sesion_completa.path.rglob("*.seq"))


def test_los_originales_quedan_intactos(siril_falso, sesion_completa):
    """Recalibrar no borra ni modifica los ficheros de la sesión."""
    originales = {p.name for p in sesion_completa.path.rglob("*") if p.is_file()}
    calibrate_session(sesion_completa)
    despues = {p.name for p in sesion_completa.path.rglob("*") if p.is_file()}
    assert originales == despues


def test_recalibrar_no_acumula_salidas(siril_falso, sesion_completa):
    """La segunda corrida limpia la carpeta de trabajo (idempotente)."""
    primera = calibrate_session(sesion_completa)
    n_antes = len(list((primera.dir / "light").glob("pp_*.fit")))
    segunda = calibrate_session(sesion_completa)
    n_despues = len(list((segunda.dir / "light").glob("pp_*.fit")))
    assert n_antes == n_despues == 1


def test_homonimas_no_comparten_salida_ni_borran_la_ajena(
    tmp_path, siril_falso, memory_db,
):
    """Dos raíces con nombre igual producen destinos estables y disjuntos."""
    sesiones = []
    for raiz in ("a", "b"):
        origen = tmp_path / raiz / "noche"
        _fits(origen / "lights" / "luz.fits", EXPOSURE=30.0)
        sesiones.append(parse_session(origen))
    primera = calibrate_session(sesiones[0])
    save_calibration(primera)
    luz = primera.dir / "light" / "pp_light_00001.fit"
    contenido = luz.read_bytes()
    segunda = calibrate_session(sesiones[1])
    save_calibration(segunda)
    assert primera.dir != segunda.dir
    assert luz.read_bytes() == contenido
    assert {fila["calibrated_dir"] for fila in list_calibrated()} == {
        str(primera.dir), str(segunda.dir)
    }
    assert calibrator.output_dir_for(sesiones[0].path) == primera.dir
    assert not (primera.dir.parent / "noche").exists()


# ----------------------------------------------------------- másters y avisas
def test_masters_de_la_sesson_se_usan_directos(tmp_path, siril_falso):
    """Si la sesión trae másters, no se apila nada nuevo para ese tipo."""
    _fits(tmp_path / "masters" / "master_bias.fits")
    _fits(tmp_path / "masters" / "master_dark.fits")
    _fits(tmp_path / "masters" / "master_flat.fits")
    _fits(tmp_path / "lights" / "light_0001.fits", EXPOSURE=10.0)
    sesion = parse_session(tmp_path)

    resultado = calibrate_session(sesion)
    assert resultado.masters["bias"] == tmp_path / "masters" / "master_bias.fits"
    # Ningún stack de máster de bias en las corridas.
    stacks_bias = [
        c for llamada in siril_falso.llamadas for c in llamada["comandos"]
        if c.startswith("stack") and "bias" in c
    ]
    assert not stacks_bias


def test_sin_flats_se_calibra_y_se_avisa(tmp_path, siril_falso):
    """Sin flats (ni propios ni globales): calibrado sin -flat + aviso."""
    _fits(tmp_path / "masters" / "master_bias.fits")
    _fits(tmp_path / "masters" / "master_dark.fits")
    _fits(tmp_path / "lights" / "light_0001.fits", EXPOSURE=10.0)
    sesion = parse_session(tmp_path)

    resultado = calibrate_session(sesion)
    assert any("flat" in aviso for aviso in resultado.avisos)
    calibrado = next(
        c for llamada in siril_falso.llamadas for c in llamada["comandos"]
        if c.startswith("calibrate")
    )
    assert "-flat=" not in calibrado


def test_sin_bias_ni_darks_se_avisa(tmp_path, siril_falso):
    """Solo flats: se avisa de las dos correcciones que faltan."""
    _fits(tmp_path / "flats" / "flat_0001.fits")
    _fits(tmp_path / "lights" / "light_0001.fits", EXPOSURE=10.0)
    sesion = parse_session(tmp_path)

    resultado = calibrate_session(sesion)
    assert sum("bias" in a for a in resultado.avisos) == 1
    assert sum("darks" in a for a in resultado.avisos) == 1


def test_flats_se_calibran_con_dark_flat(tmp_path, siril_falso):
    """Flats crudos + dark_flat de la sesión → flats calibrados antes del máster."""
    _fits(tmp_path / "masters" / "master_bias.fits")
    _fits(tmp_path / "masters" / "master_dark.fits")
    _fits(tmp_path / "masters" / "master_dark_flat.fits")
    for i in range(1, 4):
        _fits(tmp_path / "flats" / f"flat_{i:04d}.fits")
    _fits(tmp_path / "lights" / "light_0001.fits", EXPOSURE=10.0)
    sesion = parse_session(tmp_path)

    calibrate_session(sesion)
    comandos_flat = [
        c for llamada in siril_falso.llamadas
        if llamada["cwd"] and llamada["cwd"].name == "flat"
        for c in llamada["comandos"]
    ]
    # Los flats se calibran con el dark_flat de la sesión (guion propio del
    # calibrado; el link de la secuencia es otra corrida aparte)...
    assert any(c.startswith("calibrate") and "-dark=" in c for c in comandos_flat)
    # ...y el máster de flat se apila del resultado calibrado (pp_flat_).
    assert any(c.startswith("stack pp_flat") for c in comandos_flat)


def test_masters_se_enlazan_antes_de_apilar(siril_falso, sesion_completa):
    """Cada máster forma su secuencia con ``link`` ANTES de apilarla.

    Regresión: sin el link, SirIL no encuentra ninguna secuencia y el
    ``stack`` falla (el doble no lo detecta, así que se comprueban comandos).
    """
    calibrate_session(sesion_completa)
    comandos_bias = [
        c for llamada in siril_falso.llamadas
        if llamada["cwd"] and llamada["cwd"].name == "bias"
        for c in llamada["comandos"]
    ]
    assert "link bias" in comandos_bias
    # El stack usa el nombre real de la secuencia que dejó el link (bias_).
    assert any(c.startswith("stack bias_") for c in comandos_bias)


def test_rutas_con_espacios_se_entrecomillan(tmp_path, siril_falso):
    """SirIL 1.4.4 solo admite espacios entrecomillando TODO el argumento."""
    # Helper (vive ahora en siril_runner): comillas solo cuando las hay.
    assert calibrator.arg_ruta("-dark=/tmp/x/m.fits") == "-dark=/tmp/x/m.fits"
    assert calibrator.arg_ruta("-dark=/tmp/mis x/m.fits") == (
        '"-dark=/tmp/mis x/m.fits"'
    )
    # Y en el guion real: la sesión vive en una carpeta con espacios.
    # (dark SIN bias dentro — mediana por debajo del bias — para que se
    # pase el -bias y se comprueben las dos rutas entrecomilladas).
    sesion_dir = tmp_path / "con espacios"
    _fits(sesion_dir / "masters" / "master_bias.fits")
    _fits(sesion_dir / "masters" / "master_dark.fits", valor=0)
    _fits(sesion_dir / "lights" / "light_0001.fits", EXPOSURE=10.0)
    calibrate_session(parse_session(sesion_dir))

    calibrado = next(
        c for llamada in siril_falso.llamadas for c in llamada["comandos"]
        if c.startswith("calibrate")
    )
    assert '"-bias=' in calibrado and '"-dark=' in calibrado


# --------------------------------------- bias del dark y calibración cruda
def test_dark_con_bias_dentro_no_se_resta_dos_veces(tmp_path, siril_falso):
    """El dark ya trae el bias (medianas iguales) → no se pasa el ``-bias``.

    SirIL 1.4.4 resta dark Y bias si recibe los dos (validado): con el
    bias dentro del dark, la doble sustracción recortaba el fondo a cero
    y cortaba señal. Se avisa en ``resultado.avisos``.
    """
    _fits(tmp_path / "masters" / "master_bias.fits")      # mediana 1
    _fits(tmp_path / "masters" / "master_dark.fits")      # mediana 1 (igual)
    _fits(tmp_path / "lights" / "light_0001.fits", EXPOSURE=10.0)

    resultado = calibrate_session(parse_session(tmp_path))

    calibrado = next(
        c for llamada in siril_falso.llamadas for c in llamada["comandos"]
        if c.startswith("calibrate")
    )
    assert "-dark=" in calibrado
    assert "-bias=" not in calibrado
    assert any("incluye el bias" in a for a in resultado.avisos)


def test_dark_sin_bias_sii_se_pasa_el_bias(tmp_path, siril_falso):
    """Dark apilado SIN bias (mediana muy menor) → sí se le pasa el ``-bias``."""
    _fits(tmp_path / "masters" / "master_bias.fits", valor=10)
    _fits(tmp_path / "masters" / "master_dark.fits", valor=1)  # corriente sola
    _fits(tmp_path / "lights" / "light_0001.fits", EXPOSURE=10.0)

    resultado = calibrate_session(parse_session(tmp_path))

    calibrado = next(
        c for llamada in siril_falso.llamadas for c in llamada["comandos"]
        if c.startswith("calibrate")
    )
    assert "-bias=" in calibrado and "-dark=" in calibrado
    assert not any("incluye el bias" in a for a in resultado.avisos)


def test_dark_incluye_bias_umbrales():
    """El umbral 0,7 distingue darks con bias dentro de los que no."""
    assert calibrator.dark_incluye_bias(150.0, 150.0)   # típico: igual
    assert calibrator.dark_incluye_bias(150.0, 750.0)   # corriente + bias
    assert not calibrator.dark_incluye_bias(150.0, 20.0)  # bias restado
    assert not calibrator.dark_incluye_bias(150.0, 100.0)  # 0,67 < 0,7
    assert not calibrator.dark_incluye_bias(0.0, 0.0)    # sin bias no decide
    assert not calibrator.dark_incluye_bias(None, None)  # ilegibles: pasa bias


def test_calibrado_cruedo_no_debayeriza(tmp_path, siril_falso):
    """La calibración es CRUDA: ni ``-debayer`` ni ``-cfa`` en el guion.

    Regresión: antes las sesiones OSC se debayerizaban al calibrar; ahora
    el rebayerizado lo decide el usuario en el paso Apilar (drizzle off →
    debayer de los CFA, drizzle on → SirIL lo hace al rezumar).
    """
    _fits(tmp_path / "masters" / "master_bias.fits", valor=10)
    _fits(tmp_path / "masters" / "master_dark.fits", valor=1)
    _fits(
        tmp_path / "lights" / "light_0001.fits",
        EXPOSURE=10.0, BAYERPAT="RGGB",  # sesión detectada como OSC
    )
    sesion = parse_session(tmp_path)
    assert sesion.kind == "osc"

    calibrate_session(sesion)

    calibrado = next(
        c for llamada in siril_falso.llamadas for c in llamada["comandos"]
        if c.startswith("calibrate")
    )
    assert "-debayer" not in calibrado
    assert " -cfa" not in calibrado


def test_progress_y_log_por_etapas(siril_falso, sesion_completa):
    """El progreso cubre toda la sesión (0 → 0.5 → 1) y el log llega de todo.

    El log debe incluir también los apilados de másters, no solo el
    calibrado de lights: es lo que ve el usuario en la terminal.
    """
    fracciones: list[float] = []
    lineas: list[str] = []
    calibrate_session(
        sesion_completa, progress_cb=fracciones.append, log_cb=lineas.append
    )
    assert fracciones[0] == 0.0
    assert fracciones[-1] == 1.0
    assert 0.5 in fracciones  # fin de la fase de másters y flats
    assert all(a <= b for a, b in zip(fracciones, fracciones[1:], strict=False))  # monótono
    assert any("stack" in linea for linea in lineas)    # másters
    assert any("calibrate" in linea for linea in lineas)  # lights


def test_opciones_avanzadas_opt_y_cc(tmp_path, siril_falso):
    """``-opt`` y ``-cc=dark`` solo se emiten si hay el material que exigen."""
    _fits(tmp_path / "masters" / "master_bias.fits")
    _fits(tmp_path / "masters" / "master_dark.fits")
    _fits(tmp_path / "lights" / "light_0001.fits", EXPOSURE=10.0)

    calibrate_session(parse_session(tmp_path), opt=True, cc=True)
    con_material = next(
        c for llamada in siril_falso.llamadas for c in llamada["comandos"]
        if c.startswith("calibrate")
    )
    # Siempre -opt=exp: -opt a secas provoca SIGSEGV en SirIL 1.4.4.
    assert " -opt=exp" in con_material and " -opt " not in con_material
    assert "-cc=dark" in con_material

    # Sin dark: no se emiten y se explica el porqué en los avisos.
    siril_falso.llamadas.clear()
    sin_dark = tmp_path / "sin_dark"
    _fits(sin_dark / "masters" / "master_bias.fits")
    _fits(sin_dark / "lights" / "light_0001.fits", EXPOSURE=10.0)
    resultado = calibrate_session(parse_session(sin_dark), opt=True, cc=True)
    sin_material = next(
        c for llamada in siril_falso.llamadas for c in llamada["comandos"]
        if c.startswith("calibrate")
    )
    assert " -opt" not in sin_material and "-cc=dark" not in sin_material
    assert sum("omitido" in a for a in resultado.avisos) == 2

    # Sin EXPOSURE en los lights: -opt=exp se omite (SirIL lo rechazaría).
    siril_falso.llamadas.clear()
    sin_expo = tmp_path / "sin_expo"
    _fits(sin_expo / "masters" / "master_bias.fits")
    _fits(sin_expo / "masters" / "master_dark.fits")
    _fits(sin_expo / "lights" / "light_0001.fits")  # sin EXPOSURE
    resultado = calibrate_session(parse_session(sin_expo), opt=True)
    calif = next(
        c for llamada in siril_falso.llamadas for c in llamada["comandos"]
        if c.startswith("calibrate")
    )
    assert "-opt" not in calif
    assert any("EXPOSURE" in a for a in resultado.avisos)


# ------------------------------------------------------------ carpeta global
def test_carpeta_global_de_masters(tmp_path, siril_falso):
    """Sesión sin bias/darks + carpeta global con másters → usa los globales.

    La ruta global viaja por parámetro (la UI la resuelve de settings):
    el calibrador no lee la BD (A-03).
    """
    global_dir = tmp_path / "global"
    _fits(global_dir / "master_bias.fits")
    _fits(global_dir / "master_dark.fits")

    sesion_dir = tmp_path / "sesion"
    _fits(sesion_dir / "flats" / "flat_0001.fits")
    _fits(sesion_dir / "lights" / "light_0001.fits", EXPOSURE=10.0)
    sesion = parse_session(sesion_dir)

    resultado = calibrate_session(sesion, global_dir=str(global_dir))
    # El global cubrió lo que faltaba (el único aviso posible es la nota
    # de que el dark global ya incluye el bias, que es correcto).
    assert not [a for a in resultado.avisos if a.startswith("Sin ")]
    assert resultado.masters["bias"] == global_dir / "master_bias.fits"


def test_carpeta_global_de_frames_apila_una_vez(tmp_path, siril_falso):
    """Global con frames sueltos → máster apilado y cacheado en _global_."""
    global_dir = tmp_path / "global"
    for i in range(1, 6):
        _fits(global_dir / "bias" / f"bias_{i:04d}.fits")

    sesion_dir = tmp_path / "sesion"
    _fits(sesion_dir / "lights" / "light_0001.fits", EXPOSURE=10.0)
    resultado = calibrate_session(
        parse_session(sesion_dir), global_dir=str(global_dir)
    )
    master_global = resultado.masters["bias"]
    assert master_global.exists() and "_global_" in str(master_global)

    # Una segunda sesión lo reutiliza sin apilar de nuevo.
    stacks_antes = sum(
        1 for llamada in siril_falso.llamadas for c in llamada["comandos"]
        if c.startswith("stack") and "bias" in c
    )
    sesion2 = tmp_path / "sesion2"
    _fits(sesion2 / "lights" / "light_0001.fits", EXPOSURE=10.0)
    calibrate_session(parse_session(sesion2), global_dir=str(global_dir))
    stacks_despues = sum(
        1 for llamada in siril_falso.llamadas for c in llamada["comandos"]
        if c.startswith("stack") and "bias" in c
    )
    assert stacks_despues == stacks_antes


def test_sin_global_configurado_no_revienta(tmp_path, siril_falso):
    """Sin carpeta global (ruta vacía o None) → material global vacío, sin excepción."""
    _fits(tmp_path / "lights" / "light_0001.fits", EXPOSURE=10.0)
    resultado = calibrate_session(parse_session(tmp_path), global_dir="")
    assert resultado.n_lights == 1
    assert resultado.avisos  # sin nada: todos los avisos


# -------------------------------------------------------------------- errores
def test_sin_lights_lanza_error(tmp_path, siril_falso):
    """Una sesión sin lights no se puede calibrar."""
    _fits(tmp_path / "bias" / "bias_0001.fits")
    with pytest.raises(SirilError):
        calibrate_session(parse_session(tmp_path))


def test_fallo_de_siril_propaga_error(tmp_path, monkeypatch):
    """Si SirIL falla, el calibrador no finge éxito."""
    def _falla(comandos, *, cwd=None, **kwargs):
        return SirilResult(ok=False, comandos=list(comandos), motivo="fallo simulado")

    monkeypatch.setattr(calibrator, "ejecutar_script", _falla)
    _fits(tmp_path / "lights" / "light_0001.fits", EXPOSURE=10.0)
    with pytest.raises(SirilError):
        calibrate_session(parse_session(tmp_path))


def test_lights_float32_no_se_calibran(tmp_path, siril_falso):
    """SirIL solo calibra secuencias de 16 bits: fallo claro y sin ejecutar."""
    _fits(tmp_path / "masters" / "master_bias.fits")
    lights = tmp_path / "lights" / "light_0001.fits"
    lights.parent.mkdir(parents=True, exist_ok=True)
    fits.writeto(
        lights, np.full((2, 2), 1.0, dtype=np.float32),
        header=fits.Header({"EXPOSURE": 10.0}), overwrite=True,
    )

    with pytest.raises(SirilError, match="16 bits"):
        calibrate_session(parse_session(tmp_path))
    assert not siril_falso.llamadas  # se rechaza antes de invocar a SirIL


@pytest.mark.parametrize("dtype", [np.float32, np.float64, np.int32, np.uint8])
def test_bitpix_incompatible_en_segundo_light_no_se_calibra(tmp_path, siril_falso, dtype):
    """El primer light válido no autoriza los demás frames de la secuencia."""
    _fits(tmp_path / "masters" / "master_bias.fits")
    primero = _fits(tmp_path / "lights" / "light_0001.fits")
    segundo = primero.with_name("light_0002.fits")
    fits.writeto(segundo, np.ones((2, 2), dtype=dtype))
    originales = [p.read_bytes() for p in (primero, segundo)]
    with pytest.raises(SirilError, match="light_0002.*BITPIX"):
        calibrate_session(parse_session(tmp_path))
    assert not siril_falso.llamadas
    assert [p.read_bytes() for p in (primero, segundo)] == originales


def test_cabecera_ilegible_no_omite_validacion_de_fits_posteriores(tmp_path):
    """Una cabecera ilegible no interrumpe la comprobación del resto de frames."""
    primero = tmp_path / "corrupto.fit"
    primero.write_bytes(b"corrupto")
    segundo = tmp_path / "incompatible.fit"
    fits.writeto(segundo, np.ones((2, 2), dtype=np.float32))
    with pytest.raises(SirilError, match="incompatible.fit"):
        calibrator._exigir_enteros_16bit([primero, segundo], "Lights")


# ---------------------------------------------------------------- persistencia
def test_save_list_delete(memory_db, siril_falso, sesion_completa):
    """La tabla calibrated_sessions guarda, lista y olvida sesiones."""
    resultado = calibrate_session(sesion_completa)
    save_calibration(resultado)

    filas = list_calibrated()
    assert len(filas) == 1
    assert filas[0]["n_frames"] == 1
    assert filas[0]["exposure_s"] == 30.0

    save_calibration(resultado)  # upsert: no duplica
    assert len(list_calibrated()) == 1

    delete_calibrated(str(sesion_completa.path))
    assert list_calibrated() == []


def test_calibrated_sessions_migracion_idempotente(tmp_path):
    """La tabla llega a bases existentes sin perder los ajustes previos."""
    import sqlite3

    from db.connection import init_db

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO settings VALUES ('siril_path', 'ruta existente')")
        init_db(conn)
        init_db(conn)
        conn.execute(
            "INSERT INTO calibrated_sessions(session_dir, calibrated_dir, n_frames)"
            " VALUES (?, ?, ?)", (str(tmp_path), str(tmp_path / 'working'), 3)
        )
        assert conn.execute("SELECT value FROM settings").fetchone()[0] == "ruta existente"
        assert conn.execute("SELECT n_frames FROM calibrated_sessions").fetchone()[0] == 3
    finally:
        conn.close()
