"""Listing source interface.

Sourcing is deliberately separated from enrichment and scoring: the scoring
engine is the durable asset here, and it works on any listing that carries a
price, an acreage and a location. Swapping listing providers should never
require touching the scoring code.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import Listing

log = logging.getLogger(__name__)


class SourceUnavailable(RuntimeError):
    """Raised when a source cannot run, typically for missing credentials."""


@dataclass
class SearchCriteria:
    max_price: float
    min_price: float = 0.0
    min_acres: float = 0.0
    max_acres: float = 1e9
    property_types: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    limit: int = 500

    def matches(self, listing: Listing) -> bool:
        """Post-filter, since provider-side filters vary in fidelity."""
        if not (self.min_price <= listing.price <= self.max_price):
            return False
        if listing.acres is not None:
            if not (self.min_acres <= listing.acres <= self.max_acres):
                return False
        if self.states and (listing.state or "") not in self.states:
            return False
        if self.property_types and listing.property_type:
            # Providers spell these inconsistently ("Unimproved Land" vs "Land"),
            # so match on substring in either direction rather than equality.
            wanted = [t.casefold() for t in self.property_types]
            actual = listing.property_type.casefold()
            if not any(w in actual or actual in w for w in wanted):
                return False
        return True


class ListingSource(ABC):
    """A provider of land listings."""

    name: str = "base"
    # Set False for sources that require the operator to supply credentials.
    always_available: bool = False

    @abstractmethod
    def search(self, criteria: SearchCriteria) -> list[Listing]:
        """Return listings matching the criteria.

        Implementations should raise SourceUnavailable for configuration
        problems and return an empty list for a legitimately empty result.
        """

    def is_available(self) -> bool:
        return self.always_available
