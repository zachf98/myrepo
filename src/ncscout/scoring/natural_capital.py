"""Natural capital scoring.

Each subscore converts physical measurements into a 0-100 rating using the
breakpoint curves in config, then the subscores are combined with configured
weights. Confidence is tracked separately from score: a parcel that scores 80 on
two measurements is not the same proposition as one that scores 80 on six, and
the report needs to be able to tell them apart.
"""

from __future__ import annotations

from ..config import Config, clamp, default_config, interpolate
from ..models import (
    DataQuality,
    Measurement,
    NaturalCapitalScore,
    ParcelEnvironment,
    SubScore,
)

# Weight applied to a subscore's contribution to overall confidence when the
# underlying measurement is modelled rather than directly measured.
MODELED_CONFIDENCE = 0.85
REGIONAL_CONFIDENCE = 0.4


def _confidence(*measurements: Measurement) -> float:
    """Mean confidence across the measurements backing a subscore."""
    if not measurements:
        return 0.0
    scores = []
    for m in measurements:
        if not m.is_usable:
            scores.append(0.0)
        elif m.quality is DataQuality.MEASURED:
            scores.append(1.0)
        elif m.quality is DataQuality.MODELED:
            scores.append(MODELED_CONFIDENCE)
        else:
            scores.append(REGIONAL_CONFIDENCE)
    return sum(scores) / len(scores)


