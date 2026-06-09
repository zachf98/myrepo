"""Round-by-round Monte Carlo fight simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from ufc_predictor.features import build_fighter_profiles
from ufc_predictor.data import UFCDataset


@dataclass(slots=True)
class SimulationResult:
    simulations: int
    red_win_probability: float
    blue_win_probability: float
    ko_tko_probability: float
    submission_probability: float
    decision_probability: float
    goes_distance_probability: float
    finish_round_distribution: dict[int, float]
    over_under_probabilities: dict[str, float]
    confidence_intervals: dict[str, tuple[float, float]]
    raw_results: pd.DataFrame


class MonteCarloSimulator:
    """Simulate UFC fights using fighter rates, fatigue, and damage."""

    def __init__(self, random_state: int | None = 42) -> None:
        self.random_state = random_state
        self.rng = np.random.default_rng(random_state)
        self.profiles: pd.DataFrame | None = None

    def fit(self, dataset: UFCDataset) -> "MonteCarloSimulator":
        self.profiles = build_fighter_profiles(dataset)
        return self

    def simulate(
        self,
        red_fighter: str,
        blue_fighter: str,
        scheduled_rounds: int = 3,
        simulations: int = 100_000,
        over_under_lines: tuple[float, ...] = (1.5, 2.5, 3.5, 4.5),
    ) -> SimulationResult:
        if self.profiles is None:
            raise RuntimeError("MonteCarloSimulator must be fit before simulate().")
        profiles = self.profiles.set_index("fighter")
        red = profiles.loc[red_fighter]
        blue = profiles.loc[blue_fighter]

        records = []
        for _ in range(simulations):
            records.append(self._simulate_one(red, blue, int(scheduled_rounds)))
        raw = pd.DataFrame(records)
        red_win = float((raw["winner"] == red_fighter).mean())
        method_probs = raw["method"].value_counts(normalize=True).to_dict()
        finish_round_distribution = raw["finish_round"].value_counts(normalize=True).sort_index().to_dict()
        over_under = self._over_under(raw, scheduled_rounds, over_under_lines)
        intervals = {
            "red_win_probability": _binomial_ci(red_win, simulations),
            "ko_tko_probability": _binomial_ci(method_probs.get("ko_tko", 0.0), simulations),
            "submission_probability": _binomial_ci(method_probs.get("submission", 0.0), simulations),
            "decision_probability": _binomial_ci(method_probs.get("decision", 0.0), simulations),
        }
        return SimulationResult(
            simulations=simulations,
            red_win_probability=red_win,
            blue_win_probability=1.0 - red_win,
            ko_tko_probability=float(method_probs.get("ko_tko", 0.0)),
            submission_probability=float(method_probs.get("submission", 0.0)),
            decision_probability=float(method_probs.get("decision", 0.0)),
            goes_distance_probability=float(method_probs.get("decision", 0.0)),
            finish_round_distribution={int(k): float(v) for k, v in finish_round_distribution.items()},
            over_under_probabilities=over_under,
            confidence_intervals=intervals,
            raw_results=raw,
        )

    def _simulate_one(self, red: pd.Series, blue: pd.Series, scheduled_rounds: int) -> dict[str, object]:
        red_damage = {"head": 0.0, "body": 0.0, "leg": 0.0}
        blue_damage = {"head": 0.0, "body": 0.0, "leg": 0.0}
        red_score = 0.0
        blue_score = 0.0

        for round_number in range(1, scheduled_rounds + 1):
            red_fatigue = self._fatigue(red, round_number, red_damage)
            blue_fatigue = self._fatigue(blue, round_number, blue_damage)
            red_round, blue_round = self._simulate_round(red, blue, red_fatigue, blue_fatigue)
            self._apply_damage(blue_damage, red_round, red)
            self._apply_damage(red_damage, blue_round, blue)
            red_score += red_round["score"]
            blue_score += blue_round["score"]

            finish = self._finish_check(red, blue, red_damage, blue_damage, red_round, blue_round, round_number)
            if finish:
                winner, method = finish
                return {
                    "winner": winner,
                    "method": method,
                    "finish_round": round_number,
                    "elapsed_rounds": round_number - 0.5,
                    "red_score": red_score,
                    "blue_score": blue_score,
                    "red_head_damage": red_damage["head"],
                    "blue_head_damage": blue_damage["head"],
                }

        if red_score == blue_score:
            red_score += self.rng.normal(0, 0.1)
        winner = red["fighter"] if red_score > blue_score else blue["fighter"]
        return {
            "winner": winner,
            "method": "decision",
            "finish_round": scheduled_rounds,
            "elapsed_rounds": scheduled_rounds,
            "red_score": red_score,
            "blue_score": blue_score,
            "red_head_damage": red_damage["head"],
            "blue_head_damage": blue_damage["head"],
        }

    def _simulate_round(self, red: pd.Series, blue: pd.Series, red_fatigue: float, blue_fatigue: float) -> tuple[dict[str, float], dict[str, float]]:
        red_output = self._fighter_round_output(red, blue, red_fatigue)
        blue_output = self._fighter_round_output(blue, red, blue_fatigue)
        red_output["score"] = (
            red_output["sig_landed"]
            + 2.7 * red_output["knockdowns"]
            + 1.4 * red_output["takedowns"]
            + red_output["control_seconds"] / 45.0
            + 1.2 * red_output["submission_attempts"]
        )
        blue_output["score"] = (
            blue_output["sig_landed"]
            + 2.7 * blue_output["knockdowns"]
            + 1.4 * blue_output["takedowns"]
            + blue_output["control_seconds"] / 45.0
            + 1.2 * blue_output["submission_attempts"]
        )
        return red_output, blue_output

    def _fighter_round_output(self, fighter: pd.Series, opponent: pd.Series, fatigue: float) -> dict[str, float]:
        attempts = self.rng.poisson(max(1.0, fighter["sig_str_lpm"] * 5.0 * fighter["pace_index"] * fatigue))
        accuracy = np.clip((fighter["str_acc"] + (1 - opponent["str_def"])) / 2.0 * fatigue, 0.05, 0.85)
        landed = self.rng.binomial(attempts, accuracy)
        kd_lambda = max(0.01, fighter["kd_per_fight"] / 3.0 * landed / max(1.0, attempts))
        knockdowns = self.rng.poisson(kd_lambda)

        td_attempts = self.rng.poisson(max(0.0, fighter["td_per_15"] / 3.0 * fatigue))
        td_success = np.clip((fighter["td_acc"] + (1 - opponent["td_def"])) / 2.0, 0.02, 0.9)
        takedowns = self.rng.binomial(td_attempts, td_success) if td_attempts else 0
        control_seconds = float(self.rng.gamma(shape=1.0 + takedowns, scale=max(8.0, fighter["control_seconds"] / 4.0)))
        submission_attempts = self.rng.poisson(max(0.0, fighter["sub_att_per_15"] / 3.0 * (1 + takedowns) * fatigue))
        return {
            "attempts": float(attempts),
            "sig_landed": float(landed),
            "knockdowns": float(knockdowns),
            "takedowns": float(takedowns),
            "control_seconds": min(control_seconds, 300.0),
            "submission_attempts": float(submission_attempts),
        }

    def _fatigue(self, fighter: pd.Series, round_number: int, damage: Mapping[str, float]) -> float:
        cardio = np.clip(fighter["cardio_index"], 0.05, 1.0)
        damage_drag = 0.006 * damage["head"] + 0.004 * damage["body"] + 0.002 * damage["leg"]
        round_drag = (round_number - 1) * (0.08 + 0.10 * (1 - cardio))
        return float(np.clip(1.0 - round_drag - damage_drag, 0.35, 1.15))

    def _apply_damage(self, damage: dict[str, float], offense: Mapping[str, float], attacker: pd.Series) -> None:
        landed = offense["sig_landed"]
        damage["head"] += landed * attacker["head_strike_pct"] + 4.5 * offense["knockdowns"]
        damage["body"] += landed * attacker["body_strike_pct"] + 0.25 * offense["control_seconds"] / 60.0
        damage["leg"] += landed * attacker["leg_strike_pct"]

    def _finish_check(
        self,
        red: pd.Series,
        blue: pd.Series,
        red_damage: Mapping[str, float],
        blue_damage: Mapping[str, float],
        red_round: Mapping[str, float],
        blue_round: Mapping[str, float],
        round_number: int,
    ) -> tuple[str, str] | None:
        red_ko_prob = self._ko_probability(red_round, blue_damage, round_number)
        blue_ko_prob = self._ko_probability(blue_round, red_damage, round_number)
        red_sub_prob = self._sub_probability(red_round, blue, round_number)
        blue_sub_prob = self._sub_probability(blue_round, red, round_number)

        events = [
            (red["fighter"], "ko_tko", red_ko_prob),
            (blue["fighter"], "ko_tko", blue_ko_prob),
            (red["fighter"], "submission", red_sub_prob),
            (blue["fighter"], "submission", blue_sub_prob),
        ]
        for winner, method, probability in sorted(events, key=lambda item: item[2], reverse=True):
            if self.rng.random() < probability:
                return str(winner), method
        return None

    def _ko_probability(self, offense: Mapping[str, float], opponent_damage: Mapping[str, float], round_number: int) -> float:
        probability = 0.004 + 0.018 * offense["knockdowns"] + 0.0012 * opponent_damage["head"]
        probability += 0.0004 * opponent_damage["body"] + 0.001 * max(0, round_number - 2)
        return float(np.clip(probability, 0.0, 0.45))

    def _sub_probability(self, offense: Mapping[str, float], opponent: pd.Series, round_number: int) -> float:
        probability = 0.002 + 0.015 * offense["submission_attempts"] + 0.004 * offense["takedowns"]
        probability *= 1.0 + 0.08 * max(0, round_number - 1)
        probability *= 1.0 + max(0.0, 0.6 - opponent["td_def"])
        return float(np.clip(probability, 0.0, 0.35))

    def _over_under(self, raw: pd.DataFrame, scheduled_rounds: int, lines: tuple[float, ...]) -> dict[str, float]:
        result = {}
        for line in lines:
            if line <= scheduled_rounds:
                result[f"over_{line}"] = float((raw["elapsed_rounds"] > line).mean())
                result[f"under_{line}"] = float((raw["elapsed_rounds"] <= line).mean())
        return result


def _binomial_ci(probability: float, n: int, z: float = 1.96) -> tuple[float, float]:
    spread = z * np.sqrt(max(probability * (1 - probability), 0.0) / max(n, 1))
    return float(max(0.0, probability - spread)), float(min(1.0, probability + spread))
