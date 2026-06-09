import pandas as pd

from ufc_predictor.betting import evaluate_market
from ufc_predictor.card import generate_betting_card, load_upcoming_event
from ufc_predictor.engine import PredictionEngine
from ufc_predictor.sample_data import build_sample_dataset
from ufc_predictor.validation import calibration_table, classification_metrics


def test_sample_dataset_is_canonical():
    dataset = build_sample_dataset()
    assert len(dataset.fighters) >= 10
    assert len(dataset.fights) >= 20
    assert {"fighter", "age", "reach_in"}.issubset(dataset.fighters.columns)
    assert {"fight_id", "winner", "method"}.issubset(dataset.fights.columns)
    assert {"sig_str_lpm", "td_def", "sub_att_per_15"}.issubset(dataset.fighter_fight_stats.columns)


def test_prediction_engine_outputs_probabilities_and_edges():
    dataset = build_sample_dataset()
    engine = PredictionEngine(random_state=123).fit(dataset)
    prediction = engine.predict_fight(
        "Dricus Du Plessis",
        "Khamzat Chimaev",
        weight_class="Middleweight",
        scheduled_rounds=5,
        simulations=250,
        odds={"red_moneyline": 135, "blue_moneyline": -155},
    )

    assert 0.0 <= prediction.red_win_probability <= 1.0
    assert 0.0 <= prediction.blue_win_probability <= 1.0
    assert abs(prediction.red_win_probability + prediction.blue_win_probability - 1.0) < 1e-9
    method_total = prediction.ko_tko_probability + prediction.submission_probability + prediction.decision_probability
    assert abs(method_total - 1.0) < 1e-9
    assert prediction.confidence_intervals
    assert prediction.betting_edges
    assert not prediction.comparable_fights.empty
    assert prediction.top_factors


def test_betting_math_and_validation_tables():
    edge = evaluate_market("red_moneyline", 0.55, 120)
    assert edge.implied_probability > 0
    assert edge.expected_value > 0

    metrics = classification_metrics(
        y_true=pd.Series([1, 0, 1, 0]),
        probabilities=pd.Series([0.8, 0.4, 0.7, 0.2]),
    )
    assert {"accuracy", "brier_score", "log_loss"}.issubset(metrics)

    table = calibration_table(
        y_true=pd.Series([1, 0, 1, 0]),
        probabilities=pd.Series([0.8, 0.4, 0.7, 0.2]),
        bins=4,
    )
    assert not table.empty


def test_betting_card_for_upcoming_event_template():
    dataset = build_sample_dataset()
    engine = PredictionEngine(random_state=321).fit(dataset)
    event_name, fights = load_upcoming_event("examples/upcoming_event.json")

    card = generate_betting_card(engine, event_name, fights[:2], simulations=200)

    assert card.event_name == "Sample UFC Betting Card"
    assert card.summary_metrics["fights_analyzed"] == 2
    assert card.summary_metrics["markets_analyzed"] > 0
    assert not card.recommendations.empty
    assert {"fight", "market", "edge", "expected_value", "recommendation"}.issubset(card.recommendations.columns)
    assert card.fights[0]["top_factors"]
    assert "Betting Card" in card.to_markdown()
    assert card.to_dict()["recommendations"]
