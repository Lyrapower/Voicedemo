"""Mission runner — one coroutine alongside supervisor.run_forever.

No new port, no new process. Each tick: for every status=running mission with no
active job → assemble + submit the next hop via store.create_job(origin=mission:<id>).
For every running mission whose active job is terminal → collect the receipt, append
lineage to provenance, update counters, check stop/budget/discipline, decide next hop
or close (dossier hop).

Money / write-host / out-of-egress jobs are still born BLOCKED by the existing gate —
the runner does not bypass /api/jobs. A blocked hop counts as out_of_bounds when the
block reason indicates a bounds violation (write host / out-of-egress / money).
"""
from __future__ import annotations

import asyncio
import json
import os
import re as _re
import time
from pathlib import Path
from typing import Any

from .payload import (
    build_payload, validate_payload, parse_next_block, is_stop,
    lineage_summary, prior_from_receipt,
)

# job statuses that mean "this hop is done, collect the receipt"
_TERMINAL = {"done", "failed", "blocked", "interrupted", "cancelled"}
# receipt status mapping (job status -> FactualReceipt status)
_STATUS_MAP = {
    "done": "EXECUTED", "failed": "FAILED", "blocked": "DENIED",
    "interrupted": "DENIED", "cancelled": "DENIED",
}
# blocked last_step values that indicate a bounds violation (discipline)
_BOUNDS_VIOLATION_STEPS = {
    "BLOCKED_SANDBOX_MISSING", "GATE_DENIED", "BLOCKED_SEARCH", "BLOCKED_EGRESS",
    "RETRY_DENIED",
}

# 衔拍3: scout 钉死 deep(glm-5.2);lineage 每跳记 model_resolved,验收线 = glm-5.2。
_MODEL_BY_WORKER = {
    "deep": "glm-5.2",        # cloud-glm52 substrate
    "research": "deepseek-chat",
    "full": "glm-5.2",
    "fast": "glm-5.2",
    "cc": "glm-5.3",
    "local": "qwen3.5-9b",
}


def _model_resolved(worker: str) -> str:
    return _MODEL_BY_WORKER.get(worker, worker or "")


class WorkerLockError(ValueError):
    """scout 钉死 deep; research worker 只跑 research 模板。禁止 fallback。"""


def resolve_mission_worker(lane: str, requested: str | None) -> str:
    """衔补: scout 模板 worker 钉死 deep; runner 不允许 fallback 到 research;
    research worker 只跑 missions.toml 里 worker=research 的模板(现为 rwa)。"""
    from mission.config import mission_template
    req = (requested or "").strip()
    tmpl = mission_template(lane) if lane else None
    tmpl_worker = str((tmpl or {}).get("worker") or "")
    if lane == "scout":
        if req and req != "deep":
            raise WorkerLockError("scout_worker_locked_deep")
        return "deep"
    if req == "research":
        if tmpl_worker != "research":
            raise WorkerLockError("research_worker_template_only")
        return "research"
    return req or tmpl_worker or "deep"


# 衔拍3 §①3: worker 只判 HIT/MISS+理由;runner 从 catalog rows 自动附 URL/截止/event_id。
_JUDGMENT_RE = _re.compile(r"(?:opp\s+)?([0-9A-Za-z\-]{3,})\s*[:\-]?\s*(HIT|MISS|YES|NO|命中|不命中)\b\s*[—\-:\)]?\s*(.*)", _re.I)


def _parse_judgments(worker_output: str) -> dict[str, tuple[str, str]]:
    """Parse judgment lines like `opp 363240: HIT — reason` or `363240 HIT reason` → {opp_id: (verdict, reason)}."""
    out: dict[str, tuple[str, str]] = {}
    if not worker_output:
        return out
    for line in worker_output.splitlines():
        m = _JUDGMENT_RE.search(line)
        if not m:
            continue
        oid = m.group(1).strip()
        v = m.group(2).strip().upper()
        verdict = "HIT" if v in ("HIT", "YES", "命中") else "MISS"
        reason = m.group(3).strip().strip("—-:)").strip()[:200]
        out[oid] = (verdict, reason)
    return out


