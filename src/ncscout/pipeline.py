"""Scan orchestration.

Enrichment is the expensive part of a scan: full enrichment costs roughly 20
requests per parcel against public services that must not be hammered. Scanning
500 listings that way would mean ~10,000 requests for a top-10 answer, most of
them spent on parcels that were never going to place.

So the scan runs in two stages. Stage one spends a single request per listing on
climate, which alone separates the productive from the marginal, and combines it
with price efficiency. Only the survivors get the full soil, water, land cover,
flood and terrain treatment.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .config import Config, default_config
from .enrich import EnrichmentPipeline
from .enrich.climate import NasaPowerEnricher
from .enrich.geocode import Geocoder
from .http import CachedClient
from .models import Listing, ScanReport, ScoredOpportunity
from .scoring import BusinessModeler, CompositeScorer, NaturalCapitalScorer
from .sources import ListingSource, SearchCriteria, SourceUnavailable

log = logging.getLogger(__name__)


class ScanPipeline:
    def __init__(
        self,
        client: CachedClient,
        sources: list[ListingSource],
        config: Config | None = None,
        prescreen_keep: int = 60,
        max_workers: int = 4,
    ) -> None:
        self.client = client
        self.sources = sources
        self.config = config or default_config()
        self.prescreen_keep = prescreen_keep
        self.enrichment = EnrichmentPipeline(client, max_workers=max_workers)
        self.nc_scorer = NaturalCapitalScorer(self.config)
        self.business = BusinessModeler(self.config)
        self.composite = CompositeScorer(self.config)

    def criteria(self, limit: int = 500) -> SearchCriteria:
        search = self.config.search
        return SearchCriteria(
            max_price=search["max_price"],
            min_price=search.get("min_price", 0),
            min_acres=search.get("min_acres", 0),
            max_acres=search.get("max_acres", 1e9),
            property_types=tuple(search.get("property_types", ())),
            states=tuple(search.get("states", ())),
            limit=limit,
        )

    def run(self, top_n: int = 10, limit: int = 500) -> ScanReport:
        warnings: list[str] = []
        listings, sources_used = self._collect(limit, warnings)

        if not listings:
            return ScanReport(
                generated_at=datetime.now(UTC),
                listings_considered=0,
                listings_enriched=0,
                opportunities=[],
                sources_used=sources_used,
                warnings=warnings + ["no listings matched the search criteria"],
            )

        considered = len(listings)
        listings = self._filter_price_per_acre(listings, warnings)
        candidates = self._prescreen(listings, warnings)

        enriched = self.enrichment.enrich_many(candidates)
        scored = []
        for listing, env in enriched:
            nc = self.nc_scorer.score(env)
            business = self.business.model(listing, env)
            scored.append((listing, env, nc, business))

        opportunities = self.composite.rank(scored)

        return ScanReport(
            generated_at=datetime.now(UTC),
            listings_considered=considered,
            listings_enriched=len(enriched),
            opportunities=opportunities[:top_n],
            sources_used=sources_used,
            warnings=warnings,
        )

    def _collect(
        self, limit: int, warnings: list[str]
    ) -> tuple[list[Listing], list[str]]:
        criteria = self.criteria(limit)
        collected: list[Listing] = []
        used: list[str] = []
        seen: set[tuple] = set()

        for source in self.sources:
            try:
                found = source.search(criteria)
            except SourceUnavailable as exc:
                warnings.append(f"source {source.name} unavailable: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001
                log.exception("source %s failed", source.name)
                warnings.append(f"source {source.name} failed: {exc}")
                continue

            used.append(source.name)
            for listing in found:
                # The same parcel often appears in more than one feed; dedupe on
                # location and price rather than on provider listing id.
                key = (
                    round(listing.latitude, 5) if listing.latitude else None,
                    round(listing.longitude, 5) if listing.longitude else None,
                    round(listing.price),
                    listing.address,
                )
                if key in seen:
                    continue
                seen.add(key)
                collected.append(listing)

        return collected, used

    def _filter_price_per_acre(
        self, listings: list[Listing], warnings: list[str]
    ) -> list[Listing]:
        ceiling = self.config.search.get("max_price_per_acre")
        if not ceiling:
            return listings
        kept = [
            item
            for item in listings
            if item.price_per_acre is None or item.price_per_acre <= ceiling
        ]
        dropped = len(listings) - len(kept)
        if dropped:
            warnings.append(
                f"dropped {dropped} listing(s) above ${ceiling:,}/acre before enrichment"
            )
        return kept

    def _prescreen(
        self, listings: list[Listing], warnings: list[str]
    ) -> list[Listing]:
        """Cheap ranking pass to decide who earns full enrichment."""
        if len(listings) <= self.prescreen_keep:
            return listings

        geocoder = Geocoder(self.client)
        climate = NasaPowerEnricher(self.client)
        from .models import ParcelEnvironment

        ranked: list[tuple[float, Listing]] = []
        median_ppa = self._median_price_per_acre(listings)

        for listing in listings:
            if not listing.has_coordinates and not geocoder.locate(listing):
                continue

            env = ParcelEnvironment()
            climate.run(listing, env)

            nc = self.nc_scorer.score(env)
            ppa = listing.price_per_acre or median_ppa
            # Cheaper than the cohort median is a positive signal; the ratio is
            # clamped so a near-free outlier cannot dominate the prescreen.
            value_signal = max(0.0, min(2.0, median_ppa / ppa)) * 25.0
            ranked.append((nc.total + value_signal, listing))

        ranked.sort(key=lambda pair: pair[0], reverse=True)
        kept = [listing for _, listing in ranked[: self.prescreen_keep]]
        warnings.append(
            f"prescreened {len(listings)} listings down to {len(kept)} "
            "for full enrichment"
        )
        return kept

    @staticmethod
    def _median_price_per_acre(listings: list[Listing]) -> float:
        import statistics

        values = [
            item.price_per_acre for item in listings if item.price_per_acre
        ]
        return statistics.median(values) if values else 1.0


def opportunities_to_rows(opportunities: list[ScoredOpportunity]) -> list[dict]:
    """Flatten to tabular rows for CSV export and console display."""
    rows = []
    for opportunity in opportunities:
        listing = opportunity.listing
        rows.append(
            {
                "rank": opportunity.rank,
                "listing_id": listing.listing_id,
                "location": ", ".join(
                    p for p in (listing.city, listing.state) if p
                ),
                "price": listing.price,
                "acres": listing.acres,
                "price_per_acre": listing.price_per_acre,
                "composite": opportunity.composite_score,
                "natural_capital": round(opportunity.natural_capital.total, 1),
                "confidence": opportunity.natural_capital.confidence,
                "noi": round(opportunity.business.net_operating_income),
                "cap_rate": round(opportunity.business.cap_rate, 4),
                "irr": (
                    round(opportunity.business.irr, 4)
                    if opportunity.business.irr is not None
                    else None
                ),
                "streams": "|".join(s.name for s in opportunity.business.streams),
                "url": listing.url or "",
            }
        )
    return rows
