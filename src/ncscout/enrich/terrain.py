"""Elevation and local relief from the USGS 3DEP elevation point service.

Relief is a cheap proxy for two things the other datasets miss: scenic value,
which drives recreation and cabin-site demand, and buildability. It is computed
from a small ring of elevation samples around the parcel centre.
"""

from __future__ import annotations

from ..models import DataQuality, Listing, Measurement, ParcelEnvironment
from .base import Enricher, parcel_radius_m, sample_grid

EPQS_URL = "https://epqs.nationalmap.gov/v1/json"


class ElevationEnricher(Enricher):
    name = "usgs_3dep"

    def enrich(self, listing: Listing, env: ParcelEnvironment) -> None:
        radius = max(parcel_radius_m(listing.acres), 400.0)
        # One ring of four samples plus the centre is enough for a relief
        # estimate and keeps this to five requests per parcel.
        points = sample_grid(
            listing.latitude, listing.longitude, radius, rings=1, per_ring=4
        )

        elevations: list[float] = []
        for lat, lon in points:
            value = self._sample(lat, lon)
            if value is not None:
                elevations.append(value)

        if not elevations:
            env.failed_enrichers.append(self.name)
            return

        env.elevation_m = Measurement(
            value=elevations[0],
            unit="m",
            source="USGS 3DEP",
            quality=DataQuality.MEASURED,
        )
        if len(elevations) > 1:
            env.relief_m = Measurement(
                value=max(elevations) - min(elevations),
                unit="m",
                source="USGS 3DEP",
                quality=DataQuality.MEASURED,
                note=f"range across {len(elevations)} samples",
            )

    def _sample(self, lat: float, lon: float) -> float | None:
        payload = self.client.get_json(
            EPQS_URL,
            params={
                "x": round(lon, 6),
                "y": round(lat, 6),
                "units": "Meters",
                "wkid": 4326,
                "includeDate": "false",
            },
        )
        if not payload:
            return None
        value = payload.get("value")
        try:
            elevation = float(value)
        except (TypeError, ValueError):
            return None
        # 3DEP returns a large negative sentinel outside its coverage.
        return None if elevation < -1000 else elevation
