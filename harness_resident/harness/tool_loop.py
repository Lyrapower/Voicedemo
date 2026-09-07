"""Parse ```tool blocks (H1-style) and https URLs in the goal; call web.fetch."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

from . import web_fetch_v1 as WF

TOOL_FENCE = re.compile(r"```tool\s*\n(.*?)```", re.S | re.I)
URL_RE = re.compile(r"https://[^\s)>\]]+")
MAX_FETCH_ROUNDS = 2
MAX_URLS = 4

EGRESS_PATH = str(Path(__file__).resolve().parents[2] / "EGRESS.md")


def parse_tool_blocks(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for raw in TOOL_FENCE.findall(text or ""):
        item: dict[str, str] = {"raw": raw.strip()}
        for line in raw.splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            item[k.strip().lower()] = v.strip().strip('"').strip("'")
        m = URL_RE.search(raw)
        if m:
            item.setdefault("url", m.group(0))
        out.append(item)
    return out


def urls_from_goal(goal: str) -> list[str]:
    seen: list[str] = []
    for u in URL_RE.findall(goal or ""):
        u = u.rstrip(".,;\"'")
        if u not in seen:
            seen.append(u)
    return seen


def collect_fetch_urls(goal: str, worker_text: str) -> list[str]:
    urls: list[str] = []
    for block in parse_tool_blocks(worker_text):
        name = (block.get("name") or block.get("tool") or "web.fetch").lower()
        if "fetch" in name or "web.fetch" in name or block.get("url"):
            u = block.get("url") or ""
            if u.startswith("https://") and u not in urls:
                urls.append(u)
    for u in urls_from_goal(goal):
        if u not in urls:
            urls.append(u)
    return urls[:MAX_URLS]


def format_tool_result(fr: dict[str, Any]) -> str:
    if fr.get("ok"):
        body = str(fr.get("text") or "")[:4000]
        return (
            f"[web.fetch ok grade={fr.get('grade')} chars={fr.get('chars')} "
            f"url={fr.get('source_url')}]\n{body}"
        )
    return (
        f"[web.fetch {fr.get('status') or 'DENIED'} "
        f"reason={fr.get('reason') or ''} url={fr.get('source_url')}]"
    )


def run_fetches(
    urls: list[str],
    *,
    lane: str,
    db_path: str,
    route_id: str,
    mission_id: str,
    egress_path: str = EGRESS_PATH,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for url in urls:
        results.append(WF.fetch(
            url,
            lane,
            egress_path=egress_path,
            db_path=db_path,
            route_id=route_id,
            mission_id=mission_id,
            substrate=lane,
        ))
    return results
