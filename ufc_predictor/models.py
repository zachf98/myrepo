"""Machine-learning models, calibration, ensembling, and comparable fights."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.neighbors import KNeighborsClassifier, NearestNeighbors
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ufc_predictor.features import FeatureBundle, MODEL_FEATURE_COLUMNS


@dataclass(slots=True)
class ModelProbabilities:
    red_win_probability: float
    finish_probability: float
    ko_tko_probability: float
    submission_probability: float
    decision_probability: float
    goes_distance_probability: float
    model_breakdown: dict[str, float]
    ensemble_weights: dict[str, float]


@dataclass(slots=True)
class ComparableFight:
    fight_id: str
    winner: str
    method: str
    round: int
    similarity: float
    red_won: bool


@dataclass(slots=True)
class FightModelSuite:
    random_state: int = 42
    calibration: str | None = "isotonic"
    winner_models: dict[str, Any] = field(default_factory=dict)
    finish_models: dict[str, Any] = field(default_factory=dict)
    method_model: Any | None = None
    comparable_index: NearestNeighbors | None = None
    comparable_features: pd.DataFrame | None = None
    comparable_bundle: FeatureBundle | None = None
    ensemble_weights: dict[str, float] = field(default_factory=dict)
    feature_columns: list[str] = field(default_factory=lambda: MODEL_FEATURE_COLUMNS.copy())

    def fit(self, bundle: FeatureBundle) -> "FightModelSuite":
        x = bundle.x[self.feature_columns].fillna(0.0)
        self.winner_models = self._fit_binary_models(x, bundle.y_winner, "winner")
        self.finish_models = self._fit_binary_models(x, bundle.y_finish, "finish")
        self.method_model = self._fit_method_model(x, bundle.y_method)
        self.ensemble_weights = self._learn_weights(self.winner_models, x, bundle.y_winner)
        self.comparable_features = x.copy()
        self.comparable_bundle = bundle
        neighbors = min(100, len(x))
        if neighbors:
            self.comparable_index = NearestNeighbors(n_neighbors=neighbors, metric="cosine")
            self.comparable_index.fit(StandardScaler().fit_transform(x))
        return self

    def predict(self, row: pd.Series | pd.DataFrame) -> ModelProbabilities:
        x = _ensure_frame(row, self.feature_columns)
        model_breakdown = {name: _predict_positive(model, x) for name, model in self.winner_models.items()}
        red_win = self._weighted_average(model_breakdown, default=0.5)
        finish_breakdown = {name: _predict_positive(model, x) for name, model in self.finish_models.items()}
        finish_probability = float(np.mean(list(finish_breakdown.values()))) if finish_breakdown else 0.45

        method_probs = self._predict_method(x)
        ko = method_probs.get("ko_tko", finish_probability * 0.6)
        sub = method_probs.get("submission", finish_probability * 0.4)
        decision = method_probs.get("decision", 1.0 - finish_probability)
        total = ko + sub + decision
        ko, sub, decision = ko / total, sub / total, decision / total
        return ModelProbabilities(
            red_win_probability=float(red_win),
            finish_probability=float(finish_probability),
            ko_tko_probability=float(ko),
            submission_probability=float(sub),
            decision_probability=float(decision),
            goes_distance_probability=float(decision),
            model_breakdown={**model_breakdown, **{f"finish_{k}": v for k, v in finish_breakdown.items()}},
            ensemble_weights=self.ensemble_weights.copy(),
        )

    def comparable_fights(self, row: pd.Series | pd.DataFrame, fights: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
        if self.comparable_index is None or self.comparable_features is None or self.comparable_bundle is None:
            return pd.DataFrame()
        x = _ensure_frame(row, self.feature_columns)
        scaler = StandardScaler().fit(self.comparable_features)
        distances, indices = self.comparable_index.kneighbors(scaler.transform(x), n_neighbors=min(top_n, len(self.comparable_features)))
        rows = []
        fight_lookup = fights.set_index("fight_id")
        for distance, index in zip(distances[0], indices[0]):
            fight_id = self.comparable_bundle.fight_ids.iloc[index]
            fight = fight_lookup.loc[fight_id]
            rows.append(
                {
                    "fight_id": fight_id,
                    "red_fighter": fight.red_fighter,
                    "blue_fighter": fight.blue_fighter,
                    "winner": fight.winner,
                    "method": fight.method,
                    "round": int(fight["round"]),
                    "similarity": float(1.0 - distance),
                    "red_won": bool(self.comparable_bundle.y_winner.iloc[index]),
                }
            )
        return pd.DataFrame(rows)

    def _fit_binary_models(self, x: pd.DataFrame, y: pd.Series, target: str) -> dict[str, Any]:
        if y.nunique() < 2:
            return {"constant": ConstantProbability(float(y.mean()))}

        candidates: dict[str, Any] = {
            "random_forest": RandomForestClassifier(
                n_estimators=250,
                min_samples_leaf=2,
                class_weight="balanced_subsample",
                random_state=self.random_state,
            ),
            "logistic_regression": Pipeline(
                [
                    ("scaler", StandardScaler()),
                    ("model", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=self.random_state)),
                ]
            ),
        }
        if target == "winner":
            candidates["xgboost"] = _optional_xgboost(self.random_state)
        if target == "finish":
            candidates["lightgbm"] = _optional_lightgbm(self.random_state)

        fitted = {}
        for name, model in candidates.items():
            if model is None:
                continue
            try:
                model.fit(x, y)
                fitted[name] = self._calibrate_if_possible(model, x, y)
            except Exception:
                continue
        return fitted or {"constant": ConstantProbability(float(y.mean()))}

    def _fit_method_model(self, x: pd.DataFrame, y: pd.Series) -> Any:
        if y.nunique() < 2:
            return ConstantMulticlass(y.iloc[0])
        model = RandomForestClassifier(n_estimators=250, min_samples_leaf=2, class_weight="balanced", random_state=self.random_state)
        model.fit(x, y)
        return model

    def _calibrate_if_possible(self, model: Any, x: pd.DataFrame, y: pd.Series) -> Any:
        if self.calibration not in {"isotonic", "sigmoid"}:
            return model
        min_class_count = int(y.value_counts().min())
        if min_class_count < 3 or len(y) < 12:
            return model
        cv = min(5, min_class_count)
        try:
            calibrated = CalibratedClassifierCV(estimator=model, cv=cv, method=self.calibration)
        except TypeError:
            calibrated = CalibratedClassifierCV(base_estimator=model, cv=cv, method=self.calibration)
        calibrated.fit(x, y)
        return calibrated

    def _learn_weights(self, models: dict[str, Any], x: pd.DataFrame, y: pd.Series) -> dict[str, float]:
        losses = {}
        for name, model in models.items():
            try:
                prob = np.array([_predict_positive(model, x.iloc[[idx]]) for idx in range(len(x))])
                losses[name] = max(brier_score_loss(y, prob), 1e-6)
            except Exception:
                continue
        if not losses:
            return {name: 1.0 / len(models) for name in models}
        inverse = {name: 1.0 / loss for name, loss in losses.items()}
        total = sum(inverse.values())
        return {name: value / total for name, value in inverse.items()}

    def _weighted_average(self, probabilities: dict[str, float], default: float) -> float:
        if not probabilities:
            return default
        weights = self.ensemble_weights or {name: 1.0 / len(probabilities) for name in probabilities}
        total_weight = sum(weights.get(name, 0.0) for name in probabilities)
        if total_weight <= 0:
            return float(np.mean(list(probabilities.values())))
        return float(sum(probabilities[name] * weights.get(name, 0.0) for name in probabilities) / total_weight)

    def _predict_method(self, x: pd.DataFrame) -> dict[str, float]:
        if self.method_model is None:
            return {"ko_tko": 0.3, "submission": 0.18, "decision": 0.52}
        if isinstance(self.method_model, ConstantMulticlass):
            return self.method_model.predict_proba_dict()
        probabilities = self.method_model.predict_proba(x)[0]
        return {str(label): float(prob) for label, prob in zip(self.method_model.classes_, probabilities)}


class ConstantProbability:
    def __init__(self, probability: float) -> None:
        self.probability = float(np.clip(probability, 0.01, 0.99))

    def fit(self, *_: object) -> "ConstantProbability":
        return self

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        return np.tile([1.0 - self.probability, self.probability], (len(x), 1))


class ConstantMulticlass:
    def __init__(self, label: str) -> None:
        self.label = label

    def predict_proba_dict(self) -> dict[str, float]:
        return {"ko_tko": 0.0, "submission": 0.0, "decision": 0.0, self.label: 1.0}


def _ensure_frame(row: pd.Series | pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if isinstance(row, pd.Series):
        frame = row.to_frame().T
    else:
        frame = row.copy()
    return frame.reindex(columns=columns).fillna(0.0)


def _predict_positive(model: Any, x: pd.DataFrame) -> float:
    probabilities = model.predict_proba(x)
    classes = getattr(model, "classes_", None)
    if classes is None and hasattr(model, "named_steps"):
        classes = model.named_steps["model"].classes_
    if classes is None:
        return float(probabilities[0, -1])
    class_list = list(classes)
    index = class_list.index(1) if 1 in class_list else -1
    return float(np.clip(probabilities[0, index], 0.001, 0.999))


def _optional_xgboost(random_state: int) -> Any | None:
    try:
        from xgboost import XGBClassifier  # type: ignore
    except Exception:
        return None
    return XGBClassifier(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.04,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="logloss",
        random_state=random_state,
    )


def _optional_lightgbm(random_state: int) -> Any | None:
    try:
        from lightgbm import LGBMClassifier  # type: ignore
    except Exception:
        return None
    return LGBMClassifier(
        n_estimators=250,
        learning_rate=0.03,
        num_leaves=15,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=random_state,
        verbose=-1,
    )


def model_metrics(y_true: pd.Series, probabilities: np.ndarray) -> dict[str, float]:
    return {
        "brier_score": float(brier_score_loss(y_true, probabilities)),
        "log_loss": float(log_loss(y_true, np.clip(probabilities, 0.001, 0.999))),
    }