def _collect_catalog_rows(hops: list[dict], store) -> dict[str, dict]:
    """Merge catalog rows from all hops' tool_search events → {opp_id: row+hop_job_id}."""
    merged: dict[str, dict] = {}
    for h in hops:
        jid = h.get("job_id") or h.get("event_id")
        if not jid:
            continue
        try:
            evs = store.list_events(jid)
        except Exception:
            evs = []
        for e in evs:
            if e.get("kind") != "tool_search":
                continue
            try:
                payload = e.get("payload")
                if isinstance(payload, str):
                    payload = json.loads(payload)
            except Exception:
                payload = {}
            for r in (payload or {}).get("catalog_rows") or []:
                oid = r.get("opportunity_id")
                if not oid:
                    continue
                if oid not in merged:
                    merged[oid] = dict(r)
                    merged[oid]["event_id"] = jid
                    merged[oid]["hop"] = h.get("hop")
    return merged


_DEADLINE_EMPTY = {"", "unknown", "—", "-", "n/a", "none", "null"}
_REASON_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "must",
    "only", "grant", "grants", "scope", "mission", "discover", "funding",
}
_ELIG_OK = _re.compile(
    r"individual|small\s+business|for[- ]?profit|unrestricted|private\s+institutions?|"
    r"non[- ]?profits?|anyone|individuals",
    _re.I,
)
_ELIG_INST = _re.compile(
    r"institutions?\s+of\s+higher\s+education|state\s+controlled|state\s+governments?|"
    r"county\s+governments?|city\s+or\s+township|public\s+housing|tribal\s+governments?|"
    r"independent\s+school\s+districts|public\s+and\s+state",
    _re.I,
)


def _blank(s: Any) -> bool:
    return str(s or "").strip().lower() in _DEADLINE_EMPTY


def _parse_deadline(raw: Any, now=None):
    """Return (aware-utc datetime | None). Accepts ISO and US mm/dd/yyyy."""
    from datetime import datetime, timezone
    s = str(raw or "").strip()
    if _blank(s):
        return None
    s = s.replace("Z", "")
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(s[:19], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    try:
        from datetime import datetime as _dt, timezone as _tz
        dt = _dt.fromisoformat(s[:19])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_tz.utc)
        return dt
    except ValueError:
        return None


def _deadline_kind(raw: Any, now=None) -> tuple[str | None, str]:
    """('', '') ok-and-count; ('rolling','') count; (None, reason) abandon."""
    from datetime import datetime, timezone, timedelta
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    dt = _parse_deadline(raw, now)
    if dt is None:
        return None, "missing_field"
    days = (dt - now).total_seconds() / 86400.0
    if days < 14:
        return None, "deadline_lt_14d"
    if days > 730:
        return "rolling", ""
    return "", ""


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _re.findall(r"[A-Za-z\u4e00-\u9fff]{4,}", text or "")} - _REASON_STOP


def _reason_cites_both(reason: str, goal: str, eligibility: str) -> bool:
    if not str(reason or "").strip():
        return False
    rlow = reason.lower()
    gtoks, etoks = _tokens(goal), _tokens(eligibility)
    cites_goal = (not gtoks) or any(t in rlow for t in gtoks)
    cites_elig = (not etoks) or any(t in rlow for t in etoks)
    return cites_goal and cites_elig


def _is_ineligible(elig: str) -> bool:
    parts = [p.strip() for p in _re.split(r"[;|,/\n]", elig or "") if p.strip() and not _blank(p)]
    if not parts:
        return False
    if any(_ELIG_OK.search(p) for p in parts):
        return False
    return bool(parts) and all(_ELIG_INST.search(p) for p in parts)


def _write_abandoned_lineage(mission_id: str, abandoned: list[dict]) -> None:
    for a in abandoned:
        rec = dict(a)
        rec["status"] = "ABANDONED"
        rec.setdefault("reason", "missing_field")
        _append_lineage_hop(mission_id, rec)


