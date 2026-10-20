"""Encuadres de captura por sesión y solape esférico estimado, solo leyendo cabeceras FITS."""

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import wcs_to_celestial_frame

from .session_parser import FITS_EXTS, Session, campo_vision, ficha_de_luz


@dataclass
class CaptureField:
    """Huella de un FITS representativo, no garantía del apuntado de todos los lights."""

    source: Path
    corners: tuple[tuple[float, float], ...]
    method: str

    @property
    def center(self) -> tuple[float, float]:
        """Centro esférico de la huella, sin discontinuidad en RA=0 ni en los polos."""
        vector = _unit(_vectors(self.corners).sum(axis=0))
        return math.degrees(math.atan2(vector[1], vector[0])) % 360, math.degrees(math.asin(float(np.clip(vector[2], -1, 1))))


@dataclass
class SessionField:
    """Primera muestra y comprobación opcional; una discrepancia no sustituye una cabecera por otra."""

    session: str
    primary: CaptureField | None
    check: CaptureField | None = None
    check_source: Path | None = None
    state: str = "válido"
    note: str = ""


@dataclass
class FieldSurvey:
    """Comparación informativa: no decide aceptación, calibra, registra ni construye mosaicos."""

    sessions: list[SessionField] = field(default_factory=list)
    overlaps: dict[tuple[str, str], float] = field(default_factory=dict)
    classification: str = "Sin FOV comparable"

    def overview(self) -> tuple[float, float, float] | None:
        """Centro y amplitud para una vista conjunta; no fuerza campos antipodales dentro de una proyección."""
        fields = [capture for row in self.sessions for capture in (row.primary, row.check) if capture is not None]
        if not fields:
            return None
        points = np.concatenate([_vectors(capture.corners) for capture in fields])
        try:
            center = _unit(points.sum(axis=0))
        except ValueError:
            return None
        radius = math.degrees(math.acos(float(np.clip(np.min(points @ center), -1, 1))))
        if radius >= 80:
            return None
        ra = math.degrees(math.atan2(center[1], center[0])) % 360
        dec = math.degrees(math.asin(float(np.clip(center[2], -1, 1))))
        return ra, dec, max(.1, min(170, radius * 2.4))


def _unit(vector: np.ndarray) -> np.ndarray:
    """Normaliza una dirección y rechaza geometría degenerada en lugar de propagar NaN."""
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm < 1e-14:
        raise ValueError("Huella degenerada")
    return vector / norm


def _vectors(corners: tuple[tuple[float, float], ...]) -> np.ndarray:
    """Convierte coordenadas celestes en vectores para tratar cruces de RA y polos sin atajos planos."""
    coordinates = np.radians(np.asarray(corners, dtype=float))
    if coordinates.shape != (4, 2) or not np.isfinite(coordinates).all():
        raise ValueError("Huella inválida")
    ra, dec = coordinates.T
    if np.any(np.abs(dec) > math.pi / 2):
        raise ValueError("Declinación inválida")
    return np.column_stack((np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)))


def _polygon(corners: tuple[tuple[float, float], ...]) -> list[np.ndarray]:
    """Orienta una huella convexa menor que un hemisferio; no interpreta cuadriláteros arbitrarios."""
    points = list(_vectors(corners))
    center = _unit(np.sum(points, axis=0))
    signs = [float(np.dot(np.cross(a, b), center)) for a, b in zip(points, points[1:] + points[:1], strict=True)]
    if all(value < -1e-14 for value in signs):
        points.reverse()
    elif not all(value > 1e-14 for value in signs):
        raise ValueError("Huella no convexa o degenerada")
    if any(float(np.dot(point, center)) <= 0 for point in points):
        raise ValueError("Huella mayor que un hemisferio")
    return points


def _area(points: list[np.ndarray]) -> float:
    """Área en estereorradianes mediante triángulos esféricos, no área plana en RA/Dec."""
    if len(points) < 3:
        return 0.0
    center = _unit(np.sum(points, axis=0))
    result = 0.0
    for a, b in zip(points, points[1:] + points[:1], strict=True):
        numerator = abs(float(np.dot(center, np.cross(a, b))))
        denominator = 1 + float(np.dot(center, a) + np.dot(a, b) + np.dot(b, center))
        result += 2 * math.atan2(numerator, denominator)
    return result


def shared_fraction(first: CaptureField, second: CaptureField) -> float:
    """Área común dividida por la huella menor, según criterio del usuario; devuelve 0..1.

    Los bordes se aproximan con arcos de círculo máximo entre esquinas: no
    certifica distorsiones ópticas ni mide píxeles útiles de una imagen.
    """
    original, clip = _polygon(first.corners), _polygon(second.corners)
    denominator = min(_area(original), _area(clip))
    if denominator <= 1e-14:
        raise ValueError("Huella sin área suficiente")
    points = original
    for a, b in zip(clip, clip[1:] + clip[:1], strict=True):
        normal = _unit(np.cross(a, b))
        output = []
        if not points:
            return 0.0
        previous = points[-1]
        previous_distance = float(np.dot(normal, previous))
        for current in points:
            distance = float(np.dot(normal, current))
            inside, previous_inside = distance >= -1e-12, previous_distance >= -1e-12
            if inside != previous_inside:
                crossing = _unit(previous_distance * current - distance * previous)
                if np.dot(crossing, previous + current) < 0:
                    crossing = -crossing
                output.append(crossing)
            if inside:
                output.append(current)
            previous, previous_distance = current, distance
        points = output
    return min(1.0, max(0.0, _area(points) / denominator))


