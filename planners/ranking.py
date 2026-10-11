"""Ranking configurable de objetos para una noche (subpestaña "Ranking").

Los PESOS los define el usuario: los valores por defecto son solo un punto de
partida, nunca una verdad impuesta (requisito del proyecto). La UI expondrá
``RankingWeights`` para que cada uno ajuste la importancia de altura,
separación lunar y meteorología.

Cada candidato viene con su ``transit_info`` ya calculado; el ranking
combina esos factores en una puntuación 0-100 con ``reasons`` en castellano,
para que el usuario siempre sepa por qué se sugiere un objeto.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from planners.moon_distance import POSSIBLE_MOON_MARGIN, min_moon_distance
from planners.transit import NightInfo, TransitInfo


@dataclass
class RankingWeights:
    """Pesos de cada factor. El usuario puede modificarlos desde la UI.

    Por defecto: altura 50, luna 30, clima 20 — pero son solo una propuesta
    inicial; nadie está obligado a aceptarla.
    """

    altitude: float = 50.0
    moon_separation: float = 30.0
    weather: float = 20.0


@dataclass
class RankedObject:
    """Resultado del ranking para un objeto candidato."""

    object_id: str
    score: float                    # 0-100
    altitude_deg: float
    separation_moon_deg: float
    astronomical_hours: float
    reasons: list[str] = field(default_factory=list)


def _moon_score(separation_deg: float, min_dist_deg: float) -> float:
    """1.0 si supera el umbral de la fase, 0.5 si está en el margen, si no 0.

    El umbral ``min_dist_deg`` lo da :func:`planners.moon_distance.min_moon_distance`
    según la iluminación de esa noche (no es un valor fijo impuesto).
    """
    if separation_deg >= min_dist_deg:
        return 1.0
    if separation_deg >= min_dist_deg - POSSIBLE_MOON_MARGIN:
        return 0.5
    return 0.0


def _weather_score(weather: dict | None) -> float | None:
    """1 = clima perfecto, 0 = malo. None si no hay datos de ese factor.

    Escalas por defecto (ajustables desde la UI):
    - cloud_cover %: 0 % → 1.0, 100 % → 0.0 (lineal)
    - transparency (0-1, ya normalizado): se usa tal cual
    - wind_speed m/s: <= 2 → 1.0, >= 10 → 0.0
    - humidity %: <= 50 → 1.0, >= 100 → 0.0
    """
    if not weather:
        return None
    scores: list[float] = []
    if weather.get("cloud_cover") is not None:
        scores.append(max(0.0, 1.0 - float(weather["cloud_cover"]) / 100.0))
    if weather.get("transparency") is not None:
        scores.append(min(max(float(weather["transparency"]), 0.0), 1.0))
    if weather.get("wind_speed") is not None:
        wind = float(weather["wind_speed"])
        scores.append(min(max((10.0 - wind) / 8.0, 0.0), 1.0))
    if weather.get("humidity") is not None:
        humidity = float(weather["humidity"])
        scores.append(min(max((100.0 - humidity) / 50.0, 0.0), 1.0))
    if not scores:
        return None
    return sum(scores) / len(scores)


def rank_objects(
    candidates: list[dict],
    night: NightInfo,
    weather: dict | None = None,
    weights: RankingWeights | None = None,
) -> list[RankedObject]:
    """Puntúa y ordena los candidatos de mayor a menor.

    Cada candidato es un dict con:
    - ``object_id``: designación ('M31')
    - ``transit``: TransitInfo ya calculado para ese objeto
    - ``magnitude`` (opcional): magnitud aparente (para las razones)

    ``night`` es la NightInfo compartida de la noche elegida; ``weather`` son
    valores climáticos medios opcionales (None → sin factor clima, los pesos
    se renormalizan entre los factores disponibles).
    """
    weights = weights or RankingWeights()
    weather_score = _weather_score(weather)
    # Umbral lunar de la noche: depende de la fase, no es un valor fijo.
    min_moon_dist = min_moon_distance(night.moon_illumination * 100.0)

    ranked: list[RankedObject] = []
    for candidate in candidates:
        transit: TransitInfo = candidate["transit"]
        altitude_norm = min(max(transit.altitude_deg / 90.0, 0.0), 1.0)
        moon_norm = _moon_score(transit.separation_moon_deg, min_moon_dist)

        # Renormalizar: si falta un factor, su peso se reparte entre los demás
        parts: list[tuple[float, float]] = [
            (weights.altitude, altitude_norm),
            (weights.moon_separation, moon_norm),
        ]
        if weather_score is not None:
            parts.append((weights.weather, weather_score))
        total_weight = sum(w for w, _ in parts) or 1.0
        score = 100.0 * sum(w * s for w, s in parts) / total_weight

        reasons: list[str] = []
        reasons.append(f"Altura en el tránsito: {transit.altitude_deg:.0f}°")
        if transit.separation_moon_deg < min_moon_dist - POSSIBLE_MOON_MARGIN:
            reasons.append(
                f"⚠ Cerca de la luna: {transit.separation_moon_deg:.0f}° "
                f"(umbral de la fase {min_moon_dist:.0f}°, {night.moon_illumination:.0%})"
            )
        elif transit.separation_moon_deg < min_moon_dist:
            reasons.append(
                f"Separación lunar {transit.separation_moon_deg:.0f}° por debajo "
                f"del umbral {min_moon_dist:.0f}° ({night.moon_illumination:.0%} de luna)"
            )
        else:
            reasons.append(
                f"Separación lunar {transit.separation_moon_deg:.0f}° ≥ "
                f"umbral {min_moon_dist:.0f}° ({night.moon_illumination:.0%} de luna)"
            )
        if weather_score is not None:
            cloud = weather.get("cloud_cover") if weather else None
            if cloud is not None:
                reasons.append(f"Nubosidad media: {cloud:.0f}%")
            else:
                reasons.append("Con datos de clima")
        else:
            reasons.append("Sin datos de clima (puntuación solo por cielo)")
        reasons.append(f"Noche astronómica: {night.astronomical_hours:.1f} h")

        ranked.append(
            RankedObject(
                object_id=candidate["object_id"],
                score=round(score, 1),
                altitude_deg=transit.altitude_deg,
                separation_moon_deg=transit.separation_moon_deg,
                astronomical_hours=night.astronomical_hours,
                reasons=reasons,
            )
        )

    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked
