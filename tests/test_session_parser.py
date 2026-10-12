"""session_parser: detección de sesiones, másters, filtros y tipo de sesión."""
import struct

import numpy as np
import pytest
from astropy.io import fits

from stacks import session_parser
from stacks.session_parser import (
    necesita_debayer,
    parse_calibration_folder,
    parse_session,
    parse_sessions,
)


@pytest.mark.parametrize("valor", ["Unknown", "", "NaN", "inf", "-1", "0"])
def test_exposicion_invalida_es_dato_desconocido(tmp_path, valor):
    """Una exposición ilegible o sin sentido no aborta la lectura del FITS."""
    fichero = _fits(tmp_path / "light.fit", EXPTIME=valor)
    assert session_parser.exposure_de(fichero) is None


def test_exposicion_usa_alias_valido_tras_texto_invalido(tmp_path):
    """Si EXPOSURE no es numérico, EXPTIME todavía puede aportar la exposición."""
    fichero = _fits(tmp_path / "light.fit", EXPOSURE="Unknown", EXPTIME=30)
    assert session_parser.exposure_de(fichero) == 30


def test_exposicion_texto_numerico_sigue_siendo_valido(tmp_path):
    """Las cámaras que escriben segundos como texto conservan su dato."""
    fichero = _fits(tmp_path / "light.fit", EXPTIME="30.5")
    assert session_parser.exposure_de(fichero) == 30.5


@pytest.mark.parametrize("numerador, denominador", [(30, 1), (1, 125), (305, 10)])
def test_exposicion_raw_lee_exif_sin_modificar_original(tmp_path, numerador, denominador):
    """Un contenedor TIFF/EXIF mínimo permite probar el lector real de metadatos."""
    fichero = tmp_path / "light.dng"
    datos = (struct.pack("<2sHI", b"II", 42, 8)
             + struct.pack("<H", 1) + struct.pack("<HHII", 0x8769, 4, 1, 26) + struct.pack("<I", 0)
             + struct.pack("<H", 1) + struct.pack("<HHII", 0x829A, 5, 1, 44) + struct.pack("<I", 0)
             + struct.pack("<II", numerador, denominador))
    fichero.write_bytes(datos)
    assert session_parser.exposure_de(fichero) == pytest.approx(numerador / denominador)
    assert fichero.read_bytes() == datos


def test_exposicion_raw_corrupto_o_ausente_no_aborta(tmp_path):
    """Un RAW ilegible no aporta segundos ni rompe la operación."""
    fichero = tmp_path / "light.nef"
    assert session_parser.exposure_de(fichero) is None
    fichero.write_bytes(b"raw corrupto")
    assert session_parser.exposure_de(fichero) is None


def _fits(path, **cabecera):
    """Fichero FITS mínimo (2×2) con la cabecera indicada."""
    path.parent.mkdir(parents=True, exist_ok=True)
    datos = np.full((2, 2), 1.0, dtype=np.float32)
    fits.writeto(path, datos, header=fits.Header(cabecera) if cabecera else None, overwrite=True)
    return path


