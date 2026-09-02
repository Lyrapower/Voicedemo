"""Alpha Factory pipeline — propose (Grid L1) → review (L0 sandbox) → approval queue."""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

import db
import factor_dedup
import factor_sandbox
import factor_evolution
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
    finally:
        c.close()
    return {
        "draft_id": draft_id, "name": name, "status": "draft", "route": route,
        "substrate": resp.get("substrate"), "trace_id": resp.get("trace_id"), "hypothesis": hypothesis,
        "origin": decision.origin, "direction": decision.direction,
        "parent_id": decision.parent_id, "crossover_parent_b": decision.crossover_parent_b,
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
        row = c.execute(
            "SELECT name, code, hypothesis, test, meta FROM factor_drafts WHERE id=?", (draft_id,)
        ).fetchone()
        if not row:
            db.job_event(c, job_id, 100.0, "error", {"detail": "draft not found"})
            c.commit()
            return
        name, code, hypothesis, is_test, meta_raw = row
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
            write_rejection_record(
                draft_id=draft_id,
                review_id=None,
                glm_code=glm_original,
                rejection_error=err,
                rejection_detail=reject_detail,
                note="L0 sandbox rejection during review",
            )
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
