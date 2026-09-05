#!/usr/bin/env python3
"""Aether Watcher — 大脑显示屏（Streamlit）
streamlit run watcher_dashboard.py
"""
import os, json, time, datetime
import pandas as pd
import streamlit as st

BASE = os.path.dirname(os.path.abspath(__file__))
S = lambda f: os.path.join(BASE, "state", f)

def rj(p, d):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d

st.set_page_config(page_title="Aether Watcher", layout="wide")
st.title("👁 Aether Watcher — 大脑显示屏")

hb = rj(S("heartbeat.json"), {})
age = time.time() - hb.get("ts", 0) if hb.get("ts") else None
if age is None:
    st.error("❌ 未发现 daemon 心跳")
elif age > 120:
    st.error(f"🚨 心跳停止 {int(age)}s — daemon 可能挂了")
else:
    st.success(f"🟢 在线 · 心跳 {int(age)}s 前 · 监控 {len(hb.get('targets', []))} 个目标")

col1, col2 = st.columns([3, 2])
with col1:
    st.subheader("📡 目标状态")
    tgts = hb.get("targets", [])
    if tgts:
        df = pd.DataFrame(tgts)
        df["fail"] = df["fail"].apply(lambda x: f"⚠️ {x}" if x else "✓")
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("（无目标 — 编辑 watch_targets.toml）")
with col2:
    st.metric("本地时间", datetime.datetime.now().strftime("%H:%M:%S"))
    if st.button("🔄 刷新"): st.rerun()

st.divider()
st.subheader("⚡ 触发事件流")
events = rj(S("events.json"), [])
if not events:
    st.caption("（还没有触发 — 平静的一天）")
for e in reversed(events[-50:]):
    with st.container(border=True):
        st.markdown(f"**[{e['target']}] {e['kind']}** · `{e['time'][:19]}`")
        st.text(e.get("detail", ""))
        if e.get("summary"):
            st.info(e["summary"])
