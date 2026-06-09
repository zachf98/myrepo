"""Streamlit dashboard for the UFC quantitative engine."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from ufc_predictor.engine import PredictionEngine
from ufc_predictor.sample_data import build_sample_dataset


@st.cache_resource
def load_engine() -> tuple[PredictionEngine, object]:
    dataset = build_sample_dataset()
    engine = PredictionEngine()
    engine.fit(dataset)
    return engine, dataset


def main() -> None:
    st.set_page_config(page_title="UFC Quant Engine", layout="wide")
    st.title("UFC Quantitative Prediction Engine")
    engine, dataset = load_engine()
    fighters = sorted(dataset.fighters["fighter"].unique())

    with st.sidebar:
        red = st.selectbox("Red corner", fighters, index=fighters.index("Dricus Du Plessis"))
        blue = st.selectbox("Blue corner", fighters, index=fighters.index("Khamzat Chimaev"))
        weight_class = st.selectbox("Weight class", sorted(dataset.fighters["weight_class"].unique()))
        scheduled_rounds = st.radio("Scheduled rounds", [3, 5], index=1, horizontal=True)
        simulations = st.slider("Simulations", min_value=1000, max_value=100000, value=10000, step=1000)
        red_odds = st.number_input("Red moneyline", value=135)
        blue_odds = st.number_input("Blue moneyline", value=-155)

    prediction = engine.predict_fight(
        red,
        blue,
        weight_class=weight_class,
        scheduled_rounds=scheduled_rounds,
        simulations=simulations,
        odds={"red_moneyline": red_odds, "blue_moneyline": blue_odds},
    )

    col1, col2, col3 = st.columns(3)
    col1.metric(f"{red} win", f"{prediction.red_win_probability:.1%}")
    col2.metric(f"{blue} win", f"{prediction.blue_win_probability:.1%}")
    col3.metric("Goes distance", f"{prediction.goes_distance_probability:.1%}")

    prob_col, method_col = st.columns(2)
    with prob_col:
        st.subheader("Win probability")
        st.plotly_chart(
            px.bar(
                x=[red, blue],
                y=[prediction.red_win_probability, prediction.blue_win_probability],
                labels={"x": "Fighter", "y": "Probability"},
                range_y=[0, 1],
            ),
            use_container_width=True,
        )
    with method_col:
        st.subheader("Method probability")
        st.plotly_chart(
            px.pie(
                names=["KO/TKO", "Submission", "Decision"],
                values=[
                    prediction.ko_tko_probability,
                    prediction.submission_probability,
                    prediction.decision_probability,
                ],
            ),
            use_container_width=True,
        )

    round_col, betting_col = st.columns(2)
    with round_col:
        st.subheader("Finish round distribution")
        st.plotly_chart(
            px.bar(
                x=list(prediction.finish_round_distribution.keys()),
                y=list(prediction.finish_round_distribution.values()),
                labels={"x": "Round", "y": "Probability"},
            ),
            use_container_width=True,
        )
    with betting_col:
        st.subheader("Betting value")
        betting = prediction.betting_frame()
        if betting.empty:
            st.info("Enter odds to evaluate betting edges.")
        else:
            st.dataframe(betting, use_container_width=True)

    st.subheader("Top factors")
    for factor in prediction.top_factors[:8]:
        st.write(f"- {factor}")

    st.subheader("Historical comparable fights")
    st.dataframe(prediction.comparable_fights, use_container_width=True)

    st.subheader("Elo movement")
    history = engine.elo.history_frame()
    if not history.empty:
        melted = history.melt(
            id_vars=["date", "fight_id"],
            value_vars=["red_overall_elo", "blue_overall_elo"],
            var_name="corner",
            value_name="overall_elo",
        )
        st.plotly_chart(px.line(melted, x="date", y="overall_elo", color="corner"), use_container_width=True)


if __name__ == "__main__":
    main()
