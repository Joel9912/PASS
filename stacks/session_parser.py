"""Parser de sesiones: detecta qué contiene cada sesión de captura.

Para cada carpeta de sesión (p. ej. `2026-10-01_andromeda/`) identifica:
- subcarpetas de frames: ``lights``, ``flats``, ``darks``, ``bias``, ``dark_flats``
  (se aceptan alias estilo SirIL: ``Light/``, ``Dark/``, ``Flat/``, ``Bias/``…)
- carpeta de másters: ``masters/`` (master flat, master bias, master dark, ...)
- el tipo de sesión: **mono**, **osc** (color con Bayer), **filtros** (rueda de
  filtros, por subcarpeta o por cabecera FILTER) o **desconocido** (RAW que
  astropy no lee: el usuario lo corrige a mano en la UI)

Todo es solo lectura: aquí no se escribe ni se ordena nada, solo se mira.
"""
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from astropy.io import fits

#: Subcarpetas de frames que reconoce el programa.
FRAME_KINDS = ("lights", "flats", "darks", "bias", "dark_flats")

#: Alias de carpetas: nombre normalizado (`_clave`) → tipo canónico. Admite
#: el estilo SirIL del usuario (``Light/``, ``Dark/``…: singular y con
#: mayúscula) además del canónico en minúscula plural (``lights/``…).
ALIAS_CARPETAS = {
    "light": "lights", "lights": "lights",
    "flat": "flats", "flats": "flats",
    "dark": "darks", "darks": "darks",
    "bias": "bias",
    "darkflat": "dark_flats", "darkflats": "dark_flats",
    "master": "masters", "masters": "masters",
}

#: Subcarpeta de lights que el usuario descartó a mano (``Light/Descartes/``):
#: NO es un filtro y sus frames jamás entran al pool ni a la calibración.
DESCARTES_ALIAS = ("descarte", "descartes", "descartado", "descartados",
                   "rechazo", "rechazos", "rejected", "rejects", "trash", "malos")

#: Extensiones de imagen que SirIL puede leer: FITS y RAW de cámara.
FITS_EXTS = {".fit", ".fits", ".fts"}
RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".pef"}

#: Tipos de másters (claves del dict ``masters``), en orden de detección:
#: «darkflat» debe casar antes que «dark» y «flat» («master_dark_flat»
#: contiene los dos textos).
MASTER_KINDS = ("bias", "dark_flat", "dark", "flat")

#: Tipos de sesión que el usuario puede forzar a mano en la UI.
KINDS = ("mono", "osc", "filtros", "desconocido")


@dataclass
class Session:
    """Estructura detectada de una sesión de captura."""

    path: Path
    frames: dict[str, list[Path]] = field(default_factory=dict)  # tipo -> ficheros
    masters: dict[str, Path] = field(default_factory=dict)       # tipo -> fichero maestro
    filters: dict[str, list[Path]] = field(default_factory=dict)  # filtro -> lights
    kind: str = "desconocido"  # 'mono' | 'osc' | 'filtros' | 'desconocido' (KINDS)

    @property
    def n_lights(self) -> int:
        """Nº de frames de luz detectados (0 si la sesión no tiene ``lights/``)."""
        return len(self.frames.get("lights", []))


@dataclass
class FichaFITS:
    """Datos de cabecera FITS del primer light de una sesión.

    El primer light da un encuadre representativo y el equipo del paso
    «Sesiones» (región apuntada, sensor, óptica y sitio). Todos los
    campos son opcionales: ni todas las cámaras ni todos los programas
    de captura escriben las mismas claves.
    """

    objeto: str | None = None          # OBJECT si es un nombre de verdad
    ra_deg: float | None = None        # ascensión recta del centro (grados)
    dec_deg: float | None = None       # declinación del centro (grados)
    lat: float | None = None           # SITELAT: latitud del observatorio
    lon: float | None = None           # SITELONG: longitud (este positivo)
    camara: str | None = None          # INSTRUME
    montura: str | None = None         # TELESCOP (en la práctica: montura)
    focal_mm: float | None = None      # FOCALLEN
    diametro_mm: float | None = None   # APTDIA (apertura del objetivo)
    escala_as_px: float | None = None  # SCALE: segundos de arco por píxel
    px_x: int | None = None            # NAXIS1: ancho del sensor (px)
    px_y: int | None = None            # NAXIS2: alto del sensor (px)
    pix_um: float | None = None        # PIXSIZE1/XPIXSZ: píxel físico (µm)
    binning: int | None = None         # XBINNING
    rotacion_deg: float | None = None  # CROTA2: orientación si la cámara la guardó
    altitud_m: float | None = None      # SITEELEV: altitud del observatorio
    altura_obj_deg: float | None = None  # OBJCTALT: altura del objeto sobre el horizonte


