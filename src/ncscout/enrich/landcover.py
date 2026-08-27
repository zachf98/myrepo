"""Land cover composition from NLCD via the MRLC WMS.

The WMS returns one class per query, so the parcel footprint is sampled on
concentric rings and the classes are tallied into a composition. This yields
forest cover for the timber model plus cropland, pasture, wetland and developed
fractions that other models and the report rely on.
"""

from __future__ import annotations

from collections import Counter

from ..models import DataQuality, Listing, Measurement, ParcelEnvironment
from .base import Enricher, parcel_radius_m, sample_grid

MRLC_WMS = "https://www.mrlc.gov/geoserver/mrlc_display/wms"
LAYER = "NLCD_2021_Land_Cover_L48"

NLCD_CLASSES = {
    11: "open_water",
    12: "ice_snow",
    21: "developed_open",
    22: "developed_low",
    23: "developed_medium",
    24: "developed_high",
    31: "barren",
    41: "deciduous_forest",
    42: "evergreen_forest",
    43: "mixed_forest",
    51: "dwarf_scrub",
    52: "shrub_scrub",
    71: "grassland",
    72: "sedge",
    73: "lichens",
    74: "moss",
    81: "pasture_hay",
    82: "cultivated_crops",
    90: "woody_wetlands",
    95: "herbaceous_wetlands",
}

FOREST_CLASSES = {41, 42, 43}
# Woody wetlands carry timber and habitat value even though they are not upland
# forest, so they count at a discount rather than not at all.
PARTIAL_FOREST_CLASSES = {90: 0.5}


class NlcdLandCoverEnricher(Enricher):
    name = "nlcd_landcover"

    def enrich(self, listing: Listing, env: ParcelEnvironment) -> None:
        radius = parcel_radius_m(listing.acres)
        points = sample_grid(listing.latitude, listing.longitude, radius)

        codes: list[int] = []
        for lat, lon in points:
            code = self._sample(lat, lon)
            if code is not None:
                codes.append(code)

        if not codes:
            env.failed_enrichers.append(self.name)
            return

        counts = Counter(codes)
        total = len(codes)
        env.land_cover = {
            NLCD_CLASSES.get(code, f"class_{code}"): count / total * 100.0
            for code, count in counts.most_common()
        }

        forest_count = sum(
            count for code, count in counts.items() if code in FOREST_CLASSES
        )
        forest_count += sum(
            counts.get(code, 0) * weight
            for code, weight in PARTIAL_FOREST_CLASSES.items()
        )
        env.forest_cover_pct = Measurement(
            value=forest_count / total * 100.0,
            unit="%",
            source="NLCD 2021",
            quality=DataQuality.MEASURED,
            note=f"{total} sample points across parcel footprint",
        )

    def _sample(self, lat: float, lon: float) -> int | None:
        # GetFeatureInfo needs a bbox and a pixel; a tiny bbox with the query at
        # its centre pixel resolves to the single cell containing the point.
        delta = 0.0008
        payload = self.client.get_json(
            MRLC_WMS,
            params={
                "service": "WMS",
                "version": "1.1.1",
                "request": "GetFeatureInfo",
                "layers": LAYER,
                "query_layers": LAYER,
                "srs": "EPSG:4326",
                "bbox": f"{lon - delta},{lat - delta},{lon + delta},{lat + delta}",
                "width": 101,
                "height": 101,
                "x": 50,
                "y": 50,
                "info_format": "application/json",
            },
        )
        if not payload:
            return None
        features = payload.get("features") or []
        if not features:
            return None
        index = (features[0].get("properties") or {}).get("PALETTE_INDEX")
        return int(index) if index is not None else None
