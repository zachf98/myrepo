"""Address geocoding via the US Census Bureau geocoder.

Every downstream dataset is queried by coordinate, so a listing without a
lat/lon cannot be scored. The Census geocoder is free, has no key and no
commercial-use restriction, which suits a screening tool.
"""

from __future__ import annotations

import logging

from ..http import CachedClient
from ..models import Listing

log = logging.getLogger(__name__)

CENSUS_URL = (
    "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
)


class Geocoder:
    def __init__(self, client: CachedClient) -> None:
        self.client = client

    def locate(self, listing: Listing) -> bool:
        """Fill in coordinates on the listing. Returns True if successful."""
        if listing.has_coordinates:
            return True

        address = self._one_line(listing)
        if not address:
            return False

        payload = self.client.get_json(
            CENSUS_URL,
            params={
                "address": address,
                "benchmark": "Public_AR_Current",
                "format": "json",
            },
        )
        if not payload:
            return False

        matches = (payload.get("result") or {}).get("addressMatches") or []
        if not matches:
            log.debug("no geocode match for %r", address)
            return False

        coords = matches[0].get("coordinates") or {}
        lat, lon = coords.get("y"), coords.get("x")
        if lat is None or lon is None:
            return False

        listing.latitude = float(lat)
        listing.longitude = float(lon)
        return True

    @staticmethod
    def _one_line(listing: Listing) -> str | None:
        parts = [listing.address, listing.city, listing.state, listing.zip_code]
        present = [p for p in parts if p]
        # A city/state pair alone geocodes to the city centroid, which is far too
        # imprecise for parcel-level soil and water lookups.
        if not listing.address or len(present) < 3:
            return None
        return ", ".join(present)