class NaturalCapitalScorer:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or default_config()

    def score(self, env: ParcelEnvironment) -> NaturalCapitalScore:
        weights = self.config.nc_weights
        subscores = [
            self._water(env, weights["water"]),
            self._soil(env, weights["soil"]),
            self._timber(env, weights["timber"]),
            self._climate(env, weights["climate"]),
            self._solar(env, weights["solar"]),
            self._wind(env, weights["wind"]),
            self._resilience(env, weights["resilience"]),
        ]

        # Subscores with no data are dropped and the remaining weights are
        # renormalised, so a missing dataset lowers confidence rather than
        # dragging the score toward zero.
        usable = [s for s in subscores if s.confidence > 0]
        if not usable:
            return NaturalCapitalScore(total=0.0, subscores=subscores, confidence=0.0)

        resolved_weight = sum(s.weight for s in usable)
        total = sum(s.weighted for s in usable) / resolved_weight

        # Confidence has to answer two separate questions: how good is the data
        # behind the subscores that resolved, and how much of the intended
        # weight resolved at all. Averaging only over what resolved would report
        # high confidence for a parcel where five of seven subscores are blank,
        # so the quality average is scaled by the share of weight covered.
        quality = sum(s.confidence * s.weight for s in usable) / resolved_weight
        all_weight = sum(s.weight for s in subscores)
        coverage = resolved_weight / all_weight if all_weight else 0.0

        return NaturalCapitalScore(
            total=clamp(total),
            subscores=subscores,
            confidence=round(quality * coverage, 3),
        )

    def _curve(self, name: str, value: float) -> float:
        return interpolate(self.config.normalisation[name], value)

    def _water(self, env: ParcelEnvironment, weight: float) -> SubScore:
        drivers: list[str] = []
        parts: list[tuple[float, float]] = []  # (score, weight within subscore)

        if env.precipitation_mm.is_usable:
            score = self._curve("precipitation_mm", env.precipitation_mm.value)
            parts.append((score, 0.55))
            drivers.append(f"{env.precipitation_mm.value:.0f} mm/yr precipitation")

        if env.water_distance_m.is_usable:
            score = self._curve("water_distance_m", env.water_distance_m.value)
            parts.append((score, 0.30))
            label = env.nearest_water_name or "perennial water"
            drivers.append(
                f"{label} within {env.water_distance_m.value:.0f} m"
                if env.water_distance_m.value < 5000
                else "no perennial water nearby"
            )

        if env.water_storage_cm.is_usable:
            score = self._curve("water_storage_cm", env.water_storage_cm.value)
            parts.append((score, 0.15))
            drivers.append(
                f"{env.water_storage_cm.value:.1f} cm soil water storage"
            )

        return self._combine(
            "water",
            weight,
            parts,
            drivers,
            _confidence(
                env.precipitation_mm, env.water_distance_m, env.water_storage_cm
            ),
        )

    def _soil(self, env: ParcelEnvironment, weight: float) -> SubScore:
        drivers: list[str] = []
        parts: list[tuple[float, float]] = []

        if env.nccpi.is_usable:
            parts.append((self._curve("nccpi", env.nccpi.value), 0.55))
            drivers.append(f"NCCPI {env.nccpi.value:.2f}")

        if env.water_storage_cm.is_usable:
            parts.append(
                (self._curve("water_storage_cm", env.water_storage_cm.value), 0.20)
            )

        if env.slope_pct.is_usable:
            parts.append((self._curve("slope_pct", env.slope_pct.value), 0.25))
            drivers.append(f"{env.slope_pct.value:.0f}% mean slope")

        if env.soil_description:
            drivers.append(env.soil_description)

        return self._combine(
            "soil",
            weight,
            parts,
            drivers,
            _confidence(env.nccpi, env.water_storage_cm, env.slope_pct),
        )

    def _timber(self, env: ParcelEnvironment, weight: float) -> SubScore:
        drivers: list[str] = []
        parts: list[tuple[float, float]] = []

        if env.forest_cover_pct.is_usable:
            parts.append(
                (self._curve("forest_cover_pct", env.forest_cover_pct.value), 0.60)
            )
            drivers.append(f"{env.forest_cover_pct.value:.0f}% forest cover")

        # Growth rate is driven by moisture and heat; a forested parcel in a dry
        # cold climate carries far less merchantable increment per year.
        if env.precipitation_mm.is_usable:
            parts.append(
                (self._curve("precipitation_mm", env.precipitation_mm.value), 0.25)
            )
        if env.growing_degree_days.is_usable:
            parts.append(
                (
                    self._curve(
                        "growing_degree_days", env.growing_degree_days.value
                    ),
                    0.15,
                )
            )

        return self._combine(
            "timber",
            weight,
            parts,
            drivers,
            _confidence(
                env.forest_cover_pct, env.precipitation_mm, env.growing_degree_days
            ),
        )

    def _climate(self, env: ParcelEnvironment, weight: float) -> SubScore:
        drivers: list[str] = []
        parts: list[tuple[float, float]] = []

        if env.growing_degree_days.is_usable:
            parts.append(
                (
                    self._curve(
                        "growing_degree_days", env.growing_degree_days.value
                    ),
                    1.0,
                )
            )
            drivers.append(f"{env.growing_degree_days.value:.0f} GDD (base 10C)")

        return self._combine(
            "climate", weight, parts, drivers, _confidence(env.growing_degree_days)
        )

    def _solar(self, env: ParcelEnvironment, weight: float) -> SubScore:
        drivers: list[str] = []
        parts: list[tuple[float, float]] = []

        if env.solar_ghi.is_usable:
            parts.append((self._curve("solar_ghi", env.solar_ghi.value), 1.0))
            drivers.append(f"{env.solar_ghi.value:.2f} kWh/m2/day GHI")

        return self._combine(
            "solar", weight, parts, drivers, _confidence(env.solar_ghi)
        )

    def _wind(self, env: ParcelEnvironment, weight: float) -> SubScore:
        drivers: list[str] = []
        parts: list[tuple[float, float]] = []

        if env.wind_ws50m.is_usable:
            parts.append((self._curve("wind_ws50m", env.wind_ws50m.value), 1.0))
            drivers.append(f"{env.wind_ws50m.value:.2f} m/s at 50 m")

        return self._combine(
            "wind", weight, parts, drivers, _confidence(env.wind_ws50m)
        )

    def _resilience(self, env: ParcelEnvironment, weight: float) -> SubScore:
        """Starts at 100 and deducts for mapped hazards."""
        penalties = self.config.hazard_penalties
        score = 100.0
        drivers: list[str] = []
        # Hazard data is categorical rather than a Measurement, so confidence is
        # tracked by how many of the three hazard checks resolved.
        resolved = 0

        flood_table = penalties.get("flood_zone", {})
        soil_flood_table = penalties.get("soil_flood_frequency", {})
        soil_flood = (env.soil_flood_frequency or "").strip().lower()

        if env.flood_zone:
            key = env.flood_zone if env.flood_zone in flood_table else "UNKNOWN"
            deduction = flood_table.get(key, flood_table.get("UNKNOWN", 5))
            score -= deduction
            resolved += 1
            if deduction > 0:
                drivers.append(f"FEMA flood zone {env.flood_zone} (-{deduction})")
            else:
                drivers.append(f"FEMA flood zone {env.flood_zone} (minimal risk)")
        elif soil_flood in soil_flood_table:
            # FEMA has not mapped this area, but the soil survey has observed it.
            deduction = soil_flood_table[soil_flood]
            score -= deduction
            resolved += 1
            suffix = f" (-{deduction})" if deduction else ""
            drivers.append(
                f"FEMA unmapped; SSURGO flooding {soil_flood}{suffix}"
            )
        elif env.flood_zone_source and "unmapped" in env.flood_zone_source:
            deduction = flood_table.get("UNKNOWN", 5)
            score -= deduction
            resolved += 1
            drivers.append(f"flood risk unmapped (-{deduction})")

        fire_table = penalties.get("wildfire_hazard", {})
        if env.wildfire_hazard_class is not None:
            deduction = fire_table.get(env.wildfire_hazard_class, 0)
            score -= deduction
            resolved += 1
            if deduction > 0:
                drivers.append(
                    f"wildfire hazard class {env.wildfire_hazard_class} (-{deduction})"
                )

        aridity = penalties.get("aridity", {})
        if env.precipitation_mm.is_usable and aridity:
            resolved += 1
            if env.precipitation_mm.value < aridity.get("threshold_mm", 350):
                deduction = aridity.get("penalty", 20)
                score -= deduction
                drivers.append(
                    f"arid: {env.precipitation_mm.value:.0f} mm/yr (-{deduction})"
                )

        if resolved == 0:
            return SubScore(
                name="resilience", score=0.0, weight=weight, confidence=0.0
            )

        if not drivers:
            drivers.append("no mapped hazards")

        # Hazard inputs are all modelled or categorical, so confidence caps below 1.
        confidence = min(1.0, resolved / 3.0) * MODELED_CONFIDENCE
        return SubScore(
            name="resilience",
            score=clamp(score),
            weight=weight,
            drivers=drivers,
            confidence=round(confidence, 3),
        )

    @staticmethod
    def _combine(
        name: str,
        weight: float,
        parts: list[tuple[float, float]],
        drivers: list[str],
        confidence: float,
    ) -> SubScore:
        if not parts:
            return SubScore(name=name, score=0.0, weight=weight, confidence=0.0)
        total_weight = sum(w for _, w in parts)
        score = sum(s * w for s, w in parts) / total_weight
        return SubScore(
            name=name,
            score=clamp(score),
            weight=weight,
            drivers=drivers,
            confidence=round(confidence, 3),
        )
