"""Zillow Group / Bridge Interactive listing source.

This is the sanctioned route to Zillow-affiliated data. Bridge Interactive is
owned by Zillow Group and brokers MLS-sourced listing feeds under a per-dataset
agreement; you apply for access, an MLS approves it, and you receive a server
token scoped to that dataset.

Why not scrape zillow.com: its robots.txt explicitly disallows /homes/ and
/api/ (the search and listing endpoints), and the Terms of Use prohibit
automated data extraction. A scraper would be blocked in short order and would
put the operator at legal risk, so this project does not ship one.

Docs: https://bridgedataoutput.com/docs/platform/
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any

from ..http import CachedClient
from ..models import Listing
from .base import ListingSource, SearchCriteria, SourceUnavailable

log = logging.getLogger(__name__)

BRIDGE_BASE = "https://api.bridgedataoutput.com/api/v2"

# RESO property types that represent land rather than a dwelling.
LAND_PROPERTY_TYPES = ("Land", "Farm")


class BridgeSource(ListingSource):
    name = "bridge"

    def __init__(
        self,
        client: CachedClient,
        token: str | None = None,
        dataset: str | None = None,
    ) -> None:
        self.client = client
        self.token = token or os.environ.get("BRIDGE_API_TOKEN")
        # Bridge scopes every request to a dataset, e.g. an MLS abbreviation.
        self.dataset = dataset or os.environ.get("BRIDGE_DATASET", "test")

    def is_available(self) -> bool:
        return bool(self.token)

    def search(self, criteria: SearchCriteria) -> list[Listing]:
        if not self.token:
            raise SourceUnavailable(
                "BRIDGE_API_TOKEN is not set. Apply for a Bridge Interactive "
                "dataset at https://bridgedataoutput.com and set the token, or "
                "run with --source fixtures to exercise the pipeline."
            )

        url = f"{BRIDGE_BASE}/{self.dataset}/listings"
        listings: list[Listing] = []
        # Bridge caps page size at 200.
        page_size = min(200, criteria.limit)
        offset = 0

        while len(listings) < criteria.limit:
            params: dict[str, Any] = {
                "access_token": self.token,
                "limit": page_size,
                "offset": offset,
                "PropertyType.in": ",".join(LAND_PROPERTY_TYPES),
                "StandardStatus": "Active",
                "ListPrice.gte": int(criteria.min_price),
                "ListPrice.lte": int(criteria.max_price),
                "sortBy": "ModificationTimestamp",
                "order": "desc",
            }
            if criteria.states:
                params["StateOrProvince.in"] = ",".join(criteria.states)

            payload = self.client.get_json(url, params=params, cache=False)
            if not payload:
                log.warning("Bridge returned no payload at offset %s", offset)
                break
            if not payload.get("success", True):
                bundle = payload.get("bundle", {})
                raise SourceUnavailable(
                    f"Bridge API error: {bundle.get('name')}: {bundle.get('message')}"
                )

            bundle = payload.get("bundle") or []
            if not bundle:
                break

            for record in bundle:
                listing = self._parse(record)
                if listing and criteria.matches(listing):
                    listings.append(listing)

            if len(bundle) < page_size:
                break
            offset += page_size

        return listings[: criteria.limit]

    def _parse(self, record: dict[str, Any]) -> Listing | None:
        price = record.get("ListPrice")
        if not price:
            return None

        acres = record.get("LotSizeAcres")
        if acres is None:
            sqft = record.get("LotSizeSquareFeet")
            if sqft:
                acres = float(sqft) / 43560.0

        listed_on: date | None = None
        raw_date = record.get("ListingContractDate") or record.get("OnMarketDate")
        if raw_date:
            try:
                listed_on = datetime.fromisoformat(str(raw_date)[:10]).date()
            except ValueError:
                listed_on = None

        return Listing(
            listing_id=str(record.get("ListingId") or record.get("ListingKey")),
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
