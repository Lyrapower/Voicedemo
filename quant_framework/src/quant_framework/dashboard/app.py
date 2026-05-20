"""Streamlit dashboard for factor signal visualization."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from quant_framework.service import build_adapter, build_cache, build_combiner, most_recent_month_end
from quant_framework.universe.sp500 import get_sp500_constituents

st.set_page_config(
    page_title="Quant Framework",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

Z_COLS = [
    "momentum_12_1_zscore",
    "book_to_market_zscore",
    "gross_profitability_zscore",
    "low_vol_12m_zscore",
]


@st.cache_data(ttl=300)
def _load_run_results(run_id: str) -> pd.DataFrame:
    cache = build_cache()
    return cache.get_signal_results(run_id)


@st.cache_data(ttl=60)
def _list_runs() -> pd.DataFrame:
    return build_cache().list_signal_runs(limit=50)


def _style_zscore_df(df: pd.DataFrame, z_cols: list[str]) -> "pd.io.formats.style.Styler":
    def color_val(v: float) -> str:
        if pd.isna(v):
            return ""
        if v > 0:
            return "background-color: #1a4d2e; color: #90EE90"
        if v < 0:
            return "background-color: #4d1a1a; color: #FFB6C1"
        return ""

    subset = [c for c in z_cols if c in df.columns]
    return df.style.map(color_val, subset=subset)


def main() -> None:
    st.title("Quant Trading Framework")
    st.caption("Phase 1 — Factor signals & cross-sectional ranking")

    default_date = most_recent_month_end()
    cache = build_cache()

    with st.sidebar:
        st.header("Controls")
        as_of = st.date_input("As-of date", value=default_date)
        universe_label = st.selectbox("Universe", ["S&P 500"], index=0)
        w1 = st.slider("Momentum weight", 0.0, 1.0, 0.25, 0.05)
        w2 = st.slider("Value weight", 0.0, 1.0, 0.25, 0.05)
        w3 = st.slider("Quality weight", 0.0, 1.0, 0.25, 0.05)
        w4 = st.slider("Low vol weight", 0.0, 1.0, 0.25, 0.05)
        weights = [w1, w2, w3, w4]
        generate = st.button("Generate Signals", type="primary")

    session_key = "signal_df"
    if generate:
        with st.spinner("Generating signals for S&P 500..."):
            try:
                universe = get_sp500_constituents(as_of)
                combiner = build_combiner(weights=weights)
                adapter = build_adapter()
                df = combiner.compute_combined(universe, as_of, adapter)
                st.session_state[session_key] = df
                st.session_state["run_id"] = df.attrs.get("run_id")
                st.session_state["as_of"] = as_of
                st.success(f"Generated signals for {len(universe)} tickers.")
            except Exception as e:
                st.error(f"Signal generation failed: {e}")

    df = st.session_state.get(session_key)
    if df is None:
        runs = _list_runs()
        if not runs.empty:
            st.info("Select a historical run below or click Generate Signals.")
            run_id = st.selectbox("Load historical run", runs["run_id"].tolist())
            if st.button("Load run"):
                df = _load_run_results(run_id)
                st.session_state[session_key] = df
                st.session_state["run_id"] = run_id
        else:
            st.warning("No signals yet. Use the sidebar to generate.")
            _status_bar(cache)
            return

    if df is not None and not df.empty:
        ranked = df[df["rank"].notna()].sort_values("rank")
        tab1, tab2, tab3 = st.tabs(["Signal Rankings", "Factor Analysis", "Historical Runs"])

        with tab1:
            st.subheader("Top 20 long candidates")
            top = ranked.head(20).reset_index(names="ticker")
            disp_cols = ["rank", "ticker", "combined_score"] + [c for c in Z_COLS if c in top.columns]
            st.dataframe(_style_zscore_df(top[disp_cols], Z_COLS), use_container_width=True)

            st.subheader("Bottom 20 short candidates")
            bottom = ranked.tail(20).sort_values("rank", ascending=False).reset_index(names="ticker")
            st.dataframe(_style_zscore_df(bottom[disp_cols], Z_COLS), use_container_width=True)

            tickers = top["ticker"].tolist()
            selected = st.selectbox("Ticker breakdown", tickers)
            if selected in df.index:
                st.json(df.loc[selected].to_dict())

        with tab2:
            zdf = ranked[[c for c in Z_COLS if c in ranked.columns]].dropna()
            if len(zdf) > 1:
                corr = zdf.corr()
                fig = px.imshow(
                    corr,
                    text_auto=".2f",
                    color_continuous_scale="RdBu_r",
                    title="Factor correlation heatmap",
                )
                st.plotly_chart(fig, use_container_width=True)

            c1, c2 = st.columns(2)
            for i, col in enumerate([c for c in Z_COLS if c in ranked.columns]):
                with (c1 if i % 2 == 0 else c2):
                    fig_h = px.histogram(ranked, x=col, nbins=40, title=f"Distribution: {col}")
                    st.plotly_chart(fig_h, use_container_width=True)

            st.subheader("Factor exposures (top vs bottom 20)")
            top20 = ranked.head(20)
            bot20 = ranked.tail(20)
            exp = pd.DataFrame(
                {
                    "top_20_mean": top20[Z_COLS].mean(),
                    "bottom_20_mean": bot20[Z_COLS].mean(),
                }
            )
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(name="Top 20", x=exp.index, y=exp["top_20_mean"]))
            fig_bar.add_trace(go.Bar(name="Bottom 20", x=exp.index, y=exp["bottom_20_mean"]))
            fig_bar.update_layout(barmode="group", title="Mean z-scores by group")
            st.plotly_chart(fig_bar, use_container_width=True)

        with tab3:
            runs = _list_runs()
            st.dataframe(runs, use_container_width=True)
            if st.session_state.get("run_id"):
                st.caption(f"Current run: {st.session_state['run_id']}")

    _status_bar(cache)


def _status_bar(cache) -> None:
    st.divider()
    size_mb = cache.db_size_bytes() / (1024 * 1024)
    last_fetch = cache.last_fetch_time() or "N/A"
    runs = cache.list_signal_runs(limit=5)
    c1, c2, c3 = st.columns(3)
    c1.metric("Cache size", f"{size_mb:.2f} MB")
    c2.metric("Last fetch", str(last_fetch)[:19])
    c3.metric("Recent runs", len(runs))


if __name__ == "__main__":
    main()
