"""Fixture listing source.

Backed by synthetic listings at real coordinates. This exists so the enrichment
and scoring stack can be run, tested and demonstrated without a licensed
listing feed, and so CI has a deterministic input.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import Listing
from .base import ListingSource, SearchCriteria

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[3] / "data" / "fixtures" / "listings_sample.json"
)


class FixtureSource(ListingSource):
    name = "fixtures"
    always_available = True

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or DEFAULT_FIXTURE)

    def search(self, criteria: SearchCriteria) -> list[Listing]:
        with self.path.open() as fh:
            payload = json.load(fh)

        listings = []
        for record in payload.get("listings", []):
            listing = Listing(source=self.name, **record)
            if criteria.matches(listing):
                listings.append(listing)
        return listings[: criteria.limit]
