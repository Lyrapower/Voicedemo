#!/usr/bin/env python3
"""Ensure Scout morning lands on briefs JSON + GLM review + aether OPTION emit.

Repairs truncated DS JSON when possible. Never writes production cloud-* / workbench-b11.

LOCAL LANE v1 · T1: every land product stamps review_origin + review_ts.
T2/T3 hung (Lyra 2026-08-16): no SHADOW / LOCAL_REVIEW until signed Aster
path exists; then race with origin=aster_grid. qwen9b_bare is optional
control arm only with/after aster_grid — never alone. Do not invent signatures
or bypass 8501 five-layer chain.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path("/Users/ciciwang/Projects/demo")
SCOUT = Path(os.getenv("SCOUT_OUT", str(ROOT / "grid-scout")))
GW = os.getenv("GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
_ET = ZoneInfo("America/New_York")

# Live + reserved. Local aster/qwen lanes hung until signed Aster front door.
REVIEW_ORIGINS = frozenset({
    "ds",
    "glm52_cloud",
    "glm_local",       # reserved · T3 hung
    "grid_9b",         # legacy label · do not light alone
    "aster_grid",      # reserved · signed demo/aster @8501 when ready
    "qwen9b_bare",     # reserved · optional control · only with/after aster_grid
    "unknown",         # historical unmarked only
})


def _now_ts() -> str:
    return dt.datetime.now(_ET).isoformat(timespec="seconds")


def normalize_origin(raw: str | None, *, fallback: str = "ds") -> str:
    o = (raw or "").strip() or fallback
    if o == "glm_fail":
        return fallback
    if o not in REVIEW_ORIGINS:
        return "unknown" if fallback == "unknown" else fallback
    return o


def origin_banner(origin: str, review_ts: str) -> str:
    o = normalize_origin(origin)
    return f"> review_origin={o} · review_ts={review_ts}\n"


def stamp_final_markdown(body: str, *, origin: str, review_ts: str, title: str) -> str:
    """Title + origin banner + body. Idempotent if banner already present."""
    o = normalize_origin(origin)
    text = (body or "").strip()
    # strip prior banner lines
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    if lines and lines[0].startswith("> review_origin="):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    core = "\n".join(lines).strip()
    return f"# {title}\n\n{origin_banner(o, review_ts)}\n{core}\n"


def wait_gw(attempts=10, sleep_s=4.0):
    last = None
    kicked = False
    for i in range(attempts):
        try:
            req = urllib.request.Request(GW + "/health", method="GET")
            with urllib.request.urlopen(req, timeout=5) as r:
                if 200 <= r.status < 300:
                    return True
                last = "status=%s" % r.status
        except Exception as e:
            last = str(e)
        if i == 2 and not kicked:
            kicked = True
            try:
                import subprocess
                subprocess.run(
                    ["launchctl", "kickstart", "-k",
                     "gui/%d/com.demo.grid.gateway8501" % os.getuid()],
                    check=False, timeout=30, capture_output=True,
                )
                print("[land] kickstart gateway8501")
            except Exception as e:
                print("[land] kickstart skip:", e)
        print("[land] gateway wait %d/%d (%s)" % (i + 1, attempts, last))
        time.sleep(sleep_s)
    print("[land] gateway STILL DOWN:", last)
    return False


def http_json(url, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if data else "GET",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def repair_json(text: str):
    """Best-effort extract/repair truncated JSON object."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    i, j = t.find("{"), t.rfind("}")
    if i < 0:
        return None
    chunk = t[i : (j + 1 if j > i else len(t))]
    try:
        return json.loads(chunk)
    except Exception:
        pass
    for cut in range(len(chunk), max(len(chunk) - 4000, 0), -1):
        frag = chunk[:cut].rstrip()
        if not frag.endswith("}"):
            opens = frag.count("{") - frag.count("}")
            br = frag.count("[") - frag.count("]")
            frag2 = frag + ("]" * max(br, 0)) + ("}" * max(opens, 0))
        else:
            frag2 = frag
        try:
            return json.loads(frag2)
        except Exception:
            continue
    return None


