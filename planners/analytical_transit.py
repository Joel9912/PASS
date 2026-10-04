"""Tránsito analítico rápido (sin astropy) para la tabla de Búsqueda.

La tabla de resultados puede mostrar cientos de objetos a la vez; para cada
fila necesitamos horas de tránsito y horas sobre 30° sin pagar el coste de
astropy por objeto. Estas fórmulas son aproximadas (~1-2 min de error en el
tránsito) pero suficientes para planificar y ordenar la tabla.

La curva del objeto SELECCIONADO sí usa astropy (``planners.transit``), que
es la que el usuario mira con detalle.
"""
from __future__ import annotations

import math
from datetime import datetime

#: Tasa sideral: la hora sidereal avanza 1.0027379 h por hora solar.
_SIDEREAL_RATE = 1.0027379

#: Constantes de la GMST continua (Astronomical Almanac): GMST en horas
#: como función del Julian Date. Verificada contra astropy a <0.01 min.
_GMST_J2000_H = 18.697374558
_GMST_RATE_PER_DAY = 24.06570982441908
_JD_J2000 = 2451545.0


def max_altitude(latitude_deg: float, dec_deg: float) -> float:
    """Altitud máxima (culminación) de un objeto: ``90 − |lat − dec|``.

    Puede ser negativa (el objeto nunca cruza el horizonte). La UI decide
    si recorta a 0 o lo muestra tal cual.
    """
    return 90.0 - abs(latitude_deg - dec_deg)


def is_circumpolar(latitude_deg: float, dec_deg: float) -> bool:
    """¿El objeto nunca se pone para esa latitud? (no cruza el horizonte)."""
    if latitude_deg >= 0:
        return dec_deg >= 90.0 - latitude_deg
    return dec_deg <= -90.0 - latitude_deg


def never_rises(latitude_deg: float, dec_deg: float) -> bool:
    """¿El objeto nunca sale? (su culminación queda bajo el horizonte)."""
    if latitude_deg >= 0:
        return dec_deg <= latitude_deg - 90.0
    return dec_deg >= 90.0 + latitude_deg


def _julian_day_at_0h_utc(date_iso: str) -> float:
    """Julian Date a 0h UT de ``date_iso`` ('2026-10-02' → 2461315.5)."""
    from datetime import date

    year, month, day = (int(part) for part in date_iso[:10].split("-"))
    return date(year, month, day).toordinal() + 1721424.5


def gmst_0h_hours(date_iso: str) -> float:
    """GMST (horas) a 0h UT del día dado, con la fórmula continua del JD.

    ``GMST = 18.697374558 + 24.06570982441908·(JD − 2451545.0)`` (módulo 24),
    que es la del Astronomical Almanac. El error frente a astropy es <0.01 min.
    """
    jd0 = _julian_day_at_0h_utc(date_iso)
    return (_GMST_J2000_H + _GMST_RATE_PER_DAY * (jd0 - _JD_J2000)) % 24.0


def transit_utc_hours(ra_hours: float, date_iso: str, longitude_deg: float = 0.0) -> float:
    """Hora (UTC, decimal) de la culminación de ``ra_hours`` en ``date_iso``.

    El objeto culmina cuando la hora sidereal local iguala su RA, es decir
    cuando ``GMST = RA − longitud`` (longitud este positiva). Se resuelve con
    ``GMST(t) = GMST_0h + t·1.0027379``.

    ``longitude_deg`` es la del observador; con 0 (por defecto) devuelve la
    culminación sobre el meridiano de Greenwich.
    """
    lst_target = (ra_hours - longitude_deg / 15.0) % 24.0
    gmst0 = gmst_0h_hours(date_iso)
    return ((lst_target - gmst0) % 24.0 / _SIDEREAL_RATE) % 24.0


