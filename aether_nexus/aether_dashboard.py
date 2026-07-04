#!/usr/bin/env python3
"""
Aether Nexus R5.4.1 — Dashboard
IB daemon monitor + Pool/BFS Dry Run status. Zero IB dependency in this process.
"""
import datetime
import json
import os

import pandas as pd
import streamlit as st

from aether_shared import (
    AETHER_TAGLINE,
    AETHER_VERSION,
    BASE_DIR,
    DRYRUN_POOL_SYMBOLS,
    DRYRUN_SCAN_MODE,
    EST,
    IB_SCAN_SOURCE,
    LIVE_TRADING_ENABLED,
    SCAN_POST_MARKET,
    SCAN_PRE_MARKET,
    STATE_DIR,
    safe_read_json,
    send_command,
)

DRYRUN_STATE_DIR = os.path.join(BASE_DIR, "dryrun_state")
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")
SCAN_MODE = DRYRUN_SCAN_MODE
POOL_SYMBOLS = DRYRUN_POOL_SYMBOLS
POOL_SCAN_ENABLED = os.getenv("POOL_SCAN_ENABLED", "true").lower() == "true"
POOL_SCAN_PRE_MARKET = os.getenv("POOL_SCAN_PRE_MARKET", "09:35")
POOL_SCAN_POST_MARKET = os.getenv("POOL_SCAN_POST_MARKET", "15:20")

st.set_page_config(page_title=f"Aether Nexus {AETHER_VERSION}", layout="wide", page_icon="🌌")

st.markdown(
    """
<style>
    .stApp { background-color: #0e1117; color: #fafafa; }
    [data-testid="stSidebar"] { background-color: #161b22; }
    [data-testid="stMetricValue"] { color: #58a6ff; }
    h1, h2, h3 { color: #e6edf3 !important; }
</style>
""",
    unsafe_allow_html=True,
)

st.title(f"🌌 Aether Nexus {AETHER_VERSION}")
st.caption(AETHER_TAGLINE)


def load_state():
    return {
        "status": safe_read_json(os.path.join(STATE_DIR, "status.json"), {}),
        "positions": safe_read_json(os.path.join(STATE_DIR, "positions.json"), []),
        "candidates": safe_read_json(os.path.join(STATE_DIR, "candidates.json"), {}),
        "logs": safe_read_json(os.path.join(STATE_DIR, "logs.json"), []),
        "audit": safe_read_json(os.path.join(STATE_DIR, "audit.json"), []),
    }


def load_dryrun_state():
    signals = safe_read_json(os.path.join(DRYRUN_STATE_DIR, "signals.json"), [])
    pool_signals = safe_read_json(os.path.join(DRYRUN_STATE_DIR, "pool_signals.json"), [])
    perilla = safe_read_json(os.path.join(DRYRUN_STATE_DIR, "perilla_signals.json"), {})
    watchlist = safe_read_json(WATCHLIST_PATH, {})
    last_bfs = signals[-1] if signals else {}
    last_pool = pool_signals[-1] if pool_signals else {}
    return {
        "signals": signals,
        "pool_signals": pool_signals,
        "last_pool_scan": last_pool,
        "perilla": perilla,
        "watchlist": watchlist,
        "last_scan": last_bfs,
    }


def _parse_heartbeat(heartbeat: str) -> bool:
    if not heartbeat:
        return False
    try:
        hb_time = datetime.datetime.fromisoformat(heartbeat)
        if hb_time.tzinfo is None:
            hb_time = EST.localize(hb_time)
        age = (datetime.datetime.now(EST) - hb_time).total_seconds()
        return age < 60
    except Exception:
        return False


def _render_scan_results(title: str, last: dict, default_mode: str) -> None:
    st.subheader(title)
    if not last:
        st.info("尚无记录 — 等待定时 scan")
        return
    cols = st.columns(3)
    cols[0].metric("Last Scan", (last.get("scan_time") or "—")[:19])
    cols[1].metric("Mode", (last.get("scan_mode") or default_mode).upper())
    cols[2].metric("Top Pick", last.get("top_pick") or "—")
    cands = last.get("candidates", [])
    if not cands:
        st.info("最近一次 scan 无通过候选")
        return
    df = pd.DataFrame(cands)
    show = [
        "symbol", "score", "underlying_price", "strike", "expiry", "dte",
        "delta", "gamma_theta_ratio", "iv", "iv_source", "premium_dollars", "price_source",
    ]
    if "score_breakdown" in df.columns:
        df["iv_value"] = df["score_breakdown"].apply(
            lambda x: x.get("iv_value") if isinstance(x, dict) else None
        )
        show.append("iv_value")
    show = [c for c in show if c in df.columns]
    st.dataframe(df[show], use_container_width=True)