def campo_vision(ficha: FichaFITS) -> tuple[float, float] | None:
    """Campo angular ancho×alto en grados, solo si el FITS permite calcularlo.

    SCALE ya expresa segundos de arco por píxel en la imagen guardada; si
    falta, la focal y el tamaño físico del píxel permiten derivarlo. La
    orientación del sensor no está garantizada y no se deduce aquí.
    """
    if not (ficha.px_x and ficha.px_y and ficha.px_x > 0 and ficha.px_y > 0):
        return None
    escala = ficha.escala_as_px
    if escala is None and ficha.pix_um and ficha.focal_mm and ficha.focal_mm > 0:
        escala = 206.265 * ficha.pix_um * (ficha.binning or 1) / ficha.focal_mm
    if escala is None or not math.isfinite(escala) or escala <= 0:
        return None
    return ficha.px_x * escala / 3600, ficha.px_y * escala / 3600


def parse_session(session_dir: Path) -> Session:
    """Detecta frames y másters de una sesión sin modificar nada (solo lectura).

    Los lights admiten dos layouts: sueltos en ``lights/`` o agrupados en
    subcarpeta por filtro (``lights/Ha/``); en el segundo caso rellena
    ``filters`` y aplana todos los ficheros en ``frames["lights"]``.
    """
    sesion = Session(path=session_dir)
    carpetas = _carpetas_de(session_dir, FRAME_KINDS + ("masters",))
    for kind in FRAME_KINDS:
        if kind not in carpetas:
            continue
        if kind == "lights":
            _parse_lights(carpetas[kind], sesion)
            continue
        ficheros = _imagenes_de(carpetas[kind])
        if ficheros:
            sesion.frames[kind] = ficheros

    masters_dir = carpetas.get("masters")
    if masters_dir:
        for fichero in sorted(masters_dir.iterdir()):
            if not (fichero.is_file() and _es_imagen(fichero)):
                continue
            tipo = _clasificar_nombre(fichero.name)
            if tipo and tipo not in sesion.masters:
                sesion.masters[tipo] = fichero

    sesion.kind = _detectar_kind(sesion)
    return sesion


def parse_sessions(root_dir: Path) -> list[Session]:
    """Detecta todas las sesiones dentro de un directorio raíz.

    Una sesión es una subcarpeta con al menos un tipo de frame conocido
    (aceptando alias de nombre, p. ej. ``Light/``); si el propio raíz es ya
    una carpeta de sesión (trae sus ``lights/``), se devuelve a sí misma
    como única sesión.
    """
    if not root_dir.is_dir():
        return []
    if _carpetas_de(root_dir):
        return [parse_session(root_dir)]
    return [
        parse_session(hijo)
        for hijo in sorted(root_dir.iterdir())
        if hijo.is_dir() and _carpetas_de(hijo)
    ]


def parse_calibration_folder(carpeta: Path) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    """Masters y frames de calibrado hallados en una carpeta (propia o global).

    Soporta los tres layouts descritos por el usuario: subcarpetas por tipo
    (``bias/``, ``darks/``, ...), másters sueltos o en ``masters/`` y frames
    sueltos clasificados por nombre (``bias_0001.fit``, ``masterDark_...``).
    Devuelve ``(masters, frames)``.
    """
    masters: dict[str, Path] = {}
    frames: dict[str, list[Path]] = {}

    # 1) Subcarpetas por tipo de material (al mismo canónico que los
    #    másters: darks/ → «dark», dark_flats/ → «dark_flat», ...; se
    #    aceptan alias estilo SirIL como ``Dark/`` o ``Masters/``).
    carpetas = _carpetas_de(
        carpeta, ("bias", "darks", "flats", "dark_flats", "masters")
    )
    for kind in ("bias", "darks", "flats", "dark_flats"):
        if kind in carpetas:
            ficheros = _imagenes_de(carpetas[kind])
            if ficheros:
                frames.setdefault(_canonico(kind), []).extend(ficheros)

    # 2) Másters: en masters/ o sueltos en la raíz, clasificados por nombre.
    for posible in (carpetas.get("masters"), carpeta):
        if posible is None or not posible.is_dir():
            continue
        for fichero in sorted(posible.iterdir()):
            if not (fichero.is_file() and _es_imagen(fichero) and "master" in _clave(fichero.name)):
                continue
            tipo = _clasificar_nombre(fichero.name)
            if tipo and tipo not in masters:
                masters[tipo] = fichero

    # 3) Frames sueltos por nombre (solo en la raíz; los de subcarpeta ya
    #    están catalogados por el nombre de la subcarpeta).
    for fichero in sorted(carpeta.iterdir()):
        if not (fichero.is_file() and _es_imagen(fichero)):
            continue
        if "master" in _clave(fichero.name):
            continue
        tipo = _clasificar_nombre(fichero.name)
        if tipo:
            frames.setdefault(tipo, []).append(fichero)

    return masters, frames


