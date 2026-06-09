"""Feature engineering for fighter profiles and matchup-level models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from ufc_predictor.data import UFCDataset


MODEL_FEATURE_COLUMNS = [
    "age_delta",
    "height_delta",
    "reach_delta",
    "experience_delta",
    "ufc_experience_delta",
    "five_round_delta",
    "championship_delta",
    "sig_str_lpm_delta",
    "sig_str_abs_lpm_delta",
    "strike_differential_delta",
    "str_acc_delta",
    "str_def_delta",
    "kd_per_fight_delta",
    "td_per_15_delta",
    "td_acc_delta",
    "td_def_delta",
    "control_seconds_delta",
    "sub_att_per_15_delta",
    "ground_strike_rate_delta",
    "cardio_delta",
    "pace_delta",
    "southpaw_vs_orthodox",
    "same_stance",
    "red_longer_reach",
    "red_taller",
    "style_matchup_win_rate",
    "overall_elo_delta",
    "striking_elo_delta",
    "grappling_elo_delta",
    "finishing_elo_delta",
]


PROFILE_NUMERIC_COLUMNS = [
    "age",
    "height_in",
    "reach_in",
    "total_fights",
    "ufc_fights",
    "championship_fights",
    "five_round_fights",
    "sig_str_lpm",
    "sig_str_abs_lpm",
    "strike_differential",
    "str_acc",
    "str_def",
    "kd_per_fight",
    "head_strike_pct",
    "body_strike_pct",
    "leg_strike_pct",
    "td_per_15",
    "td_acc",
    "td_def",
    "control_seconds",
    "sub_att_per_15",
    "ground_strike_rate",
    "cardio_index",
    "pace_index",
]


@dataclass(slots=True)
class FeatureBundle:
    x: pd.DataFrame
    y_winner: pd.Series
    y_finish: pd.Series
    y_method: pd.Series
    y_goes_distance: pd.Series
    fight_ids: pd.Series


def build_fighter_profiles(dataset: UFCDataset) -> pd.DataFrame:
    """Combine fighter table with historical per-fight stat averages."""

    fighters = dataset.fighters.copy().set_index("fighter", drop=False)
    stats = dataset.fighter_fight_stats.copy()
    numeric_stats = [column for column in PROFILE_NUMERIC_COLUMNS if column in stats.columns]
    if numeric_stats:
        means = stats.groupby("fighter")[numeric_stats].mean(numeric_only=True)
        for column in means.columns:
            fighters[column] = means[column].combine_first(fighters.get(column))

    for column in PROFILE_NUMERIC_COLUMNS:
        if column not in fighters.columns:
            fighters[column] = 0.0
        fighters[column] = pd.to_numeric(fighters[column], errors="coerce").fillna(fighters[column].median())
        if fighters[column].isna().any():
            fighters[column] = fighters[column].fillna(0.0)

    for column in ["stance", "weight_class", "camp"]:
        if column not in fighters.columns:
            fighters[column] = "Unknown"
        fighters[column] = fighters[column].fillna("Unknown").astype(str)

    return fighters.reset_index(drop=True)


def finish_label(method: str) -> str:
    method_normalized = str(method).strip().lower()
    if "sub" in method_normalized:
        return "submission"
    if any(token in method_normalized for token in ["ko", "tko", "knockout"]):
        return "ko_tko"
    return "decision"


def style_matchup_rates(
    fights: pd.DataFrame,
    archetype_scores: pd.DataFrame | None,
) -> dict[tuple[str, str], float]:
    """Compute historical red win rates by primary archetype pairing."""

    if archetype_scores is None or archetype_scores.empty:
        return {}
    score_columns = [c for c in archetype_scores.columns if c not in {"fighter", "cluster"}]
    if not score_columns:
        return {}
    primary = archetype_scores.set_index("fighter")[score_columns].idxmax(axis=1).to_dict()
    counts: dict[tuple[str, str], list[int]] = {}
    for fight in fights.itertuples(index=False):
        red_style = primary.get(fight.red_fighter, "Unknown")
        blue_style = primary.get(fight.blue_fighter, "Unknown")
        key = (red_style, blue_style)
        counts.setdefault(key, [0, 0])
        counts[key][1] += 1
        counts[key][0] += int(fight.winner == fight.red_fighter)
    return {key: wins / total for key, (wins, total) in counts.items() if total}


def matchup_feature_row(
    red_fighter: str,
    blue_fighter: str,
    profiles: pd.DataFrame,
    elo_snapshot: Mapping[str, Mapping[str, float]] | None = None,
    archetype_scores: pd.DataFrame | None = None,
    matchup_rates: Mapping[tuple[str, str], float] | None = None,
) -> pd.Series:
    """Create one red-minus-blue matchup feature vector."""

    indexed = profiles.set_index("fighter")
    if red_fighter not in indexed.index:
        raise KeyError(f"Unknown red fighter: {red_fighter}")
    if blue_fighter not in indexed.index:
        raise KeyError(f"Unknown blue fighter: {blue_fighter}")

    red = indexed.loc[red_fighter]
    blue = indexed.loc[blue_fighter]
    features = {
        "age_delta": red["age"] - blue["age"],
        "height_delta": red["height_in"] - blue["height_in"],
        "reach_delta": red["reach_in"] - blue["reach_in"],
        "experience_delta": red["total_fights"] - blue["total_fights"],
        "ufc_experience_delta": red["ufc_fights"] - blue["ufc_fights"],
        "five_round_delta": red["five_round_fights"] - blue["five_round_fights"],
        "championship_delta": red["championship_fights"] - blue["championship_fights"],
        "sig_str_lpm_delta": red["sig_str_lpm"] - blue["sig_str_lpm"],
        "sig_str_abs_lpm_delta": red["sig_str_abs_lpm"] - blue["sig_str_abs_lpm"],
        "strike_differential_delta": red["strike_differential"] - blue["strike_differential"],
        "str_acc_delta": red["str_acc"] - blue["str_acc"],
        "str_def_delta": red["str_def"] - blue["str_def"],
        "kd_per_fight_delta": red["kd_per_fight"] - blue["kd_per_fight"],
        "td_per_15_delta": red["td_per_15"] - blue["td_per_15"],
        "td_acc_delta": red["td_acc"] - blue["td_acc"],
        "td_def_delta": red["td_def"] - blue["td_def"],
        "control_seconds_delta": red["control_seconds"] - blue["control_seconds"],
        "sub_att_per_15_delta": red["sub_att_per_15"] - blue["sub_att_per_15"],
        "ground_strike_rate_delta": red["ground_strike_rate"] - blue["ground_strike_rate"],
        "cardio_delta": red["cardio_index"] - blue["cardio_index"],
        "pace_delta": red["pace_index"] - blue["pace_index"],
        "southpaw_vs_orthodox": int({red["stance"], blue["stance"]} == {"Southpaw", "Orthodox"}),
        "same_stance": int(red["stance"] == blue["stance"]),
        "red_longer_reach": int(red["reach_in"] > blue["reach_in"]),
        "red_taller": int(red["height_in"] > blue["height_in"]),
    }

    features["style_matchup_win_rate"] = 0.5
    if archetype_scores is not None and matchup_rates:
        score_columns = [c for c in archetype_scores.columns if c not in {"fighter", "cluster"}]
        if score_columns:
            primary = archetype_scores.set_index("fighter")[score_columns].idxmax(axis=1)
            red_style = primary.get(red_fighter, "Unknown")
            blue_style = primary.get(blue_fighter, "Unknown")
            features["style_matchup_win_rate"] = matchup_rates.get((red_style, blue_style), 0.5)

    for rating in ["overall_elo", "striking_elo", "grappling_elo", "finishing_elo"]:
        red_rating = 1500.0
        blue_rating = 1500.0
        if elo_snapshot:
            red_rating = elo_snapshot.get(red_fighter, {}).get(rating, red_rating)
            blue_rating = elo_snapshot.get(blue_fighter, {}).get(rating, blue_rating)
        features[f"{rating}_delta"] = red_rating - blue_rating

    return pd.Series(features, dtype=float).reindex(MODEL_FEATURE_COLUMNS).fillna(0.0)


def build_training_matrix(
    dataset: UFCDataset,
    elo_snapshot: Mapping[str, Mapping[str, float]] | None = None,
    archetype_scores: pd.DataFrame | None = None,
) -> FeatureBundle:
    profiles = build_fighter_profiles(dataset)
    rates = style_matchup_rates(dataset.fights, archetype_scores)
    rows = []
    y_winner = []
    y_finish = []
    y_method = []
    y_goes_distance = []
    fight_ids = []

    for fight in dataset.fights.sort_values("date").itertuples(index=False):
        rows.append(
            matchup_feature_row(
                fight.red_fighter,
                fight.blue_fighter,
                profiles,
                elo_snapshot=elo_snapshot,
                archetype_scores=archetype_scores,
                matchup_rates=rates,
            )
        )
        method = finish_label(fight.method)
        y_winner.append(int(fight.winner == fight.red_fighter))
        y_finish.append(int(method != "decision"))
        y_method.append(method)
        y_goes_distance.append(int(method == "decision"))
        fight_ids.append(fight.fight_id)

    x = pd.DataFrame(rows, columns=MODEL_FEATURE_COLUMNS).fillna(0.0)
    return FeatureBundle(
        x=x,
        y_winner=pd.Series(y_winner, name="red_won"),
        y_finish=pd.Series(y_finish, name="finish"),
        y_method=pd.Series(y_method, name="method"),
        y_goes_distance=pd.Series(y_goes_distance, name="goes_distance"),
        fight_ids=pd.Series(fight_ids, name="fight_id"),
    )