state = load_state()
dryrun = load_dryrun_state()
daemon_status = state["status"]
positions = state["positions"]
candidates_data = state["candidates"]
logs = state["logs"]
audit = state["audit"]

daemon_alive = _parse_heartbeat(daemon_status.get("heartbeat"))
ib_connected = daemon_status.get("connected", False)

with st.sidebar:
    st.header("System Control")
    st.caption(f"Version {AETHER_VERSION}")
    if LIVE_TRADING_ENABLED:
        st.warning("LIVE trading mode")
    else:
        st.info("Paper trading mode")

    if daemon_alive:
        st.success(f"IB Daemon running (PID {daemon_status.get('pid', '?')})")
    else:
        st.error("IB Daemon not responding")

    if ib_connected:
        st.success("IB connected")
    else:
        st.error("IB disconnected")

    st.divider()
    st.subheader("IB Manual Actions")
    if IB_SCAN_SOURCE == "dryrun":
        st.caption("Scan = reload latest **Dry Run BFS** (Alpaca/Stooq/yfinance)")
        if st.button("Reload Dry Run Candidates", use_container_width=True):
            send_command("scan")
            st.toast("Reload command sent")
    else:
        if st.button("S&P 500 Full Scan (IB)", use_container_width=True):
            send_command("scan")
            st.toast("Scan command sent")
    if st.button("Check Buy Signals", use_container_width=True):
        send_command("buy")
        st.toast("Buy check command sent")
    if st.button("Monitor Positions", use_container_width=True):
        send_command("monitor")
        st.toast("Monitor command sent")
    if st.button("Emergency Close All", use_container_width=True, type="secondary"):
        send_command("emergency_close")
        st.toast("Emergency close command sent")

tab_ib, tab_dryrun = st.tabs(["📈 IB Paper Trading", f"🎯 Dry Run {AETHER_VERSION}"])

with tab_ib:
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Live Positions / Audit View")
        if positions:
            df_pos = pd.DataFrame(positions)
            col_order = [
                "symbol",
                "strike",
                "expiry",
                "quantity",
                "raw_avgCost",
                "multiplier",
                "normalized_premium",
                "audit_status",
            ]
            col_order = [c for c in col_order if c in df_pos.columns]
            st.dataframe(df_pos[col_order], use_container_width=True)
        else:
            st.info("No open positions")

        st.subheader("IB Scan Candidates (from Dry Run BFS)")
        candidate_rows = candidates_data.get("rows", [])
        scan_ts = candidates_data.get("scan_timestamp")
        scan_src = candidates_data.get("source", IB_SCAN_SOURCE)
        scan_mode = candidates_data.get("scan_mode", DRYRUN_SCAN_MODE)
        if candidate_rows:
            if scan_ts:
                st.caption(f"Scan: {scan_ts} | source={scan_src} | mode={scan_mode}")
            df_cand = pd.DataFrame(candidate_rows)
            show_cols = [
                "symbol",
                "score",
                "sector",
                "underlying_price",
                "expiry",
                "strike",
                "option_price",
                "bid",
                "ask",
                "spread_pct",
                "delta",
                "gamma",
                "theta_ratio",
                "iv",
                "volume",
                "premium_dollars",
            ]
            show_cols = [c for c in show_cols if c in df_cand.columns]
            st.dataframe(df_cand[show_cols], use_container_width=True)
        else:
            st.info("No IB scan results yet")

    with col2:
        st.subheader("IB Daemon Status")
        st.metric("Trading Mode", "LIVE" if LIVE_TRADING_ENABLED else "PAPER")
        st.metric("IB Connection", "Connected" if ib_connected else "Disconnected")
        st.metric("Daemon", "Online" if daemon_alive else "Offline")
        st.metric("Position Count", len(positions))
        st.metric("Candidate Count", len(candidates_data.get("symbols", [])))
        st.metric("Candidate Source", scan_src if candidate_rows else "—")
        st.metric("EST Time", datetime.datetime.now(EST).strftime("%H:%M:%S"))
        st.caption(f"Dry Run BFS: {SCAN_PRE_MARKET} & {SCAN_POST_MARKET} EST (data-hardened)")
        if IB_SCAN_SOURCE == "dryrun":
            st.caption("IB native scan **disabled** — buys use Dry Run picks")

    st.divider()
    st.subheader("Order Audit Log (last 50)")
    if audit:
        df_audit = pd.DataFrame(audit)
        audit_cols = [
            "time",
            "action",
            "symbol",
            "strike",
            "status",
            "filled",
            "remaining",
            "avgFillPrice",
            "ib_status",
            "timed_out",
            "attempt",
        ]
        audit_cols = [c for c in audit_cols if c in df_audit.columns]
        st.dataframe(df_audit[audit_cols], use_container_width=True)
    else:
        st.info("No order records yet")