def load_day(day: str):
    bdir = SCOUT / "briefs"
    jp = bdir / f"{day}-morning.json"
    if jp.is_file():
        doc = json.loads(jp.read_text(encoding="utf-8"))
        ds = doc.get("ds") if isinstance(doc.get("ds"), dict) else None
        if ds and ds.get("_parse_failed"):
            raise SystemExit(
                "[land] morning.json 带 _parse_failed 标记(%s)——拒绝 review 旧/坏卡"
                % ds.get("hint", "")
            )
        return doc, jp
    md = bdir / f"{day}-morning.md"
    if md.is_file():
        data = repair_json(md.read_text(encoding="utf-8"))
        if data:
            doc = {"_engine": {}, "ds": data}
            ds = doc.get("ds") if isinstance(doc.get("ds"), dict) else None
            if ds and ds.get("_parse_failed"):
                raise SystemExit(
                    "[land] morning.json 带 _parse_failed 标记(%s)——拒绝 review 旧/坏卡"
                    % ds.get("hint", "")
                )
            return doc, jp
    return None, jp


def glm_review(day: str, data: dict) -> dict:
    cands = data.get("candidates") or []
    prompt = (
        f"你是 Scout GLM review/编译。日期 {day}。对下列晨会 JSON 做 Markdown 编译："
        "## 编译结论 ## Top4/候选卡 ## 风险 ## 一句话给 Lyra。"
        "不编造报价。\n\n"
        + json.dumps({"candidates": cands, "macro": data.get("macro"),
                      "conclusion": data.get("conclusion")}, ensure_ascii=False)[:9000]
    )
    body = {
        "lane": "smoke",
        "messages": [
            {"role": "system", "content": "Scout GLM review. Chinese Markdown."},
            {"role": "user", "content": prompt},
        ],
        "persist": False,
        "cloud_backend": "glm52_cloud",
    }
    ts = _now_ts()
    try:
        r = http_json(GW + "/task/cloud_chat", body, timeout=300)
        text = (r.get("content") or "").strip()
        origin = normalize_origin("glm52_cloud" if text else "ds")
        return {
            "text": text,
            "meta": {
                "via": "8501:/task/cloud_chat",
                "substrate": r.get("substrate") or "glm52",
                "review_origin": origin,
                "review_ts": ts,
                "ok": bool(text),
                "memory_write": r.get("memory_write"),
            },
        }
    except Exception as e:
        return {
            "text": "",
            "meta": {
                "ok": False,
                "error": str(e),
                "review_origin": "ds",
                "review_ts": ts,
            },
        }