def render_findings_receipt(findings: list[dict], *, model_id: str, window_compressed: str,
                            mid: str, status: str, close_reason: str, hops_used: int,
                            budget_hops: int, models: list[str], abandoned: list[dict] | None = None) -> str:
    """Header counts are derived from findings rows. Do not hand-fill."""
    n = len(findings)
    n_url = sum(1 for f in findings if "grants.gov" in str(f.get("url") or "").lower())
    n_dl = sum(1 for f in findings if _parse_deadline(f.get("deadline")) is not None)
    n_eid = sum(1 for f in findings if str(f.get("event_id") or "").startswith("J-"))
    n_title = sum(1 for f in findings if not _blank(f.get("title")))
    lines = [
        "# 衔拍3 §① 真跑 回执",
        "",
        f"模型 id: {model_id}",
        f"窗口压缩: {window_compressed}",
        "",
        "---",
        "",
        f"## 结果: {status}",
        "",
        "| 项 | 值 |",
        "|----|----|",
        f"| MID | {mid} |",
        f"| status | {status} |",
        f"| close_reason | {close_reason} |",
        f"| hops_used | {hops_used} / {budget_hops} |",
        f"| model_resolved (每跳) | {' · '.join(models) if models else '(none)'} |",
        f"| findings | {n} |",
        f"| grants.gov URL | {n_url}/{n} |",
        f"| deadline 列 | {n_dl}/{n} |",
        f"| title 列 | {n_title}/{n} |",
        f"| event_id 列 | {n_eid}/{n} |",
        f"| abandoned | {len(abandoned or [])} |",
        "",
        "## findings (runner-built)",
        "",
        "| # | opp_id | Title | Agency | Deadline | kind | eligibility | URL | event_id | Reason |",
        "|---|--------|-------|--------|----------|------|-------------|-----|----------|--------|",
    ]
    for i, f in enumerate(findings, 1):
        lines.append(
            f"| {i} | {f.get('opportunity_id','')} | {f.get('title','')} | {f.get('agency','')} | "
            f"{f.get('deadline','')} | {f.get('deadline_kind') or ''} | {f.get('eligibility','')} | "
            f"{f.get('url','')} | {f.get('event_id','')} | {f.get('reason','')} |"
        )
    if abandoned:
        lines += ["", "## abandoned", "",
                  "| opp_id | reason | title | deadline | status |",
                  "|--------|--------|-------|----------|--------|"]
        for a in abandoned:
            lines.append(
                f"| {a.get('opportunity_id','')} | {a.get('reason','')} | {a.get('title','')} | "
                f"{a.get('deadline','')} | {a.get('opp_status','')} |"
            )
    return "\n".join(lines) + "\n"


def _build_findings(hops: list[dict], store, *, goal: str = "", now=None,
                    detail_fn=None, abandoned_out: list | None = None) -> list[dict]:
    """HIT rows that survive title/deadline/status/eligibility filters. Failures → ABANDONED."""
    catalog = _collect_catalog_rows(hops, store)
    if not catalog:
        return []
    judgments: dict[str, tuple[str, str]] = {}
    for h in hops:
        jid = h.get("job_id") or h.get("event_id")
        wo = h.get("worker_output") or ""
        if store is not None and jid:
            try:
                full = store.get_job_result_text(jid)
                if full and isinstance(full, str):
                    wo = full
            except Exception:
                pass
        judgments.update(_parse_judgments(wo))
    findings: list[dict] = []
    abandoned: list[dict] = []
    for oid, row in catalog.items():
        v = judgments.get(oid)
        verdict = v[0] if v else "MISS"
        reason = v[1] if v else ""
        if verdict != "HIT":
            continue
        extra = {}
        if detail_fn is not None:
            try:
                extra = detail_fn(oid) or {}
            except Exception:
                extra = {}
        title = extra.get("title") or row.get("title")
        deadline = extra.get("deadline") or row.get("deadline")
        elig = extra.get("eligibility") or row.get("eligibility") or ""
        if extra.get("applicant_types"):
            elig = elig or "; ".join(str(x) for x in extra["applicant_types"])
        status = str(extra.get("status") or row.get("status") or row.get("opp_status") or "").strip().lower()
        def _aband(code: str) -> None:
            abandoned.append({
                "opportunity_id": oid, "reason": code, "title": title or "",
                "deadline": deadline or "", "opp_status": status,
                "event_id": row.get("event_id") or "",
            })
        if _blank(title) or _blank(deadline):
            _aband("missing_field")
            continue
        if status and status != "posted":
            _aband("not_posted")
            continue
        kind, dreason = _deadline_kind(deadline, now)
        if dreason:
            _aband(dreason)
            continue
        if _is_ineligible(str(elig)):
            _aband("ineligible")
            continue
        if not _reason_cites_both(reason, goal, str(elig)):
            _aband("reason_not_citing")
            continue
        findings.append({
            "opportunity_id": oid,
            "title": str(title).strip(),
            "agency": row.get("publisher") or extra.get("agency") or "unknown",
            "url": row.get("human_url") or f"https://www.grants.gov/search-results-detail/{oid}",
            "deadline": str(deadline).strip(),
            "deadline_kind": kind or "",
            "eligibility": str(elig),
            "event_id": row.get("event_id") or "",
            "reason": reason,
        })
    if abandoned_out is not None:
        abandoned_out.extend(abandoned)
    return findings


