"""Esfera de fondo: imágenes DSS2 mapeadas sobre una esfera.

El usuario está en el centro y mira la esfera completa. Se usan los ficheros
JPG del DSS2 (zonas del cielo) como texturas. SIN proyección rectangular
(descartada por problemas de rendimiento en versiones anteriores).
"""


class Dss2Sphere:
    """Esfera con las imágenes del DSS2 como fondo."""

    def __init__(self, cache_dir: str = "data/dss2_cache") -> None:
        self.cache_dir = cache_dir  # los JPG descargados se cachean localmente

    def tiles_for_view(self, ra_hours: float, dec_deg: float, fov_deg: float) -> list[str]:
        """Devuelve las zonas DSS2 necesarias para la vista actual (rutas JPG)."""
        raise NotImplementedError

    def download_tile(self, ra_hours: float, dec_deg: float, size_deg: float) -> str:
        """Descarga (una sola vez) y cachea la imagen DSS2 de una zona."""
        raise NotImplementedError
