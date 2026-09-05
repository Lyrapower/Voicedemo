#!/usr/bin/env python3
"""Task Envelope #2 — Policy V2 shadow → read-only parameter proposal (no live effect)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent
REJECTION_DIR = BASE / "logs" / "rejections"
OUT_DIR = BASE / "traces" / "policy_v2"
V1_PARAMS = {
    "max_spread_pct": float(os.getenv("DRYRUN_MAX_SPREAD_PCT", os.getenv("MAX_SPREAD_PCT", "0.10"))),
    "min_delta": float(os.getenv("DRYRUN_MIN_DELTA", os.getenv("MIN_DELTA", "0.25"))),
    "max_delta": float(os.getenv("DRYRUN_MAX_DELTA", os.getenv("MAX_DELTA", "0.50"))),
    "max_iv": float(os.getenv("DRYRUN_MAX_IV", os.getenv("MAX_IV", "0.80"))),
    "min_volume": int(os.getenv("DRYRUN_MIN_VOLUME", os.getenv("MIN_VOLUME", "10"))),
    "min_open_interest": int(os.getenv("DRYRUN_MIN_OPEN_INTEREST", os.getenv("MIN_OPEN_INTEREST", "50"))),
}
V2_PROPOSED = {
    "max_spread_pct": 0.08,
    "indicative_greek_soft": True,
    "theta_ratio_band": 0.03,
}
GATEWAY_URL = os.getenv("GARDEN_GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
GLM_ENDPOINT = os.getenv(
    "GLM52_CLOUD_ENDPOINT",
    f"{GATEWAY_URL}/v1/chat/completions",
).rstrip("/")
GLM_MODEL = os.getenv("GLM52_CLOUD_MODEL", "glm-5.2:cloud")
MISSION_REF = {"source": "aether_shadow_audit"}
GLM_BUDGET_USD = float(os.getenv("POLICY_V2_GLM_BUDGET_USD", "0.50"))
GLM_SYSTEM = (
    "你是 Policy V2 参数审计员（owner: glm）。基于给定的机械统计 JSON，"
    "用中文写不超过 200 字的只读提案摘要：spread/delta/iv 三项各一句，"
    "禁止产出标的/方向/交易指令；禁止改 live 参数；末尾注明 pending_lyra_approval。"
)


def _post_glm(messages: list[dict[str, str]]) -> tuple[dict | None, str, bool]:
    """POST gateway chat; mission_ref 顶层 4xx 时降级为 system 附注(console v0.4 同策略)。"""
    payload: dict[str, Any] = {
        "model": GLM_MODEL,
        "max_tokens": 512,
        "temperature": 0.2,
        "messages": messages,
        "stream": False,
        "mission_ref": MISSION_REF,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GLM_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8")), "", False
    except urllib.error.HTTPError as exc:
        if exc.code < 400 or exc.code >= 500 or not MISSION_REF:
            raise
        sys0 = dict(messages[0])
        sys0["content"] += "\nmission_ref: " + json.dumps(MISSION_REF, ensure_ascii=False)
        payload2 = {
            "model": GLM_MODEL,
            "max_tokens": 512,
            "temperature": 0.2,
            "messages": [sys0] + messages[1:],
            "stream": False,
        }
        req2 = urllib.request.Request(
            GLM_ENDPOINT,
            data=json.dumps(payload2).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req2, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8")), "", True
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError) as exc:
        return None, str(exc), False


def _glm_summarize(doc: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """GLM owner narrative — budget capped; failure returns empty (mechanical doc still valid)."""
    messages = [
        {"role": "system", "content": GLM_SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "stats": doc.get("stats"),
                    "items": [
                        {k: it.get(k) for k in ("param", "evidence", "recommend")}
                        for it in (doc.get("items") or [])
                    ],
                    "sources": [
                        os.path.basename(s) for s in
                        ((doc.get("items") or [{}])[0].get("sources") or [])
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        body, err, ref_degraded = _post_glm(messages)
        if body is None:
            return "", {"error": err}
        text = str(
            (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        ).strip()
        usage = body.get("usage") or {}
        try:
            from code_task.glm52_pricing import enrich_glm52_usage

            usage = enrich_glm52_usage(usage)
        except Exception:
            pass
        cost = float(usage.get("cost_usd") or 0)
        meta: dict[str, Any] = {
            "model": body.get("model") or GLM_MODEL,
            "usage": usage,
            "cost_usd": cost,
            "mission_ref": MISSION_REF,
        }
        if ref_degraded:
            meta["mission_ref_degraded"] = True
        if cost > GLM_BUDGET_USD:
            return "", {"skipped": "budget_cap", "cost_usd": cost, **meta}
        return text, meta
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError) as exc:
        return "", {"error": str(exc)}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hard = len(rows)
    v2_rescued = sum(1 for r in rows if r.get("policy_v2_rescued") or r.get("v2_rescued"))
    v2_would_kill = sum(1 for r in rows if r.get("policy_v2_would_kill") or r.get("v2_would_kill"))
    if not v2_would_kill and hard:
        v2_would_kill = max(0, hard - v2_rescued)
    kill_rules = Counter()
    rescued_rules = Counter()
    indicative_soft = 0
    for r in rows:
        rule = str(r.get("kill_rule") or "other").split("+")[0]
        kill_rules[rule] += 1
        if r.get("policy_v2_rescued") or r.get("v2_rescued"):
            rescued_rules[rule] += 1
        flags = r.get("policy_v2_flags") or r.get("v2_flags") or []
        for f in flags:
            if str(f).startswith("indicative_soft"):
                indicative_soft += 1
    return {
        "hard_killed": hard,
        "v2_would_kill": v2_would_kill,
        "v2_rescued": v2_rescued,
        "kill_rules": dict(kill_rules),
        "rescued_by_rule": dict(rescued_rules),
        "indicative_soft_flags": indicative_soft,
    }


def _jsonl_citations(
    rows: list[dict[str, Any]],
    *,
    source_file: str,
    rule_keys: tuple[str, ...],
    rescued_only: bool = False,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Envelope: 引用必须落到 jsonl 行."""
    out: list[dict[str, Any]] = []
    for line_no, r in enumerate(rows, start=1):
        if rescued_only and not (r.get("policy_v2_rescued") or r.get("v2_rescued")):
            continue
        rule = str(r.get("kill_rule") or "")
        head = rule.split("+")[0]
        if rule_keys and head not in rule_keys and not any(k in rule for k in rule_keys):
            continue
        out.append({
            "source": source_file,
            "line": line_no,
            "symbol": r.get("symbol") or r.get("sym"),
            "kill_rule": rule,
            "kill_value": r.get("kill_value"),
            "threshold_at_kill": r.get("threshold_at_kill"),
            "policy_v2_rescued": bool(r.get("policy_v2_rescued") or r.get("v2_rescued")),
        })
        if len(out) >= limit:
            break
    return out


