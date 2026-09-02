"""Alpha Factory pipeline — propose (Grid L1) → review (L0 sandbox) → approval queue."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Callable

import db
import factor_dedup
import factor_sandbox
import factor_evolution
import factor_lineage_v1_1 as FL
import l0_runner
from l0_runner import (
    CODE_SOURCE_GLM,
    CODE_SOURCE_SUBSTITUTE,
    LANE_GLM,
    LANE_PIPELINE_SMOKE,
    attach_glm_original,
    capture_sandbox_rejection,
    ensure_l0_schema,
    record_glm_lane_stat,
    resolve_code_source,
    write_rejection_record,
)
from factor_sandbox import (
    FactorCodeError,
    ResourceLimit,
    SandboxError,
    SandboxRejection,
    WorkerPipelineError,
    build_fix_error_payload,
    eligible_for_fix_error,
)
from grid_factory_client import FactoryGridError, factory_task

_NAME_RE = re.compile(r"meta:\s*\{[^}]*name\s*:\s*['\"]([^'\"]+)['\"]", re.I)


def _extract_name(code: str, hypothesis: str) -> str:
    m = _NAME_RE.search(code or "")
    if m:
        return m.group(1).strip()[:80]
    return (hypothesis or "factor")[:40].strip() or "factor"


def _ensure_lineage_column(c) -> None:
    """幂等加 factor_drafts.lineage_id(ALTER 非幂等,PRAGMA guard)。"""
    cols = {r[1] for r in c.execute("PRAGMA table_info(factor_drafts)")}
    if "lineage_id" not in cols:
        c.execute("ALTER TABLE factor_drafts ADD COLUMN lineage_id INTEGER")
        c.commit()


def propose_factor(idea: str, *, test: bool = False, budget_hint: str = "std") -> dict[str, Any]:
    import factor_dedup

    idea = (idea or "").strip()
    if not idea:
        raise ValueError("idea required")
    if test:
        idea = f"[test] {idea}"
    # Assemble payload on 8600 side (zero gateway diff). recent_factors = 7d negative constraint.
    payload: dict[str, Any] = {"idea": idea}
    c0 = db.conn_factory()
    try:
        payload["recent_factors"] = factor_dedup.recent_factor_briefs(c0)
        # 拍板点 B: 连续 2× L0 失败 → 本侧记 escalate 意图;真升 glm52_cloud 需 gateway 解锁
        esc = c0.execute(
            "SELECT id, meta FROM factor_drafts WHERE COALESCE(json_extract(meta,'$.l0_fail_streak'),0) >= 2 "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if esc:
            payload["escalate_intent"] = True
            payload["escalate_from_draft"] = esc[0]
    except Exception:
        payload.setdefault("recent_factors", [])
    finally:
        c0.close()

    resp = factory_task("propose", payload, budget_hint=budget_hint)
    code = (resp.get("code") or "").strip()
    if not code:
        raise FactoryGridError("Grid returned no factor code block")
    hypothesis = (resp.get("hypothesis") or "").strip()
    name = _extract_name(code, hypothesis)
    slug = db.slugify(name)
    now = int(time.time())
    route = resp.get("route")
    escalated = bool(payload.get("escalate_intent"))
    # Without gateway force_cloud, route cannot become glm52_cloud; keep flag for stats.
    c = db.conn_factory()
    try:
        db.assert_db_writer("propose_factor")
        ensure_l0_schema(c)
        _ensure_lineage_column(c)
        dup = factor_dedup.check_duplicate_or_none(c, code)
        if dup and dup.get("match_id"):
            draft_id = factor_dedup.record_dup_rejected(
                c,
                slug=slug,
                name=name,
                hypothesis=hypothesis,
                code=code,
                route=route,
                trace_id=resp.get("trace_id"),
                match=dup,
                test=test,
            )
            c.commit()
            _dup_orig = dup.get("match_id")
            _dup_proposer = resp.get("substrate") or "grid-extended"
            FL.record_dead_proposal(code, name, "llm", _dup_proposer, reason=f"dup of draft {_dup_orig}")
            return {
                "draft_id": draft_id,
                "name": name,
                "status": "dup_rejected",
                "route": route,
                "substrate": resp.get("substrate"),
                "trace_id": resp.get("trace_id"),
                "hypothesis": hypothesis,
                "dup_rejected": True,
                "match_id": dup.get("match_id"),
                "escalated": escalated,
            }
        meta_json = attach_glm_original(
            json.dumps({
                "author": "grid-extended",
                "route": route,
                "substrate": resp.get("substrate"),
                "escalated": escalated,
                "escalate_blocked": escalated,  # true until gateway honors force_cloud
                "classifier": "factory 分类器",  # display name ≠ :8500 Router
            }, ensure_ascii=False),
            code,
        )
        cur = c.execute(
            "INSERT INTO factor_drafts(created, slug, name, hypothesis, code, status, route, trace_id, test, meta) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                now,
                slug,
                name,
                hypothesis,
                code,
                "draft",
                route,
                resp.get("trace_id"),
                1 if test else 0,
                meta_json,
            ),
        )
        draft_id = cur.lastrowid
        _origin = _evolve_origin(meta_json) or "llm"
        _parents = _evolve_parent(meta_json) or []
        _proposer = resp.get("substrate") or "grid-extended"
        if (hypothesis or "").strip():
            lineage_id = FL.propose(code, name, _origin, _parents, _proposer, hypothesis, notes=f"draft_id={draft_id}")
        else:
            lineage_id = FL.record_dead_proposal(code, name, _origin, _proposer)
        c.execute("UPDATE factor_drafts SET lineage_id=? WHERE id=?", (lineage_id, draft_id))
        c.commit()
    finally:
        c.close()
    return {
        "draft_id": draft_id,
        "name": name,
        "status": "draft",
        "route": route,
        "substrate": resp.get("substrate"),
        "trace_id": resp.get("trace_id"),
        "hypothesis": hypothesis,
        "escalated": escalated,
    }


def evolve_factor(*, direction: str | None = None, test: bool = False, budget_hint: str = "std",
                   mutation_first: bool = True) -> dict[str, Any]:
    """进化入口(QuantaAlpha trajectory mutation/crossover + RD-Agent(Q) bandit)。
    决策序:mutation(复用失败 trajectory 修 code)> crossover(重组高 reward 父)> propose(bandit 选向 fresh)。
    产 draft 后仍走既有 start_review 链(沙箱 + GLM 编译闸不变)。trajectory 在 _run_review_job 末尾落表。"""
    c0 = db.conn_factory()
    try:
        db.assert_db_writer("evolve_factor")
        factor_evolution.ensure_trajectory_schema(c0)
        decision = factor_evolution.decide_evolve(c0, direction=direction, mutation_first=mutation_first)
    finally:
        c0.close()

    # 按 origin 组装 factory_task payload
    if decision.origin == "mutation":
        payload = {
            "parent_hypothesis": decision.parent_hypothesis or "",
            "parent_code": decision.parent_code or "",
            "rejection_error": decision.rejection_error or "",
            "rejection_detail": decision.rejection_detail or {},
        }
        kind = "mutate"
    elif decision.origin == "crossover":
        payload = {
            "parent_hypothesis": decision.parent_hypothesis or "",
            "parent_code": decision.parent_code or "",
            "parent_b_hypothesis": decision.parent_b_hypothesis or "",
            "parent_b_code": decision.parent_b_code or "",
        }
        kind = "crossover"
    else:
        payload = {
            "direction": decision.direction,
            "knowledge_examples": decision.knowledge_examples or [],
        }
        kind = "direction"

    resp = factory_task(kind, payload, budget_hint=budget_hint)
    code = (resp.get("code") or "").strip()
    if not code:
        raise FactoryGridError(f"Grid returned no factor code block (origin={decision.origin})")
    hypothesis = (resp.get("hypothesis") or "").strip()
    name = _extract_name(code, hypothesis)
    slug = db.slugify(name)
    now = int(time.time())
    route = resp.get("route")

    c = db.conn_factory()
    try:
        db.assert_db_writer("evolve_factor")
        ensure_l0_schema(c)
        _ensure_lineage_column(c)
        dup = factor_dedup.check_duplicate_or_none(c, code)
        if dup and dup.get("match_id"):
            draft_id = factor_dedup.record_dup_rejected(
                c, slug=slug, name=name, hypothesis=hypothesis, code=code, route=route,
                trace_id=resp.get("trace_id"), match=dup, test=test,
            )
            c.commit()
            # dup 也记 trajectory(origin=propose/mutation/crossover,outcome=dup_rejected)
            _record_trajectory_for_draft(c, draft_id=draft_id, review_id=None, hypothesis=hypothesis,
                                         code=code, metrics=None, outcome="dup_rejected",
                                         origin=decision.origin, direction=decision.direction,
                                         parent_id=decision.parent_id,
                                         crossover_parent_b=decision.crossover_parent_b,
                                         code_source=None)
            c.commit()
            return {"draft_id": draft_id, "name": name, "status": "dup_rejected", "route": route,
                    "origin": decision.origin, "direction": decision.direction,
                    "parent_id": decision.parent_id, "crossover_parent_b": decision.crossover_parent_b,
                    "dup_rejected": True, "match_id": dup.get("match_id")}
        meta = {
            "author": "grid-extended", "route": route, "substrate": resp.get("substrate"),
            "evolve_origin": decision.origin, "evolve_direction": decision.direction,
            "evolve_parent_id": decision.parent_id, "evolve_crossover_b": decision.crossover_parent_b,
            "classifier": "factory 分类器",
        }
        meta_json = attach_glm_original(json.dumps(meta, ensure_ascii=False), code)
        cur = c.execute(
            "INSERT INTO factor_drafts(created, slug, name, hypothesis, code, status, route, trace_id, test, meta) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (now, slug, name, hypothesis, code, "draft", route, resp.get("trace_id"), 1 if test else 0, meta_json),
        )
        draft_id = cur.lastrowid
        c.commit()
        # lineage 接入(接入点 1 同段):origin=_evolve_origin。
        # parent_ids 需 FL factor id(非 trajectory id)——FL.lineage 按 parent_ids 递归
        # SELECT * FROM factors WHERE id=?,trajectory id 解析不到祖先。故从
        # decision.parent_id(trajectory id)→ factor_trajectories.draft_id →
        # factor_drafts.lineage_id 解析(砥要「dashboard 链能显示祖先」)。
        # decision.origin ∈ {mutation,crossover,propose};FL ORIGINS 不含 "propose"
        # (fresh direction 走 LLM)→映射 "propose"→"llm"。
        _origin = _evolve_origin(meta_json) or "llm"
        if _origin == "propose":
            _origin = "llm"
        _parents: list[int] = []
        for _traj_id in (decision.parent_id, decision.crossover_parent_b):
            if _traj_id is None:
                continue
            _t = c.execute("SELECT draft_id FROM factor_trajectories WHERE id=?", (_traj_id,)).fetchone()
            if _t and _t[0]:
                _dl = c.execute("SELECT lineage_id FROM factor_drafts WHERE id=?", (_t[0],)).fetchone()
                if _dl and _dl[0] is not None:
                    _parents.append(int(_dl[0]))
        _proposer = resp.get("substrate") or "grid-extended"
        if (hypothesis or "").strip():
            lineage_id = FL.propose(code, name, _origin, _parents, _proposer, hypothesis, notes=f"draft_id={draft_id}")
        else:
            lineage_id = FL.record_dead_proposal(code, name, _origin, _proposer)
        c.execute("UPDATE factor_drafts SET lineage_id=? WHERE id=?", (lineage_id, draft_id))
        c.commit()
    finally:
        c.close()
    return {
        "draft_id": draft_id, "name": name, "status": "draft", "route": route,
        "substrate": resp.get("substrate"), "trace_id": resp.get("trace_id"), "hypothesis": hypothesis,
        "origin": decision.origin, "direction": decision.direction,
        "parent_id": decision.parent_id, "crossover_parent_b": decision.crossover_parent_b,
        "lineage_id": lineage_id,
    }


def _record_trajectory_for_draft(
    c, *, draft_id: int, review_id: int | None, hypothesis: str, code: str,
    metrics: dict[str, Any] | None, outcome: str, origin: str, direction: str | None,
    parent_id: int | None, crossover_parent_b: int | None, code_source: str | None,
    rejection_error: str | None = None, rejection_detail: dict[str, Any] | None = None,
) -> int:
    """落一条 trajectory + bandit health 更新。"""
    meta = {}
    if rejection_error:
        meta["rejection_error"] = (rejection_error or "")[:600]
    if rejection_detail:
        meta["rejection_detail"] = rejection_detail
    traj_id = factor_evolution.record_trajectory(
        c, draft_id=draft_id, review_id=review_id, hypothesis=hypothesis, code=code,
        metrics=metrics, outcome=outcome, origin=origin, direction=direction,
        parent_id=parent_id, crossover_parent_b=crossover_parent_b, code_source=code_source, meta=meta,
    )
    if direction:
        reward, _, _ = factor_evolution.compute_reward(metrics, outcome)
        factor_evolution.update_arm(c, direction, reward)
    return traj_id


def _run_review_job(job_id: int, draft_id: int, *, code_source_override: str | None = None) -> None:
    c = db.conn_factory()
    try:
        db.assert_db_writer("_run_review_job")
        ensure_l0_schema(c)
        _ensure_lineage_column(c)
        row = c.execute(
            "SELECT name, code, hypothesis, test, meta, lineage_id FROM factor_drafts WHERE id=?", (draft_id,)
        ).fetchone()
        if not row:
            db.job_event(c, job_id, 100.0, "error", {"detail": "draft not found"})
            c.commit()
            return
        name, code, hypothesis, is_test, meta_raw, lineage_id = row
        code_source = code_source_override or resolve_code_source(code=code, meta_raw=meta_raw)
        lane = LANE_GLM if code_source == CODE_SOURCE_GLM else LANE_PIPELINE_SMOKE
        c.execute("UPDATE factor_drafts SET status='reviewing' WHERE id=?", (draft_id,))
        db.job_event(
            c,
            job_id,
            5.0,
            "review_start",
            {"draft_id": draft_id, "name": name, "code_source": code_source, "lane": lane},
        )
        c.commit()

        watchlist = db.resolve_watchlist()
        db_path = db.DB_PATH
        try:
            metrics = factor_sandbox.run_factor_review(code, db_path, watchlist)
            db.job_event(c, job_id, 70.0, "metrics_done", {"draft_id": draft_id, "metrics_keys": list(metrics.keys())})
            c.commit()
        except SandboxError as exc:
            err = str(exc)
            glm_original = l0_runner.glm_code_original(meta_raw) or code
            reject_detail = capture_sandbox_rejection(glm_original, db_path, watchlist)
            _p = write_rejection_record(
                draft_id=draft_id,
                review_id=None,
                glm_code=glm_original,
                rejection_error=err,
                rejection_detail=reject_detail,
                note="L0 sandbox rejection during review",
            )
            if lineage_id is not None:
                FL.record_sandbox(lineage_id, False, str(_p), err)
            now = int(time.time())
            # Track consecutive L0 fails on this draft (for escalate_intent on next propose).
            try:
                meta = json.loads(meta_raw or "{}")
            except Exception:
                meta = {}
            streak = int(meta.get("l0_fail_streak") or 0) + 1
            meta["l0_fail_streak"] = streak
            if streak >= 2:
                meta["escalate_ready"] = True
            c.execute(
                "UPDATE factor_drafts SET status='glm_code_rejected', meta=? WHERE id=?",
                (json.dumps(meta, ensure_ascii=False), draft_id),
            )
            c.execute(
                "INSERT INTO factor_reviews(draft_id, job_id, created, status, metrics, grid_explain, error, "
                "code_source, lane, quarantine) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (draft_id, job_id, now, "glm_code_rejected", "{}", "", err, code_source, lane, 1),
            )
            _record_trajectory_for_draft(
                c, draft_id=draft_id, review_id=None, hypothesis=hypothesis, code=code,
                metrics=None, outcome="rejected", origin=_evolve_origin(meta_raw) or "propose",
                direction=_evolve_direction(meta_raw), parent_id=_evolve_parent(meta_raw),
                crossover_parent_b=_evolve_crossover_b(meta_raw), code_source=code_source,
                rejection_error=err, rejection_detail=reject_detail,
            )
            db.job_event(
                c,
                job_id,
                100.0,
                "failed",
                {"draft_id": draft_id, "error": err, "category": exc.category, "quarantine": True},
            )
            c.commit()
            if eligible_for_fix_error(exc) and code_source == CODE_SOURCE_GLM:
                meta["last_fix_error"] = True
                c.execute("UPDATE factor_drafts SET meta=? WHERE id=?", (json.dumps(meta, ensure_ascii=False), draft_id))
                c.commit()
                _maybe_fix_once(c, draft_id, code, build_fix_error_payload(code, exc), job_id)
            return

        if code_source != CODE_SOURCE_GLM:
            now = int(time.time())
            c.execute("UPDATE factor_drafts SET status='quarantine' WHERE id=?", (draft_id,))
            c.execute(
                "INSERT INTO factor_reviews(draft_id, job_id, created, status, metrics, grid_explain, error, "
                "code_source, lane, quarantine) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    draft_id,
                    job_id,
                    now,
                    "passed",
                    json.dumps(metrics, ensure_ascii=False),
                    "",
                    "substitute code, NOT GLM output",
                    code_source,
                    LANE_PIPELINE_SMOKE,
                    1,
                ),
            )
            _record_trajectory_for_draft(
                c, draft_id=draft_id, review_id=None, hypothesis=hypothesis, code=code,
                metrics=metrics, outcome="quarantine",
                origin=_evolve_origin(meta_raw) or "propose", direction=_evolve_direction(meta_raw),
                parent_id=_evolve_parent(meta_raw), crossover_parent_b=_evolve_crossover_b(meta_raw),
                code_source=code_source,
            )
            db.job_event(
                c,
                job_id,
                100.0,
                "quarantine",
                {"draft_id": draft_id, "code_source": code_source, "lane": LANE_PIPELINE_SMOKE},
            )
            c.commit()
            return

        # 评估段(仅 GLM pass):大 universe + frame,独立超时;超时/失败不算沙箱失败(安全闸已过)
        _work = None
        _eval_err = None
        try:
            import factor_truth
            universe_symbols = factor_truth.load_sp500_symbols()
            _eval_cap = int(os.environ.get("FACTOR_EVAL_SYMBOLS", "500"))
            _metrics_eval, _work = factor_sandbox.run_factor_review(
                code, db_path, universe_symbols, symbols_cap=_eval_cap, return_frame=True,
                timeout=float(os.environ.get("FACTOR_EVAL_TIMEOUT", "120")),
            )
        except Exception as _exc:
            _eval_err = (type(_exc).__name__ + ": " + str(_exc))[:160]

        explain = ""
        try:
            ex = factory_task(
                "review_explain",
                {"name": name, "metrics": metrics},
                budget_hint="low",
            )
            explain = (ex.get("grid_explain") or ex.get("content") or "").strip()
            db.job_event(c, job_id, 90.0, "grid_explain", {"draft_id": draft_id})
            c.commit()
        except FactoryGridError as exc:
            explain = f"(Grid 解读暂不可用: {exc})"

        now = int(time.time())
        rev = c.execute(
            "INSERT INTO factor_reviews(draft_id, job_id, created, status, metrics, grid_explain, error, "
            "code_source, lane, quarantine) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                draft_id,
                job_id,
                now,
                "passed",
                json.dumps(metrics, ensure_ascii=False),
                explain,
                "",
                CODE_SOURCE_GLM,
                LANE_GLM,
                0,
            ),
        )
        review_id = rev.lastrowid
        if lineage_id is not None:
            FL.record_sandbox(lineage_id, True, f"factor_reviews:{review_id}", "")
            import ic_eval_v1_1 as IE
            if _work is not None:
                _s = IE.evaluate_frame(_work, horizon=5)
                IE.write_lineage(_s, lineage_id, f"factor_reviews:{review_id}", *IE.auto_verdict(_s))
            else:
                FL.record_eval(lineage_id, "", "", "5d", 0, None, None, "close_to_close",
                                None, f"factor_reviews:{review_id}", "insufficient",
                                "eval timeout" if _eval_err else "eval no frame")
        record_glm_lane_stat(
            c,
            review_id=review_id,
            draft_id=draft_id,
            outcome="passed",
            code_source=CODE_SOURCE_GLM,
            lane=LANE_GLM,
        )
        c.execute("UPDATE factor_drafts SET status='pending' WHERE id=?", (draft_id,))
        c.execute(
            "INSERT INTO factor_proposals(draft_id, review_id, created, status, meta) VALUES(?,?,?,?,?)",
            (
                draft_id,
                review_id,
                now,
                "pending",
                json.dumps({"test": bool(is_test), "code_source": CODE_SOURCE_GLM}, ensure_ascii=False),
            ),
        )
        _record_trajectory_for_draft(
            c, draft_id=draft_id, review_id=review_id, hypothesis=hypothesis, code=code,
            metrics=metrics, outcome="passed",
            origin=_evolve_origin(meta_raw) or "propose", direction=_evolve_direction(meta_raw),
            parent_id=_evolve_parent(meta_raw), crossover_parent_b=_evolve_crossover_b(meta_raw),
            code_source=code_source,
        )
        db.job_event(c, job_id, 100.0, "proposal_ready", {"draft_id": draft_id, "review_id": review_id})
        c.commit()
    except Exception as exc:
        try:
            db.job_event(c, job_id, 100.0, "error", {"detail": str(exc)[:300]})
            c.execute("UPDATE factor_drafts SET status='failed' WHERE id=?", (draft_id,))
            c.commit()
        except Exception:
            pass
    finally:
        c.close()


def _evolve_origin(meta_raw: str | None) -> str | None:
    try:
        return (json.loads(meta_raw or "{}") or {}).get("evolve_origin")
    except Exception:
        return None


def _evolve_direction(meta_raw: str | None) -> str | None:
    try:
        return (json.loads(meta_raw or "{}") or {}).get("evolve_direction")
    except Exception:
        return None


def _evolve_parent(meta_raw: str | None) -> int | None:
    try:
        v = (json.loads(meta_raw or "{}") or {}).get("evolve_parent_id")
        return int(v) if v is not None else None
    except Exception:
        return None


def _evolve_crossover_b(meta_raw: str | None) -> int | None:
    try:
        v = (json.loads(meta_raw or "{}") or {}).get("evolve_crossover_b")
        return int(v) if v is not None else None
    except Exception:
        return None


def _maybe_fix_once(c, draft_id: int, code: str, fix_payload: dict[str, Any], job_id: int) -> None:
    try:
        fix = factory_task("fix_error", fix_payload, budget_hint="std")
        new_code = (fix.get("code") or "").strip()
        if not new_code:
            return
        c.execute("UPDATE factor_drafts SET code=?, status='draft', route=? WHERE id=?", (new_code, fix.get("route"), draft_id))
        db.job_event(c, job_id, 100.0, "fix_applied", {"draft_id": draft_id, "route": fix.get("route")})
        c.commit()
    except FactoryGridError:
        pass


def start_review(draft_id: int, *, code_source_override: str | None = None) -> int:
    c = db.conn_jobs()
    try:
        db.assert_db_writer("start_review")
        cur = c.execute(
            "INSERT INTO jobs(kind, created, status, pct, detail) VALUES('factor_review', ?, 'running', 0, ?)",
            (int(time.time()), f"draft:{draft_id}"),
        )
        job_id = cur.lastrowid
        c.commit()
    finally:
        c.close()
    threading.Thread(
        target=_run_review_job,
        args=(job_id, draft_id),
        kwargs={"code_source_override": code_source_override},
        daemon=True,
    ).start()
    return job_id


def list_drafts(limit: int = 20) -> list[dict[str, Any]]:
    c = db.conn_factory()
    try:
        rows = c.execute(
            "SELECT id, created, slug, name, hypothesis, status, route, trace_id, test FROM factor_drafts "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "created": r[1],
                "slug": r[2],
                "name": r[3],
                "hypothesis": r[4],
                "status": r[5],
                "route": r[6],
                "trace_id": r[7],
                "test": bool(r[8]),
            }
            for r in rows
        ]
    finally:
        c.close()


def list_proposals(status: str | None = None) -> list[dict[str, Any]]:
    c = db.conn_factory()
    try:
        q = (
            "SELECT p.id, p.status, p.created, d.name, d.hypothesis, r.metrics, r.grid_explain, p.draft_id, p.review_id "
            "FROM factor_proposals p "
            "JOIN factor_drafts d ON d.id=p.draft_id "
            "JOIN factor_reviews r ON r.id=p.review_id "
        )
        if status:
            rows = c.execute(q + "WHERE p.status=? ORDER BY p.id DESC LIMIT 50", (status,)).fetchall()
        else:
            rows = c.execute(q + "ORDER BY p.id DESC LIMIT 50").fetchall()
        out = []
        for r in rows:
            metrics = json.loads(r[5] or "{}")
            out.append(
                {
                    "proposal_id": r[0],
                    "status": r[1],
                    "created": r[2],
                    "name": r[3],
                    "hypothesis": r[4],
                    "metrics": metrics,
                    "grid_explain": r[6],
                    "draft_id": r[7],
                    "review_id": r[8],
                    "card_type": "factor",
                }
            )
        return out
    finally:
        c.close()


def decide_proposal(proposal_id: int, decision: str) -> dict[str, Any]:
    decision = (decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise ValueError("decision must be approve or reject")
    now = int(time.time())
    c = db.conn_factory()
    try:
        row = c.execute(
            "SELECT p.draft_id, p.status FROM factor_proposals p WHERE p.id=?", (proposal_id,)
        ).fetchone()
        if not row:
            raise ValueError("proposal not found")
        draft_id, st = row
        if st != "pending":
            raise ValueError(f"proposal already {st}")
        new_st = "approved" if decision == "approve" else "rejected"
        c.execute(
            "UPDATE factor_proposals SET status=?, decision_ts=? WHERE id=?",
            (new_st, now, proposal_id),
        )
        c.execute(
            "UPDATE factor_drafts SET status=? WHERE id=?",
            ("active" if decision == "approve" else "archived", draft_id),
        )
        c.commit()
    finally:
        c.close()
    return {"proposal_id": proposal_id, "status": new_st, "draft_id": draft_id}


def _poll_job_done(job_id: int, *, timeout: float = 120.0, interval: float = 0.3) -> str:
    """轮询 jobs 表直到 status=done 或超时;返回最终 status(done/running/timeout)。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        jc = db.conn_jobs()
        try:
            row = jc.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        finally:
            jc.close()
        if row and row[0] == "done":
            return "done"
        time.sleep(interval)
    return "timeout"


