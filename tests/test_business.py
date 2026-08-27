"""Investment model behaviour.

The tests that matter most here are the ones guarding against inflated returns:
double-counting acres and treating speculative income as certain are the two
failure modes that would make the whole report untrustworthy.
"""

from __future__ import annotations

from ncscout.models import DataQuality, Listing, Measurement, ParcelEnvironment
from ncscout.scoring.business import AcreAllocation, BusinessModeler


def _listing(price: float = 150_000, acres: float = 100.0) -> Listing:
    return Listing(
        listing_id="T",
        source="test",
        price=price,
        acres=acres,
        latitude=34.0,
        longitude=-93.0,
    )


class TestAcreAllocation:
    def test_splits_by_land_cover(self):
        env = ParcelEnvironment(
            land_cover={
                "deciduous_forest": 50.0,
                "cultivated_crops": 30.0,
                "open_water": 20.0,
            }
        )
        alloc = AcreAllocation.from_environment(100.0, env)
        assert alloc.forest == 50.0
        assert alloc.croppable == 30.0
        # Open water hosts nothing, so it is excluded from every usable class.
        assert alloc.rangeland == 30.0

    def test_no_portion_exceeds_the_parcel(self):
        env = ParcelEnvironment(
            land_cover={"deciduous_forest": 60.0, "woody_wetlands": 60.0}
        )
        alloc = AcreAllocation.from_environment(100.0, env)
        assert alloc.forest <= 100.0

    def test_falls_back_to_forest_cover_measurement(self):
        env = ParcelEnvironment(
            forest_cover_pct=Measurement(
                value=70.0, source="t", quality=DataQuality.MEASURED
            )
        )
        alloc = AcreAllocation.from_environment(100.0, env)
        assert alloc.forest == 70.0
        assert alloc.croppable == 30.0

    def test_no_data_allocates_nothing(self):
        alloc = AcreAllocation.from_environment(100.0, ParcelEnvironment())
        assert (alloc.forest, alloc.croppable, alloc.rangeland) == (0.0, 0.0, 0.0)


class TestAcreDoubleCounting:
    """The bug this guards against produced a 25% cap rate on forest land."""

    def test_row_crop_is_charged_only_to_croppable_acres(self, rich_env):
        # rich_env is 40% cropland/pasture of a 100-acre parcel.
        case = BusinessModeler().model(_listing(acres=100.0), rich_env)
        crop = next(
            (s for s in case.streams if s.name == "row_crop_lease"), None
        )
        if crop is None:
            return  # displaced by a stronger competing use, which is also correct
        # At most the top-of-market rent across 40 acres, never across 100.
        assert crop.annual_gross <= 275 * 40 * 1.001

    def test_competing_uses_do_not_stack_on_the_same_ground(self, rich_env):
        case = BusinessModeler().model(_listing(), rich_env)
        names = {s.name for s in case.streams}
        # Only one of the open-ground uses may survive.
        assert len(names & {"row_crop_lease", "solar_lease", "grazing"}) <= 1
        # Only one of the forest uses may survive.
        assert len(names & {"timber", "carbon"}) <= 1

    def test_hunting_coexists_with_timber(self, rich_env):
        """A hunting lease over a timber tract is a normal arrangement."""
        case = BusinessModeler().model(_listing(acres=200.0), rich_env)
        names = {s.name for s in case.streams}
        assert {"timber", "hunting_lease"} <= names