def filtro_de(fichero: Path) -> str | None:
    """Valor de la cabecera FILTER del FITS (recortado), o ``None``.

    Lo usa el pool de lights calibrados para agrupar por canal en el apilado
    de sesiones mono+filtros; en OSC lo normal es ``None``.
    """
    header = _leer_header(fichero)
    if not header or not header.get("FILTER"):
        return None
    return str(header["FILTER"]).strip() or None


def exposure_de(fichero: Path) -> float | None:
    """Exposición por frame en segundos (EXPOSURE o EXPTIME), o ``None``.

    Compartida por el calibrador (resultado y ``-opt=exp``) y el pool
    (tiempo total acumulado); sin cabecera legible no hay dato.
    """
    header = _leer_header(fichero)
    if header is None:
        return None
    for clave in ("EXPOSURE", "EXPTIME"):
        if header.get(clave) is not None:
            return float(header[clave])
    return None


def ficha_de_luz(fichero: Path) -> FichaFITS:
    """Ficha del encuadre y del equipo leyendo la cabecera FITS del light.

    La cabecera describe el equipo y un apuntado representativo de la
    sesión, así que se lee solo el primer light. Cualquier
    fichero ilegible (RAW, corrupto) devuelve la ficha vacía en vez de
    romper el escaneo, que es solo lectura y no puede fallar.
    """
    header = _leer_header(fichero) or {}

    def numero(*claves: str) -> float | None:
        """Primera clave numérica legible entre ``claves`` (si no, ``None``)."""
        for clave in claves:
            if header.get(clave) is None:
                continue
            try:
                return float(header[clave])
            except (TypeError, ValueError):
                continue
        return None

    def texto(*claves: str) -> str | None:
        """Primera clave de texto con valor real («Unknown» cuenta como vacío)."""
        for clave in claves:
            valor = str(header.get(clave, "")).strip()
            if valor and valor.lower() != "unknown":
                return valor
        return None

    ancho = numero("NAXIS1")
    alto = numero("NAXIS2")
    binning = numero("XBINNING")
    return FichaFITS(
        objeto=texto("OBJECT"),
        ra_deg=numero("RA", "CRVAL1"),
        dec_deg=numero("DEC", "CRVAL2"),
        lat=numero("SITELAT"),
        lon=numero("SITELONG"),
        camara=texto("INSTRUME", "CAMERA"),
        montura=texto("TELESCOP"),
        focal_mm=numero("FOCALLEN"),
        diametro_mm=numero("APTDIA"),
        escala_as_px=numero("SCALE"),
        px_x=int(ancho) if ancho else None,
        px_y=int(alto) if alto else None,
        pix_um=numero("PIXSIZE1", "XPIXSZ"),
        binning=int(binning) if binning else None,
        rotacion_deg=numero("CROTA2"),
        altitud_m=numero("SITEELEV", "OBSGEO-H"),
        altura_obj_deg=numero("OBJCTALT"),
    )


def necesita_debayer(fichero: Path) -> bool:
    """¿El frame está en CFA crudo (Bayer sin debayerizar)?

    Decide el registro final del Apilador: con datos CFA y SIN drizzle hay
    que debayerizarlos antes de registrar; con drizzle no (SirIL 1.4.4 hace
    el debayer él mismo al rezumar). Solo manda la cabecera por fichero —
    1 capa + patrón Bayer ⇒ crudo; 3 capas o mono sin patrón ⇒ ya está—,
    porque las sesiones pueden mezclar convertidos ya rebayerizados con
    originales CR2. El patrón sobrevive a la calibración (validado con
    SirIL real), así que los lights del pool se pueden mirar así.
    """
    header = _leer_header(fichero)
    if header is None or header.get("NAXIS3", 1) != 1:
        return False
    return any(clave in header for clave in ("BAYERPAT", "BAYERRSZ"))