def read_field(path: Path) -> CaptureField | None:
    """Lee WCS celeste o un rectángulo de cabecera con escala/centro/rotación conocidos; sin datos, None."""
    try:
        header = fits.getheader(path)
        width, height = int(header.get("NAXIS1", 0)), int(header.get("NAXIS2", 0))
        if width <= 0 or height <= 0:
            return None
        celestial = WCS(header).celestial
        method = "WCS de cabecera; bordes estimados entre esquinas"
        if not celestial.has_celestial:
            ficha = ficha_de_luz(path)
            size = campo_vision(ficha)
            required = (ficha.ra_deg, ficha.dec_deg, ficha.rotacion_deg)
            if size is None or any(value is None or not math.isfinite(value) for value in required):
                return None
            if not -90 <= ficha.dec_deg <= 90 or max(size) >= 180:
                return None
            celestial = WCS(naxis=2)
            celestial.wcs.ctype = ["RA---TAN", "DEC--TAN"]
            celestial.wcs.crval = [ficha.ra_deg, ficha.dec_deg]
            celestial.wcs.crpix = [(width + 1) / 2, (height + 1) / 2]
            angle = math.radians(ficha.rotacion_deg)
            scale = size[0] / width
            celestial.wcs.cd = scale * np.array([[-math.cos(angle), -math.sin(angle)],
                                                  [-math.sin(angle), math.cos(angle)]])
            method = "Rectángulo estimado de centro, escala y rotación de cabecera"
        raw = celestial.calc_footprint(axes=(width, height), center=False)
        coordinates = SkyCoord(raw[:, celestial.wcs.lng] * u.deg, raw[:, celestial.wcs.lat] * u.deg,
                               frame=wcs_to_celestial_frame(celestial)).icrs
        corners = tuple(zip(coordinates.ra.deg.tolist(), coordinates.dec.deg.tolist(), strict=True))
        _polygon(corners)
        return CaptureField(path, corners, method)
    except (OSError, ValueError, TypeError, OverflowError, KeyError, IndexError):
        return None


def compare_fields(rows: list[SessionField], checkpoint: Callable[[], None] | None = None) -> FieldSurvey:
    """Compara todas las parejas disponibles; cualquier dato ausente/discrepante impide certeza global."""
    survey = FieldSurvey(rows)
    valid = [row for row in rows if row.primary is not None]
    for index, first in enumerate(valid):
        if checkpoint:
            checkpoint()
        for second in valid[index + 1:]:
            if checkpoint:
                checkpoint()
            survey.overlaps[first.session, second.session] = shared_fraction(first.primary, second.primary)
    if len(rows) < 2:
        survey.classification = "Una sola sesión" if valid else "Sin FOV comparable"
    elif len(valid) != len(rows) or any(row.state != "válido" for row in rows):
        survey.classification = "Revisar FOV · datos incompletos o discrepantes"
    elif any(math.isclose(value, .8, abs_tol=1e-9, rel_tol=0) for value in survey.overlaps.values()):
        survey.classification = "Revisar FOV · límite del 80 %"
    elif all(value > .8 for value in survey.overlaps.values()):
        survey.classification = "Mismo encuadre · solape >80 % del menor"
    else:
        survey.classification = "Mosaico según solape <80 % del menor"
    return survey


def survey_sessions(sessions: list[Session], checkpoint: Callable[[], None] | None = None) -> FieldSurvey:
    """Analiza cabeceras y contrasta otro FITS aleatorio cuando una sesión no solapa ninguna otra.

    No inventa una distancia de «muy lejos»: revisa conservadoramente cualquier
    sesión aislada sin solape. No sustituye una primera huella discrepante.
    """
    rows = []
    candidates = {}
    for session in sessions:
        if checkpoint:
            checkpoint()
        key = str(session.path.resolve())
        if key in candidates:
            raise ValueError("La misma carpeta de sesión aparece más de una vez en la comparación FOV.")
        paths = [path for path in session.frames.get("lights", []) if path.suffix.lower() in FITS_EXTS]
        candidates[key] = paths
        primary = read_field(paths[0]) if paths else None
        note = f"Primer FITS: {paths[0].name}" if paths else "Sin light FITS; FOV desconocido"
        note += "; " + primary.method if primary else "; sin huella celeste verificable"
        rows.append(SessionField(key, primary, state="válido" if primary else "sin datos", note=note))
    preliminary = compare_fields(rows, checkpoint)
    for row in rows:
        if checkpoint:
            checkpoint()
        matches = [value for pair, value in preliminary.overlaps.items() if row.session in pair]
        isolated = bool(matches) and all(value <= 1e-10 for value in matches)
        if row.primary is not None and not isolated:
            continue
        others = candidates[row.session][1:]
        if not others:
            if isolated:
                row.state = "sin confirmar"
                row.note += "; sin otro FITS para contrastar el encuadre aislado"
            continue
        row.check_source = random.choice(others)
        row.check = read_field(row.check_source)
        row.note += f"; comprobación aleatoria: {row.check_source.name}"
        if row.primary is None or row.check is None:
            row.state = "sin confirmar"
            row.note += "; no hay dos huellas comparables"
        elif shared_fraction(row.primary, row.check) > .8:
            row.note += "; dos cabeceras compatibles (>80 % del FOV menor)"
        else:
            row.state = "discrepante"
            row.note += "; cabeceras distintas: revisar, sin elegir una como correcta"
    return compare_fields(rows, checkpoint)
