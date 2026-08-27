"""Soil productivity from USDA NRCS SSURGO via Soil Data Access.

Soil is the single best predictor of what land can produce, and SSURGO is the
authoritative national survey. Soil Data Access accepts raw T-SQL, so all three
measurements this project needs are pulled in one query: individual queries were
measured at up to 50s each, which does not scale across a daily scan.

Docs: https://sdmdataaccess.sc.egov.usda.gov/
"""

from __future__ import annotations

from typing import Any

from ..models import DataQuality, Listing, Measurement, ParcelEnvironment
from .base import Enricher

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"

NCCPI_RULE = "NCCPI - National Commodity Crop Productivity Index (Ver 3.0)"

# One query returns map-unit aggregates joined to component-level NCCPI and
# slope. ruledepth = 0 selects the overall index rather than its submodels.
QUERY_TEMPLATE = """
SELECT
    mu.mukey,
    mag.muname,
    mag.aws0100wta,
    mag.slopegraddcp,
    mag.drclassdcd,
    co.comppct_r,
    co.slope_r,
    ci.interphr
FROM mapunit mu
LEFT JOIN muaggatt mag ON mag.mukey = mu.mukey
LEFT JOIN component co ON co.mukey = mu.mukey
LEFT JOIN cointerp ci
    ON ci.cokey = co.cokey
   AND ci.mrulename = '{rule}'
   AND ci.ruledepth = 0
WHERE mu.mukey IN (
    SELECT mukey
    FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('point({lon} {lat})')
)
"""


def _to_float(value: Any) -> float | None:
    if value in (None, "", "NULL"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class SsurgoSoilEnricher(Enricher):
    name = "ssurgo_soil"

    def enrich(self, listing: Listing, env: ParcelEnvironment) -> None:
        query = QUERY_TEMPLATE.format(
            rule=NCCPI_RULE,
            lon=round(listing.longitude, 5),
            lat=round(listing.latitude, 5),
        )
        payload = self.client.post_json(
            SDA_URL,
            json_body={"format": "JSON+COLUMNNAME", "query": query},
        )
        if not payload or not payload.get("Table"):
            env.failed_enrichers.append(self.name)
            return

        table = payload["Table"]
        if len(table) < 2:
            # A valid response with no rows means the point is outside the
            # survey area, which is common for open water and some federal land.
            env.failed_enrichers.append(f"{self.name} (no survey coverage)")
            return

        columns = table[0]
        rows = [dict(zip(columns, row, strict=False)) for row in table[1:]]
        source = "USDA NRCS SSURGO"

        env.nccpi = self._weighted_nccpi(rows, source)
        env.slope_pct = self._slope(rows, source)

        storage = _to_float(rows[0].get("aws0100wta"))
        if storage is not None:
            env.water_storage_cm = Measurement(
                value=storage,
                unit="cm",
                source=source,
                quality=DataQuality.MEASURED,
                note="available water storage, 0-100cm",
            )

        muname = rows[0].get("muname")
        drainage = rows[0].get("drclassdcd")
        if muname:
            env.soil_description = str(muname) + (f"; {drainage}" if drainage else "")

    def _weighted_nccpi(self, rows: list[dict[str, Any]], source: str) -> Measurement:
        """Component-percentage weighted NCCPI for the map unit.

        A map unit is a mixture of soil components; weighting by comppct_r gives
        the productivity a buyer would actually experience across the parcel.
        """
        pairs = [
            (_to_float(r.get("comppct_r")), _to_float(r.get("interphr")))
            for r in rows
        ]
        usable = [(pct, val) for pct, val in pairs if pct and val is not None]
        if not usable:
            # No NCCPI rating usually means non-cropland: forest, rangeland or
            # rock outcrop. That is genuinely zero commodity-crop capability
            # rather than unknown, so it is recorded as measured.
            return Measurement(
                value=0.0,
                unit="index 0-1",
                source=source,
                quality=DataQuality.MEASURED,
                note="no NCCPI rating; non-cropland soil",
            )

        total_pct = sum(pct for pct, _ in usable)
        weighted = sum(pct * val for pct, val in usable) / total_pct
        return Measurement(
            value=weighted,
            unit="index 0-1",
            source=source,
            quality=DataQuality.MEASURED,
            note=f"component-weighted over {len(usable)} components",
        )

    def _slope(self, rows: list[dict[str, Any]], source: str) -> Measurement:
        """Prefer component-weighted slope, fall back to the map-unit dominant."""
        pairs = [
            (_to_float(r.get("comppct_r")), _to_float(r.get("slope_r")))
            for r in rows
        ]
        usable = [(pct, val) for pct, val in pairs if pct and val is not None]
        if usable:
            total_pct = sum(pct for pct, _ in usable)
            weighted = sum(pct * val for pct, val in usable) / total_pct
            return Measurement(
                value=weighted,
                unit="%",
                source=source,
                quality=DataQuality.MEASURED,
            )

        dominant = _to_float(rows[0].get("slopegraddcp"))
        if dominant is not None:
            return Measurement(
                value=dominant,
                unit="%",
                source=source,
                quality=DataQuality.MEASURED,
                note="dominant condition",
            )
        return Measurement(unit="%")