def _raw(path):
    """Fichero RAW falso (el parser solo mira la extensión)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"raw")
    return path


# ------------------------------------------------------------ parse_session
def test_parse_session_detecta_las_cinco_carpetas(tmp_path):
    """Lights, flats, darks, bias y dark_flats se catalogan por tipo."""
    for kind in session_parser.FRAME_KINDS:
        for i in range(1, 3):
            _fits(tmp_path / kind / f"{kind[:-1]}_{i:04d}.fits")
    sesion = parse_session(tmp_path)
    assert sesion.n_lights == 2
    assert all(len(sesion.frames[kind]) == 2 for kind in session_parser.FRAME_KINDS)


def test_parse_session_admite_carpetas_estilo_siril(tmp_path):
    """Regresión: `Light/`, `Flat/`, `Dark/`, `Bias/` (SirIL) cuentan igual.

    El layout real del usuario usa nombres singular y con mayúscula; el
    parser solo aceptaba los canónicos en minúscula y no veía nada.
    """
    _fits(tmp_path / "Light" / "Light_60_secs_001.fits")
    _fits(tmp_path / "Flat" / "Flat_0001.fits")
    _fits(tmp_path / "Dark" / "Dark_0001.fits")
    _fits(tmp_path / "Bias" / "Bias_0001.fits")
    _fits(tmp_path / "masters" / "master_bias.fit")

    sesion = parse_session(tmp_path)
    assert sesion.n_lights == 1
    assert set(sesion.frames) == {"lights", "flats", "darks", "bias"}
    assert set(sesion.masters) == {"bias"}


def test_parse_session_gana_el_nombre_canonico_entre_alias(tmp_path):
    """Si hay `lights/` y `Light/`, manda la canónica (nada de duplicados)."""
    _fits(tmp_path / "lights" / "light_0001.fits")
    _fits(tmp_path / "Light" / "Light_0002.fits")
    sesion = parse_session(tmp_path)
    assert [p.name for p in sesion.frames["lights"]] == ["light_0001.fits"]


def test_parse_session_ignora_ficheros_que_no_son_imagen(tmp_path):
    """.seq, conversion.txt y demás ruido de SirIL no entran al catálogo."""
    _fits(tmp_path / "lights" / "light_0001.fits")
    (tmp_path / "lights" / "light_.seq").write_text("{}")
    (tmp_path / "lights" / "conversion.txt").write_text("basura")
    sesion = parse_session(tmp_path)
    assert sesion.n_lights == 1


def test_parse_session_encuentra_masters(tmp_path):
    """La carpeta masters/ se clasifica por nombre (bias/dark/flat/dark_flat)."""
    _fits(tmp_path / "masters" / "master_bias.fits")
    _fits(tmp_path / "masters" / "master_dark.fits")
    _fits(tmp_path / "masters" / "master_flat.fits")
    _fits(tmp_path / "masters" / "master_dark_flat.fits")
    _fits(tmp_path / "lights" / "light_0001.fits")
    sesion = parse_session(tmp_path)
    assert set(sesion.masters) == {"bias", "dark", "flat", "dark_flat"}


def test_dark_flat_no_se_confunde_con_dark(tmp_path):
    """«master_dark_flat» es dark_flat, no dark (contiene ambos textos)."""
    _fits(tmp_path / "masters" / "Master-Dark-Flat_0001.fits")
    sesion = parse_session(tmp_path)
    assert "dark_flat" in sesion.masters and "dark" not in sesion.masters


def test_lights_por_subcarpeta_de_filtro(tmp_path):
    """Subcarpeta por filtro → filters agrupa y frames aplana; kind = filtros."""
    for filtro in ("Ha", "OIII"):
        _fits(tmp_path / "lights" / filtro / f"{filtro}_0001.fits")
        _fits(tmp_path / "lights" / filtro / f"{filtro}_0002.fits")
    sesion = parse_session(tmp_path)
    assert set(sesion.filters) == {"Ha", "OIII"}
    assert sesion.n_lights == 4  # aplana todos
    assert sesion.kind == "filtros"


def test_lights_ignora_la_subcarpeta_de_descartes(tmp_path):
    """Regresión: `Light/Descartes/` no es filtro ni entra al pool.

    El usuario real guarda ahí los frames que descartó a mano; el parser
    los contaba como lights de un «filtro» imaginario: la sesión salía como
    «filtros» con los descartes incluidos en el recuento y en el apilado.
    """
    _fits(tmp_path / "Light" / "Light_001.fits", BAYERPAT="RGGB")
    _fits(tmp_path / "Light" / "Descartes" / "Light_002.fits", BAYERPAT="RGGB")
    sesion = parse_session(tmp_path)
    assert sesion.n_lights == 1  # el descarte queda fuera
    assert not sesion.filters
    assert sesion.kind == "osc"


def test_sesion_vacia_no_revienta(tmp_path):
    """Carpeta sin nada → sesión vacía, kind desconocido."""
    sesion = parse_session(tmp_path)
    assert sesion.n_lights == 0 and sesion.kind == "desconocido"


# ------------------------------------------------------------ kind / cabeceras
def test_kind_mono_por_cabecera(tmp_path):
    """Sin Bayer y sin FILTER → mono."""
    _fits(tmp_path / "lights" / "light_0001.fits", EXPOSURE=30.0)
    assert parse_session(tmp_path).kind == "mono"


def test_kind_osc_por_bayerpat(tmp_path):
    """BAYERPAT en la cabecera → OSC (cámara de color)."""
    _fits(tmp_path / "lights" / "light_0001.fits", BAYERPAT="RGGB")
    assert parse_session(tmp_path).kind == "osc"


def test_kind_filtros_por_cabecera_filter(tmp_path):
    """FILTER informado y sin Bayer → rueda de filtros."""
    _fits(tmp_path / "lights" / "light_0001.fits", FILTER="Ha")
    assert parse_session(tmp_path).kind == "filtros"


def test_kind_desconocido_si_solo_hay_raw(tmp_path):
    """RAW (extensión que astropy no lee) → desconocido; el usuario lo fuerza."""
    _raw(tmp_path / "lights" / "IMG_0001.CR2")
    assert parse_session(tmp_path).kind == "desconocido"


def test_kind_raw_ignorado_y_sigue_al_siguiente(tmp_path):
    """Un RAW delante no tapa al FITS que viene detrás."""
    _raw(tmp_path / "lights" / "IMG_0000.CR2")
    _fits(tmp_path / "lights" / "light_0001.fits", EXPOSURE=30.0)
    assert parse_session(tmp_path).kind == "mono"


# --------------------------------------------------------- necesita_debayer
def test_necesita_debayer_en_cfa_crudo(tmp_path):
    """1 capa + BAYERPAT → Bayer crudo: hay que debayerizar si no hay drizzle."""
    assert necesita_debayer(_fits(tmp_path / "a.fits", BAYERPAT="RGGB"))
    assert necesita_debayer(_fits(tmp_path / "b.fits", BAYERRSZ=2))


def test_no_necesita_debayer_si_ya_esta_rebayerizado(tmp_path):
    """3 capas (RGB ya convertido) → ya está, aunque traiga BAYERPAT."""
    rgb = tmp_path / "rgb.fits"
    fits.writeto(rgb, np.full((3, 2, 2), 1.0, dtype=np.float32),
                 header=fits.Header({"BAYERPAT": "RGGB"}), overwrite=True)
    assert not necesita_debayer(rgb)


def test_no_necesita_debayer_en_mono_o_sin_cabecera(tmp_path):
    """Mono sin patrón Bayer, RAW ilegible o fichero que no existe → no."""
    assert not necesita_debayer(_fits(tmp_path / "mono.fits", FILTER="Ha"))
    assert not necesita_debayer(_fits(tmp_path / "sin.fits"))
    assert not necesita_debayer(_raw(tmp_path / "IMG.CR2"))
    assert not necesita_debayer(tmp_path / "no_existe.fits")


# ----------------------------------------------------------- parse_sessions
def test_parse_sessions_en_un_raiz(tmp_path):
    """El raíz con varias sesiones (carpetas con lights/) las lista todas."""
    for fecha in ("2026-10-05", "2026-10-06"):
        _fits(tmp_path / fecha / "lights" / "light_0001.fits")
    (tmp_path / "notas.txt").write_text("yo no soy sesión")
    sesiones = parse_sessions(tmp_path)
    assert [s.path.name for s in sesiones] == ["2026-10-05", "2026-10-06"]


def test_parse_sessions_si_el_raiz_es_sesion(tmp_path):
    """Si el raíz trae sus lights/, él mismo es la sesión."""
    _fits(tmp_path / "lights" / "light_0001.fits")
    sesiones = parse_sessions(tmp_path)
    assert len(sesiones) == 1 and sesiones[0].path == tmp_path


def test_parse_sessions_dias_estilo_siril(tmp_path):
    """Regresión: raíz de días (layout real del usuario) → sus sesiones.

    `Dias/7 octubre/Light/…` no se veía y la UI respondía «No se detectó
    ninguna sesión»; una carpeta de día vacío no es sesión.
    """
    dia = tmp_path / "7 octubre"
    _fits(dia / "Light" / "Light_60_secs_001.fits")
    _fits(dia / "masters" / "master_bias.fit")
    (tmp_path / "10 setiembre").mkdir(parents=True)  # sin material
    (tmp_path / "master_stack.fit").write_bytes(b"fits")

    sesiones = parse_sessions(tmp_path)
    assert [s.path.name for s in sesiones] == ["7 octubre"]
    assert sesiones[0].n_lights == 1
    # el propio día, elegido como raíz, también es sesión
    assert parse_sessions(dia)[0].path == dia


def test_parse_sessions_raiz_inexistente(tmp_path):
    """Raíz que no existe → lista vacía, nunca excepción."""
    assert parse_sessions(tmp_path / "nope") == []


# --------------------------------------------------- parse_calibration_folder
def test_calibration_folder_subcarpetas(tmp_path):
    """Layout por subcarpetas: frames catalogados por el nombre de subcarpeta."""
    _fits(tmp_path / "bias" / "b_0001.fits")
    _fits(tmp_path / "darks" / "d_0001.fits")
    masters, frames = parse_calibration_folder(tmp_path)
    assert not masters and set(frames) == {"bias", "dark"}


def test_calibration_folder_admite_carpetas_estilo_siril(tmp_path):
    """Regresión: `Bias/`, `Dark/`, `Flat/` (SirIL) también valen aquí."""
    _fits(tmp_path / "Bias" / "b_0001.fits")
    _fits(tmp_path / "Dark" / "d_0001.fits")
    _fits(tmp_path / "Masters" / "master_bias.fit")
    masters, frames = parse_calibration_folder(tmp_path)
    assert set(frames) == {"bias", "dark"}
    assert set(masters) == {"bias"}


def test_calibration_folder_masters_y_frames_sueltos(tmp_path):
    """Masters por nombre + frames sueltos por nombre, en la misma carpeta."""
    _fits(tmp_path / "master_bias.fits")
    _fits(tmp_path / "dark_0001.fits")
    _fits(tmp_path / "dark_0002.fits")
    masters, frames = parse_calibration_folder(tmp_path)
    assert set(masters) == {"bias"}
    assert frames["dark"] and len(frames["dark"]) == 2


def test_calibration_folder_ignora_lights(tmp_path):
    """Un light suelto no es material de calibrado."""
    _fits(tmp_path / "light_0001.fits")
    masters, frames = parse_calibration_folder(tmp_path)
    assert not masters and not frames


# ------------------------------------------------------------- ficha_de_luz
def test_ficha_de_luz_vuelca_encuadre_equipo_y_sitio(tmp_path):
    """La cabecera del light da región, sensor, óptica y observatorio."""
    luz = _fits(
        tmp_path / "light_0001.fits",
        OBJECT="M31",
        RA=11.77643,
        DEC=41.26189,
        SITELAT=10.01917,
        SITELONG=-84.28153,
        INSTRUME="GPhoto CCD",
        TELESCOP="iOptron SkyGuider Pro",
        FOCALLEN=420.0,
        APTDIA=70.0,
        SCALE=1.915643,
        PIXSIZE1=3.9,
        XBINNING=1,
        OBJCTALT=47.73039,
    )
    ficha = session_parser.ficha_de_luz(luz)
    assert ficha.objeto == "M31"
    assert ficha.ra_deg == 11.77643 and ficha.dec_deg == 41.26189
    assert ficha.lat == 10.01917 and ficha.lon == -84.28153
    assert ficha.camara == "GPhoto CCD"
    assert ficha.montura == "iOptron SkyGuider Pro"
    assert ficha.focal_mm == 420.0 and ficha.diametro_mm == 70.0
    assert ficha.escala_as_px == 1.915643
    # NAXIS es del propio fichero de prueba (2×2); el mapeo es lo que cuenta.
    assert (ficha.px_x, ficha.px_y) == (2, 2)
    assert ficha.pix_um == 3.9 and ficha.binning == 1
    assert ficha.altura_obj_deg == 47.73039
    assert ficha.altitud_m is None  # OBJCTALT no es elevación del observatorio


def test_ficha_de_luz_sin_dato_no_inventa(tmp_path):
    """«Unknown» no es objeto; un FITS ilegible da la ficha vacía."""
    desconocido = _fits(tmp_path / "light_0002.fits", OBJECT="Unknown")
    ficha = session_parser.ficha_de_luz(desconocido)
    assert ficha.objeto is None and ficha.ra_deg is None and ficha.camara is None

    roto = tmp_path / "roto.fits"
    roto.write_bytes(b"esto no es un FITS")
    assert session_parser.ficha_de_luz(roto) == session_parser.FichaFITS()


def test_campo_vision_usa_escala_o_focal_sin_inventar():
    """El campo del visor exige dimensiones y escala FITS calculable."""
    ficha = session_parser.FichaFITS(px_x=3600, px_y=1800, escala_as_px=2)
    assert session_parser.campo_vision(ficha) == (2, 1)
    assert session_parser.campo_vision(session_parser.FichaFITS(px_x=3600)) is None
    assert session_parser.campo_vision(session_parser.FichaFITS(
        px_x=3600, px_y=1800, focal_mm=206.265, pix_um=1,
    )) == pytest.approx((1, 0.5), rel=1e-5)   # constante única 206,264806 (A-10)
    assert session_parser.campo_vision(session_parser.FichaFITS(
        px_x=3600, px_y=1800, escala_as_px=-1,
    )) is None
