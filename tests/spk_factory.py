"""Construye kernels SPK sintéticos originales para tests sin copiar, recortar ni modificar datos de JPL."""

from io import BytesIO
from struct import pack

from jplephem.daf import DAF, FTPSTR


def synthetic_spk(*, missing=(), frame=1, kind=2, value=1000.0, start_jd=2415020.5, end_jd=2524593.5):
    """Genera segmentos constantes propios; las posiciones no representan ningún cuerpo real ni precisión científica."""
    pairs = [(0, number) for number in range(1, 11)] + [(1, 199), (2, 299), (3, 399), (3, 301)]
    initial = (start_jd - 2451545.0) * 86400
    interval = (end_jd - start_jd) * 86400
    header = pack("<8sII60sIII8s603s28s297s", b"DAF/SPK ", 2, 6, b"PASS synthetic",
                  2, 2, 385, b"LTL-IEEE", b"", FTPSTR, b"")
    with BytesIO(header + pack("<ddd", 0, 0, 0).ljust(1024, b"\0") + bytes(1024)) as stream:
        daf = DAF(stream)
        for center, target in pairs:
            if (center, target) in missing:
                continue
            components = 6 if kind == 3 else 3
            constants = [value * (target + 1), value, value] + ([0.0] * 3 if kind == 3 else [])
            coefficients = [coefficient for constant in constants for coefficient in (constant, 0.0)]
            daf.add_array(b"PASS original synthetic", (initial, initial + interval, target, center, frame, kind),
                          [initial + interval / 2, interval / 2, *coefficients,
                           initial, interval, components * 2 + 2, 1])
        return stream.getvalue()
