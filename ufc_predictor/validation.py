"""Backtesting, calibration, and betting ROI validation."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

from ufc_predictor.betting import evaluate_market, kelly_fraction
from ufc_predictor.data import UFCDataset


def calibration_table(y_true: pd.Series, probabilities: pd.Series, bins: int = 10) -> pd.DataFrame:
    frame = pd.DataFrame({"actual": y_true.astype(float), "probability": probabilities.astype(float)})
    frame["bucket"] = pd.cut(frame["probability"], bins=np.linspace(0, 1, bins + 1), include_lowest=True)
    return (
        frame.groupby("bucket", observed=True)
        .agg(count=("actual", "size"), predicted=("probability", "mean"), observed=("actual", "mean"))
        .reset_index()
    )


def classification_metrics(y_true: pd.Series, probabilities: pd.Series) -> dict[str, float]:
    clipped = np.clip(probabilities, 0.001, 0.999)
    return {
        "accuracy": float(accuracy_score(y_true, probabilities >= 0.5)),
        "brier_score": float(brier_score_loss(y_true, clipped)),
        "log_loss": float(log_loss(y_true, clipped)),
    }


def betting_roi(
    outcomes: pd.Series,
    probabilities: pd.Series,
    odds: pd.Series,
    staking: str = "flat",
    bankroll: float = 1_000.0,
) -> dict[str, float]:
    balance = bankroll
    risked = 0.0
    bets = 0
    for outcome, probability, price in zip(outcomes, probabilities, odds):
        edge = evaluate_market("moneyline", probability, price)
        if edge.expected_value <= 0:
            continue
        stake = 10.0 if staking == "flat" else balance * kelly_fraction(probability, price)
        if stake <= 0:
            continue
        bets += 1
        risked += stake
        if outcome:
            balance += stake * (edge.odds / 100.0 if edge.odds > 0 else 100.0 / abs(edge.odds))
        else:
            balance -= stake
    profit = balance - bankroll
    return {
        "starting_bankroll": bankroll,
        "ending_bankroll": balance,
        "profit": profit,
        "risked": risked,
        "roi": profit / risked if risked else 0.0,
        "bets": float(bets),
    }


def walk_forward_backtest(
    dataset: UFCDataset,
    engine_factory: Callable[[], object],
    min_train_fights: int = 20,
) -> pd.DataFrame:
    """Walk-forward backtest that refits before each event after warmup."""

    fights = dataset.fights.sort_values("date").reset_index(drop=True)
    rows = []
    for idx in range(min_train_fights, len(fights)):
        train_ids = set(fights.iloc[:idx]["fight_id"])
        test_fight = fights.iloc[idx]
        train = UFCDataset(
            fighters=dataset.fighters.copy(),
            fights=fights.iloc[:idx].copy(),
            fighter_fight_stats=dataset.fighter_fight_stats[dataset.fighter_fight_stats["fight_id"].isin(train_ids)].copy(),
        )
        engine = engine_factory()
        engine.fit(train)
        prediction = engine.predict_fight(
            test_fight.red_fighter,
            test_fight.blue_fighter,
            weight_class=test_fight.weight_class,
            scheduled_rounds=int(test_fight.scheduled_rounds),
            simulations=1000,
        )
        actual = int(test_fight.winner == test_fight.red_fighter)
        rows.append(
            {
                "fight_id": test_fight.fight_id,
                "date": test_fight.date,
                "red_fighter": test_fight.red_fighter,
                "blue_fighter": test_fight.blue_fighter,
                "actual_red_win": actual,
                "predicted_red_win": prediction.red_win_probability,
                "method": test_fight.method,
            }
        )
    return pd.DataFrame(rows)
