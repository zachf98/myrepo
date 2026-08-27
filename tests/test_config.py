"""Config loading, validation and the interpolation helper."""

from __future__ import annotations

import pytest

from ncscout.config import Config, clamp, default_config, interpolate


def test_default_config_loads_and_validates():
    config = default_config()
    assert config.search["max_price"] == 250000
    assert pytest.approx(sum(config.nc_weights.values())) == 1.0
    assert pytest.approx(sum(config.composite_weights.values())) == 1.0


def test_rejects_weights_that_do_not_sum_to_one():
    bad = {
        "natural_capital_weights": {"water": 0.5, "soil": 0.2},
        "composite_weights": {
            "natural_capital": 0.45,
            "business_return": 0.4,
            "price_efficiency": 0.15,
        },
        "search": {},
        "normalisation": {},
        "revenue_models": {},
        "finance": {},
    }
    with pytest.raises(ValueError, match="must sum to 1.0"):
        Config(bad)


def test_rejects_missing_sections():
    bad = {
        "natural_capital_weights": {"water": 1.0},
        "composite_weights": {"natural_capital": 1.0},
    }
    with pytest.raises(ValueError, match="missing required sections"):
        Config(bad)


class TestInterpolate:
    curve = [[0, 0], [10, 50], [20, 100]]

    def test_hits_breakpoints_exactly(self):
        assert interpolate(self.curve, 0) == 0
        assert interpolate(self.curve, 10) == 50
        assert interpolate(self.curve, 20) == 100

    def test_interpolates_between_breakpoints(self):
        assert interpolate(self.curve, 5) == 25
        assert interpolate(self.curve, 15) == 75

    def test_clamps_outside_the_curve(self):
        assert interpolate(self.curve, -100) == 0
        assert interpolate(self.curve, 1e6) == 100

    def test_handles_unsorted_and_non_monotonic_curves(self):
        # Precipitation is non-monotonic: too much rain scores lower again.
        curve = [[20, 100], [0, 0], [30, 80]]
        assert interpolate(curve, 20) == 100
        assert interpolate(curve, 25) == 90

    def test_empty_curve_is_an_error(self):
        with pytest.raises(ValueError, match="empty"):
            interpolate([], 5)


def test_clamp():
    assert clamp(-5) == 0
    assert clamp(150) == 100
    assert clamp(42) == 42
