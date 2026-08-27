"""Enrichment orchestration."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..http import CachedClient
from ..models import Listing, ParcelEnvironment
from .base import Enricher
from .climate import NasaPowerEnricher
from .geocode import Geocoder
from .hazard import FemaFloodEnricher, WildfireHazardEnricher
from .landcover import NlcdLandCoverEnricher
from .soil import SsurgoSoilEnricher
from .terrain import ElevationEnricher
from .water import NhdWaterEnricher

log = logging.getLogger(__name__)

__all__ = ["EnrichmentPipeline", "Geocoder", "default_enrichers"]


def default_enrichers(client: CachedClient) -> list[Enricher]:
    """Enrichers in rough order of importance to the final score."""
    return [
        NasaPowerEnricher(client),
        SsurgoSoilEnricher(client),
        NlcdLandCoverEnricher(client),
        NhdWaterEnricher(client),
        FemaFloodEnricher(client),
        ElevationEnricher(client),
        WildfireHazardEnricher(client),
    ]


class EnrichmentPipeline:
    """Runs every enricher for a listing, then across listings in parallel."""

    def __init__(
        self,
        client: CachedClient,
        enrichers: list[Enricher] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.client = client
        self.enrichers = enrichers if enrichers is not None else default_enrichers(client)
        self.geocoder = Geocoder(client)
        # Kept low deliberately: these are public services and the rate limiter
        # is per-host, so more workers mostly means more queuing.
        self.max_workers = max_workers

    def enrich_one(self, listing: Listing) -> ParcelEnvironment:
        env = ParcelEnvironment()

        if not listing.has_coordinates and not self.geocoder.locate(listing):
            env.failed_enrichers.append("geocode")
            return env

        for enricher in self.enrichers:
            enricher.run(listing, env)
        return env

    def enrich_many(
        self, listings: list[Listing]
    ) -> list[tuple[Listing, ParcelEnvironment]]:
        results: list[tuple[Listing, ParcelEnvironment]] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self.enrich_one, item): item for item in listings}
            for future in as_completed(futures):
                listing = futures[future]
                try:
                    results.append((listing, future.result()))
                except Exception as exc:  # noqa: BLE001
                    log.error("enrichment crashed for %s: %s", listing.listing_id, exc)
                    env = ParcelEnvironment()
                    env.failed_enrichers.append("pipeline")
                    results.append((listing, env))

        # Restore input order so runs are reproducible.
        order = {item.listing_id: i for i, item in enumerate(listings)}
        results.sort(key=lambda pair: order.get(pair[0].listing_id, 0))
        return results
