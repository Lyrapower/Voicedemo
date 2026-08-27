#!/usr/bin/env python3
"""Aether Nexus Crypto V1.2 — Streamlit 监控面板（现货合规版）

V1.2: 三档模式 banner + 心跳 + 指令按钮（紧急平仓/暂停/恢复/立即扫描）
"""

import streamlit as st
import pandas as pd
import datetime
import time
from aether_crypto_shared import (
    safe_read_json, send_command, EST,
    POSITIONS_PATH, LOGS_PATH, HEARTBEAT_PATH, JOURNAL_PATH,
)

st.set_page_config(page_title="Aether Crypto V1.2", layout="wide")
st.title("🪙 Aether Nexus Crypto V1.2")
st.caption("7×24 现货合规监控面板（无杠杆）")

positions = safe_read_json(POSITIONS_PATH, [])
logs = safe_read_json(LOGS_PATH, [])
heartbeat = safe_read_json(HEARTBEAT_PATH, {})
journal = safe_read_json(JOURNAL_PATH, [])

# ---------- 心跳 ----------
hb_ts = heartbeat.get("ts", 0)
hb_age = time.time() - hb_ts if hb_ts else None
mode = heartbeat.get("mode", "PAPER")
version = heartbeat.get("version", "V1.1")
if hb_age is None:
    st.error("❌ 未发现 daemon 心跳（从未启动或 state 目录不对）")
elif hb_age > 180:
    st.error(f"🚨 daemon 心跳已停止 {int(hb_age)}s — 进程可能挂了！交易所侧 SL/TP 仍生效。")
else:
    paused = " | ⏸️ 已暂停开仓" if heartbeat.get("paused") else ""
    st.success(f"🟢 daemon 在线 [{mode}] 心跳 {int(hb_age)}s 前{paused} ({version})")

col1, col2 = st.columns([2, 1])
with col1:
    st.subheader("📊 持仓（余额对账）")
    st.dataframe(pd.DataFrame(positions) if positions else pd.DataFrame(), use_container_width=True)
    st.caption(f"候选: {', '.join(heartbeat.get('candidates', [])) or '（无）'}")
with col2:
    st.metric("美东时间", datetime.datetime.now(EST).strftime("%H:%M:%S"))
    if st.button("🔄 刷新"):
        st.rerun()
    st.divider()
    st.subheader("🎮 指令")
    if st.button("⏸️ 暂停开仓"):
        send_command("pause"); st.toast("已发送 pause")
    if st.button("▶️ 恢复开仓"):
        send_command("resume"); st.toast("已发送 resume")
    if st.button("🔍 立即扫描"):
        send_command("scan_now"); st.toast("已发送 scan_now")
    st.divider()
    confirm = st.checkbox("我确认要紧急平掉全部持仓")
    if st.button("🆘 紧急平仓", type="primary", disabled=not confirm):
        send_command("emergency_close_all"); st.toast("已发送 emergency_close_all", icon="🆘")

st.divider()
tab_logs, tab_journal = st.tabs(["📜 日志", "📒 交易流水"])
with tab_logs:
    st.code("\n".join(logs[-50:]) if logs else "（暂无日志）", language="log")
with tab_journal:
    if journal:
        st.dataframe(pd.DataFrame(journal[::-1]), use_container_width=True)
    else:
        st.caption("（暂无交易记录）")
