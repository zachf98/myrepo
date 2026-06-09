"""Data loading, cleaning, and UFCStats-compatible parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup


FIGHTER_REQUIRED_COLUMNS = {
    "fighter",
    "age",
    "height_in",
    "reach_in",
    "weight_class",
    "stance",
    "total_fights",
    "ufc_fights",
}

FIGHT_REQUIRED_COLUMNS = {
    "fight_id",
    "date",
    "red_fighter",
    "blue_fighter",
    "winner",
    "method",
    "round",
    "duration_seconds",
    "weight_class",
    "scheduled_rounds",
}

STATS_REQUIRED_COLUMNS = {
    "fight_id",
    "fighter",
    "opponent",
    "sig_str_lpm",
    "sig_str_abs_lpm",
    "str_acc",
    "str_def",
    "kd_per_fight",
    "td_per_15",
    "td_acc",
    "td_def",
    "control_seconds",
    "sub_att_per_15",
}

NUMERIC_DEFAULTS = {
    "age": 30.0,
    "height_in": 70.0,
    "reach_in": 72.0,
    "total_fights": 10.0,
    "ufc_fights": 3.0,
    "championship_fights": 0.0,
    "five_round_fights": 0.0,
    "sig_str_lpm": 3.0,
    "sig_str_abs_lpm": 3.0,
    "str_acc": 0.45,
    "str_def": 0.55,
    "kd_per_fight": 0.2,
    "head_strike_pct": 0.65,
    "body_strike_pct": 0.2,
    "leg_strike_pct": 0.15,
    "td_per_15": 1.0,
    "td_acc": 0.35,
    "td_def": 0.6,
    "control_seconds": 60.0,
    "sub_att_per_15": 0.5,
    "ground_strike_rate": 1.0,
    "cardio_index": 0.55,
    "pace_index": 0.5,
}


@dataclass(slots=True)
class UFCDataset:
    """Canonical UFC dataset used by the prediction engine."""

    fighters: pd.DataFrame
    fights: pd.DataFrame
    fighter_fight_stats: pd.DataFrame

    def copy(self) -> "UFCDataset":
        return UFCDataset(
            fighters=self.fighters.copy(),
            fights=self.fights.copy(),
            fighter_fight_stats=self.fighter_fight_stats.copy(),
        )


def snake_case(value: str) -> str:
    return (
        str(value)
        .strip()
        .lower()
        .replace("%", "pct")
        .replace("/", "_per_")
        .replace("+", "plus")
        .replace("-", "_")
        .replace(" ", "_")
        .replace(".", "")
    )


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = frame.copy()
    cleaned.columns = [snake_case(column) for column in cleaned.columns]
    return cleaned


def _coerce_percent(series: pd.Series) -> pd.Series:
    if series.dtype == object:
        return (
            series.astype(str)
            .str.strip()
            .str.rstrip("%")
            .replace({"": np.nan, "nan": np.nan, "--": np.nan})
            .astype(float)
            .div(np.where(series.astype(str).str.contains("%"), 100.0, 1.0))
        )
    return pd.to_numeric(series, errors="coerce")


def clean_fighters(fighters: pd.DataFrame) -> pd.DataFrame:
    frame = normalize_columns(fighters)
    if "name" in frame.columns and "fighter" not in frame.columns:
        frame = frame.rename(columns={"name": "fighter"})
    for column, default in NUMERIC_DEFAULTS.items():
        if column not in frame.columns and column in FIGHTER_REQUIRED_COLUMNS.union(NUMERIC_DEFAULTS):
            frame[column] = default
    for column in [c for c in frame.columns if c in NUMERIC_DEFAULTS]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(NUMERIC_DEFAULTS[column])
    if "stance" not in frame.columns:
        frame["stance"] = "Orthodox"
    if "camp" not in frame.columns:
        frame["camp"] = "Unknown"
    if "ufc_debut_date" not in frame.columns:
        frame["ufc_debut_date"] = pd.NaT
    frame["fighter"] = frame["fighter"].astype(str).str.strip()
    frame["stance"] = frame["stance"].fillna("Unknown").astype(str)
    frame["weight_class"] = frame["weight_class"].fillna("Unknown").astype(str)
    return _require_columns(frame, FIGHTER_REQUIRED_COLUMNS, "fighters")


def clean_fights(fights: pd.DataFrame) -> pd.DataFrame:
    frame = normalize_columns(fights)
    aliases = {
        "r_fighter": "red_fighter",
        "b_fighter": "blue_fighter",
        "result": "winner",
        "finish_round": "round",
        "time_seconds": "duration_seconds",
    }
    frame = frame.rename(columns={source: target for source, target in aliases.items() if source in frame.columns})
    if "fight_id" not in frame.columns:
        frame["fight_id"] = [f"fight_{idx}" for idx in range(len(frame))]
    if "scheduled_rounds" not in frame.columns:
        frame["scheduled_rounds"] = np.where(frame.get("title_fight", False), 5, 3)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ["round", "duration_seconds", "scheduled_rounds"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["method"] = frame["method"].fillna("Decision").astype(str)
    frame["winner"] = frame["winner"].fillna("").astype(str).str.strip()
    frame["red_fighter"] = frame["red_fighter"].astype(str).str.strip()
    frame["blue_fighter"] = frame["blue_fighter"].astype(str).str.strip()
    frame["weight_class"] = frame["weight_class"].fillna("Unknown").astype(str)
    return _require_columns(frame, FIGHT_REQUIRED_COLUMNS, "fights")


def clean_fighter_fight_stats(stats: pd.DataFrame) -> pd.DataFrame:
    frame = normalize_columns(stats)
    aliases = {
        "sig_strikes_landed_per_min": "sig_str_lpm",
        "sig_strikes_absorbed_per_min": "sig_str_abs_lpm",
        "striking_accuracy": "str_acc",
        "striking_defense": "str_def",
        "knockdowns": "kd_per_fight",
        "takedowns_per_15": "td_per_15",
        "takedown_accuracy": "td_acc",
        "takedown_defense": "td_def",
        "submission_attempts_per_15": "sub_att_per_15",
    }
    frame = frame.rename(columns={source: target for source, target in aliases.items() if source in frame.columns})
    for column, default in NUMERIC_DEFAULTS.items():
        if column not in frame.columns:
            frame[column] = default
    for column in [c for c in frame.columns if c in NUMERIC_DEFAULTS]:
        if column.endswith("_pct") or column.endswith("_acc") or column.endswith("_def"):
            frame[column] = _coerce_percent(frame[column]).fillna(NUMERIC_DEFAULTS[column])
        else:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(NUMERIC_DEFAULTS[column])
    frame["fighter"] = frame["fighter"].astype(str).str.strip()
    frame["opponent"] = frame["opponent"].astype(str).str.strip()
    frame["fight_id"] = frame["fight_id"].astype(str)
    frame["strike_differential"] = frame["sig_str_lpm"] - frame["sig_str_abs_lpm"]
    return _require_columns(frame, STATS_REQUIRED_COLUMNS, "fighter_fight_stats")


def load_dataset(
    fighters_path: str | Path,
    fights_path: str | Path,
    stats_path: str | Path,
) -> UFCDataset:
    """Load the canonical dataset from CSV files."""

    return UFCDataset(
        fighters=clean_fighters(pd.read_csv(fighters_path)),
        fights=clean_fights(pd.read_csv(fights_path)),
        fighter_fight_stats=clean_fighter_fight_stats(pd.read_csv(stats_path)),
    )


def _require_columns(frame: pd.DataFrame, required: Iterable[str], table_name: str) -> pd.DataFrame:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{table_name} is missing required columns: {', '.join(missing)}")
    return frame


class UFCStatsClient:
    """Small UFCStats-oriented fetcher/parser.

    The client intentionally returns raw DataFrames and avoids hard-coding a
    brittle end-to-end scraper. Production users should cache HTML snapshots and
    map parsed columns into the canonical dataset with the cleaners above.
    """

    def __init__(self, timeout: int = 20, user_agent: str = "ufc-quant-engine/0.1") -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def fetch_html(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def parse_tables(self, html: str) -> list[pd.DataFrame]:
        soup = BeautifulSoup(html, "html.parser")
        tables = []
        for table in soup.find_all("table"):
            rows = []
            headers = [cell.get_text(" ", strip=True) for cell in table.find_all("th")]
            for row in table.find_all("tr"):
                cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
                if cells:
                    rows.append(cells)
            if rows:
                width = max(len(row) for row in rows)
                if not headers or len(headers) != width:
                    headers = [f"column_{idx}" for idx in range(width)]
                tables.append(normalize_columns(pd.DataFrame(rows, columns=headers[:width])))
        return tables

    def read_tables(self, url_or_path: str | Path) -> list[pd.DataFrame]:
        value = str(url_or_path)
        if value.startswith(("http://", "https://")):
            html = self.fetch_html(value)
        else:
            html = Path(value).read_text(encoding="utf-8")
        return self.parse_tables(html)


def train_test_by_date(dataset: UFCDataset, cutoff: str | pd.Timestamp) -> tuple[UFCDataset, UFCDataset]:
    """Split fight and fighter-stat rows by fight date for leakage-safe validation."""

    cutoff_ts = pd.Timestamp(cutoff)
    fights = dataset.fights.copy()
    train_fights = fights[fights["date"] < cutoff_ts]
    test_fights = fights[fights["date"] >= cutoff_ts]

    train_ids = set(train_fights["fight_id"])
    test_ids = set(test_fights["fight_id"])
    stats = dataset.fighter_fight_stats
    return (
        UFCDataset(dataset.fighters.copy(), train_fights.copy(), stats[stats["fight_id"].isin(train_ids)].copy()),
        UFCDataset(dataset.fighters.copy(), test_fights.copy(), stats[stats["fight_id"].isin(test_ids)].copy()),
    )
