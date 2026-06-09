"""Command line interface for the UFC quantitative engine."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from ufc_predictor.card import generate_betting_card, load_upcoming_event
from ufc_predictor.engine import PredictionEngine
from ufc_predictor.sample_data import build_sample_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="UFC quantitative prediction engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="Run the bundled Dricus vs Khamzat demo")
    demo.add_argument("--red", default="Dricus Du Plessis")
    demo.add_argument("--blue", default="Khamzat Chimaev")
    demo.add_argument("--weight-class", default="Middleweight")
    demo.add_argument("--scheduled-rounds", type=int, default=5)
    demo.add_argument("--simulations", type=int, default=5000)
    demo.add_argument("--red-moneyline", type=float, default=135)
    demo.add_argument("--blue-moneyline", type=float, default=-155)
    demo.add_argument("--over-2-5", type=float, default=-120)
    demo.add_argument("--json", action="store_true", help="Emit a JSON summary")

    card = subparsers.add_parser("card", help="Generate a betting card for an upcoming event file")
    card.add_argument(
        "--event-file",
        default="examples/upcoming_event.json",
        help="JSON or CSV with red_fighter, blue_fighter, weight_class, scheduled_rounds, and odds columns",
    )
    card.add_argument("--simulations", type=int, default=5000)
    card.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown")
    card.add_argument("--output", help="Optional path to save the betting card")

    args = parser.parse_args()
    if args.command == "demo":
        run_demo(args)
    elif args.command == "card":
        run_card(args)


def run_demo(args: argparse.Namespace) -> None:
    dataset = build_sample_dataset()
    engine = PredictionEngine()
    engine.fit(dataset)
    prediction = engine.predict_fight(
        red_fighter=args.red,
        blue_fighter=args.blue,
        weight_class=args.weight_class,
        scheduled_rounds=args.scheduled_rounds,
        odds={
            "red_moneyline": args.red_moneyline,
            "blue_moneyline": args.blue_moneyline,
            "over_2_5": args.over_2_5,
        },
        simulations=args.simulations,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "red_fighter": prediction.red_fighter,
                    "blue_fighter": prediction.blue_fighter,
                    "red_win_probability": prediction.red_win_probability,
                    "blue_win_probability": prediction.blue_win_probability,
                    "ko_tko_probability": prediction.ko_tko_probability,
                    "submission_probability": prediction.submission_probability,
                    "decision_probability": prediction.decision_probability,
                    "goes_distance_probability": prediction.goes_distance_probability,
                    "finish_round_distribution": prediction.finish_round_distribution,
                    "betting_edges": [asdict(edge) for edge in prediction.betting_edges],
                    "top_factors": prediction.top_factors,
                },
                indent=2,
            )
        )
        return

    print(prediction.summary())
    print("\nModel breakdown")
    for name, value in sorted(prediction.model_breakdown.items()):
        print(f"  {name}: {value:.3f}")
    if prediction.betting_edges:
        print("\nBetting edges")
        for edge in prediction.betting_edges:
            print(
                f"  {edge.market}: model={edge.model_probability:.1%} implied={edge.implied_probability:.1%} "
                f"edge={edge.edge:.1%} EV={edge.expected_value:.1%} Kelly={edge.kelly_fraction:.1%} {edge.recommendation}"
            )
    print("\nTop comparable fights")
    for row in prediction.comparable_fights.head(5).itertuples(index=False):
        print(f"  {row.red_fighter} vs {row.blue_fighter}: {row.winner} by {row.method} (similarity={row.similarity:.2f})")


def run_card(args: argparse.Namespace) -> None:
    dataset = build_sample_dataset()
    engine = PredictionEngine()
    engine.fit(dataset)
    event_name, fights = load_upcoming_event(args.event_file)
    card = generate_betting_card(engine, event_name, fights, simulations=args.simulations)
    if args.json:
        rendered = json.dumps(card.to_dict(), indent=2, default=str)
    else:
        rendered = card.to_markdown()

    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
