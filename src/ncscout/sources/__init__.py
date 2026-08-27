"""Listing sources and the registry used by the CLI."""

from __future__ import annotations

from ..http import CachedClient
from .base import ListingSource, SearchCriteria, SourceUnavailable
from .bridge import BridgeSource
from .fixtures import FixtureSource
from .reso import ResoSource

__all__ = [
    "BridgeSource",
    "FixtureSource",
    "ListingSource",
    "ResoSource",
    "SearchCriteria",
    "SourceUnavailable",
    "build_source",
    "available_sources",
]

_REGISTRY = {
    "fixtures": FixtureSource,
    "bridge": BridgeSource,
    "reso": ResoSource,
}


def available_sources() -> list[str]:
    return sorted(_REGISTRY)


def build_source(name: str, client: CachedClient) -> ListingSource:
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise SourceUnavailable(
            f"unknown source {name!r}; available: {', '.join(available_sources())}"
        ) from None

    # Only the fixture source is self-contained; the rest need the HTTP client.
    if cls is FixtureSource:
        return FixtureSource()
    return cls(client)
