"""Generic RESO Web API listing source.

RESO Web API is the industry-standard OData interface that most MLSs and
aggregators expose. Implementing it once covers a large number of legitimate
feeds (including many Bridge and Spark-hosted datasets) with a single adapter,
so you are not locked to one vendor.

Spec: https://www.reso.org/reso-web-api/
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from ..http import CachedClient
from ..models import Listing
from .base import ListingSource, SearchCriteria, SourceUnavailable

log = logging.getLogger(__name__)


class ResoSource(ListingSource):
    name = "reso"

    def __init__(
        self,
        client: CachedClient,
        base_url: str | None = None,
        token: str | None = None,
    ) -> None:
        self.client = client
        self.base_url = (base_url or os.environ.get("RESO_BASE_URL", "")).rstrip("/")
        self.token = token or os.environ.get("RESO_ACCESS_TOKEN")

    def is_available(self) -> bool:
        return bool(self.base_url and self.token)

    def search(self, criteria: SearchCriteria) -> list[Listing]:
        if not self.is_available():
            raise SourceUnavailable(
                "RESO_BASE_URL and RESO_ACCESS_TOKEN must both be set."
            )

        filters = [
            "StandardStatus eq 'Active'",
            f"ListPrice ge {int(criteria.min_price)}",
            f"ListPrice le {int(criteria.max_price)}",
            "(PropertyType eq 'Land' or PropertyType eq 'Farm')",
        ]
        if criteria.states:
            state_clause = " or ".join(
                f"StateOrProvince eq '{s}'" for s in criteria.states
            )
            filters.append(f"({state_clause})")

        listings: list[Listing] = []
        # OData caps vary by vendor; 200 is widely safe.
        page_size = min(200, criteria.limit)
        skip = 0

        while len(listings) < criteria.limit:
            params = {
                "$filter": " and ".join(filters),
                "$top": page_size,
                "$skip": skip,
                "$orderby": "ModificationTimestamp desc",
            }
            payload = self.client.get_json(
                f"{self.base_url}/Property",
                params=params,
                headers={"Authorization": f"Bearer {self.token}"},
                cache=False,
            )
            if not payload:
                break
            records = payload.get("value") or []
            if not records:
                break

            for record in records:
                listing = self._parse(record)
                if listing and criteria.matches(listing):
                    listings.append(listing)

            if len(records) < page_size:
                break
            skip += page_size

        return listings[: criteria.limit]

    def _parse(self, record: dict[str, Any]) -> Listing | None:
        price = record.get("ListPrice")
        listing_key = record.get("ListingKey") or record.get("ListingId")
        if not price or not listing_key:
            return None

        acres = record.get("LotSizeAcres")
        if acres is None and record.get("LotSizeSquareFeet"):
            acres = float(record["LotSizeSquareFeet"]) / 43560.0

        listed_on = None
        if record.get("OnMarketDate"):
            try:
                listed_on = datetime.fromisoformat(
                    str(record["OnMarketDate"])[:10]
                ).date()
            except ValueError:
                pass

        return Listing(
            listing_id=str(listing_key),
            source=self.name,
            price=float(price),
            acres=float(acres) if acres else None,
            address=record.get("UnparsedAddress"),
            city=record.get("City"),
            state=record.get("StateOrProvince"),
            zip_code=record.get("PostalCode"),
            latitude=record.get("Latitude"),
            longitude=record.get("Longitude"),
            property_type=record.get("PropertyType"),
            url=record.get("ListingURL"),
            listed_on=listed_on,
            description=record.get("PublicRemarks"),
            raw=record,
        )
