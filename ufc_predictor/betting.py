"""Sportsbook odds, edge, EV, Kelly, and market inefficiency tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(slots=True)
class BettingEdge:
    market: str
    model_probability: float
    odds: float
    implied_probability: float
    edge: float
    expected_value: float
    kelly_fraction: float
    recommendation: str


def american_to_decimal(odds: float) -> float:
    odds = float(odds)
    if odds > 0:
        return 1.0 + odds / 100.0
    return 1.0 + 100.0 / abs(odds)


def implied_probability(odds: float) -> float:
    decimal = american_to_decimal(odds)
    return 1.0 / decimal


def expected_value(probability: float, odds: float) -> float:
    decimal = american_to_decimal(odds)
    payout = decimal - 1.0
    return probability * payout - (1.0 - probability)


def kelly_fraction(probability: float, odds: float, cap: float = 0.05) -> float:
    decimal = american_to_decimal(odds)
    b = decimal - 1.0
    fraction = (probability * b - (1.0 - probability)) / b
    return float(np.clip(fraction, 0.0, cap))


def recommendation(edge: float, ev: float) -> str:
    if edge >= 0.08 and ev > 0.08:
        return "Strong Value"
    if edge >= 0.035 and ev > 0.02:
        return "Moderate Value"
    return "Pass"


def evaluate_market(market: str, probability: float, odds: float) -> BettingEdge:
    implied = implied_probability(odds)
    edge = probability - implied
    ev = expected_value(probability, odds)
    return BettingEdge(
        market=market,
        model_probability=float(probability),
        odds=float(odds),
        implied_probability=float(implied),
        edge=float(edge),
        expected_value=float(ev),
        kelly_fraction=kelly_fraction(probability, odds),
        recommendation=recommendation(edge, ev),
    )


def evaluate_fight_odds(probabilities: dict[str, float], odds: dict[str, float]) -> list[BettingEdge]:
    """Evaluate all odds keys that have a matching model probability."""

    market_aliases = {
        "red_moneyline": "red_win_probability",
        "blue_moneyline": "blue_win_probability",
        "ko_tko": "ko_tko_probability",
        "submission": "submission_probability",
        "decision": "decision_probability",
        "goes_distance": "goes_distance_probability",
    }
    edges: list[BettingEdge] = []
    for market, price in odds.items():
        probability_key = market_aliases.get(market, market)
        if market.startswith(("over_", "under_")):
            side, line = market.split("_", 1)
            probability_key = f"{side}_{line.replace('_', '.')}"
        if probability_key in probabilities:
            edges.append(evaluate_market(market, probabilities[probability_key], price))
    return sorted(edges, key=lambda edge: edge.expected_value, reverse=True)


def edges_to_frame(edges: list[BettingEdge]) -> pd.DataFrame:
    return pd.DataFrame([asdict(edge) for edge in edges])


def detect_market_inefficiencies(edges_by_fight: dict[str, list[BettingEdge]]) -> pd.DataFrame:
    """Rank most mispriced fights on a card by best positive expected value."""

    rows = []
    for fight_name, edges in edges_by_fight.items():
        if not edges:
            continue
        best = max(edges, key=lambda edge: edge.expected_value)
        rows.append(
            {
                "fight": fight_name,
                "market": best.market,
                "edge": best.edge,
                "expected_value": best.expected_value,
                "kelly_fraction": best.kelly_fraction,
                "recommendation": best.recommendation,
                "inefficiency_type": classify_inefficiency(best),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.sort_values(["expected_value", "edge"], ascending=False).reset_index(drop=True)


def classify_inefficiency(edge: BettingEdge) -> str:
    if edge.market.endswith("moneyline") and edge.odds < -180 and edge.edge < 0:
        return "Public favorite inflation"
    if edge.market.endswith("moneyline") and edge.odds > 120 and edge.edge > 0.06:
        return "Undervalued underdog"
    if "under" in edge.market and edge.edge > 0.05:
        return "Finish risk underpriced"
    if "over" in edge.market and edge.edge > 0.05:
        return "Durability/cardio underpriced"
    return "Model-market disagreement"
