"""模块⑤ · 事件赔率 Δ + 隔夜要闻(Polymarket 已有 + DS 缩编配菜)。"""
from __future__ import annotations
import json
import os
import urllib.request

from .http_util import http_get_json


def odds_from_raw(payload: dict | None) -> list[dict]:
    """从 scout raw fetchers 结果抽 Polymarket 条目。"""
    out = []
    for block in (payload or {}).get("results") or []:
        if block.get("source") != "polymarket_odds":
            continue
        if not block.get("ok"):
            return [{"ok": False, "error": block.get("error") or "polymarket fail"}]
        for it in block.get("items") or []:
            out.append({"ok": True, **(it if isinstance(it, dict) else {"text": str(it)})})
    return out


def fetch_polymarket_live() -> list[dict]:
    """轻量直拉(与 fetchers 同源思路);失败返回空。"""
    try:
        # 复用 fetchers 若可 import
        import fetchers
        block = fetchers.fetch_polymarket()
        if not block.get("ok"):
            return [{"ok": False, "error": block.get("error")}]
        return [{"ok": True, **it} for it in (block.get("items") or []) if isinstance(it, dict)]
    except Exception as e:
        return [{"ok": False, "error": str(e)[:200]}]


def ds_news_digest(raw_json: str, *, max_items: int = 5) -> dict:
    """DS 只缩编隔夜要闻 ≤5 条。价位/方向不要求、也不该编。"""
    ds_base = os.getenv("DEEPSEEK_BASE", "http://127.0.0.1:11434/v1").rstrip("/")
    ds_key = os.getenv("DEEPSEEK_API_KEY", "ollama").strip()
    ds_model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro:cloud")
    if not ds_key:
        return {"ok": False, "error": "DEEPSEEK_API_KEY 空", "lines": []}
    system = (
        "你是隔夜要闻缩编员。只输出≤%d条事实要点,每条一行:"
        "`- 事实(来源名)`。禁止买卖方向、点位、仓位、策略建议。"
        % max_items
    )
    body = {
        "model": ds_model,
        "max_tokens": 700,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "原始采集 JSON(截断):\n" + raw_json[:10000],
            },
        ],
    }
    if "11434" in ds_base:
        body["think"] = True
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        ds_base + "/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + ds_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            resp = json.loads(r.read().decode())
        text = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        text = text.strip()
        if not text:
            return {"ok": False, "error": "DS 空正文", "lines": []}
        lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("-")][:max_items]
        if not lines:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:max_items]
        return {"ok": True, "error": "", "lines": lines, "raw": text}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300], "lines": []}