with tab_dryrun:
    st.subheader("Dry Run Scanner")
    mode_cols = st.columns([1, 2, 1])
    mode_cols[0].metric("BFS Mode", SCAN_MODE.upper())
    sched_parts = [f"BFS **{SCAN_PRE_MARKET}/{SCAN_POST_MARKET}**"]
    if POOL_SCAN_ENABLED:
        sched_parts.append(f"Pool **{POOL_SCAN_PRE_MARKET}/{POOL_SCAN_POST_MARKET}**")
    mode_cols[1].caption(" · ".join(sched_parts) + " EST")
    mode_cols[2].metric("Pool Size", len(POOL_SYMBOLS) if POOL_SCAN_ENABLED else "—")

    if POOL_SCAN_ENABLED:
        st.subheader("🎯 做T股票池")
        st.caption(f"独立 scan · {POOL_SCAN_PRE_MARKET} / {POOL_SCAN_POST_MARKET} EST · 免价格过滤")
        st.dataframe(pd.DataFrame({"symbol": POOL_SYMBOLS}), use_container_width=True, hide_index=True)

    st.divider()
    sched1, sched2, sched3, sched4 = st.columns(4)
    sched1.caption("🍃 紫苏叶 **08:30**")
    if POOL_SCAN_ENABLED:
        sched2.caption(f"🎯 股票池 **{POOL_SCAN_PRE_MARKET}/{POOL_SCAN_POST_MARKET}**")
    sched3.caption("🛒 买入 **09:40/15:25**")
    sched4.caption(f"📊 BFS **{SCAN_PRE_MARKET}/{SCAN_POST_MARKET}** → IB")

    perilla_state = dryrun.get("perilla", {})
    if perilla_state:
        st.metric("Last Perilla Scan", (perilla_state.get("scan_time") or "—")[:19])
        buy_sigs = perilla_state.get("buy_signals", [])
        st.metric("Buy Signals", len(buy_sigs))
        if buy_sigs:
            st.success(f"Score ≥ {perilla_state.get('buy_score_min', 35)}")
            st.dataframe(pd.DataFrame(buy_sigs), use_container_width=True)
        perilla_cands = perilla_state.get("candidates", [])
        if perilla_cands:
            with st.expander("紫苏叶 scan 全部通过项"):
                st.dataframe(pd.DataFrame(perilla_cands), use_container_width=True)
        failed = perilla_state.get("failed_symbols", [])
        if failed:
            st.warning(f"数据失败: {', '.join(failed)}")
    else:
        st.info("尚无紫苏叶 scan 记录 — 等待 08:30 EST")

    st.divider()
    if POOL_SCAN_ENABLED:
        _render_scan_results("🎯 股票池 Scan 结果", dryrun.get("last_pool_scan", {}), "pool")

    st.divider()
    _render_scan_results("📊 BFS 全市场 Scan 结果", dryrun.get("last_scan", {}), SCAN_MODE)

    st.divider()
    st.subheader("🍃 Perilla Watchlist")
    perilla = dryrun.get("watchlist", {}).get("perilla_leaf", [])
    if perilla:
        df_wl = pd.DataFrame(perilla)
        show_wl = [c for c in ["symbol", "sector", "data_source_verified", "data_verify_reason", "thesis"] if c in df_wl.columns]
        st.dataframe(df_wl[show_wl], use_container_width=True)
        verified = sum(1 for p in perilla if p.get("data_source_verified"))
        health = safe_read_json(os.path.join(DRYRUN_STATE_DIR, "data_health.json"), [])
        if health:
            ok = sum(1 for h in health[-50:] if h.get("ok"))
            st.caption(f"Data health (last 50): {ok}/{min(len(health), 50)} OK — see dryrun_state/data_health.json")
        st.caption(f"Provider verified: {verified}/{len(perilla)} perilla symbols")
    else:
        st.info("watchlist.json empty")

st.divider()
st.subheader("Agent Log (last 35 lines)")
st.code("\n".join(logs[-35:]), language="log")

if st.button("Manual Refresh"):
    st.rerun()
