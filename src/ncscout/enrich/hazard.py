"""Flood and wildfire hazard.

Hazard is treated as a deduction against natural capital rather than a separate
concern: a productive parcel inside a regulatory floodway or a class-5 wildfire
zone carries costs and insurance problems that offset the resource base.
"""

from __future__ import annotations

import logging

from ..models import Listing, ParcelEnvironment
from .base import Enricher

log = logging.getLogger(__name__)

NFHL_URL = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
)

# Relative flammability of NLCD cover types. Shrub and evergreen fuels carry
# fire far more readily than deciduous hardwood or cultivated ground.
FUEL_WEIGHTS = {
    "shrub_scrub": 0.95,
    "dwarf_scrub": 0.85,
    "evergreen_forest": 0.90,
    "mixed_forest": 0.65,
    "deciduous_forest": 0.45,
    "grassland": 0.60,
    "sedge": 0.50,
    "pasture_hay": 0.35,
    "woody_wetlands": 0.25,
    "cultivated_crops": 0.20,
    "herbaceous_wetlands": 0.10,
    "barren": 0.05,
    "developed_open": 0.15,
    "developed_low": 0.15,
    "developed_medium": 0.10,
    "developed_high": 0.05,
    "open_water": 0.0,
    "ice_snow": 0.0,
    "lichens": 0.3,
    "moss": 0.2,
}


class FemaFloodEnricher(Enricher):
    name = "fema_flood"

    def enrich(self, listing: Listing, env: ParcelEnvironment) -> None:
        payload = self.client.get_json(
            NFHL_URL,
            params={
                "geometry": f"{listing.longitude},{listing.latitude}",
                "geometryType": "esriGeometryPoint",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "FLD_ZONE,ZONE_SUBTY",
                "returnGeometry": "false",
                "f": "json",
            },
        )
        if payload is None:
            env.failed_enrichers.append(self.name)
            return

        features = payload.get("features") or []
        if not features:
            # No NFHL polygon means the area is unmapped, which is not the same
            # as low risk and must not be scored as zone X.
            env.flood_zone = None
            env.flood_zone_source = "FEMA NFHL (unmapped)"
            return

        attrs = features[0].get("attributes") or {}
        zone = attrs.get("FLD_ZONE")
        env.flood_zone = str(zone).strip().upper() if zone else None
        env.flood_zone_source = "FEMA NFHL"


class WildfireHazardEnricher(Enricher):
    """Derives a 1-5 wildfire hazard class from the fire-behaviour triangle.

    The USFS Wildfire Hazard Potential raster would be preferable, but its
    ImageServer endpoints return 403 to unauthenticated clients, so hazard is
    instead modelled from fuel (NLCD cover), weather (aridity and temperature)
    and topography (slope) using data already fetched for other subscores. This
    costs no extra requests and is always available; it is recorded as modelled,
    never measured. Set an authenticated WHP service to override it.

    Must run after the land cover, climate and soil enrichers.
    """

    name = "wildfire_model"
    requires_coordinates = False

    WEIGHTS = {"fuel": 0.40, "aridity": 0.40, "slope": 0.20}

    def enrich(self, listing: Listing, env: ParcelEnvironment) -> None:
        fuel = self._fuel_score(env)
        aridity = self._aridity_score(env)
        slope = self._slope_score(env)

        components = {"fuel": fuel, "aridity": aridity, "slope": slope}
        available = {k: v for k, v in components.items() if v is not None}
        if not available:
            env.failed_enrichers.append(self.name)
            return

        # Renormalise over whatever is available so a missing input does not
        # silently deflate the hazard estimate.
        total_weight = sum(self.WEIGHTS[k] for k in available)
        index = sum(self.WEIGHTS[k] * v for k, v in available.items()) / total_weight
        env.wildfire_hazard_class = max(1, min(5, int(round(1 + index * 4))))

    @staticmethod
    def _fuel_score(env: ParcelEnvironment) -> float | None:
        if not env.land_cover:
            return None
        # Cover-weighted mean flammability across the parcel.
        return sum(
            FUEL_WEIGHTS.get(cover, 0.3) * pct / 100.0
            for cover, pct in env.land_cover.items()
        )

    @staticmethod
    def _aridity_score(env: ParcelEnvironment) -> float | None:
        precip = env.precipitation_mm
        if not precip.is_usable:
            return None
        # 200mm/yr or less is maximally fire-prone; 1200mm/yr or more suppresses
        # fire spread in all but drought years.
        score = (1200.0 - precip.value) / 1000.0
        temp = env.mean_temp_c
        if temp.is_usable and temp.value > 15.0:
            # Hotter climates dry fuels faster within the same rainfall band.
            score += min(0.15, (temp.value - 15.0) * 0.02)
        return max(0.0, min(1.0, score))

    @staticmethod
    def _slope_score(env: ParcelEnvironment) -> float | None:
        slope = env.slope_pct
        if not slope.is_usable:
            return None
        # Fire spreads uphill; 50% slope is treated as the practical maximum.
        return max(0.0, min(1.0, slope.value / 50.0))
