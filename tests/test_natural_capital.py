"""Natural capital scoring behaviour."""

from __future__ import annotations

from ncscout.models import DataQuality, Measurement, ParcelEnvironment
from ncscout.scoring import NaturalCapitalScorer


def test_rich_land_outscores_marginal_land(rich_env, poor_env):
    scorer = NaturalCapitalScorer()
    assert scorer.score(rich_env).total > scorer.score(poor_env).total


def test_scores_stay_in_range(rich_env, poor_env, empty_env):
    scorer = NaturalCapitalScorer()
    for env in (rich_env, poor_env, empty_env):
        score = scorer.score(env)
        assert 0.0 <= score.total <= 100.0
        for sub in score.subscores:
            assert 0.0 <= sub.score <= 100.0


def test_no_data_yields_zero_score_and_zero_confidence(empty_env):
    score = NaturalCapitalScorer().score(empty_env)
    assert score.total == 0.0
    assert score.confidence == 0.0


def test_measured_data_earns_more_confidence_than_modelled():
    scorer = NaturalCapitalScorer()

    def env_with(quality: DataQuality) -> ParcelEnvironment:
        return ParcelEnvironment(
            nccpi=Measurement(value=0.7, source="t", quality=quality),
            water_storage_cm=Measurement(value=18, source="t", quality=quality),
            slope_pct=Measurement(value=3, source="t", quality=quality),
        )

    measured = scorer.score(env_with(DataQuality.MEASURED))
    modeled = scorer.score(env_with(DataQuality.MODELED))
    regional = scorer.score(env_with(DataQuality.REGIONAL_DEFAULT))

    # Same inputs, so the score matches while confidence separates them.
    assert measured.total == modeled.total == regional.total
    assert measured.confidence > modeled.confidence > regional.confidence


def test_missing_subscores_do_not_drag_the_total_down():
    """A parcel with only good soil data should not be punished for the rest."""
    env = ParcelEnvironment(
        nccpi=Measurement(value=0.85, source="t", quality=DataQuality.MEASURED),
        water_storage_cm=Measurement(
            value=22, source="t", quality=DataQuality.MEASURED
        ),
        slope_pct=Measurement(value=1, source="t", quality=DataQuality.MEASURED),
    )
    score = NaturalCapitalScorer().score(env)
    # Soil alone carries 20% weight; without renormalisation the total would be
    # about 18 rather than the ~90 the soil data actually supports.
    assert score.total > 80
    # But confidence must reflect how little was resolved.
    assert score.confidence < 0.35


def test_subscores_without_data_are_reported_with_zero_confidence(empty_env):
    score = NaturalCapitalScorer().score(empty_env)
    names = {s.name for s in score.subscores}
    assert names == {
        "water",
        "soil",
        "timber",
        "climate",
        "solar",
        "wind",
        "resilience",
    }
    assert all(s.confidence == 0.0 for s in score.subscores)


class TestResilience:
    def test_flood_zone_penalty_applies(self):
        scorer = NaturalCapitalScorer()
        safe = ParcelEnvironment(flood_zone="X", flood_zone_source="FEMA NFHL")
        risky = ParcelEnvironment(flood_zone="AE", flood_zone_source="FEMA NFHL")
        assert (
            scorer.score(safe).by_name("resilience").score
            > scorer.score(risky).by_name("resilience").score
        )

    def test_coastal_v_zone_is_the_harshest_flood_penalty(self):
        scorer = NaturalCapitalScorer()
        ae = ParcelEnvironment(flood_zone="AE", flood_zone_source="FEMA NFHL")
        ve = ParcelEnvironment(flood_zone="VE", flood_zone_source="FEMA NFHL")
        assert (
            scorer.score(ve).by_name("resilience").score
            < scorer.score(ae).by_name("resilience").score
        )

    def test_ssurgo_flooding_substitutes_where_fema_is_unmapped(self):
        scorer = NaturalCapitalScorer()
        base = {"flood_zone_source": "FEMA NFHL (unmapped)"}
        dry = ParcelEnvironment(soil_flood_frequency="None", **base)
        wet = ParcelEnvironment(soil_flood_frequency="Frequent", **base)
        assert (
            scorer.score(dry).by_name("resilience").score
            > scorer.score(wet).by_name("resilience").score
        )

    def test_fema_takes_precedence_over_ssurgo(self):
        """FEMA carries regulatory weight, so it wins when both are present."""
        scorer = NaturalCapitalScorer()
        env = ParcelEnvironment(
            flood_zone="X",
            flood_zone_source="FEMA NFHL",
            soil_flood_frequency="Frequent",
        )
        drivers = scorer.score(env).by_name("resilience").drivers
        assert any("FEMA flood zone X" in d for d in drivers)
        assert not any("SSURGO" in d for d in drivers)

    def test_aridity_penalty_applies_below_threshold(self):
        scorer = NaturalCapitalScorer()
        arid = ParcelEnvironment(
            precipitation_mm=Measurement(
                value=200, source="t", quality=DataQuality.MODELED
            )
        )
        wet = ParcelEnvironment(
            precipitation_mm=Measurement(
                value=1000, source="t", quality=DataQuality.MODELED
            )
        )
        assert (
            scorer.score(arid).by_name("resilience").score
            < scorer.score(wet).by_name("resilience").score
        )

    def test_no_hazard_data_gives_zero_confidence_not_a_free_pass(self):
        """An unscreened parcel must not be credited with perfect resilience."""
        sub = NaturalCapitalScorer().score(ParcelEnvironment()).by_name("resilience")
        assert sub.confidence == 0.0
        assert sub.score == 0.0
