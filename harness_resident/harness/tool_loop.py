"""Parse ```tool blocks (H1-style) and https URLs in the goal; call web.fetch."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

from . import web_fetch_v1 as WF

TOOL_FENCE = re.compile(r"```tool\s*\n(.*?)```", re.S | re.I)
URL_RE = re.compile(r"https://[^\s)>\]]+")
MAX_FETCH_ROUNDS = int(__import__("os").environ.get("WEB_FETCH_MAX_ROUNDS", "4"))
MAX_SEARCH_ROUNDS = 1
MAX_URLS = int(__import__("os").environ.get("WEB_FETCH_MAX_URLS", "6"))
MAX_QUERIES = 3
MIN_CONTENT_CHARS = 200

PROVIDER_KIND = {
    "wikipedia": "topic_lookup",
    "ddg_api": "instant_answer",
    "ddg_html": "web_search",
    "ddg_lite": "web_search",
    "github": "repo_search",
    "searxng": "web_search",
}

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


def collect_search_queries(goal: str, worker_text: str) -> dict:
    qs: list[str] = []
    rewrites: list[dict] = []
    for block in parse_tool_blocks(worker_text):
        name = (block.get("name") or block.get("tool") or "").lower()
        if "search" in name:
            q = block.get("query") or block.get("q") or ""
            if q and q not in qs:
                qs.append(q)
                rewrites.append({"from": q, "to": q, "reason": "tool_block"})
    orig = (goal or "").strip()
    if orig:
        kept = orig[:300]
        if kept not in qs:
            qs.append(kept)
            rewrites.append({"from": orig[:80], "to": kept, "reason": "preserve_original"})
        keys = re.findall(
            r"grant[s]?|rfp|procurement|eligib\w*|open-?source|data-?value|legal|region|deadline|fy\s*\d{2}|opportunity",
            orig, re.I,
        )
        if keys:
            compact = " ".join(dict.fromkeys(k.lower() for k in keys)) + " listing source eligibility"
            if compact not in qs:
                qs.append(compact[:160])
                rewrites.append({"from": orig[:80], "to": compact[:160], "reason": "keep_eligibility_domain"})
    return {"queries": qs[:MAX_QUERIES], "rewrites": rewrites[:MAX_QUERIES]}


def run_search(
    queries: list[str],
    *,
    lane: str,
    db_path: str,
    route_id: str,
    mission_id: str,
    egress_path: str = EGRESS_PATH,
) -> dict:
    return WF.search_many(
        queries,
        lane,
        n=8,
        max_pages=2,
        egress_path=egress_path,
        db_path=db_path,
        route_id=route_id,
        mission_id=mission_id,
        substrate=lane,
    )


def format_search_result(sr: dict) -> str:
    lines = [
        f"[web.search status={sr.get('status')} ok={sr.get('ok')} "
        f"retryable={sr.get('retryable')} n={len(sr.get('results') or [])} "
        f"discovery={sr.get('discovery_class','')}]"
    ]
    for r in (sr.get("results") or [])[:8]:
        kind = r.get("provider_kind") or PROVIDER_KIND.get(str(r.get("provider") or ""), "unknown")
        lines.append(
            f"- [{kind}/{r.get('provider','')}] {r.get('title','')} | {r.get('url','')} | "
            f"{r.get('snippet','')[:160]}"
        )
    # 衔拍3 §①3: catalog rows 全量展示(不混入 results[:8] 被截断)——worker 据此对每条判 HIT/MISS
    cat = sr.get("catalog") or {}
    cat_rows = cat.get("rows") or []
    if cat_rows:
        lines.append(f"[grants.catalog status={cat.get('status')} hit_count={cat.get('hit_count')} rows={len(cat_rows)}]")
        for r in cat_rows:
            lines.append(
                f"- [grants_gov] opp {r.get('opportunity_id')} | {r.get('title','')} | "
                f"agency={r.get('publisher','')} | deadline={r.get('deadline','')} | "
                f"status={r.get('status','')} | summary={(r.get('summary') or '')[:200]}"
            )
    for q in sr.get("queries") or []:
        lines.append(f"query {q.get('query')} status={q.get('status')} attempts={q.get('attempts')}")
    return "\n".join(lines)


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
    if fr.get("ok") and fr.get("status") != "INSUFFICIENT_CONTENT":
        body = str(fr.get("text") or "")[:4000]
        return (
            f"[web.fetch ok grade={fr.get('grade')} chars={fr.get('chars')} "
            f"url={fr.get('source_url')}]\n{body}"
        )
    if fr.get("status") == "INSUFFICIENT_CONTENT":
        return (
            f"[web.fetch INSUFFICIENT_CONTENT chars={fr.get('chars')} "
            f"http={fr.get('http_status')} url={fr.get('source_url')}]"
        )
    return (
        f"[web.fetch {fr.get('status') or 'DENIED'} "
        f"reason={fr.get('reason') or ''} url={fr.get('source_url')}]"
    )


def qualify_fetch(fr: dict[str, Any]) -> dict[str, Any]:
    out = dict(fr)
    chars = int(out.get("chars") or len(str(out.get("text") or "")))
    status = str(out.get("status") or "")
    http = out.get("http_status")
    text = str(out.get("text") or "")
    if out.get("ok") and (chars < MIN_CONTENT_CHARS or (http and int(http) == 202 and chars < MIN_CONTENT_CHARS)):
        out["ok"] = False
        out["status"] = "INSUFFICIENT_CONTENT"
        out["chars"] = chars
    if re.search(r"anomaly-modal|challenge-form|bots use DuckDuckGo|captcha", text, re.I):
        out["ok"] = False
        out["status"] = "SEARCH_CHALLENGE"
    out.setdefault("http_status", http)
    return out


def classify_discovery(results: list[dict], *, lane: str) -> str:
    concrete = []
    for r in results or []:
        kind = r.get("provider_kind") or PROVIDER_KIND.get(str(r.get("provider") or ""), "")
        title = str(r.get("title") or "")
        url = str(r.get("url") or "")
        snip = str(r.get("snippet") or "")
        blob = f"{title} {snip}"
        has_date = bool(re.search(r"20\d{2}|deadline|due|posted|closing", blob, re.I))
        has_opp = bool(re.search(r"grant|rfp|solicitation|opportunity|award|nofo", blob, re.I))
        listing = bool(re.search(
            r"opportunity number|nofo|foa-|solicitation no|closing date|posted date|eligibility:",
            blob, re.I,
        ))
        if kind == "catalog_discovery" and listing and url.startswith("https://"):
            concrete.append(r)
        elif kind == "web_search" and url.startswith("https://") and has_opp and (has_date or listing):
            concrete.append(r)
        elif has_date and has_opp and listing and url.startswith("https://"):
            concrete.append(r)
    if concrete:
        return "catalog_or_listing"
    kinds = set()
    for r in (results or []):
        kinds.add(r.get("provider_kind") or PROVIDER_KIND.get(str(r.get("provider") or ""), ""))
    if not results:
        return "INSUFFICIENT_DISCOVERY"
    if kinds <= {"topic_lookup", "instant_answer", "catalog_discovery", ""}:
        return "INSUFFICIENT_DISCOVERY"
    return "unverified_hits"


# Official catalog pages, verified live against EGRESS exact rows. Do not invent APIs.
SCOUT_CATALOG_URLS = [
    "https://www.grants.gov/",
]


def catalog_follow_urls(text: str, *, base: str = "https://www.grants.gov") -> list[str]:
    """Same-host listing/extract links discovered in an already-fetched official page."""
    out: list[str] = []
    for href in re.findall(r"""href=["']([^"']+)["']""", text or "", re.I):
        href = html_unescape(href).split("#")[0].strip()
        if not href or href.startswith("javascript:"):
            continue
        if href.startswith("/"):
            href = base.rstrip("/") + href
        if not href.startswith("https://www.grants.gov/"):
            continue
        if re.search(r"extract|\.xml|download|search-grants|opp", href, re.I):
            if href not in out and href.rstrip("/") != base.rstrip("/"):
                out.append(href)
    return out[:4]


def html_unescape(s: str) -> str:
    return s.replace("&amp;", "&")


def parse_catalog_rows(text: str, *, source_url: str) -> list[dict]:
    rows = []
    xml_titles = re.findall(
        r"<OpportunityTitle>([^<]{8,200})</OpportunityTitle>", text or "", re.I)
    xml_nums = re.findall(
        r"<OpportunityNumber>([^<]{3,80})</OpportunityNumber>", text or "", re.I)
    xml_dead = re.findall(
        r"<CloseDate>([^<]{4,40})</CloseDate>|<CurrentClosingDate>([^<]{4,40})</CurrentClosingDate>",
        text or "", re.I)
    for i, title in enumerate(xml_titles[:8]):
        num = xml_nums[i] if i < len(xml_nums) else ""
        dead = ""
        if i < len(xml_dead):
            dead = xml_dead[i][0] or xml_dead[i][1]
        rows.append({
            "provider": "grants_gov",
            "provider_kind": "catalog_discovery",
            "title": re.sub(r"\s+", " ", title).strip(),
            "url": source_url,
            "snippet": f"opportunity number {num or 'unknown'} closing {dead or 'unknown'} eligibility: unknown",
            "opportunity_number": num or "",
            "deadline": dead or "",
        })
    return rows


def catalog_hits_from_fetch(fr: dict[str, Any]) -> list[dict]:
    """Turn a qualified catalog page into discovery rows. Not a search provider."""
    if not fr.get("ok"):
        return []
    text = str(fr.get("text") or "")
    url = str(fr.get("source_url") or "")
    if not url.startswith("https://") :
        return []
    parsed = parse_catalog_rows(text, source_url=url)
    if parsed:
        return parsed
    if len(text) < MIN_CONTENT_CHARS:
        return []
    title = "grants.gov catalog"
    m = re.search(r"<title>([^<]{4,80})</title>", text, re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
    snippet = re.sub(r"<[^>]+>", " ", text)
    snippet = re.sub(r"\s+", " ", snippet).strip()[:240]
    return [{
        "provider": "grants_gov",
        "provider_kind": "catalog_discovery",
        "title": title,
        "url": url,
        "snippet": snippet or "official grant catalog",
    }]


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


def catalog_keyword(goal: str) -> str:
    g = (goal or "").strip()
    if not g:
        return "grant"
    return g[:200]


def derive_catalog_query(goal: str) -> dict:
    original = (goal or "").strip()
    derived = catalog_keyword(original)
    return {
        "original_query": original,
        "derived_query": derived,
        "derivation": "instance goal truncated to catalog API keyword max 200; not a template slice",
    }


def run_grants_catalog(
    original_query: str,
    *,
    lane: str,
    db_path: str,
    route_id: str,
    mission_id: str,
    egress_path: str = EGRESS_PATH,
    max_details: int = 5,
) -> dict:
    from . import web_fetch_v3 as W3
    derived = derive_catalog_query(original_query)
    kw = derived["derived_query"]
    search = W3.catalog_json_post(
        W3.CATALOG_SEARCH2,
        {"rows": 10, "keyword": kw, "oppStatuses": "posted"},
        lane,
        egress_path=egress_path,
        db_path=db_path,
        route_id=route_id,
        mission_id=mission_id,
        substrate=lane,
    )
    out = {
        "ok": bool(search.get("ok")),
        "status": search.get("status"),
        "reason": search.get("reason"),
        "original_query": original_query,
        "derived_query": kw,
        "derivation": derived["derivation"],
        "matched_rule": search.get("matched_rule"),
        "match_kind": search.get("match_kind"),
        "search": {"source_url": search.get("source_url"), "errorcode": search.get("errorcode"),
                   "http": search.get("status")},
        "rows": [],
        "pagination_incomplete": True,
    }
    if not search.get("ok"):
        return out
    parsed = W3.normalize_opp_hits(
        search.get("json") or {},
        source_url=str(search.get("source_url") or W3.CATALOG_SEARCH2),
        fetched_at=search.get("fetched_at") or 0,
        original_query=original_query,
        derived_query=kw,
    )
    out["pagination_incomplete"] = bool(parsed.get("pagination_incomplete"))
    out["hit_count"] = parsed.get("hit_count")
    rows = []
    for row in (parsed.get("rows") or [])[:max_details]:
        detail = W3.catalog_json_post(
            W3.CATALOG_FETCH_OPP,
            {"opportunityId": row["opportunity_id"]},
            lane,
            egress_path=egress_path,
            db_path=db_path,
            route_id=route_id,
            mission_id=mission_id,
            substrate=lane,
        )
        row = dict(row)
        row["detail_ok"] = bool(detail.get("ok"))
        row["detail_status"] = detail.get("status")
        dj = detail.get("json") if isinstance(detail.get("json"), dict) else {}
        data = dj.get("data") if isinstance(dj.get("data"), dict) else {}
        if data:
            row["title"] = str(data.get("opportunityTitle") or row.get("title") or "unknown")
            row["publisher"] = str(data.get("owningAgencyName") or data.get("agencyName") or row.get("publisher") or "unknown")
            row["published_at"] = str(data.get("postedDate") or row.get("published_at") or "unknown")
            row["deadline"] = str(data.get("closeDate") or data.get("currentClosingDate") or row.get("deadline") or "unknown")
            elig = data.get("eligibility") or data.get("eligibleApplicants") or row.get("eligibility") or "unknown"
            if isinstance(elig, list):
                elig = "; ".join(str(x) for x in elig[:8]) or "unknown"
            row["eligibility"] = str(elig).strip() or "unknown"
            st = str(data.get("opportunityStatus") or row.get("status") or "unknown")
            row["status"] = st
            if st.lower() in {"forecasted", "forecast"}:
                row["qualification"] = "rejected"
                row["qualification_reason"] = "forecasted is not an open application"
            elif st.lower() not in {"posted", "posted - forecasted"}:
                row["qualification"] = "needs_verification"
                row["qualification_reason"] = f"status {st}; posted does not prove still accepting"
            else:
                row["qualification"] = "needs_verification"
                row["qualification_reason"] = "posted list+detail; eligibility timezone unknown unless present"
            syn = data.get("synopsis") or data.get("description") or ""
            blob = str(syn)[:400]
            row["summary"] = blob
            row["evidence_hash"] = __import__("hashlib").sha256(blob.encode("utf-8", "replace")).hexdigest()[:16]
        else:
            row["qualification"] = "needs_verification"
            row["qualification_reason"] = "detail missing or denied"
        rows.append(row)
    out["rows"] = rows
    out["ok"] = bool(rows) or (parsed.get("hit_count") == 0)
    if parsed.get("hit_count") == 0 and not rows:
        out["status"] = "NO_MATCH"
    elif rows:
        out["status"] = "ok"
    return out


def run_grants_detail(
    opp_id: str,
    *,
    lane: str,
    db_path: str,
    route_id: str = "",
    mission_id: str = "",
    egress_path: str = EGRESS_PATH,
) -> dict:
    """grants.detail(oppId) — runner only. Extracts applicantTypes/eligibility."""
    from . import web_fetch_v3 as W3
    detail = W3.catalog_json_post(
        W3.CATALOG_FETCH_OPP, {"opportunityId": str(opp_id)}, lane,
        egress_path=egress_path, db_path=db_path, route_id=route_id,
        mission_id=mission_id, substrate=lane,
    )
    out: dict[str, Any] = {
        "ok": bool(detail.get("ok")), "opportunity_id": str(opp_id),
        "eligibility": "", "applicant_types": [], "title": "",
        "deadline": "", "status": "", "agency": "",
    }
    dj = detail.get("json") if isinstance(detail.get("json"), dict) else {}
    data = dj.get("data") if isinstance(dj.get("data"), dict) else {}
    if not data:
        return out
    syn = data.get("synopsis") if isinstance(data.get("synopsis"), dict) else {}
    at = (syn.get("applicantTypes") or data.get("applicantTypes")
          or data.get("eligibleApplicants") or data.get("eligibility") or [])
    if isinstance(at, dict):
        at = at.get("applicantType") or at.get("list") or list(at.values())
    if not isinstance(at, list):
        at = [at]
    labels = []
    for x in at:
        if isinstance(x, dict):
            labels.append(str(x.get("description") or x.get("name") or x.get("id") or "").strip())
        else:
            labels.append(str(x).strip())
    labels = [x for x in labels if x]
    out["applicant_types"] = labels
    desc = str(syn.get("applicantEligibilityDesc") or "").strip()
    out["eligibility"] = ("; ".join(labels) if labels else "") or desc[:400] or str(data.get("eligibility") or "").strip()
    out["title"] = str(data.get("opportunityTitle") or syn.get("opportunityTitle") or "").strip()
    raw_dl = str(syn.get("responseDateStr") or data.get("closeDate") or data.get("currentClosingDate") or "").strip()
    # grants.gov: 2027-01-20-00-00-00
    parts = raw_dl.split("-")
    if len(parts) >= 3 and parts[0].isdigit() and len(parts[0]) == 4:
        out["deadline"] = f"{parts[0]}-{parts[1]}-{parts[2]}"
    else:
        out["deadline"] = raw_dl
    ost = str(data.get("ost") or data.get("opportunityStatus") or syn.get("opportunityStatus") or "").strip()
    out["status"] = "posted" if ost.upper() == "POSTED" else ost
    out["agency"] = str((data.get("agencyDetails") or {}).get("agencyName") or syn.get("agencyName") or "").strip()
    return out


# 衔拍3 §①1: 结构化 catalog——同 query 一个 mission 内缓存(消 RATE_LIMITED×10)。
_CATALOG_CACHE: dict[str, list] = {}


def _catalog_cache_key(mission_id: str, keyword: str, statuses: str, agencies: str) -> str:
    return f"{mission_id}|{keyword}|{statuses}|{agencies}"


def run_grants_catalog_structured(
    search_block: dict,
    *,
    lane: str,
    db_path: str,
    route_id: str,
    mission_id: str,
    egress_path: str = EGRESS_PATH,
    max_details: int = 10,
) -> dict:
    """Structured grants.gov catalog from a missions.toml [search] block.

    Iterates keywords (one Search2 POST each, cached per mission+keyword), merges rows,
    dedupes by opportunity_id, filters by deadline_min_days, then fetches detail per row.
    Returns {ok, status, rows, hit_count, keywords_run, cached, ...}.
    """
    from . import web_fetch_v3 as W3
    import time as _t
    keywords = list(search_block.get("keywords") or [])
    opp_statuses = search_block.get("opp_statuses") or ["posted"]
    agencies = search_block.get("agencies") or []
    deadline_min_days = int(search_block.get("deadline_min_days") or 0)
    rows_per = int(search_block.get("rows_per_query") or 10)
    offset = int(search_block.get("offset") or 0)  # 衔拍3: 分页——每跳取不同页,累积 HITs
    statuses_str = ",".join(opp_statuses) if isinstance(opp_statuses, list) else str(opp_statuses)
    agencies_str = ",".join(agencies) if isinstance(agencies, list) else (str(agencies) if agencies else "")
    out: dict[str, Any] = {
        "ok": False, "status": "pending", "rows": [], "hit_count": 0,
        "keywords_run": [], "cached_hits": 0, "deadline_min_days": deadline_min_days,
        "original_queries": keywords,
    }
    if not keywords:
        out["status"] = "NO_KEYWORDS"
        return out
    merged: dict[str, dict] = {}
    cached_hits = 0
    import time as _t2
    for kw in keywords:
        ckey = _catalog_cache_key(mission_id, kw, statuses_str, agencies_str) + f"|off{offset}"
        if ckey in _CATALOG_CACHE:
            cached_hits += 1
            for r in _CATALOG_CACHE[ckey]:
                merged.setdefault(r["opportunity_id"], r)
            out["keywords_run"].append({"keyword": kw, "cached": True})
            continue
        body = {"rows": rows_per, "keyword": kw, "oppStatuses": statuses_str}
        if offset > 0:
            body["startRecordNum"] = offset
        if agencies_str:
            body["agencies"] = agencies_str
        # retry on transient failure (CONNECT_FAILED/TIMEOUT) — 衔拍3 §①1 可靠性
        search = None
        for attempt in range(3):
            search = W3.catalog_json_post(
                W3.CATALOG_SEARCH2, body, lane,
                egress_path=egress_path, db_path=db_path, route_id=route_id,
                mission_id=mission_id, substrate=lane,
            )
            if search.get("ok"):
                break
            _t2.sleep(1.0 * (attempt + 1))  # backoff 1s, 2s
        rows_k = []
        if search and search.get("ok"):
            parsed = W3.normalize_opp_hits(
                search.get("json") or {},
                source_url=str(search.get("source_url") or W3.CATALOG_SEARCH2),
                fetched_at=search.get("fetched_at") or 0,
                original_query=kw, derived_query=kw,
            )
            rows_k = parsed.get("rows") or []
            _CATALOG_CACHE[ckey] = rows_k
        for r in rows_k:
            merged.setdefault(r["opportunity_id"], r)
        out["keywords_run"].append({"keyword": kw, "cached": False, "ok": bool(search and search.get("ok")),
                                    "status": (search or {}).get("status"), "n": len(rows_k),
                                    "attempts": attempt + 1})
        _t2.sleep(0.4)  # gentle pacing between keywords (avoid grants.gov rate limit)
    out["cached_hits"] = cached_hits
    # deadline filter (client-side; closeDate >= now + deadline_min_days)
    now = _t.time()
    cutoff = now + deadline_min_days * 86400 if deadline_min_days > 0 else 0
    rows = list(merged.values())
    if cutoff > 0:
        kept = []
        for r in rows:
            dl = r.get("deadline") or ""
            try:
                import datetime as _dt
                ts = _dt.datetime.fromisoformat(dl.replace("Z", "")).timestamp()
            except Exception:
                ts = 0
            if ts == 0 or ts >= cutoff:
                kept.append(r)
        rows = kept
    # detail fetch per row (grants.detail by oppId — worker never拼 URL)
    detailed = []
    for row in rows[:max_details]:
        detail = W3.catalog_json_post(
            W3.CATALOG_FETCH_OPP, {"opportunityId": row["opportunity_id"]}, lane,
            egress_path=egress_path, db_path=db_path, route_id=route_id,
            mission_id=mission_id, substrate=lane,
        )
        row = dict(row)
        row["detail_ok"] = bool(detail.get("ok"))
        row["detail_status"] = detail.get("status")
        dj = detail.get("json") if isinstance(detail.get("json"), dict) else {}
        data = dj.get("data") if isinstance(dj.get("data"), dict) else {}
        if data:
            row["title"] = str(data.get("opportunityTitle") or row.get("title") or "unknown")
            row["publisher"] = str(data.get("owningAgencyName") or data.get("agencyName") or row.get("publisher") or "unknown")
            row["deadline"] = str(data.get("closeDate") or data.get("currentClosingDate") or row.get("deadline") or "unknown")
            syn = str(data.get("synopsis") or data.get("description") or "")[:400]
            row["summary"] = syn
            at = data.get("applicantTypes") or data.get("eligibleApplicants") or data.get("eligibility") or []
            if isinstance(at, dict):
                at = at.get("applicantType") or at.get("list") or list(at.values())
            if not isinstance(at, list):
                at = [at]
            labels = []
            for x in at:
                if isinstance(x, dict):
                    labels.append(str(x.get("description") or x.get("name") or x.get("id") or "").strip())
                else:
                    labels.append(str(x).strip())
            labels = [x for x in labels if x]
            row["applicant_types"] = labels
            row["eligibility"] = "; ".join(labels) if labels else str(row.get("eligibility") or "")
            row["status"] = str(data.get("opportunityStatus") or data.get("oppStatus") or row.get("status") or "")
        detailed.append(row)
    out["rows"] = detailed
    out["hit_count"] = len(merged)
    out["ok"] = bool(detailed) or bool(merged)
    out["status"] = "ok" if detailed else ("NO_MATCH" if not merged else "NO_DEADLINE_MATCH")
    return out

def run_rwa_read_tool(args=None):
    from harness.rwa_read import run_rwa_read
    return run_rwa_read(args)

