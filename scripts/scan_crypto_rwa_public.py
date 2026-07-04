#!/usr/bin/env python3
"""Local public-URL scanner for Crypto/RWA evidence cards.

Fetches allowlisted public pages from deliver/crypto/scan_sources.json and writes
JSON evidence cards under deliver/crypto/evidence/.

Constraints: no wallet, no API keys, no private endpoints, stdlib HTTP only.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "deliver" / "crypto" / "scan_sources.json"
EVIDENCE_DIR = ROOT / "deliver" / "crypto" / "evidence"
LAST_RUN_PATH = ROOT / "deliver" / "crypto" / "scan_last_run.json"
LOG_PATH = ROOT / "logs" / "crypto_rwa_scan.log"

USER_AGENT = "Jarvis-Crypto-RWA-LocalScanner/1.0 (+local research; no wallet)"
TIMEOUT_SEC = 15
MAX_SNIPPET = 420

CHENG_KEYWORDS = (
    "regulatory",
    "regulation",
    "enforcement",
    "securities",
    "lawsuit",
    "subpoena",
    "sanction",
    "hack",
    "exploit",
    "breach",
    "custody loss",
    "insolvency",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _strip_html(raw: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_title(raw_html: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw_html)
    if match:
        title = _strip_html(match.group(1))
        if title:
            return title[:160]
    match = re.search(
        r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        raw_html,
    )
    if match:
        return html.unescape(match.group(1)).strip()[:160]
    return ""


def _extract_description(raw_html: str) -> str:
    for pattern in (
        r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'(?is)<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
    ):
        match = re.search(pattern, raw_html)
        if match:
            desc = html.unescape(match.group(1)).strip()
            if desc:
                return desc[:MAX_SNIPPET]
    stripped = _strip_html(raw_html)
    return stripped[:MAX_SNIPPET] if stripped else ""


def _fetch_public_url(url: str) -> tuple[int | None, str, str | None]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with urlopen(req, timeout=TIMEOUT_SEC, context=_SSL_CONTEXT) as resp:
            status = getattr(resp, "status", 200)
            body = resp.read(250_000).decode("utf-8", errors="ignore")
            return status, body, None
    except HTTPError as exc:
        try:
            body = exc.read(80_000).decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        return exc.code, body, str(exc)
    except URLError as exc:
        return None, "", str(exc.reason)


def _needs_cheng_review(
    *,
    text: str,
    force: bool,
    http_status: int | None,
    default_risk: str,
    prior: bool,
    fetch_error: str | None,
) -> bool:
    if prior:
        return True
    if force:
        return True
    if fetch_error or (http_status is not None and http_status >= 400):
        return True
    if default_risk == "high":
        return True
    lowered = text.lower()
    return any(word in lowered for word in CHENG_KEYWORDS)


def _risk_level(default: str, http_status: int | None, text: str) -> str:
    if http_status is not None and http_status >= 400:
        return "high"
    lowered = text.lower()
    if any(word in lowered for word in CHENG_KEYWORDS):
        return "high" if default != "low" else "medium"
    return default if default in {"low", "medium", "high"} else "medium"


def _card_path(card_id: str) -> Path:
    matches = sorted(EVIDENCE_DIR.glob(f"{card_id}*.json"))
    if matches:
        return matches[0]
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", card_id).strip("-").lower()
    return EVIDENCE_DIR / f"{slug}.json"


def _build_card(source: dict[str, Any], *, dry_run: bool) -> tuple[dict[str, Any], str]:
    card_id = str(source.get("id", "")).strip()
    url = str(source.get("url", "")).strip()
    section = str(source.get("section", "")).strip()
    title_hint = str(source.get("title_hint", "")).strip()
    default_risk = str(source.get("default_risk_level", "medium")).strip().lower()
    force_review = bool(source.get("force_cheng_review", False))

    if not card_id or not url or not section:
        return {}, "missing id, url, or section"

    if dry_run:
        return {
            "id": card_id,
            "section": section,
            "source_url": url,
            "dry_run": True,
        }, "dry-run"

    status, body, err = _fetch_public_url(url)
    title = _extract_title(body) or title_hint or card_id
    snippet = _extract_description(body)
    if not snippet:
        snippet = title_hint or f"Fetched public page at {url}."
    if err:
        snippet = f"Fetch issue: {err}. {snippet}".strip()
    if status is not None and status >= 400:
        snippet = f"HTTP {status}. {snippet}".strip()

    existing = _load_json(_card_path(card_id), {})
    prior_review = bool(existing.get("needs_cheng_review", False)) if isinstance(existing, dict) else False
    manual_lock = bool(existing.get("manual_lock", False)) if isinstance(existing, dict) else False

    combined_text = f"{title} {snippet}"
    risk = _risk_level(default_risk, status, combined_text)
    review = _needs_cheng_review(
        text=combined_text,
        force=force_review,
        http_status=status,
        default_risk=risk,
        prior=prior_review,
        fetch_error=err,
    )

    content_hash = hashlib.sha256(body.encode("utf-8", errors="ignore")).hexdigest()[:16]
    now = _utc_now()

    card: dict[str, Any] = {
        "id": card_id,
        "title": existing.get("title", title) if manual_lock and existing.get("title") else title,
        "section": section,
        "source_url": url,
        "risk_level": risk,
        "summary": existing.get("summary", snippet) if manual_lock and existing.get("summary") else snippet,
        "needs_cheng_review": review,
        "created_at": existing.get("created_at", now) if isinstance(existing, dict) and existing.get("created_at") else now,
        "updated_at": now,
        "scan": {
            "method": "public_url_fetch",
            "http_status": status,
            "scanned_at": now,
            "content_hash": content_hash,
            "error": err,
        },
    }
    if manual_lock:
        card["manual_lock"] = True
    return card, "ok" if (status is not None and status < 400) else "warn"


def run_scan(*, dry_run: bool, source_id: str | None) -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    config = _load_json(SOURCES_PATH, {})
    sources = config.get("sources", [])
    if not isinstance(sources, list) or not sources:
        print(f"No sources in {SOURCES_PATH}", file=sys.stderr)
        return 1

    if source_id:
        sources = [s for s in sources if isinstance(s, dict) and s.get("id") == source_id]
        if not sources:
            print(f"Unknown source id: {source_id}", file=sys.stderr)
            return 1

    results: list[dict[str, Any]] = []
    ok_count = warn_count = fail_count = 0

    for source in sources:
        if not isinstance(source, dict):
            continue
        card, outcome = _build_card(source, dry_run=dry_run)
        if not card:
            fail_count += 1
            results.append({"id": source.get("id"), "outcome": "fail", "detail": outcome})
            continue

        if dry_run:
            ok_count += 1
            results.append({"id": card["id"], "outcome": "dry-run", "url": card.get("source_url")})
            continue

        path = _card_path(str(card["id"]))
        path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        rel = str(path.relative_to(ROOT))
        if outcome == "ok":
            ok_count += 1
        elif outcome == "warn":
            warn_count += 1
        else:
            fail_count += 1
        results.append({"id": card["id"], "outcome": outcome, "path": rel, "http_status": card.get("scan", {}).get("http_status")})

    run_doc = {
        "schema": "crypto_rwa_scan_run_v1",
        "ran_at": _utc_now(),
        "dry_run": dry_run,
        "sources_config": str(SOURCES_PATH.relative_to(ROOT)),
        "evidence_dir": str(EVIDENCE_DIR.relative_to(ROOT)),
        "counts": {"ok": ok_count, "warn": warn_count, "fail": fail_count, "total": len(results)},
        "results": results,
    }
    if not dry_run:
        LAST_RUN_PATH.write_text(json.dumps(run_doc, indent=2) + "\n", encoding="utf-8")

    log_line = f"{run_doc['ran_at']} dry_run={dry_run} ok={ok_count} warn={warn_count} fail={fail_count}"
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(log_line + "\n")

    print(json.dumps(run_doc, indent=2))
    return 0 if fail_count == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan public URLs into Crypto/RWA evidence cards.")
    parser.add_argument("--dry-run", action="store_true", help="Validate sources without HTTP fetch or writes.")
    parser.add_argument("--source", help="Scan a single source id from scan_sources.json")
    args = parser.parse_args()
    return run_scan(dry_run=args.dry_run, source_id=args.source)


if __name__ == "__main__":
    raise SystemExit(main())
