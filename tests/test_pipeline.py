"""Sources, composite ranking, pipeline wiring and report rendering.

External HTTP is stubbed so these run offline and deterministically.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from ncscout.enrich import EnrichmentPipeline
from ncscout.enrich.hazard import WildfireHazardEnricher
from ncscout.models import (
    BusinessCase,
    DataQuality,
    Listing,
    Measurement,
    NaturalCapitalScore,
    ParcelEnvironment,
    ScanReport,
)
from ncscout.pipeline import ScanPipeline, opportunities_to_rows
from ncscout.report import render_csv, render_html, render_json, render_markdown
from ncscout.scoring import BusinessModeler, CompositeScorer, NaturalCapitalScorer
from ncscout.sources import FixtureSource, SearchCriteria
from ncscout.sources.base import SourceUnavailable
from ncscout.sources.bridge import BridgeSource


class StubClient:
    """Stands in for CachedClient; returns nothing so enrichers degrade."""

    def __init__(self) -> None:
        self.stats = {"hits": 0, "misses": 0, "errors": 0}

    def get_json(self, *args, **kwargs):
        return None

    def post_json(self, *args, **kwargs):
        return None

    def request_json(self, *args, **kwargs):
        return None


class TestFixtureSource:
    def test_loads_and_respects_price_ceiling(self):
        listings = FixtureSource().search(
            SearchCriteria(max_price=100_000, min_price=0)
        )
        assert listings
        assert all(item.price <= 100_000 for item in listings)

    def test_respects_acreage_and_state_filters(self):
        listings = FixtureSource().search(
            SearchCriteria(max_price=250_000, min_acres=100, states=("MI", "WI"))
        )
        assert listings
        assert all(item.state in ("MI", "WI") for item in listings)
        assert all(item.acres >= 100 for item in listings)

    def test_every_fixture_has_coordinates(self):
        """Enrichment is coordinate-driven, so fixtures must be locatable."""
        listings = FixtureSource().search(SearchCriteria(max_price=10**9))
        assert listings
        assert all(item.has_coordinates for item in listings)

    def test_respects_the_limit(self):
        listings = FixtureSource().search(
            SearchCriteria(max_price=10**9, limit=3)
        )
        assert len(listings) == 3


class TestListingModel:
    def test_price_per_acre(self):
        listing = Listing(listing_id="a", source="t", price=100_000, acres=50)
        assert listing.price_per_acre == 2000

    def test_price_per_acre_is_none_without_acreage(self):
        assert Listing(listing_id="a", source="t", price=1).price_per_acre is None

    def test_zero_acres_does_not_divide_by_zero(self):
        listing = Listing(listing_id="a", source="t", price=100, acres=0)
        assert listing.price_per_acre is None

    def test_state_is_normalised_to_uppercase(self):
        listing = Listing(listing_id="a", source="t", price=1, state="ar")
        assert listing.state == "AR"


class TestBridgeSource:
    def test_reports_unavailable_without_a_token(self, monkeypatch):
        monkeypatch.delenv("BRIDGE_API_TOKEN", raising=False)
        source = BridgeSource(StubClient())
        assert not source.is_available()
        with pytest.raises(SourceUnavailable, match="BRIDGE_API_TOKEN"):
            source.search(SearchCriteria(max_price=250_000))

    def test_parses_a_reso_style_record(self):
        source = BridgeSource(StubClient(), token="t")
        listing = source._parse(
            {
                "ListingId": "X1",
                "ListPrice": 120000,
                "LotSizeAcres": 40,
                "City": "Somewhere",
                "StateOrProvince": "TN",
                "Latitude": 35.1,
                "Longitude": -89.0,
                "PropertyType": "Land",
                "ListingContractDate": "2026-03-04",
            }
        )
        assert listing.price == 120000
        assert listing.acres == 40
        assert listing.listed_on.isoformat() == "2026-03-04"

    def test_converts_square_feet_when_acres_are_absent(self):
        source = BridgeSource(StubClient(), token="t")
        listing = source._parse(
            {"ListingId": "X", "ListPrice": 1000, "LotSizeSquareFeet": 43560}
        )
        assert listing.acres == pytest.approx(1.0)

    def test_skips_records_without_a_price(self):
        source = BridgeSource(StubClient(), token="t")
        assert source._parse({"ListingId": "X"}) is None

    def test_tolerates_a_malformed_date(self):
        source = BridgeSource(StubClient(), token="t")
        listing = source._parse(
            {"ListingId": "X", "ListPrice": 1000, "OnMarketDate": "not-a-date"}
        )
        assert listing.listed_on is None


class TestEnrichmentResilience:
    def test_total_api_failure_does_not_raise(self, listing):
        env = EnrichmentPipeline(StubClient()).enrich_one(listing)
        assert env.failed_enrichers
        assert env.coverage() == 0.0

    def test_scoring_survives_a_fully_failed_enrichment(self, listing):
        env = EnrichmentPipeline(StubClient()).enrich_one(listing)
        nc = NaturalCapitalScorer().score(env)
        business = BusinessModeler().model(listing, env)
        ranked = CompositeScorer().rank([(listing, env, nc, business)])
        assert ranked[0].composite_score >= 0
        assert any("missing data" in f for f in ranked[0].flags)

    def test_listing_without_coordinates_is_flagged_not_fatal(self):
        listing = Listing(listing_id="n", source="t", price=1000, acres=10)
        env = EnrichmentPipeline(StubClient()).enrich_one(listing)
        assert "geocode" in env.failed_enrichers


class TestWildfireModel:
    def test_arid_shrubland_scores_higher_than_wet_hardwood(self):
        enricher = WildfireHazardEnricher(StubClient())

        def classify(cover: dict, precip: float, slope: float) -> int:
            env = ParcelEnvironment(
                land_cover=cover,
                precipitation_mm=Measurement(
                    value=precip, source="t", quality=DataQuality.MODELED
                ),
                slope_pct=Measurement(
                    value=slope, source="t", quality=DataQuality.MEASURED
                ),
            )
            enricher.enrich(Listing(listing_id="a", source="t", price=1), env)
            return env.wildfire_hazard_class

        assert classify({"shrub_scrub": 100.0}, 220, 35) > classify(
            {"deciduous_forest": 100.0}, 1300, 5
        )

    def test_class_is_always_within_one_to_five(self):
        enricher = WildfireHazardEnricher(StubClient())
        for cover, precip, slope in (
            ({"shrub_scrub": 100.0}, 50, 60),
            ({"open_water": 100.0}, 3000, 0),
        ):
            env = ParcelEnvironment(
                land_cover=cover,
                precipitation_mm=Measurement(
                    value=precip, source="t", quality=DataQuality.MODELED
                ),
                slope_pct=Measurement(
                    value=slope, source="t", quality=DataQuality.MEASURED
                ),
            )
            enricher.enrich(Listing(listing_id="a", source="t", price=1), env)
            assert 1 <= env.wildfire_hazard_class <= 5

    def test_no_inputs_records_a_failure_rather_than_guessing(self):
        enricher = WildfireHazardEnricher(StubClient())
        env = ParcelEnvironment()
        enricher.enrich(Listing(listing_id="a", source="t", price=1), env)
        assert env.wildfire_hazard_class is None
        assert "wildfire_model" in env.failed_enrichers


class TestCompositeRanking:
    def _score(self, listing: Listing, env: ParcelEnvironment):
        nc = NaturalCapitalScorer().score(env)
        return listing, env, nc, BusinessModeler().model(listing, env)

    def test_ranks_descending_and_assigns_ranks(self, rich_env, poor_env):
        good = Listing(
            listing_id="good", source="t", price=100_000, acres=100,
            latitude=34.0, longitude=-93.0,
        )
        bad = Listing(
            listing_id="bad", source="t", price=240_000, acres=100,
            latitude=38.0, longitude=-114.0,
        )
        ranked = CompositeScorer().rank(
            [self._score(bad, poor_env), self._score(good, rich_env)]
        )
        assert [o.listing.listing_id for o in ranked] == ["good", "bad"]
        assert [o.rank for o in ranked] == [1, 2]
        assert ranked[0].composite_score >= ranked[1].composite_score

    def test_empty_input_returns_empty(self):
        assert CompositeScorer().rank([]) == []

    def test_cheaper_land_scores_better_on_price_efficiency(self, rich_env):
        cheap = Listing(
            listing_id="cheap", source="t", price=50_000, acres=100,
            latitude=34.0, longitude=-93.0,
        )
        pricey = Listing(
            listing_id="pricey", source="t", price=240_000, acres=100,
            latitude=34.0, longitude=-93.0,
        )
        ranked = CompositeScorer().rank(
            [self._score(cheap, rich_env), self._score(pricey, rich_env)]
        )
        by_id = {o.listing.listing_id: o for o in ranked}
        assert (
            by_id["cheap"].price_efficiency_score
            > by_id["pricey"].price_efficiency_score
        )

    def test_confidence_damping_penalises_thin_data(self, rich_env):
        """Identical listings should rank behind when the data is thinner."""
        listing = Listing(
            listing_id="a", source="t", price=100_000, acres=100,
            latitude=34.0, longitude=-93.0,
        )
        thin = ParcelEnvironment(
            nccpi=rich_env.nccpi,
            water_storage_cm=rich_env.water_storage_cm,
            slope_pct=rich_env.slope_pct,
        )
        full = CompositeScorer().rank([self._score(listing, rich_env)])[0]
        sparse = CompositeScorer().rank([self._score(listing, thin)])[0]
        assert full.natural_capital.confidence > sparse.natural_capital.confidence

    def test_flags_surface_real_risks(self):
        flooded = ParcelEnvironment(
            flood_zone="AE",
            flood_zone_source="FEMA NFHL",
            slope_pct=Measurement(
                value=40, source="t", quality=DataQuality.MEASURED
            ),
            precipitation_mm=Measurement(
                value=150, source="t", quality=DataQuality.MODELED
            ),
        )
        listing = Listing(
            listing_id="a", source="t", price=100_000, acres=100,
            latitude=30.0, longitude=-90.0,
        )
        flags = CompositeScorer().rank([self._score(listing, flooded)])[0].flags
        text = " ".join(flags)
        assert "flood hazard area" in text
        assert "steep" in text
        assert "arid" in text


class TestScanPipeline:
    def test_end_to_end_with_stubbed_http(self):
        pipeline = ScanPipeline(StubClient(), [FixtureSource()], prescreen_keep=5)
        report = pipeline.run(top_n=3, limit=10)
        assert report.listings_considered > 0
        assert len(report.opportunities) <= 3
        assert "fixtures" in report.sources_used

    def test_unavailable_source_becomes_a_warning(self, monkeypatch):
        monkeypatch.delenv("BRIDGE_API_TOKEN", raising=False)
        client = StubClient()
        pipeline = ScanPipeline(client, [BridgeSource(client), FixtureSource()])
        report = pipeline.run(top_n=3, limit=5)
        assert any("bridge" in w for w in report.warnings)
        # The scan still completes on the remaining source.
        assert report.opportunities

    def test_no_sources_yields_an_empty_report_not_a_crash(self):
        report = ScanPipeline(StubClient(), []).run(top_n=10)
        assert report.opportunities == []
        assert report.listings_considered == 0
        assert any("no listings" in w for w in report.warnings)

    def test_prescreen_reduces_the_enrichment_set(self):
        pipeline = ScanPipeline(StubClient(), [FixtureSource()], prescreen_keep=4)
        report = pipeline.run(top_n=10, limit=100)
        assert report.listings_enriched <= 4
        assert any("prescreened" in w for w in report.warnings)


@pytest.fixture
def sample_report() -> ScanReport:
    pipeline = ScanPipeline(StubClient(), [FixtureSource()], prescreen_keep=5)
    return pipeline.run(top_n=5, limit=10)


class TestReports:
    def test_markdown_includes_the_headline_facts(self, sample_report):
        text = render_markdown(sample_report)
        assert "# Land Opportunity Scan" in text
        assert "## Summary" in text
        assert "Method and caveats" in text
        # The caveats must state that revenue figures are modelled.
        assert "modelled, not quoted" in text

    def test_markdown_table_rows_are_well_formed(self, sample_report):
        lines = render_markdown(sample_report).splitlines()
        start = lines.index("| # | Location | Price | Acres | $/acre | Score "
                            "| Nat cap | Cap rate | IRR |")
        header_cols = lines[start].count("|")
        for row in lines[start + 2 :]:
            if not row.startswith("|"):
                break
            assert row.count("|") == header_cols

    def test_html_renders_and_escapes(self, sample_report):
        html = render_html(sample_report)
        assert html.startswith("<!DOCTYPE html>")
        assert "Land Opportunity Scan" in html
        assert "<script>" not in html

    def test_json_round_trips(self, sample_report):
        payload = json.loads(render_json(sample_report))
        assert "opportunities" in payload
        assert payload["listings_considered"] > 0

    def test_csv_has_a_row_per_opportunity(self, sample_report):
        csv_text = render_csv(sample_report)
        rows = [r for r in csv_text.strip().splitlines() if r]
        assert len(rows) == len(sample_report.opportunities) + 1

    def test_empty_report_renders_without_error(self):
        empty = ScanReport(
            generated_at=datetime.now(UTC),
            listings_considered=0,
            listings_enriched=0,
            opportunities=[],
        )
        assert "No qualifying opportunities" in render_markdown(empty)
        assert render_html(empty).startswith("<!DOCTYPE html>")
        assert render_csv(empty) == ""

    def test_rows_export_expected_columns(self, sample_report):
        rows = opportunities_to_rows(sample_report.opportunities)
        if rows:
            assert {"rank", "price", "cap_rate", "natural_capital"} <= set(rows[0])


def test_models_accept_partial_data():
    """Report rendering must not require every field to be populated."""
    nc = NaturalCapitalScore(total=50.0)
    assert nc.by_name("water") is None
    assert BusinessCase().contracted_streams == []


class TestPropertyTypeFiltering:
    def test_matches_across_inconsistent_provider_spellings(self):
        criteria = SearchCriteria(
            max_price=10**9, property_types=("Land", "Farm", "Ranch")
        )
        for spelling in ("Land", "Unimproved Land", "FARM", "Ranch"):
            listing = Listing(
                listing_id="a", source="t", price=1000, property_type=spelling
            )
            assert criteria.matches(listing), spelling

    def test_rejects_dwellings(self):
        criteria = SearchCriteria(max_price=10**9, property_types=("Land", "Farm"))
        listing = Listing(
            listing_id="a", source="t", price=1000, property_type="Residential"
        )
        assert not criteria.matches(listing)

    def test_absent_property_type_is_not_filtered_out(self):
        """A missing field should not silently drop an otherwise good listing."""
        criteria = SearchCriteria(max_price=10**9, property_types=("Land",))
        assert criteria.matches(Listing(listing_id="a", source="t", price=1000))

    def test_no_configured_types_means_no_filtering(self):
        criteria = SearchCriteria(max_price=10**9)
        listing = Listing(
            listing_id="a", source="t", price=1000, property_type="Residential"
        )
        assert criteria.matches(listing)


class TestPrescreenDeterminism:
    def test_survivor_set_is_reproducible_across_runs(self):
        """Parallel prescreening must not make the shortlist order-dependent."""
        runs = []
        for _ in range(3):
            pipeline = ScanPipeline(
                StubClient(), [FixtureSource()], prescreen_keep=6
            )
            report = pipeline.run(top_n=6, limit=100)
            runs.append([o.listing.listing_id for o in report.opportunities])
        assert runs[0] == runs[1] == runs[2]

    def test_prescreen_is_skipped_when_the_cohort_is_small(self):
        pipeline = ScanPipeline(StubClient(), [FixtureSource()], prescreen_keep=100)
        report = pipeline.run(top_n=10, limit=100)
        assert not any("prescreened" in w for w in report.warnings)


class TestReportDate:
    """The date identifies the report; these are read one per day."""

    def test_html_shows_the_date_prominently(self, sample_report):
        html = render_html(sample_report)
        assert '<div class="date">' in html
        # Spelled out, not just the ISO stamp buried in the title.
        assert sample_report.generated_at.strftime("%B") in html
        assert str(sample_report.generated_at.day) in html

    def test_html_title_carries_the_iso_date_for_filing(self, sample_report):
        stamp = sample_report.generated_at.strftime("%Y-%m-%d")
        assert f"<title>Land Opportunity Scan {stamp}</title>" in render_html(
            sample_report
        )

    def test_markdown_heading_carries_the_date(self, sample_report):
        stamp = sample_report.generated_at.strftime("%Y-%m-%d")
        assert f"# Land Opportunity Scan - {stamp}" in render_markdown(sample_report)

    def test_date_formatting_avoids_platform_specific_directives(self):
        """Padding-suppression directives are glibc-only and break on Windows."""
        import re

        from ncscout.report import html as html_module

        # Matches strftime forms like %-d or %-H, but not Jinja's {%- ... -%}
        # whitespace control, where the dash is followed by whitespace.
        offenders = re.findall(r"%-[a-zA-Z]", html_module.TEMPLATE)
        assert not offenders, f"non-portable strftime directives: {offenders}"
