"""Apilado final con SirIL: todas sus opciones y todo el hardware disponible.

Expone los parámetros de apilado de SirIL (documentados en sus docs):
- drizzle (activado/desactivado, escala)
- criterios de rechazo (sigma, winsorized, percentile...)
- ponderación de frames (peso por FWHM/redondez/fondo)
- integración (suma, media, mediana, winsorized mean)

Ejecución: SirIL se lanza con todos los hilos de la CPU que tenga la máquina.
"""
from dataclasses import dataclass, field


@dataclass
class StackOptions:
    """Opciones de apilado expuestas al usuario (todas las de SirIL)."""

    drizzle: bool = False
    drizzle_scale: float = 2.0
    rejection: str = "sigma"            # 'sigma' | 'winsorized' | 'percentile' | 'none'
    sigma_low: float = 3.0
    sigma_high: float = 3.0
    weighting: str = "equal"            # 'equal' | 'fwhm' | 'roundness' | 'background'
    integration: str = "avg"            # 'sum' | 'avg' | 'median' | 'winsorized_mean'
    extra_args: list[str] = field(default_factory=list)  # parámetros libres de SirIL

    def to_siril_args(self) -> list[str]:
        """Convierte las opciones en argumentos CLI de SirIL."""
        raise NotImplementedError


def stack(
    pool_paths: list[str],
    output_path: str,
    options: StackOptions | None = None,
    progress_cb=None,
) -> str:
    """Apila los lights referenciados por el pool y devuelve la imagen de salida.

    - Usa todos los hilos disponibles de la CPU.
    - Trabaja por referencias: no copia ficheros de entrada.
    - `progress_cb(fraccion)` notifica el avance a la interfaz.
    """
    raise NotImplementedError
