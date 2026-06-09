"""High-level UFC fight prediction engine."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ufc_predictor.archetypes import ArchetypeClassifier, ArchetypeResult
from ufc_predictor.bayes import BayesianPrediction, BayesianUpdater
from ufc_predictor.betting import BettingEdge, edges_to_frame, evaluate_fight_odds
from ufc_predictor.data import UFCDataset
from ufc_predictor.elo import EloSystem
from ufc_predictor.explain import factor_narrative, permutation_explanation
from ufc_predictor.features import build_fighter_profiles, build_training_matrix, matchup_feature_row, style_matchup_rates
from ufc_predictor.models import FightModelSuite, ModelProbabilities
from ufc_predictor.simulation import MonteCarloSimulator, SimulationResult


@dataclass(slots=True)
class FightPrediction:
    red_fighter: str
    blue_fighter: str
    red_win_probability: float
    blue_win_probability: float
    ko_tko_probability: float
    submission_probability: float
    decision_probability: float
    goes_distance_probability: float
    finish_round_distribution: dict[int, float]
    over_under_probabilities: dict[str, float]
    confidence_intervals: dict[str, tuple[float, float]]
    betting_edges: list[BettingEdge] = field(default_factory=list)
    comparable_fights: pd.DataFrame = field(default_factory=pd.DataFrame)
    model_breakdown: dict[str, float] = field(default_factory=dict)
    bayesian_components: dict[str, float] = field(default_factory=dict)
    top_factors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        winner = self.red_fighter if self.red_win_probability >= 0.5 else self.blue_fighter
        winner_probability = max(self.red_win_probability, self.blue_win_probability)
        lines = [
            f"Projected winner: {winner} ({winner_probability:.1%})",
            f"KO/TKO: {self.ko_tko_probability:.1%} | Submission: {self.submission_probability:.1%} | Decision: {self.decision_probability:.1%}",
            f"Goes distance: {self.goes_distance_probability:.1%}",
        ]
        if self.betting_edges:
            best = self.betting_edges[0]
            lines.append(
                f"Best betting signal: {best.market} {best.odds:+.0f} "
                f"edge={best.edge:.1%} EV={best.expected_value:.1%} ({best.recommendation})"
            )
        if self.top_factors:
            lines.append("Top factors: " + "; ".join(self.top_factors[:3]))
        return "\n".join(lines)

    def betting_frame(self) -> pd.DataFrame:
        return edges_to_frame(self.betting_edges)


class PredictionEngine:
    """End-to-end fight prediction platform API."""

    def __init__(
        self,
        random_state: int = 42,
        ensemble_weights: dict[str, float] | None = None,
    ) -> None:
        self.random_state = random_state
        self.ensemble_weights = ensemble_weights or {
            "models": 0.38,
            "elo": 0.17,
            "bayes": 0.20,
            "simulation": 0.25,
        }
        self.dataset: UFCDataset | None = None
        self.profiles: pd.DataFrame | None = None
        self.archetypes: ArchetypeResult | None = None
        self.elo = EloSystem()
        self.bayes = BayesianUpdater()
        self.models = FightModelSuite(random_state=random_state)
        self.simulator = MonteCarloSimulator(random_state=random_state)

    def fit(self, dataset: UFCDataset) -> "PredictionEngine":
        self.dataset = dataset.copy()
        self.profiles = build_fighter_profiles(self.dataset)
        self.archetypes = ArchetypeClassifier(random_state=self.random_state).fit_predict(self.dataset)
        self.elo.fit(self.dataset)
        self.bayes.fit(self.dataset)
        bundle = build_training_matrix(
            self.dataset,
            elo_snapshot=self.elo.snapshot(),
            archetype_scores=self.archetypes.scores,
        )
        self.models.fit(bundle)
        self.simulator.fit(self.dataset)
        return self

    def predict_fight(
        self,
        red_fighter: str,
        blue_fighter: str,
        weight_class: str | None = None,
        scheduled_rounds: int = 3,
        odds: dict[str, float] | None = None,
        simulations: int = 100_000,
    ) -> FightPrediction:
        if self.dataset is None or self.profiles is None or self.archetypes is None:
            raise RuntimeError("PredictionEngine must be fit before predict_fight().")

        weight_class = weight_class or self._infer_weight_class(red_fighter, blue_fighter)
        rates = style_matchup_rates(self.dataset.fights, self.archetypes.scores)
        row = matchup_feature_row(
            red_fighter,
            blue_fighter,
            self.profiles,
            elo_snapshot=self.elo.snapshot(),
            archetype_scores=self.archetypes.scores,
            matchup_rates=rates,
        )
        model_prediction = self.models.predict(row)
        bayes_prediction = self.bayes.predict(
            red_fighter,
            blue_fighter,
            weight_class,
            elo_snapshot=self.elo.snapshot(),
            archetype_scores=self.archetypes.scores,
        )
        simulation = self.simulator.simulate(
            red_fighter,
            blue_fighter,
            scheduled_rounds=scheduled_rounds,
            simulations=simulations,
        )
        elo_probability = self._elo_probability(red_fighter, blue_fighter)
        probabilities = self._ensemble(model_prediction, bayes_prediction, simulation, elo_probability)
        probabilities["blue_win_probability"] = 1.0 - probabilities["red_win_probability"]
        probabilities.update(simulation.over_under_probabilities)

        betting_edges = evaluate_fight_odds(probabilities, odds or {})
        comparable = self.models.comparable_fights(row, self.dataset.fights, top_n=20)
        explanation = permutation_explanation(self.models, row, top_n=8)
        top_factors = factor_narrative(explanation, red_fighter, blue_fighter)

        model_breakdown = {
            "model_red_win": model_prediction.red_win_probability,
            "bayes_red_win": bayes_prediction.red_win_probability,
            "simulation_red_win": simulation.red_win_probability,
            "elo_red_win": elo_probability,
            **model_prediction.model_breakdown,
        }

        return FightPrediction(
            red_fighter=red_fighter,
            blue_fighter=blue_fighter,
            red_win_probability=probabilities["red_win_probability"],
            blue_win_probability=probabilities["blue_win_probability"],
            ko_tko_probability=probabilities["ko_tko_probability"],
            submission_probability=probabilities["submission_probability"],
            decision_probability=probabilities["decision_probability"],
            goes_distance_probability=probabilities["goes_distance_probability"],
            finish_round_distribution=simulation.finish_round_distribution,
            over_under_probabilities=simulation.over_under_probabilities,
            confidence_intervals=simulation.confidence_intervals,
            betting_edges=betting_edges,
            comparable_fights=comparable,
            model_breakdown=model_breakdown,
            bayesian_components=bayes_prediction.components,
            top_factors=top_factors,
        )

    def _ensemble(
        self,
        model_prediction: ModelProbabilities,
        bayes_prediction: BayesianPrediction,
        simulation: SimulationResult,
        elo_probability: float,
    ) -> dict[str, float]:
        weights = self.ensemble_weights
        red_win = _weighted(
            {
                "models": model_prediction.red_win_probability,
                "elo": elo_probability,
                "bayes": bayes_prediction.red_win_probability,
                "simulation": simulation.red_win_probability,
            },
            weights,
        )
        ko = _weighted(
            {
                "models": model_prediction.ko_tko_probability,
                "bayes": bayes_prediction.ko_tko_probability,
                "simulation": simulation.ko_tko_probability,
            },
            {"models": 0.35, "bayes": 0.25, "simulation": 0.40},
        )
        sub = _weighted(
            {
                "models": model_prediction.submission_probability,
                "bayes": bayes_prediction.submission_probability,
                "simulation": simulation.submission_probability,
            },
            {"models": 0.35, "bayes": 0.25, "simulation": 0.40},
        )
        decision = _weighted(
            {
                "models": model_prediction.decision_probability,
                "bayes": bayes_prediction.decision_probability,
                "simulation": simulation.decision_probability,
            },
            {"models": 0.35, "bayes": 0.25, "simulation": 0.40},
        )
        method_total = max(ko + sub + decision, 1e-9)
        return {
            "red_win_probability": float(np.clip(red_win, 0.01, 0.99)),
            "ko_tko_probability": float(ko / method_total),
            "submission_probability": float(sub / method_total),
            "decision_probability": float(decision / method_total),
            "goes_distance_probability": float(decision / method_total),
        }

    def _elo_probability(self, red_fighter: str, blue_fighter: str) -> float:
        return self.elo.expected_score(red_fighter, blue_fighter, "overall_elo")

    def _infer_weight_class(self, red_fighter: str, blue_fighter: str) -> str:
        assert self.profiles is not None
        indexed = self.profiles.set_index("fighter")
        if red_fighter in indexed.index:
            return str(indexed.loc[red_fighter]["weight_class"])
        if blue_fighter in indexed.index:
            return str(indexed.loc[blue_fighter]["weight_class"])
        return "Unknown"


def _weighted(values: dict[str, float], weights: dict[str, float]) -> float:
    denominator = sum(weights.get(key, 0.0) for key in values)
    if denominator <= 0:
        return float(np.mean(list(values.values())))
    return float(sum(values[key] * weights.get(key, 0.0) for key in values) / denominator)
