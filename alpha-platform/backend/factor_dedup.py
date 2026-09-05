"""Factor draft dedup — deterministic AST/expression fingerprint (zero LLM)."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from typing import Any

DUP_WINDOW_DAYS = 30
RECENT_LIST_DAYS = 7


def _strip_noise(src: str) -> str:
    s = (src or "").strip()
    s = re.sub(r"#.*?$", "", s, flags=re.M)
    s = re.sub(r'"""[\s\S]*?"""', "", s)
    s = re.sub(r"'''[\s\S]*?'''", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def factor_fingerprint(code: str) -> str:
    """Stable fingerprint of factor() body / expression logic."""
    text = _strip_noise(code)
    try:
        tree = ast.parse(code or "")
        bodies: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "factor":
                bodies.append(ast.dump(node, annotate_fields=True, include_attributes=False))
        if bodies:
            blob = "|".join(bodies)
        else:
            blob = ast.dump(tree, annotate_fields=True, include_attributes=False)
    except SyntaxError:
        blob = text
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def recent_factor_briefs(c, *, days: int = RECENT_LIST_DAYS) -> list[dict[str, str]]:
    """Name + one-liner hypothesis for propose negative constraint."""
    cutoff = int(time.time()) - days * 86400
    rows = c.execute(
        "SELECT name, hypothesis FROM factor_drafts WHERE created>=? "
        "AND COALESCE(status,'') NOT IN ('dup_rejected') "
        "ORDER BY id DESC LIMIT 40",
        (cutoff,),
    ).fetchall()
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for name, hyp in rows:
        n = (name or "").strip()[:80]
        if not n or n in seen:
            continue
        seen.add(n)
        one = re.sub(r"\s+", " ", (hyp or "").strip())[:120]
        out.append({"name": n, "summary": one or "(no hypothesis)"})
    return out


def check_duplicate_or_none(c, code: str, *, days: int = DUP_WINDOW_DAYS) -> dict[str, Any] | None:
    fp = factor_fingerprint(code)
    cutoff = int(time.time()) - days * 86400
    rows = c.execute(
        "SELECT id, name, code, created, status FROM factor_drafts "
        "WHERE created>=? AND COALESCE(status,'') != 'dup_rejected' "
        "ORDER BY id DESC LIMIT 200",
        (cutoff,),
    ).fetchall()
    for did, name, prev_code, created, status in rows:
        if factor_fingerprint(prev_code or "") == fp:
            return {
                "fingerprint": fp,
                "match_id": did,
                "match_name": name,
                "match_created": created,
                "match_status": status,
            }
    return None


def record_dup_rejected(
    c,
    *,
    slug: str,
    name: str,
    hypothesis: str,
    code: str,
    route: str | None,
    trace_id: str | None,
    match: dict[str, Any],
    test: bool = False,
) -> int:
    now = int(time.time())
    meta = {
        "dup_rejected": True,
        "fingerprint": match.get("fingerprint"),
        "match_id": match.get("match_id"),
        "match_name": match.get("match_name"),
    }
    cur = c.execute(
        "INSERT INTO factor_drafts(created, slug, name, hypothesis, code, status, route, trace_id, test, meta) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            now,
            slug,
            name,
            hypothesis,
            code,
            "dup_rejected",
            route,
            trace_id,
            1 if test else 0,
            json.dumps(meta, ensure_ascii=False),
        ),
    )
    # doctor counter
    try:
        row = c.execute(
            "SELECT detail FROM health WHERE component='dup_rejected'"
        ).fetchone()
        n = 0
        if row and row[0]:
            try:
                n = int(json.loads(row[0]).get("count") or 0)
            except Exception:
                n = 0
        detail = json.dumps({"count": n + 1, "last_id": cur.lastrowid}, ensure_ascii=False)
        c.execute(
            "INSERT INTO health(component, ts, status, detail) VALUES(?,?,?,?) "
            "ON CONFLICT(component) DO UPDATE SET ts=excluded.ts, status=excluded.status, detail=excluded.detail",
            ("dup_rejected", now, "ok", detail[:400]),
        )
    except Exception:
        pass
    return int(cur.lastrowid)


def unique_factor_rate_3d(c) -> dict[str, Any]:
    cutoff = int(time.time()) - 3 * 86400
    rows = c.execute(
        "SELECT id, code, status FROM factor_drafts WHERE created>=?",
        (cutoff,),
    ).fetchall()
    total = len(rows)
    fps: set[str] = set()
    for _id, code, status in rows:
        if status == "dup_rejected":
            continue
        fps.add(factor_fingerprint(code or ""))
    unique = len(fps)
    rate = (unique / total) if total else 1.0
    if rate < 0.5:
        level = "red"
    elif rate < 0.7:
        level = "amber"
    else:
        level = "green"
    return {
        "unique": unique,
        "total": total,
        "rate": round(rate, 4),
        "level": level,
        "window_days": 3,
    }
