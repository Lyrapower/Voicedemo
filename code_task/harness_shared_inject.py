"""Read-only harness-shared cards for Cloud DeepSeek inject. No store writes."""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

SHARED_NODE = "harness-shared"
TITLE = "工作卡·harness-shared"
BUDGET = 2000


def _headers() -> dict[str, str]:
    h = {"Accept": "application/json"}
    tok = (os.environ.get("GRID_STORE_TOKEN") or os.environ.get("BRIDGE_STORE_TOKEN") or "").strip()
    if tok:
        h["X-Grid-Token"] = tok
    return h


def load_cards(limit: int = 200) -> list[str]:
    base = (os.environ.get("GRID_STORE_BASE") or "http://127.0.0.1:8501").rstrip("/")
    url = f"{base}/store/conversations/{SHARED_NODE}?limit={int(limit)}"
    try:
        req = urllib.request.Request(url, headers=_headers())
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return []
    rows = data if isinstance(data, list) else (data.get("messages") or [])
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        c = str(row.get("content") or "")
        if "test_run_id=" in c:
            continue
        if c.startswith("[工作日志]") or c.startswith("[决定]") or c.startswith("[终判]") \
                or c.startswith("[收口]") or c.startswith("[播种]"):
            out.append(c)
    return out[-20:]


def _tool_surface() -> str:
    return (
        "这是你此刻全部工具,表外没有\n"
        "web.fetch · GET 已登记域名 · ```tool {\"tool\":\"web.fetch\",\"url\":\"https://…\"} · 结果回 prior.status/text\n"
        "web.search · 检索 · ```tool {\"tool\":\"web.search\",\"q\":\"…\"} · 结果回 prior.hits\n"
        "grants.catalog · 联邦/州目录 · ```tool {\"tool\":\"grants.catalog\"} · 结果回 prior.rows\n"
        "本线程只可读,执行请绑 mission"
    )[:1500]


def _identity() -> str:
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    return (
        "agents·此刻身份\n"
        f"clock PDT {now.strftime('%Y-%m-%d %H:%M')}\n"
        "ports 8630=harness 8501=gateway+store\n"
        "lanes scout,research,builder,gardener,rwa · workers fast,deep,full,research,local,cc\n"
        "research=DeepSeek · local=9B · deep=scout 决策官 · Grid 是主体且不调度\n"
        "门: money/写宿主/表外出网 出生 BLOCKED；read_only 剥写工具\n"
        "harness-shared 只 harness 写；lane 节点只读"
    )


def system_blocks() -> list[dict[str, str]]:
    cards = load_cards()
    blocks = []
    if cards:
        body = TITLE + "\n" + "\n".join(cards)
        if len(body) > BUDGET:
            body = body[: BUDGET - 6] + "[截断]"
        blocks.append({"role": "system", "content": body})
    blocks.append({"role": "system", "content": _tool_surface()})
    blocks.append({"role": "system", "content": _identity()})
    return blocks
