"""Configuration loading and the interpolation helper the scorers rely on."""

from __future__ import annotations

import os
from bisect import bisect_left
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "scoring.yaml"


class Config:
    """Thin typed accessor over the scoring YAML."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self._validate()

    @property
    def raw(self) -> dict[str, Any]:
        return self._data

    def _validate(self) -> None:
        for key in ("natural_capital_weights", "composite_weights"):
            weights = self._data.get(key, {})
            total = sum(weights.values())
            if abs(total - 1.0) > 1e-6:
                raise ValueError(
                    f"{key} must sum to 1.0, got {total:.4f}. "
                    "Adjust config/scoring.yaml."
                )
        required = ("search", "normalisation", "revenue_models", "finance")
        missing = [k for k in required if k not in self._data]
        if missing:
            raise ValueError(f"config is missing required sections: {missing}")

    def section(self, name: str) -> dict[str, Any]:
        return self._data.get(name, {})

    @property
    def search(self) -> dict[str, Any]:
        return self._data["search"]

    @property
    def nc_weights(self) -> dict[str, float]:
        return self._data["natural_capital_weights"]

    @property
    def composite_weights(self) -> dict[str, float]:
        return self._data["composite_weights"]

    @property
    def normalisation(self) -> dict[str, list[list[float]]]:
        return self._data["normalisation"]

    @property
    def hazard_penalties(self) -> dict[str, Any]:
        return self._data.get("hazard_penalties", {})

    @property
    def revenue_models(self) -> dict[str, Any]:
        return self._data["revenue_models"]

    @property
    def finance(self) -> dict[str, Any]:
        return self._data["finance"]

    def revenue_model(self, name: str) -> dict[str, Any]:
        return self._data["revenue_models"].get(name, {})


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path or os.environ.get("NCSCOUT_CONFIG") or DEFAULT_CONFIG_PATH)
    if not path.exists():
        raise FileNotFoundError(f"scoring config not found at {path}")
    with path.open() as fh:
        return Config(yaml.safe_load(fh))


@lru_cache(maxsize=1)
def default_config() -> Config:
    return load_config()


def interpolate(curve: list[list[float]] | list[tuple[float, float]], value: float) -> float:
    """Piecewise-linear interpolation over an (input, score) breakpoint curve.

    Curves are authored in config as ascending lists of ``[measurement, score]``.
    Values outside the curve clamp to the nearest endpoint, which keeps an
    extreme measurement from producing a nonsensical score.
    """
    if not curve:
        raise ValueError("interpolation curve is empty")

    points = sorted(((float(x), float(y)) for x, y in curve), key=lambda p: p[0])
    xs = [p[0] for p in points]

    if value <= xs[0]:
        return points[0][1]
    if value >= xs[-1]:
        return points[-1][1]

    idx = bisect_left(xs, value)
    x0, y0 = points[idx - 1]
    x1, y1 = points[idx]
    if x1 == x0:
        return y1
    ratio = (value - x0) / (x1 - x0)
    return y0 + ratio * (y1 - y0)


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))