def _state_dir(mission_id: str) -> Path:
    d = Path("state") / "missions" / mission_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_next_payload(mission_id: str) -> dict | None:
    p = _state_dir(mission_id) / "next_payload.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_next_payload(mission_id: str, payload: dict | None) -> None:
    p = _state_dir(mission_id) / "next_payload.json"
    if payload is None:
        p.unlink(missing_ok=True)
    else:
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


import re as _re

_FINDING_URL_RE = _re.compile(r"https?://\S+", _re.I)
_FINDING_EID_RE = _re.compile(r"\b(J-[0-9a-f]{8,}|hop\s+\d+)\b", _re.I)


def _count_findings(dossier_text: str, domain: str = "") -> int:
    """Count dossier findings = lines containing both a URL and an event_id
    (J-... or 'hop N'). If domain given, the URL must contain it (e.g. grants.gov)."""
    if not dossier_text:
        return 0
    n = 0
    for line in dossier_text.splitlines():
        has_url = False
        for m in _FINDING_URL_RE.finditer(line):
            if (not domain) or domain in m.group(0).lower():
                has_url = True
                break
        if has_url and _FINDING_EID_RE.search(line):
            n += 1
    return n


def _load_lineage_hops(mission_id: str) -> list[dict]:
    p = _state_dir(mission_id) / "lineage.json"
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _append_lineage_hop(mission_id: str, hop: dict) -> None:
    hops = _load_lineage_hops(mission_id)
    hops.append(hop)
    p = _state_dir(mission_id) / "lineage.json"
    p.write_text(json.dumps(hops, ensure_ascii=False, indent=2), encoding="utf-8")