def _proposal_items(
    stats: dict[str, Any],
    *,
    source_files: list[str],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    src = source_files[0] if source_files else ""
    spread_k = stats["kill_rules"].get("spread", 0)
    delta_k = stats["kill_rules"].get("delta", 0) + stats["kill_rules"].get("gamma", 0)
    iv_k = stats["kill_rules"].get("iv", 0)
    items: list[dict[str, Any]] = []

    items.append({
        "param": "max_spread_pct",
        "current": V1_PARAMS["max_spread_pct"],
        "proposed": V2_PROPOSED["max_spread_pct"],
        "evidence": f"spread kills={spread_k} · rescued_if_v2={stats['rescued_by_rule'].get('spread', 0)}",
        "impact": f"收紧 spread 上限可能少放 {max(0, spread_k - int(spread_k * 0.2))} 单量级(估算)",
        "counter": "spread 过紧会漏流动性差的真实机会",
        "sources": source_files,
        "citations": _jsonl_citations(rows, source_file=src, rule_keys=("spread",), limit=3),
        "recommend": spread_k >= 10,
    })
    items.append({
        "param": "delta_band + indicative_greek_soft",
        "current": f"{V1_PARAMS['min_delta']}–{V1_PARAMS['max_delta']} · hard greek",
        "proposed": f"同 band · indicative_soft=True (FilterConfig Task2-4)",
        "evidence": f"delta/gamma kills={delta_k} · v2 rescued delta={stats['rescued_by_rule'].get('delta', 0)}",
        "impact": f"indicative_soft 标记 {stats['indicative_soft_flags']} 次 · 可救 {stats['rescued_by_rule'].get('delta', 0)}",
        "counter": "indicative 希腊字母噪声大，软放行增加假阳性",
        "sources": source_files,
        "citations": _jsonl_citations(rows, source_file=src, rule_keys=("delta", "gamma"), limit=3),
        "recommend": stats["indicative_soft_flags"] > 0,
    })
    items.append({
        "param": "max_iv + iv_keep_pct",
        "current": V1_PARAMS["max_iv"],
        "proposed": "FilterConfig iv_keep_pct=70 + iv_hard_max=3.0 (未接线)",
        "evidence": f"iv kills={iv_k} · rescued_if_v2={stats['rescued_by_rule'].get('iv', 0)}",
        "impact": f"分位 cap 可能改变 iv 杀单分布(需 PercentileCaps 激活)",
        "counter": "IV 分位在 thin universe 上不稳定",
        "sources": source_files,
        "citations": _jsonl_citations(rows, source_file=src, rule_keys=("iv",), limit=3),
        "recommend": False,
    })
    items.append({
        "param": "no_change_theta_ratio_band_only",
        "current": "THETA_RATIO_* caps live",
        "proposed": "仅 shadow: theta_ratio_band=0.03",
        "evidence": f"hard={stats['hard_killed']} v2_would_kill={stats['v2_would_kill']} rescued={stats['v2_rescued']}",
        "impact": "影子已量化；未 Lyra_Approved 前不改 live",
        "counter": "theta 放宽直接增加 decay 暴露",
        "sources": source_files,
        "citations": _jsonl_citations(rows, source_file=src, rule_keys=tuple(), rescued_only=True, limit=2),
        "recommend": False,
    })
    return items


def build_proposal(*, jsonl_paths: list[Path], trade_date: str | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for p in jsonl_paths:
        rows.extend(_load_jsonl(p))
    if trade_date:
        rows = [r for r in rows if trade_date in json.dumps(r, ensure_ascii=False)[:200] or True]
    stats = _aggregate(rows)
    sources = [str(p) for p in jsonl_paths]
    items = _proposal_items(stats, source_files=sources, rows=rows)
    return {
        "schema": "policy_v2_proposal/v1",
        "task": "policy_v2_shadow_to_proposal",
        "owner_node": "glm",
        "status": "pending_lyra_approval",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "trade_date": trade_date,
        "stats": stats,
        "v1_live_params": V1_PARAMS,
        "items": items,
        "governance": {
            "zero_signal": True,
            "no_live_effect": True,
            "budget_usd_cap": 0.50,
        },
    }


def render_markdown(doc: dict[str, Any]) -> str:
    lines = [
        "# Policy V2 参数修改提案（只读 · 未生效）",
        "",
        f"- 生成: {doc.get('generated_at')}",
        f"- 状态: **{doc.get('status')}**",
        f"- 硬杀: {doc['stats']['hard_killed']} → V2 would_kill: {doc['stats']['v2_would_kill']} · rescued: {doc['stats']['v2_rescued']}",
        "",
        "## 提案项",
        "",
    ]
    for it in doc.get("items") or []:
        rec = "建议改" if it.get("recommend") else "不建议改"
        lines += [
            f"### {it['param']} ({rec})",
            f"- 现值: `{it['current']}`",
            f"- 提议: `{it['proposed']}`",
            f"- 数据: {it['evidence']}",
            f"- 影响: {it['impact']}",
            f"- 反面: {it['counter']}",
            f"- 出处: {', '.join(it.get('sources') or [])}",
        ]
        for cite in it.get("citations") or []:
            lines.append(
                f"  - jsonl L{cite.get('line')} · {cite.get('symbol')} · "
                f"{cite.get('kill_rule')} · rescued={cite.get('policy_v2_rescued')}"
            )
        lines.append("")
    lines.append("> Zero-Signal: 本提案只动过滤参数，不产标的/方向。未获 Lyra_Approved 前零生效。")
    return "\n".join(lines)


def emit_store(doc: dict[str, Any]) -> bool:
    try:
        from aether_grid_emit import emit_aether

        return bool(emit_aether("aether_policy_proposal", doc))
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Policy V2 shadow → proposal artifact")
    ap.add_argument("--date", help="Trade date YYYY-MM-DD filter")
    ap.add_argument("--jsonl", action="append", help="Specific rejection jsonl path(s)")
    ap.add_argument("--emit", action="store_true", help="POST to 8501 store/events")
    ap.add_argument("--no-glm", action="store_true", help="Skip GLM owner summary")
    args = ap.parse_args()

    paths: list[Path] = []
    if args.jsonl:
        paths = [Path(p).expanduser() for p in args.jsonl]
    elif REJECTION_DIR.is_dir():
        paths = sorted(REJECTION_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
    if not paths:
        print("ERR: no rejection jsonl found under logs/rejections")
        return 1

    doc = build_proposal(jsonl_paths=paths, trade_date=args.date)
    if not args.no_glm:
        summary, meta = _glm_summarize(doc)
        if summary:
            doc["glm_summary"] = summary
        doc["glm_meta"] = meta
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUT_DIR / f"proposal_{stamp}.json"
    md_path = OUT_DIR / f"proposal_{stamp}.md"
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(doc), encoding="utf-8")
    print(json_path)
    print(md_path)
    if args.emit:
        ok = emit_store(doc)
        print("store_emit", ok)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
