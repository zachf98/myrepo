"""Enricher interface and shared geospatial helpers."""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod

from ..http import CachedClient
from ..models import Listing, ParcelEnvironment

log = logging.getLogger(__name__)

EARTH_RADIUS_M = 6_371_000.0


class Enricher(ABC):
    """Populates part of a ParcelEnvironment from an external dataset.

    Enrichers must never raise for data problems. A failed lookup leaves the
    measurement MISSING and appends the enricher name to failed_enrichers, so
    the scoring layer can lower confidence instead of the run dying.
    """

    name: str = "base"
    requires_coordinates: bool = True

    def __init__(self, client: CachedClient) -> None:
        self.client = client

    @abstractmethod
    def enrich(self, listing: Listing, env: ParcelEnvironment) -> None:
        """Mutate ``env`` in place with whatever this dataset provides."""

    def run(self, listing: Listing, env: ParcelEnvironment) -> None:
        if self.requires_coordinates and not listing.has_coordinates:
            env.failed_enrichers.append(f"{self.name} (no coordinates)")
            return
        try:
            self.enrich(listing, env)
        except Exception as exc:  # noqa: BLE001 - isolation is the point
            log.warning(
                "enricher %s failed for %s: %s", self.name, listing.listing_id, exc
            )
            env.failed_enrichers.append(self.name)


def parcel_radius_m(acres: float | None) -> float:
    """Radius of a circle with the same area as the parcel.

    Listings rarely include a boundary polygon, so a circle centred on the
    listing point is the honest approximation for sampling area-based rasters.
    """
    if not acres or acres <= 0:
        return 200.0
    area_m2 = acres * 4046.8564224
    return math.sqrt(area_m2 / math.pi)


def sample_grid(
    lat: float, lon: float, radius_m: float, rings: int = 2, per_ring: int = 6
) -> list[tuple[float, float]]:
    """Concentric-ring sample points covering the parcel footprint.

    A grid is preferable to a single centre pixel for area statistics such as
    forest cover, and rings distribute samples more evenly over a circle than a
    square lattice does.
    """
    points = [(lat, lon)]
    if radius_m <= 0:
        return points

    for ring in range(1, rings + 1):
        r = radius_m * (ring / rings) * 0.8
        for i in range(per_ring):
            bearing = 2 * math.pi * i / per_ring
            d_lat = (r * math.cos(bearing)) / EARTH_RADIUS_M
            d_lon = (r * math.sin(bearing)) / (
                EARTH_RADIUS_M * math.cos(math.radians(lat))
            )
            points.append(
                (lat + math.degrees(d_lat), lon + math.degrees(d_lon))
            )
    return points


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = p2 - p1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