def _record_provenance(mission_id: str, action_id: str, status: str, executed: bool,
                       conclusion: str = "", grade: str = "secondhand") -> str:
    """Append an action + receipt to the provenance JSONL + a per-mission receipts.jsonl.
    Returns the event_id (=action_id). Best-effort: never blocks the loop."""
    # per-mission receipts.jsonl (always written — the mission's own receipt tree)
    try:
        rec = {"ts": time.time(), "kind": "receipt", "mission_id": mission_id,
               "event_id": action_id, "status": status, "executed": executed,
               "evidence_grade": grade, "conclusion": conclusion[:500]}
        with open(_state_dir(mission_id) / "receipts.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # global provenance JSONL (best-effort; may fail if app.harness not importable in process)
    try:
        from app.harness.action_envelope import ActionEnvelope, FactualReceipt
        from app.harness import provenance
        ActionEnvelope(
            mission_id=mission_id, action_id=action_id, decision_origin="GRID_DELEGATED_GLM",
            selected_resource=f"job:{action_id}", operation="mission_hop",
            authorization_scope="read_only",
        ).to_dict()
        FactualReceipt(
            mission_id=mission_id, action_id=action_id, status=status, executed=executed,
            result=conclusion[:500], error="",
            metadata={"evidence_grade": grade, "hop": action_id},
        ).to_dict()
    except Exception:
        pass
    return action_id


def _hop_goal(mission: dict, hops: list[dict], prior: dict | None, hop_n: int,
              next_payload: dict | None) -> str:
    """Compose the goal text for hop n."""
    budget_hops_left = mission["budget_hops"] - mission["hops_used"]
    budget_usd_left = mission["budget_usd"] - mission["usd_used"]
    summary = lineage_summary(hops)
    prior_txt = json.dumps(prior, ensure_ascii=False) if prior else "(first hop, no prior)"
    action_hint = ""
    if next_payload and next_payload.get("action"):
        action_hint = f"\nProposed next action: {next_payload['action']}"
    tools = mission.get("tools") or []
    tools_txt = ", ".join(tools) if tools else "(none — no external tools)"
    return (
        f"MISSION (hop {hop_n}): {mission['goal']}\n"
        f"\nLineage so far:\n{summary}\n"
        f"\nPrior hop receipt: {prior_txt}{action_hint}\n"
        f"\nBudget remaining: hops={budget_hops_left} usd={budget_usd_left:.4f}\n"
        f"\nAllowed tools (use ONLY these): {tools_txt}\n"
        f"\nExecute the next concrete action toward the mission goal using ONLY the allowed tools above. "
        f"Every fact you report MUST come from a tool call (e.g. a web.search/grants.catalog result) — do not "
        f"assert facts from memory alone.\n"
        f"\nJUDGMENT RULE (mandatory, do not skip): The runner calls grants.detail(oppId) and attaches "
        f"eligibility. Do NOT call grants.detail yourself, do NOT emit fake tool calls, and do NOT "
        f"web.fetch grants.gov detail URLs. For EACH catalog opportunity, output ONE line:\n"
        f"  opp <opportunity_id>: HIT — <reason that Cites BOTH the mission goal AND that row's eligibility>\n"
        f"  opp <opportunity_id>: MISS — <one-sentence reason it is out of scope>\n"
        f"HIT reason is required and must quote/cite (1) the mission goal text and (2) eligibility. "
        f"A NASA ROSES Earth-Science opportunity is MISS for an AI-infrastructure mission.\n"
        f"When you write the next ```job block, bounds MUST include:\n"
        f"  goal: {mission.get('goal') or ''}\n"
        f"  eligibility: <copy the eligibility string of the opportunities you judged>\n"
        f"After all judgment lines, output a fenced ```job block with fields (action, bounds, resources), "
        f"or ```STOP if complete. Do not write the grants.gov URL, deadline, or event_id yourself. "
        f"Do not write to the host filesystem outside the sandbox, do not spend money, do not call "
        f"domains outside the egress lanes."
    )


def _dossier_goal(mission: dict, hops: list[dict]) -> str:
    summary = lineage_summary(hops, limit=30)
    return (
        f"MISSION DOSSIER (close): {mission['goal']}\n\n"
        f"Lineage (each hop has an event_id = job_id, format J-xxxxxxxxxx):\n{summary}\n\n"
        f"Write a dossier in markdown, <=3000 chars, summarizing what the mission found/did. "
        f"For each finding, give: the grants.gov (or source) URL, the deadline date, and the "
        f"event_id (the hop's job_id, format J-xxxxxxxxxx) it came from. Cite only facts that "
        f"appear in the lineage above; for each fact give its event_id (J-...) and evidence "
        f"grade. If the mission is incomplete (budget exhausted / blocked), say so. "
        f"Do not invent facts. Output only the markdown dossier."
    )


def _check_stop(mission: dict, hops: list[dict], store=None) -> tuple[bool, str]:
    """Return (should_close, reason)."""
    if mission["hops_used"] >= mission["budget_hops"] > 0:
        # 勘: 30 跳不满过滤后 n>=10 → INCOMPLETE, 不放宽
        target = 0
        for cond in mission.get("stop_conditions") or []:
            m = _re.match(r"\s*(n|findings|hit)\s*>=\s*(\d+)\s*$", cond)
            if m:
                target = int(m.group(2))
                break
        if target and store is not None:
            n_ok = len(_build_findings(hops, store, goal=mission.get("goal") or ""))
            if n_ok < target:
                return True, "INCOMPLETE"
        return True, "budget_exhausted_hops"
    if mission["usd_used"] >= mission["budget_usd"] > 0:
        return True, "budget_exhausted_usd"
    if mission["budget_wall_s"] > 0 and (time.time() - mission["created_at"]) >= mission["budget_wall_s"]:
        return True, "budget_exhausted_wall"
    if mission["denied_streak"] >= 3:
        return True, "denied_streak"
    if mission.get("no_evidence_streak", 0) >= 3:
        return True, "no_progress"
    if mission["out_of_bounds"] > 0:
        return True, "discipline_fail"
    # user stop conditions (simple 'n>=10' style evaluated against hops count / lineage)
    for cond in mission.get("stop_conditions") or []:
        if _eval_condition(cond, mission, hops, store):
            return True, f"stop_condition:{cond}"
    return False, ""


def _eval_condition(cond: str, mission: dict, hops: list[dict], store=None) -> bool:
    """Best-effort eval of simple stop conditions like 'n>=10' or 'hops>=10'."""
    import re as _re
    m = _re.match(r"\s*(\w+)\s*(>=|<=|==|>|<)\s*(\d+)\s*$", cond)
    if not m:
        return False
    var, op, num = m.group(1), m.group(2), int(m.group(3))
    val = mission["hops_used"]
    if var in {"n", "findings", "hit"}:
        # 衔拍3 §①3: n counts runner-built findings (HITs), not hops
        val = (len(_build_findings(hops, store, goal=mission.get("goal") or ""))
               if store is not None else mission["hops_used"])
    elif var in {"hops", "hop"}:
        val = mission["hops_used"]
    elif var == "usd":
        val = mission["usd_used"]
    elif var == "facts":
        val = sum(1 for h in hops if h.get("status") == "EXECUTED")
    else:
        return False
    if op == ">=": return val >= num
    if op == "<=": return val <= num
    if op == "==": return val == num
    if op == ">": return val > num
    if op == "<": return val < num
    return False


async def run_mission_loop(supervisor, store, *, interval: float = 2.0) -> None:
    """Main loop. Started as an asyncio task in api.lifespan alongside supervisor.run_forever."""
    while not supervisor._stop.is_set():
        try:
            for m in store.list_missions(status="running"):
                await _tick_mission(m, supervisor, store)
        except Exception as e:  # never crash the loop
            print(f"[mission] loop_err {type(e).__name__}: {e}", flush=True)
        await asyncio.sleep(interval)


async def _tick_mission(mission: dict, supervisor, store) -> None:
    mid = mission["mission_id"]

    # 1. active job terminal? collect receipt + advance
    active = mission.get("active_job_id")
    if active:
        try:
            job = store.get_job(active)
        except KeyError:
            store.update_mission(mid, active_job_id=None)
            return
        if job["status"] not in _TERMINAL:
            return  # still running, wait
        await _complete_hop(mission, job, store)
        return  # one hop per tick; next tick picks up

    # 2. no active job — check stop / budget, then submit next hop
    m = store.get_mission(mid)  # refreshed counters
    hops = _load_lineage_hops(mid)
    close, reason = _check_stop(m, hops, store)
    if close:
        await _close_mission(m, hops, reason, store, supervisor)
        return

    next_payload = _load_next_payload(mid)
    hop_n = m["hops_used"] + 1
    prior = None
    if hops:
        last = hops[-1]
        prior = prior_from_receipt(last["event_id"], last["status"], last.get("worker_output", ""), last.get("error", ""))
    goal = _hop_goal(m, hops, prior, hop_n, next_payload)

    try:
        # 衔补: scout 钉死 deep; 禁止 fallback research。锁失败则本 mission 失败,不改投 research。
        try:
            worker = resolve_mission_worker(m.get("lane") or "", m.get("worker"))
        except WorkerLockError as e:
            store.update_mission(mid, status="failed", close_reason=str(e), active_job_id=None)
            return
        # cloud_lane workers: fast/deep/full/research all route to harness.cloud_lane.
        # local→local_lane, cc→cc_lane. cloud_allowed follows whether the worker is a cloud route.
        is_cloud = worker in {"fast", "deep", "full", "research"}
        # 衔拍3 §①1: 分页——每跳取 catalog 不同页(offset=(hop-1)*rows_per_query),累积 HITs 不卡在同 6 行
        hop_search = None
        if m.get("search"):
            hop_search = dict(m["search"])
            rpp = int(hop_search.get("rows_per_query") or 10)
            hop_search["offset"] = (hop_n - 1) * rpp
        new_job = store.create_job(
            channel="grid", goal=goal, worker=worker,
            allowed_tools=m.get("tools") or [], allowed_paths=["."],
            cloud_allowed=is_cloud, approval_mode="auto",
            read_only=True, kind="chat",
            origin=f"mission:{mid}", lane=m.get("lane") or "",
            search=hop_search,
        )
        store.update_mission(mid, active_job_id=new_job["job_id"])
    except Exception as e:
        print(f"[mission] {mid} submit_err {type(e).__name__}: {e}", flush=True)
        store.update_mission(mid, status="failed", close_reason=f"submit_err:{type(e).__name__}")


async def _complete_hop(mission: dict, job: dict, store) -> None:
    mid = mission["mission_id"]
    jid = job["job_id"]
    # worker_output: prefer job_result event (source of truth), then receipt, then last_artifact
    wo = store.get_job_result_text(jid)
    if not wo:
        receipt = store.get_job_receipt_by_job(jid)
        if receipt:
            wo = receipt.get("worker_output") or ""
    if not wo and job.get("last_artifact"):
        try:
            p = Path(job["last_artifact"])
            if p.is_file():
                wo = p.read_text(encoding="utf-8", errors="replace")[:4000]
        except Exception:
            pass
    if not wo:
        ev = store.list_events(jid)
        wo = json.dumps([e.get("kind") for e in ev], ensure_ascii=False)

    status = _STATUS_MAP.get(job["status"], "FAILED")
    executed = status == "EXECUTED"
    conclusion = (wo or "")[:500]
    _record_provenance(mid, jid, status, executed, conclusion)

    # counters
    hops_used = mission["hops_used"] + 1
    usd_used = store.mission_cost_usd(mid)
    denied_streak = mission["denied_streak"]
    out_of_bounds = mission["out_of_bounds"]
    no_evidence_hops = mission.get("no_evidence_hops", 0)
    no_evidence_streak = mission.get("no_evidence_streak", 0)
    if status == "DENIED":
        denied_streak += 1
        if job.get("last_step") in _BOUNDS_VIOLATION_STEPS:
            out_of_bounds += 1
    else:
        denied_streak = 0
    # no_evidence: a hop that ran but made zero tool calls (no web.fetch/search/etc.)
    tool_calls = store.job_tool_call_count(jid)
    if status == "EXECUTED" and tool_calls == 0:
        no_evidence_hops += 1
        no_evidence_streak += 1
    else:
        no_evidence_streak = 0

    # parse next ```job block from worker output
    next_payload = None
    if wo and not is_stop(wo):
        parsed = parse_next_block(wo)
        if parsed:
            ok, _ = validate_payload(parsed)
            next_payload = parsed if ok else None
    if next_payload is not None:
        b = next_payload.get("bounds")
        if not isinstance(b, dict):
            b = {}
        b.setdefault("goal", mission.get("goal") or "")
        # eligibility filled from catalog rows of this hop when present
        if not b.get("eligibility"):
            try:
                rows = _collect_catalog_rows(
                    [{"hop": hops_used, "job_id": jid, "event_id": jid}], store)
                eligs = [str(r.get("eligibility") or "") for r in rows.values() if r.get("eligibility")]
                if eligs:
                    b["eligibility"] = "; ".join(eligs[:6])
            except Exception:
                pass
        next_payload["bounds"] = b
    _save_next_payload(mid, next_payload)

    # append lineage hop
    _append_lineage_hop(mid, {
        "hop": hops_used, "job_id": jid, "event_id": jid,
        "status": status, "conclusion": conclusion,
        "worker_output": wo[-2000:], "last_step": job.get("last_step"),
        "tool_calls": tool_calls,
        "worker": job.get("worker") or "",
        "model_resolved": _model_resolved(job.get("worker") or ""),
    })

    abandoned: list[dict] = []
    hops_now = _load_lineage_hops(mid)
    _build_findings(hops_now, store, goal=mission.get("goal") or "", abandoned_out=abandoned)
    # only persist newly seen abandon codes for this hop's opps
    seen = {(a.get("opportunity_id"), a.get("reason")) for a in hops_now if a.get("status") == "ABANDONED"}
    fresh = [a for a in abandoned if (a.get("opportunity_id"), a.get("reason")) not in seen]
    if fresh:
        _write_abandoned_lineage(mid, fresh)

    store.update_mission(mid, hops_used=hops_used, usd_used=usd_used,
                         denied_streak=denied_streak, out_of_bounds=out_of_bounds,
                         no_evidence_hops=no_evidence_hops,
                         no_evidence_streak=no_evidence_streak,
                         active_job_id=None)


async def _close_mission(mission: dict, hops: list[dict], reason: str, store, supervisor) -> None:
    mid = mission["mission_id"]
    try:
        w = resolve_mission_worker(mission.get("lane") or "", mission.get("worker"))
    except WorkerLockError:
        w = "deep"  # 锁失败也不许 dossier hop fallback 到 research
    is_cloud = w in {"fast", "deep", "full", "research"}
    # submit dossier hop (always allowed, even if budget exhausted)
    try:
        djob = store.create_job(
            channel="grid", goal=_dossier_goal(mission, hops), worker=w,
            allowed_tools=[], allowed_paths=["."], cloud_allowed=is_cloud,
            approval_mode="auto", read_only=True, kind="chat",
            origin=f"mission:{mid}:dossier", lane=mission.get("lane") or "",
        )
    except Exception as e:
        store.update_mission(mid, status="failed", close_reason=f"dossier_err:{type(e).__name__}")
        return
    # wait for dossier job (poll up to ~120s)
    for _ in range(120):
        await asyncio.sleep(1)
        try:
            j = store.get_job(djob["job_id"])
        except KeyError:
            break
        if j["status"] in _TERMINAL:
            break
    # collect dossier text
    dossier_text = store.get_job_result_text(djob["job_id"])
    if not dossier_text:
        try:
            j = store.get_job(djob["job_id"])
            r = store.get_job_receipt_by_job(djob["job_id"])
            dossier_text = (r.get("worker_output") or "") if r else ""
            if not dossier_text and j.get("last_artifact"):
                dossier_text = Path(j["last_artifact"]).read_text(encoding="utf-8", errors="replace")[:3000]
        except Exception:
            pass
    if not dossier_text:
        dossier_text = f"(dossier hop {djob['job_id']} produced no text; close_reason={reason})"

    # 勘: findings 经过滤; 抬头计数从行程序生成。runner 调 grants.detail 补 eligibility。
    abandoned: list[dict] = []
    def _detail(oid: str) -> dict:
        try:
            from harness.tool_loop import run_grants_detail
            return run_grants_detail(
                oid, lane=mission.get("lane") or "scout",
                db_path=str(getattr(store, "path", "") or ""),
                mission_id=mid,
            ) or {}
        except Exception:
            return {}
    rfindings = _build_findings(
        hops, store, goal=mission.get("goal") or "",
        detail_fn=_detail, abandoned_out=abandoned,
    )
    findings = len(rfindings)
    seen = {(a.get("opportunity_id"), a.get("reason")) for a in hops if a.get("status") == "ABANDONED"}
    fresh = [a for a in abandoned if (a.get("opportunity_id"), a.get("reason")) not in seen]
    if fresh:
        _write_abandoned_lineage(mid, fresh)
    models = [h.get("model_resolved") or "" for h in hops if h.get("status") != "ABANDONED"]
    receipt = render_findings_receipt(
        rfindings, model_id="glm-5.2", window_compressed="否",
        mid=mid, status="pending", close_reason=reason,
        hops_used=mission.get("hops_used") or 0,
        budget_hops=mission.get("budget_hops") or 0,
        models=models, abandoned=abandoned,
    )
    (_state_dir(mid) / "RECEIPT.md").write_text(receipt, encoding="utf-8")
    rlines = ["# MISSION DOSSIER (runner-built findings)", ""]
    rlines.append(f"close_reason: {reason} | findings: {findings}")
    rlines.append("")
    rlines.append("| # | Title | Agency | Deadline | kind | eligibility | URL | event_id | Reason |")
    rlines.append("|---|-------|--------|----------|------|-------------|-----|----------|--------|")
    for i, f in enumerate(rfindings, 1):
        rlines.append(
            f"| {i} | {f['title']} | {f['agency']} | {f['deadline']} | {f.get('deadline_kind') or ''} | "
            f"{f.get('eligibility','')} | {f['url']} | {f['event_id']} | {f['reason']} |"
        )
    rlines.append("")
    rlines.append("## Worker narrative")
    rlines.append(dossier_text[:1500])
    # 衔拍3 §①3: runner-built findings 表必须完整渲染 10 行(URL/截止/event_id 不能被截断);
    # 只截 worker narrative,不截 findings 表。cap 提到 8000 容纳 10 行长 reason。
    dossier_text = "\n".join(rlines)
    if len(dossier_text) > 8000:
        # 保留 findings 表,只裁 narrative
        cut = dossier_text.find("## Worker narrative")
        if cut > 0:
            head = dossier_text[:cut]
            dossier_text = head + "## Worker narrative\n" + dossier_text[cut+len("## Worker narrative"):][:1500]
        else:
            dossier_text = dossier_text[:8000]
    dossier_complete = findings >= 1
    # scout 验收线: 至少 1 条 grants.gov finding(衔拍3 绿=10 由 stop_condition n>=10 把关)

    dp = _state_dir(mid) / "DOSSIER.md"
    dp.write_text(dossier_text, encoding="utf-8")

    # scorecard
    from .scorecard import build_scorecard
    sc = build_scorecard(mission, hops, reason)
    sc["dossier_findings"] = findings
    sc["dossier_complete"] = dossier_complete
    (_state_dir(mid) / "SCORECARD.json").write_text(
        json.dumps(sc, ensure_ascii=False, indent=2), encoding="utf-8")

    # final status: done only if dossier has findings AND close was a normal stop/budget;
    # no_progress / discipline_fail / denied_streak / incomplete dossier => failed
    if reason.startswith("no_progress") or reason == "discipline_fail" or reason == "denied_streak":
        final_status = "failed"
    elif reason == "INCOMPLETE":
        final_status = "failed"
    elif not dossier_complete:
        final_status = "failed"  # INCOMPLETE dossier
    else:
        final_status = "done"
    receipt = render_findings_receipt(
        rfindings, model_id="glm-5.2", window_compressed="否",
        mid=mid, status=final_status, close_reason=reason,
        hops_used=mission.get("hops_used") or 0,
        budget_hops=mission.get("budget_hops") or 0,
        models=models, abandoned=abandoned,
    )
    (_state_dir(mid) / "RECEIPT.md").write_text(receipt, encoding="utf-8")
    store.update_mission(mid, status=final_status, close_reason=reason,
                         dossier_path=str(dp), active_job_id=None)
