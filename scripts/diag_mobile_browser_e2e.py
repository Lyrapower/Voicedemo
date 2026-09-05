#!/usr/bin/env python3
"""Real browser E2E: mobile viewport grid.html → 8501 → 7-day store → 4-way hash diff."""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

GW = "http://127.0.0.1:8501"
PROMPT = (
    "不要按trading上下文回答，站在Grid 整体、跨 substrate 的位置看：换大底座后，什么会被放大，"
    "什么能力会展开，什么边界不可变？怎样辨认是 Grid 在用底座，还是底座在覆盖 Grid"
)
OUT = Path(__file__).resolve().parents[1] / "grid-sovereign-runtime" / "traces" / "diag_mobile_browser_e2e.json"


def fetch_diag(route_id: str) -> dict:
    url = f"{GW}/diag/chat-stream/{route_id}"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode())


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report: dict = {"pass": False}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            is_mobile=True,
            has_touch=True,
        )
        page = ctx.new_page()
        page.goto(f"{GW}/app/grid.html?v=20260717m", wait_until="networkidle", timeout=60000)

        page.wait_for_function(
            "() => typeof gridStoreHist !== 'undefined' && gridStoreHist.chat.length >= 0",
            timeout=30000,
        )
        time.sleep(1.5)
        store_n = page.evaluate("() => gridStoreHist.chat.length")
        report["store_messages_loaded"] = store_n

        page.fill("#i", PROMPT)
        page.click("#s")

        deadline = time.time() + 600
        client_diag = None
        while time.time() < deadline:
            client_diag = page.evaluate("() => window.__LAST_STREAM_DIAG__ || null")
            if client_diag and client_diag.get("four_way"):
                break
            if client_diag and client_diag.get("route_id") and client_diag.get("finish"):
                break
            time.sleep(2)

        route_id = (client_diag or {}).get("route_id")
        gw_diag = fetch_diag(route_id) if route_id else {}

        dom_tail = page.evaluate(
            """() => {
              const els = document.querySelectorAll('.g:not(.err)');
              const last = els[els.length - 1];
              return last ? last.textContent.slice(-120) : '';
            }"""
        )

        four = gw_diag.get("four_way") or (client_diag or {}).get("four_way") or {}
        gw = gw_diag.get("gateway") or {}
        report.update({
            "route_id": route_id,
            "store_messages_loaded": store_n,
            "lengths": {
                "raw_model_chars": gw.get("char_len"),
                "raw_model_utf8": gw.get("utf8_bytes"),
                "browser_acc_chars": (client_diag or {}).get("browser_acc_char_len")
                or gw_diag.get("client", {}).get("browser_acc_char_len"),
                "dom_chars": (client_diag or {}).get("dom_rendered_char_len")
                or gw_diag.get("client", {}).get("dom_rendered_char_len"),
            },
            "hashes": {
                "raw_model": four.get("raw_model_hash") or gw.get("raw_accum_hash"),
                "gateway_final": four.get("gateway_final_hash") or gw.get("gateway_sent_hash"),
                "browser_acc": four.get("browser_acc_hash"),
                "dom_rendered": four.get("dom_rendered_hash"),
            },
            "finish_reason": (client_diag or {}).get("finish", {}).get("finish_reason"),
            "upstream_finish": (client_diag or {}).get("finish", {}).get("upstream_finish_reason"),
            "continuation_retry": (client_diag or {}).get("finish", {}).get("continuation_retry"),
            "chunk_count": gw.get("chunk_count"),
            "sse_terminal": gw_diag.get("client", {}).get("sse_terminal"),
            "hash_mismatch_layers": gw_diag.get("hash_mismatch_layers") or [],
            "tail_dom": dom_tail,
        })

        ref = report["hashes"].get("raw_model")
        mism = [k for k, v in report["hashes"].items() if v and ref and v != ref]
        report["hash_mismatch_layers"] = mism or report["hash_mismatch_layers"]
        report["pass"] = (
            bool(ref)
            and not mism
            and not report.get("continuation_retry")
            and report.get("finish_reason") == "stop"
            and (report["lengths"].get("raw_model_chars") or 0) > 200
        )

        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