def emit(day, title, body_store, bp, data, cross, glm_txt, glm_meta):
    origin = normalize_origin((glm_meta or {}).get("review_origin"), fallback="ds")
    review_ts = (glm_meta or {}).get("review_ts") or _now_ts()
    payload = {
        "date": day,
        "mode": "morning",
        "title": title,
        "body": body_store,
        "brief_path": str(bp),
        "via": "scout_land_option",
        "expanded_final": glm_txt or "",
        "expanded_meta": glm_meta or {},
        "primary_review": "glm" if glm_txt else "ds",
        "review_origin": origin,
        "review_ts": review_ts,
        "glm_final": glm_txt or "",
        "structured": {"_engine": cross, "ds": data},
        "liquidation_watch": bool((cross or {}).get("liquidation_watch")),
        "amc_tonight": (cross or {}).get("amc_tonight"),
    }
    data_b = json.dumps(
        {"source": "aether", "kind": "aether_scout_brief", "payload": payload},
        ensure_ascii=False,
    ).encode()
    if not wait_gw():
        raise SystemExit("[land] gateway8501 down — cannot emit")
    last = None
    for attempt in range(5):
        req = urllib.request.Request(
            GW + "/store/events", data=data_b,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                print("[land] aether emit", resp.status, "attempt", attempt + 1)
                if 200 <= resp.status < 300:
                    return
                last = "status=%s" % resp.status
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(e)
            print("[land] emit fail attempt", attempt + 1, e)
            wait_gw(attempts=4, sleep_s=3)
            time.sleep(2 + attempt)
    raise SystemExit("[land] emit gave up: %s" % last)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument(
        "--restamp-final-only",
        action="store_true",
        help="T1 ops: rewrite final.md origin banner from morning.json review; no GLM/emit",
    )
    a = ap.parse_args()
    sys.path.insert(0, str(SCOUT))
    import fetchers  # noqa

    day = (a.date or fetchers.trading_date().isoformat())[:10]
    doc, jp = load_day(day)
    if not doc:
        raise SystemExit(f"[land] no morning data for {day}")
    data = doc.get("ds") if isinstance(doc.get("ds"), dict) else doc.get("data")
    if not isinstance(data, dict):
        raise SystemExit("[land] ds missing")
    cross = doc.get("_engine") if isinstance(doc.get("_engine"), dict) else {}
    title = f"Scout 晨会 · {day}"
    final = SCOUT / "briefs" / f"{day}-morning-final.md"

    if a.restamp_final_only:
        rev = doc.get("review") if isinstance(doc.get("review"), dict) else {}
        meta = rev.get("glm_meta") if isinstance(rev.get("glm_meta"), dict) else {}
        origin = normalize_origin(
            rev.get("review_origin") or meta.get("review_origin"),
            fallback="unknown",
        )
        # Do not upgrade unknown from guess; if json already has live origin, surface it
        review_ts = rev.get("review_ts") or meta.get("review_ts") or _now_ts()
        body = rev.get("glm_final") or rev.get("expanded_final") or ""
        if not body and final.is_file():
            body = final.read_text(encoding="utf-8")
        if not body:
            raise SystemExit("[land] restamp: no final body")
        # persist ts onto review block
        rev = dict(rev)
        rev["review_origin"] = origin
        rev["review_ts"] = review_ts
        if isinstance(rev.get("glm_meta"), dict):
            rev["glm_meta"] = {**rev["glm_meta"], "review_origin": origin, "review_ts": review_ts}
        doc["review"] = rev
        jp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        final.write_text(
            stamp_final_markdown(body, origin=origin, review_ts=review_ts, title=title),
            encoding="utf-8",
        )
        print(f"[land] restamp-final-only {final} origin={origin} ts={review_ts}")
        return

    cands = [c for c in (data.get("candidates") or []) if isinstance(c, dict)]
    if not cands:
        raise SystemExit("[land] no candidates")
    if all(c.get("empty") for c in cands):
        print("[land] ⚠ 四槽全空(制度上合法但罕见)——请人工确认晨会非事故产物")

    glm = glm_review(day, data)
    meta = dict(glm.get("meta") or {})
    origin = normalize_origin(meta.get("review_origin"), fallback="ds")
    review_ts = meta.get("review_ts") or _now_ts()
    glm_txt = (glm.get("text") or "").strip()
    # 硬闸:DS json 不是落盘。无 GLM 正文或 origin 不是 glm52_cloud → 禁止写 final / emit
    if not glm_txt or origin != "glm52_cloud":
        raise SystemExit(
            "[land] GLM 编译未完成 origin=%s chars=%d err=%s——禁止把 DS 直出当晨报落盘"
            % (origin, len(glm_txt), (meta.get("error") or "")[:160])
        )
    meta["review_origin"] = origin
    meta["review_ts"] = review_ts
    review = {
        "primary_label": "glm",
        "review_origin": origin,
        "review_ts": review_ts,
        "glm_final": glm_txt,
        "glm_meta": meta,
        "expanded_final": glm_txt,
        "expanded_meta": meta,
    }
    doc["ds"] = data
    doc["_engine"] = cross
    doc["review"] = review
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    final.write_text(
        stamp_final_markdown(
            glm_txt,
            origin=origin,
            review_ts=review_ts,
            title=title,
        ),
        encoding="utf-8",
    )
    ticks = ",".join(
        str(c.get("ticker") or "") for c in cands if not c.get("empty")
    )
    body_store = f"scout {day} · {ticks} · briefs/{day}-morning.html"
    emit(day, title, body_store, jp, data, cross, glm_txt, meta)
    print(
        "[land] wrote", jp,
        "glm_chars", len(glm_txt),
        "origin", origin,
        "ts", review_ts,
    )


if __name__ == "__main__":
    main()
