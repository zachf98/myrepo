"""Bayesian fight probability updates."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, log
from typing import Mapping

import numpy as np
import pandas as pd
from scipy.special import expit, logit

from ufc_predictor.data import UFCDataset
from ufc_predictor.features import build_fighter_profiles, finish_label, style_matchup_rates


@dataclass(slots=True)
class BayesianPrediction:
    red_win_probability: float
    ko_tko_probability: float
    submission_probability: float
    decision_probability: float
    goes_distance_probability: float
    components: dict[str, float]


class BayesianUpdater:
    """Blend priors and evidence with interpretable log-odds updates."""

    def __init__(self, prior_strength: float = 12.0) -> None:
        self.prior_strength = prior_strength
        self.dataset: UFCDataset | None = None
        self.profiles: pd.DataFrame | None = None
        self.division_rates: pd.DataFrame | None = None
        self.fighter_records: pd.DataFrame | None = None

    def fit(self, dataset: UFCDataset) -> "BayesianUpdater":
        self.dataset = dataset
        self.profiles = build_fighter_profiles(dataset)
        fights = dataset.fights.copy()
        fights["finish_label"] = fights["method"].map(finish_label)
        fights["red_won"] = (fights["winner"] == fights["red_fighter"]).astype(int)
        self.division_rates = (
            fights.groupby("weight_class")
            .agg(
                red_win_rate=("red_won", "mean"),
                ko_tko_rate=("finish_label", lambda s: float((s == "ko_tko").mean())),
                submission_rate=("finish_label", lambda s: float((s == "submission").mean())),
                decision_rate=("finish_label", lambda s: float((s == "decision").mean())),
            )
            .reset_index()
        )
        self.fighter_records = self._fighter_records(fights)
        return self

    def predict(
        self,
        red_fighter: str,
        blue_fighter: str,
        weight_class: str,
        elo_snapshot: Mapping[str, Mapping[str, float]] | None = None,
        archetype_scores: pd.DataFrame | None = None,
    ) -> BayesianPrediction:
        if self.dataset is None or self.profiles is None:
            raise RuntimeError("BayesianUpdater must be fit before predict().")

        division = self._division_prior(weight_class)
        record_prior = self._record_prior(red_fighter, blue_fighter)
        profile_prior = self._profile_prior(red_fighter, blue_fighter)
        style_prior = self._style_prior(red_fighter, blue_fighter, archetype_scores)
        elo_prior = self._elo_prior(red_fighter, blue_fighter, elo_snapshot)
        recent_prior = self._recent_form_prior(red_fighter, blue_fighter)

        log_odds = np.average(
            [
                logit(division["red_win_rate"]),
                logit(record_prior),
                logit(profile_prior),
                logit(style_prior),
                logit(elo_prior),
                logit(recent_prior),
            ],
            weights=[1.0, 1.4, 1.2, 0.9, 1.6, 1.1],
        )
        red_win = float(expit(log_odds))

        ko = self._method_probability(red_fighter, blue_fighter, division["ko_tko_rate"], "ko_tko")
        sub = self._method_probability(red_fighter, blue_fighter, division["submission_rate"], "submission")
        decision = self._method_probability(red_fighter, blue_fighter, division["decision_rate"], "decision")
        total = ko + sub + decision
        ko, sub, decision = ko / total, sub / total, decision / total

        return BayesianPrediction(
            red_win_probability=red_win,
            ko_tko_probability=float(ko),
            submission_probability=float(sub),
            decision_probability=float(decision),
            goes_distance_probability=float(decision),
            components={
                "division": division["red_win_rate"],
                "career_record": record_prior,
                "profile": profile_prior,
                "style": style_prior,
                "elo": elo_prior,
                "recent_form": recent_prior,
            },
        )

    def _division_prior(self, weight_class: str) -> dict[str, float]:
        assert self.division_rates is not None
        row = self.division_rates[self.division_rates["weight_class"] == weight_class]
        if row.empty:
            return {"red_win_rate": 0.5, "ko_tko_rate": 0.32, "submission_rate": 0.18, "decision_rate": 0.5}
        data = row.iloc[0].to_dict()
        return {key: _clip_prob(value) for key, value in data.items() if key != "weight_class"}

    def _record_prior(self, red_fighter: str, blue_fighter: str) -> float:
        assert self.fighter_records is not None
        records = self.fighter_records.set_index("fighter")
        red = records.loc[red_fighter] if red_fighter in records.index else pd.Series({"wins": 0, "losses": 0})
        blue = records.loc[blue_fighter] if blue_fighter in records.index else pd.Series({"wins": 0, "losses": 0})
        red_rate = (red["wins"] + self.prior_strength * 0.5) / (red["wins"] + red["losses"] + self.prior_strength)
        blue_rate = (blue["wins"] + self.prior_strength * 0.5) / (blue["wins"] + blue["losses"] + self.prior_strength)
        return _clip_prob(0.5 + (red_rate - blue_rate) / 2.0)

    def _profile_prior(self, red_fighter: str, blue_fighter: str) -> float:
        assert self.profiles is not None
        profiles = self.profiles.set_index("fighter")
        red = profiles.loc[red_fighter]
        blue = profiles.loc[blue_fighter]
        score = (
            0.25 * (red["strike_differential"] - blue["strike_differential"])
            + 0.15 * (red["td_def"] - blue["td_def"])
            + 0.15 * (red["td_per_15"] - blue["td_per_15"])
            + 0.10 * (red["cardio_index"] - blue["cardio_index"])
            + 0.004 * (red["reach_in"] - blue["reach_in"])
            - 0.015 * max(0.0, red["age"] - blue["age"])
        )
        return _clip_prob(float(expit(score)))

    def _style_prior(self, red_fighter: str, blue_fighter: str, archetype_scores: pd.DataFrame | None) -> float:
        if archetype_scores is None or archetype_scores.empty or self.dataset is None:
            return 0.5
        rates = style_matchup_rates(self.dataset.fights, archetype_scores)
        score_columns = [c for c in archetype_scores.columns if c not in {"fighter", "cluster"}]
        primary = archetype_scores.set_index("fighter")[score_columns].idxmax(axis=1)
        return _clip_prob(rates.get((primary.get(red_fighter, "Unknown"), primary.get(blue_fighter, "Unknown")), 0.5))

    def _elo_prior(
        self,
        red_fighter: str,
        blue_fighter: str,
        elo_snapshot: Mapping[str, Mapping[str, float]] | None,
    ) -> float:
        if not elo_snapshot:
            return 0.5
        red = elo_snapshot.get(red_fighter, {}).get("overall_elo", 1500.0)
        blue = elo_snapshot.get(blue_fighter, {}).get("overall_elo", 1500.0)
        return _clip_prob(1.0 / (1.0 + 10 ** ((blue - red) / 400.0)))

    def _recent_form_prior(self, red_fighter: str, blue_fighter: str) -> float:
        assert self.dataset is not None
        fights = self.dataset.fights.sort_values("date")
        return _clip_prob(0.5 + (self._recent_score(fights, red_fighter) - self._recent_score(fights, blue_fighter)) / 3.0)

    def _recent_score(self, fights: pd.DataFrame, fighter: str, n: int = 3) -> float:
        mask = (fights["red_fighter"] == fighter) | (fights["blue_fighter"] == fighter)
        recent = fights[mask].tail(n)
        if recent.empty:
            return 0.0
        score = 0.0
        for age, fight in enumerate(reversed(list(recent.itertuples(index=False)))):
            outcome = 1.0 if fight.winner == fighter else -1.0
            finish = 0.35 if finish_label(fight.method) != "decision" else 0.0
            score += exp(-age / 2.0) * (outcome + finish * np.sign(outcome))
        return float(score / n)

    def _method_probability(self, red_fighter: str, blue_fighter: str, division_rate: float, method: str) -> float:
        assert self.dataset is not None
        fights = self.dataset.fights
        mask = fights["winner"].isin([red_fighter, blue_fighter])
        fighter_methods = fights[mask]["method"].map(finish_label)
        fighter_rate = float((fighter_methods == method).mean()) if len(fighter_methods) else division_rate
        return _clip_prob(0.55 * division_rate + 0.45 * fighter_rate)

    def _fighter_records(self, fights: pd.DataFrame) -> pd.DataFrame:
        records: dict[str, dict[str, float]] = {}
        for fight in fights.itertuples(index=False):
            for fighter in [fight.red_fighter, fight.blue_fighter]:
                records.setdefault(fighter, {"fighter": fighter, "wins": 0.0, "losses": 0.0})
            records[fight.winner]["wins"] += 1
            loser = fight.blue_fighter if fight.winner == fight.red_fighter else fight.red_fighter
            records[loser]["losses"] += 1
        return pd.DataFrame(records.values())


def _clip_prob(value: float) -> float:
    return float(np.clip(value, 0.01, 0.99))
