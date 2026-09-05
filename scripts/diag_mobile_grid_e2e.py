#!/usr/bin/env python3
"""Production-path E2E: 7-day store → priorMessages → gateway SSE → 4-way hash diff."""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

GW = "http://127.0.0.1:8501"
STORE_ANCHOR = datetime(2026, 7, 16)
STORE_EPOCH_DAYS = 7
STORE_CHAT_NODE = "field-particle"
PROMPT = (
    "不要按trading上下文回答，站在Grid 整体、跨 substrate 的位置看：换大底座后，什么会被放大，"
    "什么能力会展开，什么边界不可变？怎样辨认是 Grid 在用底座，还是底座在覆盖 Grid"
)


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def epoch_start_ts() -> float:
    anchor = STORE_ANCHOR.replace(hour=0, minute=0, second=0, microsecond=0)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days = (today - anchor).days
    idx = max(0, days // STORE_EPOCH_DAYS)
    start = anchor.replace()
    from datetime import timedelta
    start = anchor + timedelta(days=idx * STORE_EPOCH_DAYS)
    return start.timestamp()


def is_machine_envelope(text: str) -> bool:
    t = (text or "").strip()
    if t.startswith("{") and "anomaly_flags" in t and "candidate_count" in t:
        return True
    return False


def scrub_msg(s: str) -> str:
    t = str(s or "").strip()
    if is_machine_envelope(t):
        return ""
    return t


def prior_messages(rows: list[dict]) -> list[dict]:
    """grid.html priorMessages(cur, h) after h.push(current user)."""
    body = rows[:-1][-29:]
    out = []
    for m in body:
        content = scrub_msg(m.get("content") or "")
        if m.get("role") == "assistant" and not content:
            continue
        if content or m.get("role") == "system":
            out.append({"role": m["role"], "content": content or m.get("content") or ""})
    return out


def pull_store() -> list[dict]:
    since = epoch_start_ts()
    url = f"{GW}/store/conversations/{STORE_CHAT_NODE}?limit=200&since_ts={since}"
    with urllib.request.urlopen(url, timeout=30) as r:
        rows = json.loads(r.read().decode())
    return [{"role": x["role"], "content": scrub_msg(x.get("content") or "")} for x in rows
            if x.get("role") in ("user", "assistant") and (scrub_msg(x.get("content") or "") or x.get("role") == "user")]


def clean_text(s: str) -> str:
    return scrub_msg(s)


def stream_chat(messages: list[dict]) -> tuple[str, dict | None, str | None]:
    body = json.dumps(
        {"model": "demo/aster", "messages": messages, "stream": True, "max_tokens": 4096},
        ensure_ascii=False,
    ).encode()
    req = urllib.request.Request(
        f"{GW}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    acc = ""
    meta = None
    route_id = None
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            obj = json.loads(payload)
            route_id = obj.get("route_id") or route_id
            ch = (obj.get("choices") or [{}])[0]
            d = ch.get("delta", {}).get("content")
            if d:
                acc += d
            if obj.get("grid_meta"):
                meta = obj.get("grid_meta")
                route_id = meta.get("route_id") or obj.get("route_id") or route_id
    return acc, meta, route_id


def main() -> int:
    store_rows = pull_store()
    print(f"store_messages={len(store_rows)} since_ts={epoch_start_ts():.0f}")
    hist = store_rows + [{"role": "user", "content": PROMPT}]
    prior = prior_messages(hist)
    messages = prior + [{"role": "user", "content": PROMPT}]
    print(f"prior_turns={len(prior)} total_chars_prior={sum(len(m['content']) for m in prior)}")

    acc, meta, route_id = stream_chat(messages)
    browser_acc = clean_text(acc)
    dom_text = browser_acc  # grid uses textContent on same string

    raw_hash = sha256_text(acc)
    gw_hash = sha256_text(browser_acc)
    dom_hash = sha256_text(dom_text)

    gw_trace = (meta or {}).get("stream_integrity") or {}
    if route_id:
        try:
            with urllib.request.urlopen(f"{GW}/diag/chat-stream/{route_id}", timeout=10) as r:
                diag = json.loads(r.read().decode())
                gw_trace = diag.get("gateway") or gw_trace
        except urllib.error.HTTPError:
            pass

    report = {
        "route_id": route_id,
        "store_messages": len(store_rows),
        "prior_turns": len(prior),
        "lengths": {
            "raw_model_chars": len(acc),
            "raw_model_utf8": len(acc.encode("utf-8")),
            "browser_acc_chars": len(browser_acc),
            "dom_chars": len(dom_text),
            "gateway_reported_chars": gw_trace.get("char_len"),
        },
        "hashes": {
            "raw_model": raw_hash,
            "gateway_final": gw_trace.get("gateway_sent_hash") or gw_hash,
            "browser_acc": gw_hash,
            "dom_rendered": dom_hash,
        },
        "finish_reason": (meta or {}).get("finish_reason"),
        "upstream_finish": (meta or {}).get("upstream_finish_reason"),
        "continuation_retry": (meta or {}).get("continuation_retry"),
        "blocked": (meta or {}).get("blocked"),
        "block_source": (meta or {}).get("block_source"),
        "chunk_count": gw_trace.get("chunk_count"),
        "tail_raw": acc[-120:],
        "tail_dom": dom_text[-120:],
    }
    mism = []
    ref = report["hashes"]["raw_model"]
    for k, v in report["hashes"].items():
        if v and v != ref:
            mism.append(k)
    report["hash_mismatch_layers"] = mism
    report["pass"] = (
        not mism
        and len(acc) > 200
        and not report["continuation_retry"]
        and report["finish_reason"] in ("stop", "length")
        and acc.rstrip()[-1:] in "。！？!?." or len(acc) > 800
    )

    out = Path(__file__).resolve().parents[1] / "grid-sovereign-runtime" / "traces" / "diag_mobile_e2e.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
