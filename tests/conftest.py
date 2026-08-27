"""Shared fixtures."""

from __future__ import annotations

import pytest

from ncscout.models import (
    DataQuality,
    Listing,
    Measurement,
    ParcelEnvironment,
)


def measured(value: float, unit: str = "") -> Measurement:
    return Measurement(
        value=value, unit=unit, source="test", quality=DataQuality.MEASURED
    )


def modeled(value: float, unit: str = "") -> Measurement:
    return Measurement(
        value=value, unit=unit, source="test", quality=DataQuality.MODELED
    )


@pytest.fixture
def listing() -> Listing:
    return Listing(
        listing_id="TEST-1",
        source="test",
        price=150_000,
        acres=100.0,
        city="Testville",
        state="AR",
        latitude=34.0,
        longitude=-93.0,
    )


@pytest.fixture
def rich_env() -> ParcelEnvironment:
    """A high-quality parcel: wet, fertile, flat, forested, low hazard."""
    return ParcelEnvironment(
        precipitation_mm=modeled(1300, "mm/yr"),
        mean_temp_c=modeled(16, "C"),
        growing_degree_days=modeled(2900, "GDD base 10C"),
        solar_ghi=modeled(4.6, "kWh/m2/day"),
        wind_ws50m=modeled(4.4, "m/s"),
        nccpi=measured(0.80, "index 0-1"),
        water_storage_cm=measured(20.0, "cm"),
        slope_pct=measured(2.0, "%"),
        forest_cover_pct=measured(60.0, "%"),
        water_distance_m=modeled(230, "m"),
        elevation_m=measured(150, "m"),
        relief_m=measured(30, "m"),
        flood_zone="X",
        flood_zone_source="FEMA NFHL",
        wildfire_hazard_class=2,
        land_cover={
            "deciduous_forest": 40.0,
            "evergreen_forest": 20.0,
            "pasture_hay": 25.0,
            "cultivated_crops": 15.0,
        },
    )


@pytest.fixture
def poor_env() -> ParcelEnvironment:
    """A marginal parcel: arid, infertile, steep, no cover, high hazard."""
    return ParcelEnvironment(
        precipitation_mm=modeled(210, "mm/yr"),
        mean_temp_c=modeled(12, "C"),
        growing_degree_days=modeled(900, "GDD base 10C"),
        solar_ghi=modeled(5.6, "kWh/m2/day"),
        wind_ws50m=modeled(4.0, "m/s"),
        nccpi=measured(0.02, "index 0-1"),
        water_storage_cm=measured(1.5, "cm"),
        slope_pct=measured(38.0, "%"),
        forest_cover_pct=measured(0.0, "%"),
        water_distance_m=modeled(15000, "m"),
        flood_zone="D",
        flood_zone_source="FEMA NFHL",
        wildfire_hazard_class=4,
        land_cover={"shrub_scrub": 90.0, "barren": 10.0},
    )


@pytest.fixture
def empty_env() -> ParcelEnvironment:
    """Nothing resolved: every enricher failed."""
    return ParcelEnvironment(
        failed_enrichers=["nasa_power", "ssurgo_soil", "nlcd_landcover"]
    )
