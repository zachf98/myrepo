"""Unsupervised fighter archetype analysis."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from ufc_predictor.data import UFCDataset
from ufc_predictor.features import PROFILE_NUMERIC_COLUMNS, build_fighter_profiles


ARCHETYPES = [
    "Pressure Striker",
    "Technical Kickboxer",
    "Counter Striker",
    "Power Puncher",
    "Offensive Wrestler",
    "Control Wrestler",
    "Submission Hunter",
    "BJJ Specialist",
    "Well-Rounded",
    "Cardio Machine",
    "Aging Veteran",
]


@dataclass(slots=True)
class ArchetypeResult:
    scores: pd.DataFrame
    kmeans_labels: np.ndarray
    hierarchical_labels: np.ndarray
    hdbscan_labels: np.ndarray | None
    silhouette: float | None


class ArchetypeClassifier:
    """Cluster fighters and assign interpretable archetype probabilities."""

    def __init__(self, n_clusters: int = 8, random_state: int = 42) -> None:
        self.n_clusters = n_clusters
        self.random_state = random_state
        self.scaler = StandardScaler()
        self.kmeans: KMeans | None = None
        self.hierarchical: AgglomerativeClustering | None = None

    def fit_predict(self, dataset: UFCDataset) -> ArchetypeResult:
        profiles = build_fighter_profiles(dataset)
        numeric = profiles[[column for column in PROFILE_NUMERIC_COLUMNS if column in profiles.columns]].fillna(0.0)
        scaled = self.scaler.fit_transform(numeric)
        cluster_count = max(2, min(self.n_clusters, len(profiles)))

        self.kmeans = KMeans(n_clusters=cluster_count, n_init=10, random_state=self.random_state)
        kmeans_labels = self.kmeans.fit_predict(scaled)
        self.hierarchical = AgglomerativeClustering(n_clusters=cluster_count)
        hierarchical_labels = self.hierarchical.fit_predict(scaled)

        hdbscan_labels = self._try_hdbscan(scaled)
        silhouette = None
        if len(set(kmeans_labels)) > 1 and len(profiles) > cluster_count:
            silhouette = float(silhouette_score(scaled, kmeans_labels))

        scores = self._score_archetypes(profiles, kmeans_labels)
        return ArchetypeResult(scores, kmeans_labels, hierarchical_labels, hdbscan_labels, silhouette)

    def _try_hdbscan(self, scaled: np.ndarray) -> np.ndarray | None:
        try:
            import hdbscan  # type: ignore
        except Exception:
            return None
        min_cluster_size = max(2, min(8, len(scaled) // 4 or 2))
        return hdbscan.HDBSCAN(min_cluster_size=min_cluster_size).fit_predict(scaled)

    def _score_archetypes(self, profiles: pd.DataFrame, labels: np.ndarray) -> pd.DataFrame:
        normalized = profiles.copy()
        for column in PROFILE_NUMERIC_COLUMNS:
            if column in normalized:
                series = normalized[column].astype(float)
                span = series.max() - series.min()
                normalized[f"z_{column}"] = 0.5 if span == 0 else (series - series.min()) / span

        rows = []
        for idx, fighter in normalized.iterrows():
            raw = {
                "Pressure Striker": 0.55 * fighter["z_sig_str_lpm"] + 0.25 * fighter["z_pace_index"] + 0.20 * (1 - fighter["z_sig_str_abs_lpm"]),
                "Technical Kickboxer": 0.35 * fighter["z_str_acc"] + 0.35 * fighter["z_str_def"] + 0.30 * fighter["z_reach_in"],
                "Counter Striker": 0.45 * fighter["z_str_def"] + 0.30 * (1 - fighter["z_pace_index"]) + 0.25 * fighter["z_kd_per_fight"],
                "Power Puncher": 0.65 * fighter["z_kd_per_fight"] + 0.20 * fighter["z_sig_str_lpm"] + 0.15 * fighter["z_head_strike_pct"],
                "Offensive Wrestler": 0.55 * fighter["z_td_per_15"] + 0.25 * fighter["z_td_acc"] + 0.20 * fighter["z_control_seconds"],
                "Control Wrestler": 0.50 * fighter["z_control_seconds"] + 0.25 * fighter["z_td_def"] + 0.25 * fighter["z_td_per_15"],
                "Submission Hunter": 0.65 * fighter["z_sub_att_per_15"] + 0.20 * fighter["z_td_acc"] + 0.15 * fighter["z_ground_strike_rate"],
                "BJJ Specialist": 0.50 * fighter["z_sub_att_per_15"] + 0.25 * (1 - fighter["z_sig_str_lpm"]) + 0.25 * fighter["z_td_def"],
                "Well-Rounded": 1.0 - np.std(
                    [
                        fighter["z_sig_str_lpm"],
                        fighter["z_str_def"],
                        fighter["z_td_per_15"],
                        fighter["z_td_def"],
                        fighter["z_sub_att_per_15"],
                    ]
                ),
                "Cardio Machine": 0.65 * fighter["z_cardio_index"] + 0.20 * fighter["z_five_round_fights"] + 0.15 * fighter["z_pace_index"],
                "Aging Veteran": 0.45 * fighter["z_age"] + 0.35 * fighter["z_total_fights"] + 0.20 * fighter["z_ufc_fights"],
            }
            values = np.array([max(0.001, float(raw[name])) for name in ARCHETYPES])
            probabilities = values / values.sum()
            row = {"fighter": fighter["fighter"], "cluster": int(labels[idx])}
            row.update({name: float(prob) for name, prob in zip(ARCHETYPES, probabilities)})
            rows.append(row)
        return pd.DataFrame(rows)