def evolve_loop(*, rounds: int = 15, test: bool = False, budget_hint: str = "std",
                poll_timeout: float = 120.0, mutation_first: bool = True,
                on_round: Callable[[int, dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """自动进化 N 轮(QuantaAlpha 风格固定轮次循环)。
    每轮:evolve_factor → start_review → 轮询 review 完成 → trajectory 自动落表(_run_review_job 末尾记)。
    返回汇总:各 outcome 计数、best reward/direction、lineage 深度。
    不破沙箱主权 + GLM 编译闸(进化层只产 draft,落盘走既有 review→proposal 链)。"""
    from collections import Counter
    outcomes: Counter = Counter()
    best_reward = 0.0
    best_direction: str | None = None
    best_traj_id: int | None = None
    last_draft_id: int | None = None
    for i in range(rounds):
        try:
            res = evolve_factor(test=test, budget_hint=budget_hint, mutation_first=mutation_first)
        except FactoryGridError as exc:
            outcomes["factory_error"] += 1
            if on_round:
                on_round(i, {"round": i, "status": "factory_error", "error": str(exc)[:200]})
            continue
        last_draft_id = res.get("draft_id")
        origin = res.get("origin", "propose")
        direction = res.get("direction")
        if res.get("dup_rejected"):
            outcomes["dup_rejected"] += 1
            if on_round:
                on_round(i, {"round": i, "status": "dup_rejected", "origin": origin, "direction": direction})
            continue
        # 跑 review(异步线程)
        job_id = start_review(last_draft_id)
        status = _poll_job_done(job_id, timeout=poll_timeout)
        if status != "done":
            outcomes["review_timeout"] += 1
            if on_round:
                on_round(i, {"round": i, "status": "review_timeout", "draft_id": last_draft_id, "origin": origin})
            continue
        # 从 trajectory 表读本轮结果(_run_review_job 已落表)
        c = db.conn_factory()
        try:
            factor_evolution.ensure_trajectory_schema(c)
            row = c.execute(
                "SELECT id, outcome, reward, direction FROM factor_trajectories "
                "WHERE draft_id=? ORDER BY id DESC LIMIT 1", (last_draft_id,)
            ).fetchone()
        finally:
            c.close()
        if not row:
            outcomes["no_trajectory"] += 1
            continue
        traj_id, outcome, reward, traj_dir = row
        outcomes[outcome] += 1
        if (reward or 0) > best_reward:
            best_reward = float(reward or 0)
            best_direction = traj_dir or direction
            best_traj_id = traj_id
        if on_round:
            on_round(i, {"round": i, "status": outcome, "draft_id": last_draft_id,
                         "traj_id": traj_id, "origin": origin, "direction": traj_dir or direction,
                         "reward": reward})
    # lineage 深度(追最近一条 trajectory 的 parent 链)
    lineage_depth = 0
    if best_traj_id is not None:
        c = db.conn_factory()
        try:
            factor_evolution.ensure_trajectory_schema(c)
            lineage_depth = len(factor_evolution.trajectory_lineage(c, best_traj_id))
        finally:
            c.close()
    return {
        "rounds": rounds,
        "outcomes": dict(outcomes),
        "best_reward": round(best_reward, 6),
        "best_direction": best_direction,
        "best_traj_id": best_traj_id,
        "lineage_depth": lineage_depth,
        "last_draft_id": last_draft_id,
    }
