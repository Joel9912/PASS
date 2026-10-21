"""Describe modelos y cobertura IERS efectivos sin asignar una precisión científica que no se haya validado."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.coordinates import solar_system_ephemeris
from astropy.utils import iers


@dataclass(frozen=True)
class AstronomyStatus:
    """Estado informativo de una malla calculada; cobertura de tabla no equivale a precisión certificada."""

    orientation: str
    moon_model: str
    table: str

    @property
    def summary(self) -> str:
        """Rótulo corto visible, sin prometer exactitud instrumental ni ocultar aproximaciones."""
        model = "Modelo interno" if self.moon_model == "builtin" else "Modelo lunar externo"
        source = {"local": "IERS local", "prediction": "IERS predicho", "outside": "IERS fuera de tabla",
                  "unknown": "IERS desconocido"}[self.orientation]
        return f"≈ {model} · {source}"

    @property
    def details(self) -> str:
        """Detalle accesible con procedencia y limitaciones, sin exponer una ruta privada del kernel."""
        state = {"local": "Instantes cubiertos por datos locales.", "prediction": "Incluye predicciones IERS.",
                 "outside": "Incluye instantes fuera de la tabla IERS; orientación terrestre aproximada.",
                 "unknown": "No se pudo verificar la orientación terrestre para esta malla."}[self.orientation]
        return (f"Sol: ERFA/Astropy get_sun. Luna: {Path(self.moon_model).name}.\n"
                f"Tabla IERS: {self.table}. {state}\n"
                "No se ha certificado precisión uniforme para 1950–2100 ni precisión instrumental. "
                "Los avisos no corrigen incertidumbres de UTC ni certifican las ventanas de captura.")


def astronomy_status(times, *, table=None) -> AstronomyStatus:
    """Inspecciona UT1 y movimiento polar de toda la malla sin red, ni cambiar sus cálculos o umbrales."""
    model = str(solar_system_ephemeris.get())
    table_name = "no disponible"
    try:
        with iers.conf.set_temp("auto_download", False):
            local = table if table is not None else iers.earth_orientation_table.get()
            table_name = type(local).__name__
            ut1, ut1_status = local.ut1_utc(times, return_status=True)
            x, y, pole_status = local.pm_xy(times, return_status=True)
        codes = np.concatenate([np.atleast_1d(ut1_status), np.atleast_1d(pole_status)])
        finite = all(np.all(np.isfinite(np.ma.filled(np.ma.asarray(value), np.nan))) for value in (ut1, x, y))
        known = [iers.FROM_IERS_B, iers.FROM_IERS_A, iers.FROM_IERS_A_PREDICTION,
                 iers.TIME_BEFORE_IERS_RANGE, iers.TIME_BEYOND_IERS_RANGE]
        if not codes.size or not finite or not np.all(np.isin(codes, known)):
            state = "unknown"
        elif np.any(codes < 0):
            state = "outside"
        elif np.any(codes == iers.FROM_IERS_A_PREDICTION):
            state = "prediction"
        else:
            state = "local"
    except (OSError, ValueError, TypeError, IndexError, RuntimeError):
        state = "unknown"
    return AstronomyStatus(state, model, table_name)
