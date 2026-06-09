"""Prediction explainability helpers."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def permutation_explanation(model_suite: Any, feature_row: pd.Series, baseline: pd.Series | None = None, top_n: int = 10) -> pd.DataFrame:
    """Explain a single prediction by perturbing each feature toward baseline."""

    baseline = baseline if baseline is not None else pd.Series(0.0, index=feature_row.index)
    base_probability = model_suite.predict(feature_row).red_win_probability
    rows = []
    for feature in feature_row.index:
        perturbed = feature_row.copy()
        perturbed[feature] = baseline.get(feature, 0.0)
        changed_probability = model_suite.predict(perturbed).red_win_probability
        rows.append(
            {
                "feature": feature,
                "value": feature_row[feature],
                "impact": base_probability - changed_probability,
                "abs_impact": abs(base_probability - changed_probability),
            }
        )
    return pd.DataFrame(rows).sort_values("abs_impact", ascending=False).head(top_n).reset_index(drop=True)


def shap_explanation(model: Any, feature_frame: pd.DataFrame) -> pd.DataFrame | None:
    """Return SHAP values for models supported by the optional shap package."""

    try:
        import shap  # type: ignore
    except Exception:
        return None
    try:
        explainer = shap.Explainer(model, feature_frame)
        values = explainer(feature_frame)
        array = values.values
        if array.ndim == 3:
            array = array[:, :, -1]
        return pd.DataFrame(array, columns=feature_frame.columns)
    except Exception:
        return None


def factor_narrative(explanation: pd.DataFrame, red_fighter: str, blue_fighter: str) -> list[str]:
    """Convert feature impacts into short human-readable drivers."""

    labels = {
        "reach_delta": "Reach advantage",
        "height_delta": "Height advantage",
        "cardio_delta": "Cardio edge",
        "td_def_delta": "Takedown defense edge",
        "td_per_15_delta": "Wrestling volume edge",
        "str_acc_delta": "Striking accuracy edge",
        "str_def_delta": "Striking defense edge",
        "kd_per_fight_delta": "Knockdown power edge",
        "overall_elo_delta": "Overall Elo advantage",
        "grappling_elo_delta": "Grappling Elo advantage",
        "finishing_elo_delta": "Finishing Elo advantage",
        "style_matchup_win_rate": "Historical style matchup edge",
    }
    factors = []
    for row in explanation.itertuples(index=False):
        direction = red_fighter if row.impact >= 0 else blue_fighter
        label = labels.get(row.feature, row.feature.replace("_", " ").title())
        factors.append(f"{label}: favors {direction} ({row.impact:+.3f})")
    return factors
