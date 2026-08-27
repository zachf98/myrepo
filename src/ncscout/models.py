"""Domain models shared across sourcing, enrichment, scoring and reporting."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Listing(BaseModel):
    """A land listing as returned by a source adapter, before enrichment."""

    listing_id: str
    source: str
    price: float
    acres: float | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    property_type: str | None = None
    url: str | None = None
    listed_on: date | None = None
    description: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @field_validator("state")
    @classmethod
    def _upper_state(cls, v: str | None) -> str | None:
        return v.upper() if v else v

    @property
    def price_per_acre(self) -> float | None:
        if not self.acres or self.acres <= 0:
            return None
        return self.price / self.acres

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class DataQuality(str, Enum):
    """How much of a measurement came from a real observation versus a fallback.

    Every downstream number carries this so a high score built on regional
    defaults is never mistaken for one built on a parcel-level measurement.
    """

    MEASURED = "measured"
    MODELED = "modeled"
    REGIONAL_DEFAULT = "regional_default"
    MISSING = "missing"


class Measurement(BaseModel):
    """A single physical measurement with its provenance."""

    value: float | None = None
    unit: str = ""
    source: str = ""
    quality: DataQuality = DataQuality.MISSING
    note: str | None = None

    @property
    def is_usable(self) -> bool:
        return self.value is not None and self.quality is not DataQuality.MISSING


class ParcelEnvironment(BaseModel):
    """Physical resource measurements for one parcel."""

    precipitation_mm: Measurement = Measurement(unit="mm/yr")
    mean_temp_c: Measurement = Measurement(unit="C")
    growing_degree_days: Measurement = Measurement(unit="GDD base 10C")
    solar_ghi: Measurement = Measurement(unit="kWh/m2/day")
    wind_ws50m: Measurement = Measurement(unit="m/s")
    nccpi: Measurement = Measurement(unit="index 0-1")
    water_storage_cm: Measurement = Measurement(unit="cm")
    slope_pct: Measurement = Measurement(unit="%")
    forest_cover_pct: Measurement = Measurement(unit="%")
    water_distance_m: Measurement = Measurement(unit="m")
    flood_zone: str | None = None
    flood_zone_source: str | None = None
    wildfire_hazard_class: int | None = None
    elevation_m: Measurement = Measurement(unit="m")
    town_distance_km: Measurement = Measurement(unit="km")
    grid_distance_km: Measurement = Measurement(unit="km")

    # SSURGO observed flooding frequency. Covers rural land FEMA never mapped.
    soil_flood_frequency: str | None = None

    # Descriptive context carried into reports so a score can be explained.
    soil_description: str | None = None
    land_cover: dict[str, float] = Field(default_factory=dict)
    nearest_water_name: str | None = None
    relief_m: Measurement = Measurement(unit="m")

    # Names of enrichers that failed, so reports can state what is unknown.
    failed_enrichers: list[str] = Field(default_factory=list)

    def coverage(self) -> float:
        """Fraction of the core measurements backed by real data."""
        core = [
            self.precipitation_mm,
            self.solar_ghi,
            self.wind_ws50m,
            self.nccpi,
            self.slope_pct,
            self.forest_cover_pct,
        ]
        usable = sum(
            1
            for m in core
            if m.is_usable and m.quality is not DataQuality.REGIONAL_DEFAULT
        )
        return usable / len(core)


class SubScore(BaseModel):
    """One component of the natural capital composite."""

    name: str
    score: float
    weight: float
    drivers: list[str] = Field(default_factory=list)
    confidence: float = 1.0

    @property
    def weighted(self) -> float:
        return self.score * self.weight


class NaturalCapitalScore(BaseModel):
    total: float
    subscores: list[SubScore] = Field(default_factory=list)
    confidence: float = 1.0

    def by_name(self, name: str) -> SubScore | None:
        return next((s for s in self.subscores if s.name == name), None)


class RevenueStream(BaseModel):
    """A monetisation path with its physical justification."""

    name: str
    annual_gross: float
    annual_net: float
    rationale: str
    # Streams that depend on a third party (a developer, a registry) are
    # probability-weighted rather than assumed.
    probability: float = 1.0
    speculative: bool = False


class BusinessCase(BaseModel):
    streams: list[RevenueStream] = Field(default_factory=list)
    annual_gross_revenue: float = 0.0
    annual_operating_expense: float = 0.0
    annual_carrying_cost: float = 0.0
    net_operating_income: float = 0.0
    cap_rate: float = 0.0
    payback_years: float | None = None
    npv: float = 0.0
    irr: float | None = None
    score: float = 0.0

    @property
    def contracted_streams(self) -> list[RevenueStream]:
        return [s for s in self.streams if not s.speculative]


class ScoredOpportunity(BaseModel):
    listing: Listing
    environment: ParcelEnvironment
    natural_capital: NaturalCapitalScore
    business: BusinessCase
    price_efficiency_score: float
    composite_score: float
    rank: int | None = None
    flags: list[str] = Field(default_factory=list)


class ScanReport(BaseModel):
    generated_at: datetime
    listings_considered: int
    listings_enriched: int
    opportunities: list[ScoredOpportunity]
    sources_used: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
