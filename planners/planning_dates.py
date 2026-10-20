"""Alcance de fechas aprobado para cálculos de planificación; no certifica precisión ni cobertura de un kernel."""

from datetime import date, timedelta

FIRST_PLANNING_DATE = date(1950, 1, 1)
LAST_PLANNING_DATE = date(2100, 12, 31)
_RANGE_ERROR = "La planificación admite noches entre 1950-01-01 y 2100-12-31; no se extrapolan fechas fuera de ese rango."


def planning_date(value: str | date) -> date:
    """Valida la fecha nominal de la noche, sin truncar una hora, recortar al límite ni reescribir sesiones."""
    if type(value) is date:
        day = value
    elif isinstance(value, str) and len(value) == 10:
        try:
            day = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Fecha de planificación inválida; usa AAAA-MM-DD.") from exc
    else:
        raise ValueError("Fecha de planificación inválida; usa AAAA-MM-DD.")
    if not FIRST_PLANNING_DATE <= day <= LAST_PLANNING_DATE:
        raise ValueError(_RANGE_ERROR)
    return day


def planning_interval(first: str | date, nights: int) -> date:
    """Valida el intervalo completo antes de calcular; no entrega una lista parcial si el final queda fuera."""
    day = planning_date(first)
    if type(nights) is not int or nights < 1:
        raise ValueError("El intervalo de planificación debe contener un número entero positivo de noches.")
    # Comparar días evita desbordar timedelta/date con un entero arbitrario.
    if nights - 1 > (LAST_PLANNING_DATE - day).days:
        raise ValueError(_RANGE_ERROR)
    planning_date(day + timedelta(days=nights - 1))
    return day