# ------------------------------------------------------------------ internas
def _parse_lights(carpeta: Path, sesion: Session) -> None:
    """Rellena ``frames["lights"]`` y, si hay subcarpeta por filtro, ``filters``.

    Los lights sueltos van directos a ``frames``; los de subcarpeta se
    agrupan por nombre de filtro Y se aplana todo en ``frames`` (el
    calibrador trabaja con el conjunto; el apilado por canal usa ``filters``).
    """
    sueltos = _imagenes_de(carpeta)
    subdirs = sorted(
        p for p in carpeta.iterdir()
        if p.is_dir() and _clave(p.name) not in DESCARTES_ALIAS
    )
    for sub in subdirs:
        ficheros = _imagenes_de(sub)
        if ficheros:
            sesion.filters[sub.name] = ficheros
            sueltos.extend(ficheros)
    if sueltos:
        sesion.frames["lights"] = sueltos


def _imagenes_de(carpeta: Path) -> list[Path]:
    """Ficheros de imagen (FITS o RAW) de una carpeta, ordenados."""
    return sorted(
        p for p in carpeta.iterdir()
        if p.is_file() and _es_imagen(p)
    )


def _carpetas_de(carpeta: Path, kinds: tuple[str, ...] = FRAME_KINDS) -> dict[str, Path]:
    """Subcarpetas de material de ``carpeta``: tipo canónico → carpeta real.

    Admite el nombre canónico (``lights/``) o cualquier alias de
    ``ALIAS_CARPETAS`` (``Light/``, ``DARK/``…). Con dos carpetas para el
    mismo tipo manda la canónica; entre alias, la primera alfabética.
    """
    resueltas = {kind: carpeta / kind for kind in kinds if (carpeta / kind).is_dir()}
    for sub in sorted(carpeta.iterdir()):
        if not sub.is_dir():
            continue
        canonico = ALIAS_CARPETAS.get(_clave(sub.name))
        if canonico in kinds and canonico not in resueltas:
            resueltas[canonico] = sub
    return resueltas


def _es_imagen(path: Path) -> bool:
    """¿El fichero es una imagen que SirIL podría leer (FITS o RAW)?"""
    return path.suffix.lower() in (FITS_EXTS | RAW_EXTS)


def _clave(nombre: str) -> str:
    """Nombre en minúsculas y sin separadores: 'Master-Flat_1.FITS' → 'masterflat1'."""
    return re.sub(r"[^a-z0-9]", "", nombre.lower())


def _canonico(kind: str) -> str:
    """Nombre de carpeta → tipo canónico ('darks' → 'dark', 'flats' → 'flat')."""
    return {"darks": "dark", "flats": "flat"}.get(kind, kind)


def _clasificar_nombre(nombre: str) -> str | None:
    """Tipo de material según el nombre ('master_bias_001' → 'bias') o None.

    El orden importa: «darkflat» antes que «dark» y «flat», porque
    «master_dark_flat» contiene los dos textos.
    """
    clave = _clave(nombre)
    if "darkflat" in clave:
        return "dark_flat"
    for tipo in ("bias", "dark", "flat"):
        if tipo in clave:
            return tipo
    return None


def _leer_header(path: Path) -> dict | None:
    """Cabecera FITS del fichero, o ``None`` si no es FITS legible (RAW, corrupto)."""
    if path.suffix.lower() not in FITS_EXTS:
        return None
    try:
        with fits.open(path, memmap=True) as hdul:
            return dict(hdul[0].header)
    except Exception:  # cualquier fichero ilegible cuenta como «desconocido»
        return None


def _detectar_kind(sesion: Session) -> str:
    """Tipo de sesión: subcarpetas por filtro > cabeceras (Bayer > FILTER) > mono.

    Un RAW que astropy no lee no se adivina: queda «desconocido» y el
    usuario lo fuerza en la UI (decisión del usuario: nunca imponer).
    """
    if sesion.filters:
        return "filtros"
    for light in sesion.frames.get("lights", []):
        header = _leer_header(light)
        if header is None:
            continue  # RAW o ilegible: se mira el siguiente
        if any(clave in header for clave in ("BAYERPAT", "BAYERRSZ", "DEBAYERED")):
            return "osc"
        if header.get("FILTER"):
            return "filtros"
        return "mono"
    return "desconocido"
