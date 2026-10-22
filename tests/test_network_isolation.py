"""Comprueba el bloqueo HTTP común, incluidas las rutas que no pasan por urllib.request.urlopen."""

import urllib.request

import pytest


@pytest.mark.parametrize("route", ["opener", "astropy"])
def test_abridores_http_no_eluden_bloqueo_de_red(monkeypatch, route):
    """Un transporte centinela garantiza que incluso la regresión roja no pueda abrir una conexión real."""
    def transport(*args, **kwargs):
        """Falla de forma distinta si se alcanza la capa que intentaría contactar al servidor."""
        raise RuntimeError("Se alcanzó el transporte; falta el bloqueo de la suite")

    monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", transport)
    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", transport)
    with pytest.raises(AssertionError, match="sin red"):
        if route == "opener":
            urllib.request.build_opener().open("https://pass.invalid/synthetic")
        else:
            from astropy.utils.data import download_file

            download_file("https://pass.invalid/synthetic", cache=False)
