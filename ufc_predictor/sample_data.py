"""Deterministic sample dataset for demos and tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ufc_predictor.data import UFCDataset, clean_fighter_fight_stats, clean_fighters, clean_fights


def build_sample_dataset() -> UFCDataset:
    fighters = pd.DataFrame(
        [
            _fighter("Dricus Du Plessis", 32, 73, 76, "Middleweight", "Orthodox", 25, 9, 3, 3, 4.8, 3.9, 0.51, 0.54, 0.75, 2.7, 0.42, 0.58, 88, 1.1, 0.78, 0.72),
            _fighter("Khamzat Chimaev", 32, 74, 75, "Middleweight", "Orthodox", 15, 8, 1, 2, 5.9, 2.1, 0.58, 0.61, 0.85, 4.5, 0.57, 0.82, 160, 2.4, 0.69, 0.76),
            _fighter("Sean Strickland", 35, 73, 76, "Middleweight", "Orthodox", 35, 20, 4, 7, 6.0, 4.2, 0.42, 0.64, 0.25, 0.9, 0.32, 0.84, 55, 0.2, 0.86, 0.88),
            _fighter("Israel Adesanya", 36, 76, 80, "Middleweight", "Switch", 30, 18, 10, 12, 3.9, 3.0, 0.49, 0.57, 0.55, 0.1, 0.14, 0.77, 18, 0.0, 0.73, 0.56),
            _fighter("Robert Whittaker", 35, 72, 73, "Middleweight", "Orthodox", 33, 22, 7, 9, 4.6, 3.4, 0.43, 0.60, 0.42, 1.0, 0.38, 0.82, 62, 0.0, 0.82, 0.68),
            _fighter("Paulo Costa", 35, 73, 72, "Middleweight", "Orthodox", 18, 10, 1, 3, 6.2, 6.4, 0.57, 0.47, 0.85, 0.5, 0.75, 0.79, 35, 0.1, 0.58, 0.80),
            _fighter("Jared Cannonier", 42, 71, 77, "Middleweight", "Switch", 26, 18, 1, 5, 4.7, 4.0, 0.50, 0.59, 0.70, 0.3, 0.46, 0.62, 30, 0.0, 0.65, 0.62),
            _fighter("Marvin Vettori", 32, 72, 74, "Middleweight", "Southpaw", 29, 17, 2, 6, 4.4, 3.8, 0.45, 0.58, 0.20, 1.8, 0.44, 0.74, 118, 0.6, 0.84, 0.70),
            _fighter("Alex Pereira", 38, 76, 79, "Light Heavyweight", "Orthodox", 14, 9, 6, 6, 5.0, 3.7, 0.62, 0.55, 1.05, 0.2, 0.50, 0.70, 20, 0.0, 0.66, 0.57),
            _fighter("Magomed Ankalaev", 34, 75, 75, "Light Heavyweight", "Southpaw", 24, 15, 2, 4, 3.8, 2.4, 0.52, 0.60, 0.55, 1.1, 0.36, 0.86, 84, 0.1, 0.73, 0.52),
            _fighter("Islam Makhachev", 34, 70, 70, "Lightweight", "Southpaw", 29, 16, 8, 8, 2.6, 1.5, 0.59, 0.62, 0.30, 3.2, 0.61, 0.90, 180, 1.5, 0.82, 0.48),
            _fighter("Charles Oliveira", 36, 70, 74, "Lightweight", "Orthodox", 46, 33, 6, 8, 3.5, 3.2, 0.53, 0.52, 0.42, 2.1, 0.40, 0.56, 95, 2.7, 0.76, 0.64),
        ]
    )

    fights = pd.DataFrame(
        [
            _fight("f001", "2019-04-13", "Israel Adesanya", "Marvin Vettori", "Israel Adesanya", "Decision", 3, 900, "Middleweight", 3),
            _fight("f002", "2019-08-17", "Paulo Costa", "Robert Whittaker", "Paulo Costa", "KO/TKO", 2, 510, "Middleweight", 3),
            _fight("f003", "2020-03-07", "Sean Strickland", "Jared Cannonier", "Sean Strickland", "Decision", 3, 900, "Middleweight", 3),
            _fight("f004", "2020-09-26", "Israel Adesanya", "Paulo Costa", "Israel Adesanya", "KO/TKO", 2, 429, "Middleweight", 5),
            _fight("f005", "2021-01-23", "Robert Whittaker", "Marvin Vettori", "Robert Whittaker", "Decision", 5, 1500, "Middleweight", 5),
            _fight("f006", "2021-04-10", "Dricus Du Plessis", "Jared Cannonier", "Dricus Du Plessis", "KO/TKO", 3, 690, "Middleweight", 3),
            _fight("f007", "2021-10-30", "Khamzat Chimaev", "Marvin Vettori", "Khamzat Chimaev", "Submission", 1, 205, "Middleweight", 3),
            _fight("f008", "2022-02-12", "Israel Adesanya", "Robert Whittaker", "Israel Adesanya", "Decision", 5, 1500, "Middleweight", 5),
            _fight("f009", "2022-07-02", "Sean Strickland", "Alex Pereira", "Alex Pereira", "KO/TKO", 1, 276, "Middleweight", 3),
            _fight("f010", "2022-10-22", "Islam Makhachev", "Charles Oliveira", "Islam Makhachev", "Submission", 2, 522, "Lightweight", 5),
            _fight("f011", "2022-12-17", "Jared Cannonier", "Sean Strickland", "Jared Cannonier", "Decision", 5, 1500, "Middleweight", 5),
            _fight("f012", "2023-01-21", "Magomed Ankalaev", "Alex Pereira", "Magomed Ankalaev", "Decision", 5, 1500, "Light Heavyweight", 5),
            _fight("f013", "2023-07-08", "Dricus Du Plessis", "Robert Whittaker", "Dricus Du Plessis", "KO/TKO", 2, 543, "Middleweight", 3),
            _fight("f014", "2023-09-10", "Sean Strickland", "Israel Adesanya", "Sean Strickland", "Decision", 5, 1500, "Middleweight", 5),
            _fight("f015", "2023-10-21", "Khamzat Chimaev", "Paulo Costa", "Khamzat Chimaev", "Decision", 3, 900, "Middleweight", 3),
            _fight("f016", "2024-01-20", "Dricus Du Plessis", "Sean Strickland", "Dricus Du Plessis", "Decision", 5, 1500, "Middleweight", 5),
            _fight("f017", "2024-04-13", "Alex Pereira", "Magomed Ankalaev", "Alex Pereira", "KO/TKO", 2, 420, "Light Heavyweight", 5),
            _fight("f018", "2024-06-01", "Islam Makhachev", "Charles Oliveira", "Islam Makhachev", "Decision", 5, 1500, "Lightweight", 5),
            _fight("f019", "2024-08-17", "Dricus Du Plessis", "Israel Adesanya", "Dricus Du Plessis", "Submission", 4, 1060, "Middleweight", 5),
            _fight("f020", "2024-10-26", "Khamzat Chimaev", "Robert Whittaker", "Khamzat Chimaev", "Submission", 1, 217, "Middleweight", 5),
            _fight("f021", "2025-02-08", "Sean Strickland", "Paulo Costa", "Sean Strickland", "Decision", 5, 1500, "Middleweight", 5),
            _fight("f022", "2025-04-12", "Magomed Ankalaev", "Jared Cannonier", "Magomed Ankalaev", "Decision", 3, 900, "Light Heavyweight", 3),
            _fight("f023", "2025-07-05", "Charles Oliveira", "Marvin Vettori", "Charles Oliveira", "Submission", 2, 610, "Middleweight", 3),
            _fight("f024", "2025-10-11", "Alex Pereira", "Paulo Costa", "Alex Pereira", "KO/TKO", 1, 318, "Light Heavyweight", 3),
        ]
    )
    stats = _build_stats(fighters, fights)
    return UFCDataset(clean_fighters(fighters), clean_fights(fights), clean_fighter_fight_stats(stats))


def _fighter(
    fighter: str,
    age: int,
    height_in: int,
    reach_in: int,
    weight_class: str,
    stance: str,
    total_fights: int,
    ufc_fights: int,
    championship_fights: int,
    five_round_fights: int,
    sig_str_lpm: float,
    sig_str_abs_lpm: float,
    str_acc: float,
    str_def: float,
    kd_per_fight: float,
    td_per_15: float,
    td_acc: float,
    td_def: float,
    control_seconds: float,
    sub_att_per_15: float,
    cardio_index: float,
    pace_index: float,
) -> dict[str, object]:
    return {
        "fighter": fighter,
        "age": age,
        "height_in": height_in,
        "reach_in": reach_in,
        "weight_class": weight_class,
        "stance": stance,
        "camp": "Sample MMA",
        "ufc_debut_date": "2018-01-01",
        "total_fights": total_fights,
        "ufc_fights": ufc_fights,
        "championship_fights": championship_fights,
        "five_round_fights": five_round_fights,
        "sig_str_lpm": sig_str_lpm,
        "sig_str_abs_lpm": sig_str_abs_lpm,
        "strike_differential": sig_str_lpm - sig_str_abs_lpm,
        "str_acc": str_acc,
        "str_def": str_def,
        "kd_per_fight": kd_per_fight,
        "head_strike_pct": 0.64,
        "body_strike_pct": 0.21,
        "leg_strike_pct": 0.15,
        "td_per_15": td_per_15,
        "td_acc": td_acc,
        "td_def": td_def,
        "control_seconds": control_seconds,
        "sub_att_per_15": sub_att_per_15,
        "ground_strike_rate": 1.0 + td_per_15 / 2.0,
        "cardio_index": cardio_index,
        "pace_index": pace_index,
    }


def _fight(
    fight_id: str,
    date: str,
    red_fighter: str,
    blue_fighter: str,
    winner: str,
    method: str,
    round_number: int,
    duration_seconds: int,
    weight_class: str,
    scheduled_rounds: int,
) -> dict[str, object]:
    return {
        "fight_id": fight_id,
        "date": date,
        "red_fighter": red_fighter,
        "blue_fighter": blue_fighter,
        "winner": winner,
        "method": method,
        "round": round_number,
        "duration_seconds": duration_seconds,
        "weight_class": weight_class,
        "scheduled_rounds": scheduled_rounds,
    }


def _build_stats(fighters: pd.DataFrame, fights: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    lookup = fighters.set_index("fighter").to_dict(orient="index")
    rows = []
    stat_columns = [
        "sig_str_lpm",
        "sig_str_abs_lpm",
        "strike_differential",
        "str_acc",
        "str_def",
        "kd_per_fight",
        "head_strike_pct",
        "body_strike_pct",
        "leg_strike_pct",
        "td_per_15",
        "td_acc",
        "td_def",
        "control_seconds",
        "sub_att_per_15",
        "ground_strike_rate",
        "cardio_index",
        "pace_index",
    ]
    for fight in fights.itertuples(index=False):
        for fighter, opponent in [(fight.red_fighter, fight.blue_fighter), (fight.blue_fighter, fight.red_fighter)]:
            base = lookup[fighter]
            row = {"fight_id": fight.fight_id, "fighter": fighter, "opponent": opponent}
            for column in stat_columns:
                value = float(base[column])
                jitter = rng.normal(1.0, 0.07)
                if column.endswith("_pct") or column.endswith("_acc") or column.endswith("_def") or column.endswith("_index"):
                    row[column] = float(np.clip(value * jitter, 0.01, 0.99))
                else:
                    row[column] = max(0.0, value * jitter)
            rows.append(row)
    return pd.DataFrame(rows)
