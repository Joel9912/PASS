"""Fija el modelo astronómico por cálculo y serializa el estado global de Astropy, sin descargas ni fallback oculto."""

import sqlite3
from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from threading import RLock, current_thread, main_thread

from astropy.coordinates import solar_system_ephemeris
from astropy.utils import iers

from db import catalog_editions, connection

_LOCK = RLock()
_CURRENT = ContextVar("pass_ephemeris", default=None)


@dataclass(frozen=True)
class EphemerisModel:
    """Selección inmutable de un cálculo; edición y huella separan cachés aunque el contenido se reutilice."""

    path: Path | None = None
    edition: str = "legacy"
    sha256: str = "builtin"
    label: str = "builtin"

    @property
    def cache_key(self):
        """Identifica modelo y edición sin depender de la selección global que pueda cambiar después."""
        return self.edition, self.sha256


def current_model() -> EphemerisModel | None:
    """Devuelve la selección de este contexto, nunca el cálculo que esté ejecutándose en otro hilo."""
    return _CURRENT.get()


def _read_model(personal) -> EphemerisModel:
    """Obtiene recursos verificados de una edición; un registro roto falla antes de llamar a Astropy."""
    with catalog_editions.data_snapshot(personal) as (_catalog, resources, binding):
        if binding is None:
            return EphemerisModel()
        manifest = binding["manifest"]
        kernels = [name for name in resources if manifest["resources"][name]["format"] == "spk-planets-v1"]
        if len(kernels) > 1:
            raise ValueError("La edición selecciona más de un modelo planetario; no se elige arbitrariamente.")
        if not kernels:
            return EphemerisModel(edition=manifest["edition"])
        name = kernels[0]
        item = manifest["resources"][name]
        return EphemerisModel(resources[name], manifest["edition"], item["sha256"], item["revision"])


def selected_model() -> EphemerisModel:
    """Lee en el hilo principal o con conexión propia readonly en workers, sin compartir SQLite ni crear bases."""
    if current_thread() is main_thread():
        return _read_model(connection.get_connection())
    path = Path(connection.DB_PATH).absolute()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as personal:
        personal.execute("PRAGMA query_only=ON")
        return _read_model(personal)


@contextmanager
def model_scope(model: EphemerisModel | None = None):
    """Mantiene modelo/edición durante todo un recorrido y restaura estado/lectores de Astropy incluso ante error."""
    active = current_model()
    if active is not None:
        if model is not None and model != active:
            raise ValueError("No se pueden mezclar modelos dentro del mismo cálculo astronómico.")
        yield active
        return
    with _LOCK:
        chosen = selected_model() if model is None else model
        value = "builtin" if chosen.path is None else str(chosen.path.absolute())
        # get() valida y puede descargar; leer el estado antes de autorizarlo.
        previous = solar_system_ephemeris._value
        if previous != "builtin" and not (isinstance(previous, str) and Path(previous).is_file()):
            raise ValueError("El modelo previo de Astropy no es local; no se permite restaurarlo descargando datos.")
        if value != "builtin" and not Path(value).is_file():
            raise ValueError("El kernel local seleccionado no está disponible; no se sustituye por otro modelo.")
        token = _CURRENT.set(chosen)
        try:
            with (solar_system_ephemeris.set(value), iers.conf.set_temp("auto_download", False),
                  iers.conf.set_temp("auto_max_age", None)):
                yield chosen
        finally:
            _CURRENT.reset(token)
            solar_system_ephemeris.get_kernel(previous)


def with_model(function):
    """Envuelve una API completa para que sus consultas y transformaciones compartan una selección estable."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        """Fija un modelo en la llamada exterior y lo reutiliza en llamadas anidadas del mismo recorrido."""
        with model_scope():
            return function(*args, **kwargs)

    return wrapped
