"""Live checks against the public data services.

Deselected by default (`-m "not live"`). These exist because the failure mode
that matters most for this project is silent: a federal service changes a field
name or an endpoint moves, every enricher degrades to MISSING, and the scan
keeps producing confident-looking reports built on nothing. Run these when a
scan starts returning suspiciously low coverage.
"""

from __future__ import annotations

import pytest

from ncscout.enrich.climate import NasaPowerEnricher
from ncscout.enrich.geocode import Geocoder
from ncscout.enrich.hazard import FemaFloodEnricher
from ncscout.enrich.landcover import NlcdLandCoverEnricher
from ncscout.enrich.soil import SsurgoSoilEnricher
from ncscout.enrich.terrain import ElevationEnricher
from ncscout.enrich.water import NhdWaterEnricher
from ncscout.http import CachedClient
from ncscout.models import Listing, ParcelEnvironment

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def client():
    with CachedClient() as c:
        yield c


# Prime Iowa farmland: known-good values make a regression obvious.
IOWA = Listing(
    listing_id="live-iowa",
    source="test",
    price=500_000,
    acres=80.0,
    latitude=41.8,
    longitude=-93.6,
)

# Appalachian timber: steep, wet, forested; the opposite corner of the space.
WEST_VIRGINIA = Listing(
    listing_id="live-wv",
    source="test",
    price=148_000,
    acres=62.0,
    latitude=38.301,
    longitude=-80.098,
)


def test_nasa_power_returns_plausible_climate(client):
    env = ParcelEnvironment()
    NasaPowerEnricher(client).run(IOWA, env)

    assert 600 < env.precipitation_mm.value < 1400, "Iowa annual rainfall"
    assert 3.5 < env.solar_ghi.value < 5.5, "midwest irradiance"
    assert 2.0 < env.wind_ws50m.value < 9.0, "50m wind speed"
    assert 1500 < env.growing_degree_days.value < 4000, "corn belt GDD"


def test_ssurgo_returns_high_productivity_for_iowa(client):
    env = ParcelEnvironment()
    SsurgoSoilEnricher(client).run(IOWA, env)

    assert env.nccpi.value > 0.5, "Iowa mollisols should rate highly"
    assert env.water_storage_cm.value > 10, "deep prairie soils hold water"
    assert env.slope_pct.value < 12, "central Iowa is not steep"
    assert env.soil_description


def test_ssurgo_returns_low_productivity_for_steep_appalachian_ground(client):
    env = ParcelEnvironment()
    SsurgoSoilEnricher(client).run(WEST_VIRGINIA, env)

    assert env.nccpi.value < 0.4, "steep stony forest soil is not cropland"
    assert env.slope_pct.value > 20, "Appalachian side slopes"


def test_nlcd_identifies_forest_in_west_virginia(client):
    env = ParcelEnvironment()
    NlcdLandCoverEnricher(client).run(WEST_VIRGINIA, env)

    assert env.forest_cover_pct.value > 50
    assert env.land_cover


def test_nlcd_identifies_cropland_in_iowa(client):
    env = ParcelEnvironment()
    NlcdLandCoverEnricher(client).run(IOWA, env)

    assert env.forest_cover_pct.value < 40
    assert "cultivated_crops" in env.land_cover


def test_nhd_finds_water_near_an_appalachian_creek(client):
    env = ParcelEnvironment()
    NhdWaterEnricher(client).run(WEST_VIRGINIA, env)

    assert env.water_distance_m.is_usable
    assert env.water_distance_m.value < 5000


def test_fema_returns_a_zone_or_reports_unmapped(client):
    env = ParcelEnvironment()
    FemaFloodEnricher(client).run(WEST_VIRGINIA, env)

    assert env.flood_zone_source is not None
    assert "fema_flood" not in env.failed_enrichers


def test_3dep_returns_elevation_and_relief(client):
    env = ParcelEnvironment()
    ElevationEnricher(client).run(WEST_VIRGINIA, env)

    assert 500 < env.elevation_m.value < 1500, "Allegheny highlands"
    assert env.relief_m.is_usable


def test_census_geocoder_resolves_an_address(client):
    listing = Listing(
        listing_id="geo",
        source="test",
        price=1,
        address="1600 Pennsylvania Ave NW",
        city="Washington",
        state="DC",
        zip_code="20500",
    )
    assert Geocoder(client).locate(listing)
    assert 38.0 < listing.latitude < 39.5
    assert -78.0 < listing.longitude < -76.0


def test_full_enrichment_achieves_usable_coverage(client):
    """The end-to-end guard: most core measurements must actually resolve."""
    from ncscout.enrich import EnrichmentPipeline

    env = EnrichmentPipeline(client).enrich_one(WEST_VIRGINIA)
    assert env.coverage() >= 0.8, f"only {env.coverage():.0%} coverage: {env.failed_enrichers}"
