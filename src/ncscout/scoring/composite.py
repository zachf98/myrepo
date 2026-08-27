"""Composite ranking.

The final score blends the resource base, the modelled return, and how cheaply
the resource is being acquired. Price efficiency is scored against peers in the
same run rather than an absolute scale, because $/acre is only meaningful in
comparison: $3,000/acre is expensive in west Texas and a bargain in Ohio.
"""

from __future__ import annotations

import statistics

from ..config import Config, clamp, default_config
from ..models import (
    BusinessCase,
    Listing,
    NaturalCapitalScore,
    ParcelEnvironment,
    ScoredOpportunity,
)

# Below this confidence the parcel is flagged rather than silently trusted.
LOW_CONFIDENCE_THRESHOLD = 0.6


class CompositeScorer:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or default_config()

    def rank(
        self,
        scored: list[tuple[Listing, ParcelEnvironment, NaturalCapitalScore, BusinessCase]],
    ) -> list[ScoredOpportunity]:
        if not scored:
            return []

        efficiency = self._price_efficiency([item[0] for item in scored])
        weights = self.config.composite_weights

        opportunities: list[ScoredOpportunity] = []
        for listing, env, nc, business in scored:
            eff = efficiency.get(listing.listing_id, 50.0)
            composite = (
                weights["natural_capital"] * nc.total
                + weights["business_return"] * business.score
                + weights["price_efficiency"] * eff
            )
            # A score built on thin data should not outrank a well-measured one
            # on equal merit, so confidence damps the composite toward the mean.
            damped = composite * (0.75 + 0.25 * nc.confidence)

            opportunities.append(
                ScoredOpportunity(
                    listing=listing,
                    environment=env,
                    natural_capital=nc,
                    business=business,
                    price_efficiency_score=round(eff, 1),
                    composite_score=round(clamp(damped), 2),
                    flags=self._flags(listing, env, nc, business),
                )
            )

        opportunities.sort(key=lambda o: o.composite_score, reverse=True)
        for i, opportunity in enumerate(opportunities, start=1):
            opportunity.rank = i
        return opportunities

    @staticmethod
    def _price_efficiency(listings: list[Listing]) -> dict[str, float]:
        """Percentile-style score for $/acre against the run's own cohort.

        Cheap relative to peers scores high. The median is the anchor so a single
        extreme outlier cannot compress everything else.
        """
        priced = [
            (item.listing_id, item.price_per_acre)
            for item in listings
            if item.price_per_acre
        ]
        if len(priced) < 2:
            return {lid: 50.0 for lid, _ in priced}

        values = sorted(v for _, v in priced)
        median = statistics.median(values)
        if median <= 0:
            return {lid: 50.0 for lid, _ in priced}

        scores: dict[str, float] = {}
        for listing_id, value in priced:
            # Ratio to median, mapped so half the median scores 100 and twice the
            # median scores near zero.
            ratio = value / median
            scores[listing_id] = clamp(100.0 * (2.0 - ratio) / 1.5)
        return scores

    @staticmethod
    def _flags(
        listing: Listing,
        env: ParcelEnvironment,
        nc: NaturalCapitalScore,
        business: BusinessCase,
    ) -> list[str]:
        """Human-facing caveats that a score alone cannot express."""
        flags: list[str] = []

        if nc.confidence < LOW_CONFIDENCE_THRESHOLD:
            flags.append(
                f"low data confidence ({nc.confidence:.0%}) - verify before acting"
            )
        if env.failed_enrichers:
            flags.append(f"missing data: {', '.join(sorted(set(env.failed_enrichers)))}")

        if env.flood_zone and env.flood_zone.startswith(("A", "V")):
            flags.append(
                f"in FEMA special flood hazard area (zone {env.flood_zone})"
            )
        if (env.soil_flood_frequency or "").strip().lower() in (
            "occasional",
            "frequent",
            "very frequent",
        ):
            flags.append(
                f"SSURGO records {env.soil_flood_frequency.lower()} flooding"
            )
        if env.wildfire_hazard_class and env.wildfire_hazard_class >= 4:
            flags.append(f"high modelled wildfire hazard (class {env.wildfire_hazard_class})")
        if env.slope_pct.is_usable and env.slope_pct.value > 30:
            flags.append(f"steep terrain ({env.slope_pct.value:.0f}% mean slope)")
        if env.precipitation_mm.is_usable and env.precipitation_mm.value < 300:
            flags.append(
                f"arid ({env.precipitation_mm.value:.0f} mm/yr) - water rights are decisive"
            )

        if business.net_operating_income <= 0:
            flags.append("modelled income does not cover carrying costs")

        speculative = [s for s in business.streams if s.speculative]
        if speculative:
            spec_share = sum(s.annual_net for s in speculative) / max(
                1e-6, sum(s.annual_net for s in business.streams)
            )
            if spec_share > 0.5:
                flags.append(
                    f"{spec_share:.0%} of modelled income is speculative "
                    f"({', '.join(s.name for s in speculative)})"
                )

        if not listing.has_coordinates:
            flags.append("could not be geolocated; scores are unreliable")

        return flags
