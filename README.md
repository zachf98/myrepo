# UFC Quantitative Prediction Engine

A professional Python platform for UFC fight prediction that combines:

- cleaned historical fight and fighter data
- fighter archetype clustering
- matchup-specific feature engineering
- dynamic Elo ratings
- Random Forest, Logistic Regression, optional XGBoost and LightGBM models
- Bayesian updating
- KNN comparable fight search
- round-by-round Monte Carlo simulation
- calibrated ensemble probabilities
- sportsbook edge, EV, and Kelly staking recommendations
- Plotly/Streamlit visualizations
- historical backtesting utilities

The repository ships with deterministic sample data so the full workflow can be
run immediately, while the ingestion layer is designed for CSV exports or
UFCStats-style HTML pages.

## Install

```bash
python -m pip install -e .
```

Optional heavyweight integrations:

```bash
python -m pip install -e ".[boosting,explain,clustering,dev]"
```

## Quick demo

```bash
ufc-quant demo --simulations 5000
```

or:

```bash
python -m ufc_predictor.cli demo --simulations 5000
```

The demo trains on bundled historical sample fights, predicts a fictional
upcoming matchup, runs a Monte Carlo simulation, and prints betting edges for
example odds.

## Streamlit dashboard

```bash
streamlit run ufc_predictor/dashboard.py
```

## Data model

The canonical tables are:

- `fighters`: one row per fighter with demographics, stance, camp, career
  totals, and descriptive statistics.
- `fights`: one row per completed bout with red/blue fighters, winner, method,
  round, duration, weight class, scheduled rounds, and odds if available.
- `fighter_fight_stats`: one row per fighter per fight with striking,
  grappling, damage, pace, and cardio observations.

`ufc_predictor.data` includes CSV loaders, schema normalization, missing-value
cleaning, and a conservative UFCStats HTML parser for local pages or fetched
URLs.

## Major modules

- `data.py` - loading, cleaning, validation, and UFCStats-compatible parsing.
- `features.py` - matchup features, historical style matchup rates, and model
  matrices.
- `archetypes.py` - K-Means, hierarchical, optional HDBSCAN clustering, and
  archetype probability scoring.
- `elo.py` - overall, striking, grappling, and finishing Elo with opponent
  quality, finish bonuses, method effects, recency weighting, and weight-class
  adjustments.
- `models.py` - trainable supervised models, KNN comparable fights, calibration,
  learned ensemble weighting, and prediction APIs.
- `bayes.py` - priors from career, division, style, and recency evidence.
- `simulation.py` - 100k+ capable round-by-round fight simulation with striking,
  grappling, fatigue, cumulative damage, finish method, totals, and confidence
  intervals.
- `betting.py` - odds conversion, edge, EV, Kelly, recommendation labels, and
  card-level market inefficiency ranking.
- `explain.py` - permutation importance and optional SHAP explanations.
- `validation.py` - walk-forward backtesting, Brier score, log loss, calibration
  buckets, and betting ROI accounting.

## Example API

```python
from ufc_predictor.sample_data import build_sample_dataset
from ufc_predictor.engine import PredictionEngine

dataset = build_sample_dataset()
engine = PredictionEngine()
engine.fit(dataset)

prediction = engine.predict_fight(
    red_fighter="Dricus Du Plessis",
    blue_fighter="Khamzat Chimaev",
    odds={"red_moneyline": 135, "blue_moneyline": -155, "over_2_5": -120},
    simulations=10000,
)

print(prediction.summary())
```

## Notes

This project is an analytical engine, not betting advice. Real deployment
requires licensed or otherwise permitted data feeds, sportsbook line history,
injury/news inputs, and out-of-sample monitoring.