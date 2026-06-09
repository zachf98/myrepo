"""Dynamic Elo ratings for UFC fighters."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp

import pandas as pd

from ufc_predictor.data import UFCDataset
from ufc_predictor.features import finish_label


RATING_KEYS = ("overall_elo", "striking_elo", "grappling_elo", "finishing_elo")


@dataclass(slots=True)
class EloConfig:
    base_rating: float = 1500.0
    k_factor: float = 32.0
    finish_bonus: float = 10.0
    title_bonus: float = 4.0
    recency_half_life_days: float = 730.0
    weight_class_change_penalty: float = 8.0


@dataclass(slots=True)
class EloSystem:
    config: EloConfig = field(default_factory=EloConfig)
    ratings: dict[str, dict[str, float]] = field(default_factory=dict)
    last_date: dict[str, pd.Timestamp] = field(default_factory=dict)
    last_weight_class: dict[str, str] = field(default_factory=dict)
    history: list[dict[str, object]] = field(default_factory=list)

    def fit(self, dataset: UFCDataset) -> "EloSystem":
        self.ratings.clear()
        self.last_date.clear()
        self.last_weight_class.clear()
        self.history.clear()
        for fight in dataset.fights.sort_values("date").itertuples(index=False):
            self.update_fight(fight)
        return self

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {fighter: ratings.copy() for fighter, ratings in self.ratings.items()}

    def fighter_rating(self, fighter: str) -> dict[str, float]:
        return self.ratings.setdefault(
            fighter,
            {key: self.config.base_rating for key in RATING_KEYS},
        )

    def expected_score(self, red_fighter: str, blue_fighter: str, key: str = "overall_elo") -> float:
        red = self.fighter_rating(red_fighter)[key]
        blue = self.fighter_rating(blue_fighter)[key]
        return 1.0 / (1.0 + 10 ** ((blue - red) / 400.0))

    def update_fight(self, fight: object) -> None:
        red = fight.red_fighter
        blue = fight.blue_fighter
        winner = fight.winner
        method = finish_label(fight.method)
        date = pd.Timestamp(fight.date)
        weight_class = str(fight.weight_class)

        red_score = 1.0 if winner == red else 0.0
        blue_score = 1.0 - red_score
        red_expected = self.expected_score(red, blue)
        blue_expected = 1.0 - red_expected
        importance = self._importance_multiplier(fight, method)

        for fighter, opponent, score, expected in [
            (red, blue, red_score, red_expected),
            (blue, red, blue_score, blue_expected),
        ]:
            self._apply_weight_class_penalty(fighter, weight_class)
            recency = self._recency_multiplier(fighter, date)
            opponent_quality = self.fighter_rating(opponent)["overall_elo"] / self.config.base_rating
            delta = self.config.k_factor * recency * importance * opponent_quality * (score - expected)
            self._update_rating_keys(fighter, delta, method, score)
            self.last_date[fighter] = date
            self.last_weight_class[fighter] = weight_class

        self.history.append(
            {
                "fight_id": fight.fight_id,
                "date": date,
                "red_fighter": red,
                "blue_fighter": blue,
                "winner": winner,
                "method": method,
                "red_expected": red_expected,
                "red_overall_elo": self.fighter_rating(red)["overall_elo"],
                "blue_overall_elo": self.fighter_rating(blue)["overall_elo"],
            }
        )

    def _importance_multiplier(self, fight: object, method: str) -> float:
        multiplier = 1.0
        if method != "decision":
            multiplier += self.config.finish_bonus / self.config.k_factor
        if getattr(fight, "scheduled_rounds", 3) == 5:
            multiplier += self.config.title_bonus / self.config.k_factor
        round_number = float(getattr(fight, "round", 3) or 3)
        if method != "decision" and round_number <= 2:
            multiplier += 0.12
        return multiplier

    def _recency_multiplier(self, fighter: str, date: pd.Timestamp) -> float:
        previous = self.last_date.get(fighter)
        if previous is None:
            return 1.0
        days = max(0.0, (date - previous).days)
        decay = exp(-days / self.config.recency_half_life_days)
        return 0.75 + 0.5 * decay

    def _apply_weight_class_penalty(self, fighter: str, weight_class: str) -> None:
        previous = self.last_weight_class.get(fighter)
        if previous and previous != weight_class:
            ratings = self.fighter_rating(fighter)
            for key in RATING_KEYS:
                ratings[key] -= self.config.weight_class_change_penalty

    def _update_rating_keys(self, fighter: str, delta: float, method: str, score: float) -> None:
        ratings = self.fighter_rating(fighter)
        ratings["overall_elo"] += delta
        if method == "ko_tko":
            ratings["striking_elo"] += delta * 1.15
            ratings["finishing_elo"] += delta * (1.25 if score else 1.0)
            ratings["grappling_elo"] += delta * 0.45
        elif method == "submission":
            ratings["grappling_elo"] += delta * 1.15
            ratings["finishing_elo"] += delta * (1.25 if score else 1.0)
            ratings["striking_elo"] += delta * 0.45
        else:
            ratings["striking_elo"] += delta * 0.75
            ratings["grappling_elo"] += delta * 0.75
            ratings["finishing_elo"] += delta * 0.35

    def history_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.history)