def local_utc_offset(
    longitude_deg: float, utc_offset_hours: float | None = None
) -> float:
    """Horas que hay que sumar a UTC para obtener la hora local del lugar.

    Si la ubicación guarda su desfase horario se usa ese (hora de reloj, con
    horario de verano incluido). Si no, se infiere de la longitud
    redondeada a la hora (`round(lon / 15)`, huso horario estándar): así
    una ubicación en el otro lado del planeta no acaba con el huso del
    sistema (que es de otro continente) y la noche queda «invertida».

    Todo lo que convierta a hora local (curvas, culminación, efemérides)
    pasa por aquí: una única fuente de verdad. Sin astropy, para que la
    tabla de tránsitos siga siendo barata.
    """
    if utc_offset_hours is not None:
        return float(utc_offset_hours)
    return round(longitude_deg / 15.0)


def transit_local_hours(
    ra_hours: float,
    date_iso: str,
    longitude_deg: float,
    utc_offset_hours: float | None = None,
) -> float:
    """Hora local (decimal) de la culminación, en el huso de la ubicación."""
    utc_hours = transit_utc_hours(ra_hours, date_iso, longitude_deg)
    return (
        utc_hours + local_utc_offset(longitude_deg, utc_offset_hours)
    ) % 24.0


def hours_above_altitude(latitude_deg: float, dec_deg: float, min_alt_deg: float) -> float:
    """Horas al día que el objeto está sobre ``min_alt_deg`` (0-24).

    Fórmula clásica del arco horario::

        cos(H) = (sin(alt) − sin(lat)·sin(dec)) / (cos(lat)·cos(dec))
        horas  = 2·H / 15

    Devuelve 0 si nunca alcanza esa altura y 24 si siempre está sobre ella
    (círculo polar / objeto circumpolar sobre el umbral).
    """
    cos_h = (
        (math.sin(math.radians(min_alt_deg))
         - math.sin(math.radians(latitude_deg)) * math.sin(math.radians(dec_deg)))
        / (math.cos(math.radians(latitude_deg)) * math.cos(math.radians(dec_deg)))
    )
    if cos_h >= 1.0:
        return 0.0
    if cos_h <= -1.0:
        return 24.0
    arc_hours = math.degrees(math.acos(cos_h)) / 15.0
    return round(2.0 * arc_hours, 2)


def altitude_at_utc(
    ra_hours: float,
    dec_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    instant: datetime,
) -> float:
    """Altitud (grados) del objeto en ``instant`` (UTC, sin zona horaria).

    Sin astropy: GMST con la fórmula continua del Almanac (la misma que
    :func:`gmst_0h_hours`) y la fórmula clásica::

        sin(alt) = sinφ·sinδ + cosφ·cosδ·cos(H),   H = LST − RA

    La usa ``best_dates`` para medir la altura de cada noche dentro de su
    propia ventana (decisión D-2 / M-11): la culminación sola es la misma
    en las 30 noches y no llega a ordenar nada.
    """
    jd = (
        instant.toordinal() + 1721424.5
        + (instant.hour + instant.minute / 60.0 + instant.second / 3600.0) / 24.0
    )
    gmst_hours = (_GMST_J2000_H + _GMST_RATE_PER_DAY * (jd - _JD_J2000)) % 24.0
    lst_hours = gmst_hours + longitude_deg / 15.0
    hour_angle_deg = (lst_hours - ra_hours) * 15.0
    sin_alt = (
        math.sin(math.radians(latitude_deg)) * math.sin(math.radians(dec_deg))
        + math.cos(math.radians(latitude_deg)) * math.cos(math.radians(dec_deg))
        * math.cos(math.radians(hour_angle_deg))
    )
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))


def format_transit_hours(hour_decimal: float) -> str:
    """18.6 → '18:36' (para la columna Tránsito de la tabla)."""
    hour_decimal = hour_decimal % 24.0
    hours = int(hour_decimal)
    minutes = int(round((hour_decimal - hours) * 60.0))
    if minutes == 60:
        hours = (hours + 1) % 24
        minutes = 0
    return f"{hours:02d}:{minutes:02d}"
