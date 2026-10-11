"""Formateo de horas decimales a ``HH:MM``, único de todo el programa (A-34).

Antes había cuatro copias idénticas del mismo algoritmo (``_format_hours``,
``format_transit_hours``, ``_format_hour`` y ``fmt_hhmm``): cualquier ajuste
de redondeo podía aplicarse a una y no a las otras. Este módulo es la única
implementación; los demás delegan.
"""


def format_hhmm(hour_decimal: float) -> str:
    """18.6 → ``'18:36'``; módulo 24 con vuelta al 60→00 (borde del día)."""
    hour_decimal = hour_decimal % 24.0
    hours = int(hour_decimal)
    minutes = int(round((hour_decimal - hours) * 60.0))
    if minutes == 60:  # redondeo justo en el borde: sube la hora
        hours = (hours + 1) % 24
        minutes = 0
    return f"{hours:02d}:{minutes:02d}"
