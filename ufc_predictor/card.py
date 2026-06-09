"""Upcoming-event betting card generation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ufc_predictor.betting import BettingEdge, detect_market_inefficiencies
from ufc_predictor.engine import FightPrediction, PredictionEngine


ODDS_COLUMNS = {
    "red_moneyline",
    "blue_moneyline",
    "ko_tko",
    "submission",
    "decision",
    "goes_distance",
    "over_1_5",
    "under_1_5",
    "over_2_5",
    "under_2_5",
    "over_3_5",
    "under_3_5",
    "over_4_5",
    "under_4_5",
}


@dataclass(slots=True)
class UpcomingFight:
    red_fighter: str
    blue_fighter: str
    weight_class: str | None = None
    scheduled_rounds: int = 3
    odds: dict[str, float] = field(default_factory=dict)

    @property
    def fight_name(self) -> str:
        return f"{self.red_fighter} vs {self.blue_fighter}"


@dataclass(slots=True)
class BettingCard:
    event_name: str
    fights: list[dict[str, Any]]
    recommendations: pd.DataFrame
    summary_metrics: dict[str, Any]
    market_inefficiencies: pd.DataFrame

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_name": self.event_name,
            "summary_metrics": self.summary_metrics,
            "recommendations": self.recommendations.to_dict(orient="records"),
            "market_inefficiencies": self.market_inefficiencies.to_dict(orient="records"),
            "fights": self.fights,
        }

    def to_markdown(self) -> str:
        lines = [f"# Betting Card: {self.event_name}", ""]
        lines.append("## Summary Metrics")
        for key, value in self.summary_metrics.items():
            lines.append(f"- **{key.replace('_', ' ').title()}**: {_format_metric(value)}")
        lines.append("")

        lines.append("## Ranked Betting Recommendations")
        if self.recommendations.empty:
            lines.append("No positive-EV betting recommendations found.")
        else:
            display = self.recommendations[
                [
                    "rank",
                    "fight",
                    "market",
                    "odds",
                    "model_probability",
                    "implied_probability",
                    "edge",
                    "expected_value",
                    "kelly_fraction",
                    "recommendation",
                ]
            ].copy()
            lines.extend(_markdown_table(display))
        lines.append("")

        lines.append("## Fight Analysis")
        for fight in self.fights:
            lines.extend(
                [
                    f"### {fight['fight']}",
                    f"- Projected winner: **{fight['projected_winner']}** ({fight['projected_winner_probability']:.1%})",
                    (
                        f"- Method probabilities: KO/TKO {fight['ko_tko_probability']:.1%}, "
                        f"Submission {fight['submission_probability']:.1%}, "
                        f"Decision {fight['decision_probability']:.1%}"
                    ),
                    f"- Goes distance: {fight['goes_distance_probability']:.1%}",
                    f"- Confidence interval: {fight['win_probability_ci'][0]:.1%} to {fight['win_probability_ci'][1]:.1%}",
                    f"- Best market: {fight['best_market_summary']}",
                    "- Top factors: " + "; ".join(fight["top_factors"][:3]),
                    "",
                ]
            )
        return "\n".join(lines)


def load_upcoming_event(path: str | Path) -> tuple[str, list[UpcomingFight]]:
    """Load an upcoming event from JSON or CSV.

    JSON can be either:
    {"event": "UFC Example", "fights": [{...}]}
    or a plain list of fight objects. CSV uses one row per fight.
    """

    path = Path(path)
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            event_name = str(raw.get("event", path.stem))
            fights = raw.get("fights", [])
        elif isinstance(raw, list):
            event_name = path.stem
            fights = raw
        else:
            raise ValueError("JSON event file must be an object with fights or a list of fights.")
        return event_name, [_fight_from_mapping(fight) for fight in fights]

    frame = pd.read_csv(path)
    event_name = path.stem.replace("_", " ").title()
    if "event" in frame.columns and not frame["event"].dropna().empty:
        event_name = str(frame["event"].dropna().iloc[0])
    return event_name, [_fight_from_mapping(row) for row in frame.to_dict(orient="records")]


def generate_betting_card(
    engine: PredictionEngine,
    event_name: str,
    fights: list[UpcomingFight],
    simulations: int = 10_000,
) -> BettingCard:
    fight_rows = []
    recommendation_rows = []
    edges_by_fight: dict[str, list[BettingEdge]] = {}

    for fight in fights:
        prediction = engine.predict_fight(
            red_fighter=fight.red_fighter,
            blue_fighter=fight.blue_fighter,
            weight_class=fight.weight_class,
            scheduled_rounds=fight.scheduled_rounds,
            odds=fight.odds,
            simulations=simulations,
        )
        edges_by_fight[fight.fight_name] = prediction.betting_edges
        fight_rows.append(_fight_analysis_row(fight, prediction))
        for edge in prediction.betting_edges:
            recommendation_rows.append(_recommendation_row(fight, prediction, edge))

    recommendations = pd.DataFrame(recommendation_rows)
    if not recommendations.empty:
        recommendations = recommendations.sort_values(["expected_value", "edge"], ascending=False).reset_index(drop=True)
        recommendations.insert(0, "rank", range(1, len(recommendations) + 1))

    inefficiencies = detect_market_inefficiencies(edges_by_fight)
    summary = _summary_metrics(fight_rows, recommendations)
    return BettingCard(
        event_name=event_name,
        fights=fight_rows,
        recommendations=recommendations,
        summary_metrics=summary,
        market_inefficiencies=inefficiencies,
    )


def _fight_from_mapping(data: dict[str, Any]) -> UpcomingFight:
    normalized = {str(key).strip().lower(): value for key, value in data.items()}
    red = normalized.get("red_fighter") or normalized.get("red") or normalized.get("fighter_a")
    blue = normalized.get("blue_fighter") or normalized.get("blue") or normalized.get("fighter_b")
    if not red or not blue:
        raise ValueError("Each fight must include red_fighter and blue_fighter columns/keys.")
    odds = {}
    for key, value in normalized.items():
        if key in ODDS_COLUMNS and pd.notna(value):
            odds[key] = float(value)
    scheduled_rounds = normalized.get("scheduled_rounds", normalized.get("rounds", 3))
    return UpcomingFight(
        red_fighter=str(red),
        blue_fighter=str(blue),
        weight_class=str(normalized["weight_class"]) if pd.notna(normalized.get("weight_class")) else None,
        scheduled_rounds=int(scheduled_rounds) if pd.notna(scheduled_rounds) else 3,
        odds=odds,
    )


def _fight_analysis_row(fight: UpcomingFight, prediction: FightPrediction) -> dict[str, Any]:
    projected_winner = prediction.red_fighter if prediction.red_win_probability >= 0.5 else prediction.blue_fighter
    projected_probability = max(prediction.red_win_probability, prediction.blue_win_probability)
    ci_key = "red_win_probability"
    raw_ci = prediction.confidence_intervals.get(ci_key, (prediction.red_win_probability, prediction.red_win_probability))
    if projected_winner == prediction.blue_fighter:
        win_ci = (1.0 - raw_ci[1], 1.0 - raw_ci[0])
    else:
        win_ci = raw_ci
    best_edge = prediction.betting_edges[0] if prediction.betting_edges else None
    return {
        "fight": fight.fight_name,
        "red_fighter": fight.red_fighter,
        "blue_fighter": fight.blue_fighter,
        "weight_class": fight.weight_class,
        "scheduled_rounds": fight.scheduled_rounds,
        "projected_winner": projected_winner,
        "projected_winner_probability": projected_probability,
        "red_win_probability": prediction.red_win_probability,
        "blue_win_probability": prediction.blue_win_probability,
        "ko_tko_probability": prediction.ko_tko_probability,
        "submission_probability": prediction.submission_probability,
        "decision_probability": prediction.decision_probability,
        "goes_distance_probability": prediction.goes_distance_probability,
        "win_probability_ci": tuple(float(value) for value in win_ci),
        "best_market_summary": _edge_summary(best_edge),
        "best_edge": best_edge.edge if best_edge else 0.0,
        "best_expected_value": best_edge.expected_value if best_edge else 0.0,
        "top_factors": prediction.top_factors,
        "model_breakdown": prediction.model_breakdown,
        "bayesian_components": prediction.bayesian_components,
        "finish_round_distribution": prediction.finish_round_distribution,
    }


def _recommendation_row(fight: UpcomingFight, prediction: FightPrediction, edge: BettingEdge) -> dict[str, Any]:
    winner = prediction.red_fighter if prediction.red_win_probability >= 0.5 else prediction.blue_fighter
    row = asdict(edge)
    row.update(
        {
            "fight": fight.fight_name,
            "projected_winner": winner,
            "red_win_probability": prediction.red_win_probability,
            "blue_win_probability": prediction.blue_win_probability,
            "goes_distance_probability": prediction.goes_distance_probability,
            "top_factor": prediction.top_factors[0] if prediction.top_factors else "",
        }
    )
    return row


def _summary_metrics(fight_rows: list[dict[str, Any]], recommendations: pd.DataFrame) -> dict[str, Any]:
    positive = recommendations[recommendations["expected_value"] > 0] if not recommendations.empty else pd.DataFrame()
    strong = recommendations[recommendations["recommendation"] == "Strong Value"] if not recommendations.empty else pd.DataFrame()
    moderate = recommendations[recommendations["recommendation"] == "Moderate Value"] if not recommendations.empty else pd.DataFrame()
    pass_count = int((recommendations["recommendation"] == "Pass").sum()) if not recommendations.empty else 0
    return {
        "fights_analyzed": len(fight_rows),
        "markets_analyzed": int(len(recommendations)),
        "positive_ev_markets": int(len(positive)),
        "strong_value_markets": int(len(strong)),
        "moderate_value_markets": int(len(moderate)),
        "pass_markets": pass_count,
        "average_best_edge": float(pd.Series([row["best_edge"] for row in fight_rows]).mean()) if fight_rows else 0.0,
        "average_projected_winner_confidence": float(pd.Series([row["projected_winner_probability"] for row in fight_rows]).mean()) if fight_rows else 0.0,
        "total_recommended_kelly": float(positive["kelly_fraction"].sum()) if not positive.empty else 0.0,
        "best_expected_value": float(recommendations["expected_value"].max()) if not recommendations.empty else 0.0,
    }


def _edge_summary(edge: BettingEdge | None) -> str:
    if edge is None:
        return "No odds supplied"
    return (
        f"{edge.market} {edge.odds:+.0f}: model {edge.model_probability:.1%}, "
        f"edge {edge.edge:.1%}, EV {edge.expected_value:.1%}, {edge.recommendation}"
    )


def _format_metric(value: Any) -> str:
    if isinstance(value, float):
        if abs(value) <= 1:
            return f"{value:.1%}"
        return f"{value:.2f}"
    return str(value)


def _markdown_table(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return []
    formatted = frame.copy()
    for column in ["model_probability", "implied_probability", "edge", "expected_value", "kelly_fraction"]:
        if column in formatted:
            formatted[column] = formatted[column].map(lambda value: f"{float(value):.1%}")
    if "odds" in formatted:
        formatted["odds"] = formatted["odds"].map(lambda value: f"{float(value):+.0f}")
    columns = list(formatted.columns)
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for record in formatted.to_dict(orient="records"):
        rows.append("| " + " | ".join(str(record[column]) for column in columns) + " |")
    return rows
