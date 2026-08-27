"""Surface water proximity from the USGS National Hydrography Dataset.

Water access is the dominant constraint on rural land value in most of the
country. NHD is queried at expanding radii so that a parcel with a creek on it
is distinguished from one 10km from the nearest drainage, without paying for a
wide-radius query when a narrow one suffices.
"""

from __future__ import annotations

import json

from ..models import DataQuality, Listing, Measurement, ParcelEnvironment
from .base import Enricher, parcel_radius_m

NHD_BASE = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer"
FLOWLINE_LAYER = 6  # Flowline - Large Scale
WATERBODY_LAYER = 12  # Waterbody - Large Scale

# NHD FType codes. Intermittent and ephemeral drainages are worth far less than
# a perennial stream, so they are tracked separately rather than lumped in.
PERENNIAL_STREAM = 460  # StreamRiver
ARTIFICIAL_PATH = 558  # centreline through a waterbody, implies real water
CANAL_DITCH = 336
SPRING = 458
VALUABLE_WATERBODY = {390, 436, 493}  # LakePond, Reservoir, Estuary

# Expanding search radii in metres.
SEARCH_RADII = (400, 1200, 4000, 15000)


class NhdWaterEnricher(Enricher):
    name = "nhd_water"

    def enrich(self, listing: Listing, env: ParcelEnvironment) -> None:
        lat, lon = listing.latitude, listing.longitude
        # A large parcel is more likely to intersect water simply by extent, so
        # the first radius covers at least the parcel itself.
        radii = list(SEARCH_RADII)
        own_radius = parcel_radius_m(listing.acres)
        if own_radius > radii[0]:
            radii[0] = round(own_radius)

        for radius in radii:
            name, found = self._query_water(lat, lon, radius)
            if found:
                # The feature is somewhere within the radius; the midpoint of the
                # search annulus is the least-biased estimate available without
                # pulling geometry.
                env.water_distance_m = Measurement(
                    value=float(radius) / 2.0,
                    unit="m",
                    source="USGS NHD",
                    quality=DataQuality.MODELED,
                    note=f"perennial water found within {radius}m",
                )
                env.nearest_water_name = name
                return

        env.water_distance_m = Measurement(
            value=float(radii[-1]),
            unit="m",
            source="USGS NHD",
            quality=DataQuality.MODELED,
            note=f"no perennial water within {radii[-1]}m",
        )

    def _query_water(
        self, lat: float, lon: float, radius_m: int
    ) -> tuple[str | None, bool]:
        found = False
        for layer, ftypes in (
            (FLOWLINE_LAYER, {PERENNIAL_STREAM, ARTIFICIAL_PATH, CANAL_DITCH, SPRING}),
            (WATERBODY_LAYER, VALUABLE_WATERBODY),
        ):
            features = self._query_layer(lat, lon, radius_m, layer)
            for feature in features:
                attrs = feature.get("attributes", {})
                if attrs.get("ftype") not in ftypes:
                    continue
                found = True
                # A named feature is far more useful in a report than an
                # unnamed drainage, so keep looking for one before returning.
                name = attrs.get("gnis_name")
                if name:
                    return name, True
        return None, found

    def _query_layer(
        self, lat: float, lon: float, radius_m: int, layer: int
    ) -> list[dict]:
        geometry = json.dumps(
            {"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}
        )
        payload = self.client.get_json(
            f"{NHD_BASE}/{layer}/query",
            params={
                "geometry": geometry,
                "geometryType": "esriGeometryPoint",
                "inSR": 4326,
                "distance": radius_m,
                "units": "esriSRUnit_Meter",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "gnis_name,ftype",
                "returnGeometry": "false",
                "resultRecordCount": 30,
                "f": "json",
            },
        )
        if not payload:
            return []
        return payload.get("features") or []