class TestStreamGating:
    def test_no_streams_without_any_environmental_data(self, empty_env):
        case = BusinessModeler().model(_listing(), empty_env)
        assert case.streams == []
        # Carrying cost still applies, so the parcel loses money.
        assert case.net_operating_income < 0
        assert case.cap_rate < 0

    def test_arid_parcel_gets_no_row_crop(self, poor_env):
        case = BusinessModeler().model(_listing(acres=300.0), poor_env)
        assert not any(s.name == "row_crop_lease" for s in case.streams)

    def test_utility_solar_needs_flat_ground(self, poor_env):
        """Irradiance alone is not enough; panels need buildable slope."""
        modeler = BusinessModeler()
        steep = modeler.model(_listing(acres=300.0), poor_env)
        assert not any(s.name == "solar_lease" for s in steep.streams)

        flat = poor_env.model_copy(
            update={
                "slope_pct": Measurement(
                    value=3.0, source="t", quality=DataQuality.MEASURED
                )
            }
        )
        assert any(
            s.name == "solar_lease"
            for s in modeler.model(_listing(acres=300.0), flat).streams
        )

    def test_timber_requires_forest_cover(self):
        env = ParcelEnvironment(
            forest_cover_pct=Measurement(
                value=5.0, source="t", quality=DataQuality.MEASURED
            ),
            precipitation_mm=Measurement(
                value=1200, source="t", quality=DataQuality.MODELED
            ),
        )
        case = BusinessModeler().model(_listing(), env)
        assert not any(s.name == "timber" for s in case.streams)

    def test_wind_requires_the_speed_threshold(self):
        def env_with_wind(speed: float) -> ParcelEnvironment:
            return ParcelEnvironment(
                wind_ws50m=Measurement(
                    value=speed, source="t", quality=DataQuality.MODELED
                )
            )

        modeler = BusinessModeler()
        weak = modeler.model(_listing(acres=600.0), env_with_wind(5.0))
        strong = modeler.model(_listing(acres=600.0), env_with_wind(8.0))
        assert not any(s.name == "wind_lease" for s in weak.streams)
        assert any(s.name == "wind_lease" for s in strong.streams)

    def test_small_parcels_do_not_get_utility_solar(self, poor_env):
        case = BusinessModeler().model(_listing(acres=5.0), poor_env)
        assert not any(s.name == "solar_lease" for s in case.streams)


class TestSpeculativeIncome:
    def test_solar_and_carbon_are_marked_speculative(self, rich_env, poor_env):
        for env, expected in ((poor_env, "solar_lease"), (rich_env, "carbon")):
            case = BusinessModeler().model(_listing(acres=300.0), env)
            stream = next((s for s in case.streams if s.name == expected), None)
            if stream is not None:
                assert stream.speculative
                assert stream.probability < 1.0

    def test_contracted_streams_exclude_speculative_ones(self, rich_env):
        case = BusinessModeler().model(_listing(acres=300.0), rich_env)
        assert all(not s.speculative for s in case.contracted_streams)

    def test_timber_and_crop_leases_are_not_speculative(self, rich_env):
        case = BusinessModeler().model(_listing(acres=300.0), rich_env)
        for stream in case.streams:
            if stream.name in ("timber", "row_crop_lease", "hunting_lease"):
                assert not stream.speculative


class TestFinance:
    def test_carrying_cost_scales_with_price(self, rich_env):
        modeler = BusinessModeler()
        cheap = modeler.model(_listing(price=50_000), rich_env)
        pricey = modeler.model(_listing(price=250_000), rich_env)
        assert pricey.annual_carrying_cost > cheap.annual_carrying_cost

    def test_cheaper_land_with_identical_resources_yields_a_higher_cap_rate(
        self, rich_env
    ):
        modeler = BusinessModeler()
        cheap = modeler.model(_listing(price=50_000), rich_env)
        pricey = modeler.model(_listing(price=250_000), rich_env)
        assert cheap.cap_rate > pricey.cap_rate

    def test_irr_is_recovered_for_a_normal_cashflow(self, rich_env):
        case = BusinessModeler().model(_listing(), rich_env)
        assert case.irr is not None
        # A land deal returning over 60% would mean the model is broken.
        assert -0.5 < case.irr < 0.6

    def test_npv_and_irr_agree_on_direction(self, rich_env):
        """Positive NPV at the discount rate implies IRR above that rate."""
        case = BusinessModeler().model(_listing(), rich_env)
        discount = BusinessModeler().config.finance["discount_rate"]
        if case.npv > 0:
            assert case.irr > discount
        else:
            assert case.irr <= discount

    def test_payback_is_none_when_income_is_negative(self, empty_env):
        case = BusinessModeler().model(_listing(), empty_env)
        assert case.payback_years is None

    def test_zero_acreage_produces_an_empty_case(self):
        listing = Listing(
            listing_id="T", source="test", price=100_000, acres=None
        )
        case = BusinessModeler().model(listing, ParcelEnvironment())
        assert case.streams == []
        assert case.net_operating_income == 0.0


class TestSceneryScore:
    def test_relief_forest_and_water_all_raise_it(self):
        def env(relief: float, forest: float, water: float) -> ParcelEnvironment:
            m = lambda v: Measurement(  # noqa: E731
                value=v, source="t", quality=DataQuality.MEASURED
            )
            return ParcelEnvironment(
                relief_m=m(relief), forest_cover_pct=m(forest), water_distance_m=m(water)
            )

        score = BusinessModeler.scenery_score
        assert score(env(150, 90, 100)) > score(env(5, 5, 12000))

    def test_no_data_scores_zero(self):
        assert BusinessModeler.scenery_score(ParcelEnvironment()) == 0.0
