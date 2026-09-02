"""factor_evolution.py · Alpha Factory 进化层(QuantaAlpha trajectory + RD-Agent(Q) bandit)

借鉴:
  QuantaAlpha — trajectory 级 mutation(定位失败步重写,前缀冻结)+ crossover(重组高 reward 父段)
  RD-Agent(Q) — multi-armed bandit 调度(UCB 选向)+ 知识库复用(验证过的 pattern 当 crossover 父池)

设计原则(守恒,不破现有红线):
  - 纯 additive:不动 factor_sandbox / l0_runner / factor_dedup / grid_factory_client 既有逻辑
  - LLM 输出永不进 metrics dict(沙箱主权不变;metrics 仍由 factor_sandbox 确定性算)
  - GLM 编译闸不变(进化层只产 draft,落盘仍走既有 propose_factor → review → proposal 链)
  - trajectory = 一次完整 propose→review 的可复用单元(hypothesis+code+metrics+outcome+reward+lineage)
  - bandit 选向替代"每次从零 propose";mutation/crossover 复用验证过的 trajectory
  - reward = |IC|(passed)/ 0(rejected);QuantaAlpha 用 RankIC 贪心选,此处用 abs(IC) 作 reward,IR 作 tiebreak
  - bandit 用 UCB(平均 reward + 探索_bonus),arm = 方向集(momentum/mean_rev/volume/...)

落码范围:本文件 + factory_prompts.py(加 mutate/crossover/direction 三个 prompt kind)
        + factory_pipeline.py(propose_factor 加 evolve 入口,_run_review_job 末尾 record trajectory + update bandit)
        + 测试。不碰 local_gateway.py / 冻结链 / 部署形态。
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import db

# ---- 方向集(bandit arms)----
# 可由 env FACTORY_DIRECTIONS 覆盖(逗号分隔);默认覆盖常见因子族。
DEFAULT_DIRECTIONS = [
    "momentum",        # 动量:过去 N 日收益
    "mean_reversion",  # 均值回归:短期反转
    "volume",          # 量能:量价背离 / 量缩价涨
    "volatility",      # 波动:已实现波动 vs 隐含
    "overnight_gap",   # 隔夜跳空:close→open gap
    "earnings_drift",  # 财报漂移:财报后漂移
    "breadth",        # 市场宽度:涨跌家数比
    "cross_sectional", # 截面:相对强弱
]


def directions() -> list[str]:
    env = os.getenv("FACTORY_DIRECTIONS", "").strip()
    if env:
        return [d.strip() for d in env.split(",") if d.strip()]
    return list(DEFAULT_DIRECTIONS)


# ---- trajectory schema ----
TRAJECTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS factor_trajectories(
  id INTEGER PRIMARY KEY,
  created INTEGER NOT NULL,
  draft_id INTEGER,
  review_id INTEGER,
  hypothesis TEXT,
  code TEXT,
  metrics TEXT,
  outcome TEXT NOT NULL,
  reward REAL NOT NULL DEFAULT 0,
  ic REAL,
  ir REAL,
  fingerprint TEXT,
  origin TEXT NOT NULL,
  direction TEXT,
  parent_id INTEGER,
  crossover_parent_b INTEGER,
  code_source TEXT,
  meta TEXT);
CREATE INDEX IF NOT EXISTS ix_traj_outcome ON factor_trajectories(outcome);
CREATE INDEX IF NOT EXISTS ix_traj_reward ON factor_trajectories(reward DESC);
CREATE INDEX IF NOT EXISTS ix_traj_direction ON factor_trajectories(direction);
CREATE INDEX IF NOT EXISTS ix_traj_parent ON factor_trajectories(parent_id);
"""


def ensure_trajectory_schema(c: sqlite3.Connection) -> None:
    c.executescript(TRAJECTORY_SCHEMA)


# ---- reward ----
def compute_reward(metrics: dict[str, Any] | None, outcome: str) -> tuple[float, float | None, float | None]:
    """返回 (reward, ic, ir)。passed 用 |IC|,其余 0。QuantaAlpha RankIC 贪心 → abs(IC) 等价。"""
    if not metrics or outcome != "passed":
        return 0.0, None, None
    ic = metrics.get("ic")
    ir = metrics.get("ir")
    try:
        ic_v = float(ic) if ic is not None else None
    except (TypeError, ValueError):
        ic_v = None
    try:
        ir_v = float(ir) if ir is not None else None
    except (TypeError, ValueError):
        ir_v = None
    reward = abs(ic_v) if ic_v is not None else 0.0
    return round(reward, 6), ic_v, ir_v


# ---- trajectory record / query ----
def record_trajectory(
    c: sqlite3.Connection,
    *,
    draft_id: int | None,
    review_id: int | None,
    hypothesis: str,
    code: str,
    metrics: dict[str, Any] | None,
    outcome: str,
    origin: str,
    direction: str | None = None,
    parent_id: int | None = None,
    crossover_parent_b: int | None = None,
    code_source: str | None = None,
    fingerprint: str | None = None,
    meta: dict[str, Any] | None = None,
) -> int:
    """记一条 trajectory。outcome ∈ {passed, rejected, quarantine, dup_rejected, failed}。"""
    ensure_trajectory_schema(c)
    reward, ic, ir = compute_reward(metrics, outcome)
    if fingerprint is None:
        try:
            import factor_dedup
            fingerprint = factor_dedup.factor_fingerprint(code or "")
        except Exception:
            fingerprint = None
    cur = c.execute(
        "INSERT INTO factor_trajectories(created, draft_id, review_id, hypothesis, code, metrics, "
        "outcome, reward, ic, ir, fingerprint, origin, direction, parent_id, crossover_parent_b, "
        "code_source, meta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            int(time.time()), draft_id, review_id, (hypothesis or "")[:600], code or "",
            json.dumps(metrics or {}, ensure_ascii=False), outcome, reward, ic, ir, fingerprint,
            origin, direction, parent_id, crossover_parent_b, code_source,
            json.dumps(meta or {}, ensure_ascii=False),
        ),
    )
    return int(cur.lastrowid)


def top_trajectories(c: sqlite3.Connection, *, limit: int = 10, outcome: str = "passed") -> list[dict[str, Any]]:
    """高 reward trajectory(作 crossover 父池 / few-shot 知识库)。"""
    ensure_trajectory_schema(c)
    rows = c.execute(
        "SELECT id, hypothesis, code, metrics, reward, ic, ir, direction, origin, fingerprint "
        "FROM factor_trajectories WHERE outcome=? AND reward>0 ORDER BY reward DESC, ir DESC LIMIT ?",
        (outcome, limit),
    ).fetchall()
    return [
        {"id": r[0], "hypothesis": r[1], "code": r[2], "metrics": json.loads(r[3] or "{}"),
         "reward": r[4], "ic": r[5], "ir": r[6], "direction": r[7], "origin": r[8], "fingerprint": r[9]}
        for r in rows
    ]


def recent_rejected(c: sqlite3.Connection, *, limit: int = 5, fixable_only: bool = True) -> list[dict[str, Any]]:
    """最近被拒 trajectory(mutation 候选)。fixable_only:只取有 rejection error 的(factor_code 类)。"""
    ensure_trajectory_schema(c)
    rows = c.execute(
        "SELECT id, hypothesis, code, metrics, outcome, direction, parent_id, meta "
        "FROM factor_trajectories WHERE outcome IN ('rejected','failed') ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        meta = json.loads(r[7] or "{}")
        if fixable_only and not meta.get("rejection_error"):
            continue
        out.append({
            "id": r[0], "hypothesis": r[1], "code": r[2], "metrics": json.loads(r[3] or "{}"),
            "outcome": r[4], "direction": r[5], "parent_id": r[6], "meta": meta,
        })
    return out


# ---- bandit (UCB) ----
@dataclass
class ArmStats:
    arm: str
    n: int = 0
    total_reward: float = 0.0
    last_selected: float = 0.0

    @property
    def mean(self) -> float:
        return (self.total_reward / self.n) if self.n else 0.0


def _arm_stats(c: sqlite3.Connection) -> dict[str, ArmStats]:
    ensure_trajectory_schema(c)
    rows = c.execute(
        "SELECT direction, COUNT(*), COALESCE(SUM(reward),0), COALESCE(MAX(created),0) "
        "FROM factor_trajectories WHERE direction IS NOT NULL GROUP BY direction"
    ).fetchall()
    stats = {d: ArmStats(d) for d in directions()}
    for arm, n, tot, last in rows:
        if arm in stats:
            stats[arm].n = int(n or 0)
            stats[arm].total_reward = float(tot or 0)
            stats[arm].last_selected = float(last or 0)
    return stats


def ucb_select(c: sqlite3.Connection, *, c_param: float = 2.0, explore_bonus_untried: float = 1.0) -> str:
    """UCB1:arm_score = mean + c*sqrt(ln(N_total)/n_arm);未试 arm 给探索 bonus。
    N_total = 所有 trajectory 数(含 0 reward);n_arm = 该 arm trajectory 数。"""
    stats = _arm_stats(c)
    total_n = sum(s.n for s in stats.values()) or 1
    log_n = math.log(max(total_n, 1))
    best_arm = None
    best_score = -float("inf")
    for arm, s in stats.items():
        if s.n == 0:
            score = explore_bonus_untried  # 未试 arm 优先探索
        else:
            exploit = s.mean
            explore = c_param * math.sqrt(log_n / s.n)
            score = exploit + explore
        if score > best_score:
            best_score = score
            best_arm = arm
    return best_arm or directions()[0]


def update_arm(c: sqlite3.Connection, direction: str, reward: float) -> None:
    """bandit 更新 = 记 trajectory 时 direction+reward 已落表;此处仅作 health 记录(可选)。"""
    try:
        detail = json.dumps({"direction": direction, "reward": reward, "ts": int(time.time())})
        c.execute(
            "INSERT INTO health(component, ts, status, detail) VALUES(?,?,?,?) "
            "ON CONFLICT(component) DO UPDATE SET ts=excluded.ts, status=excluded.status, detail=excluded.detail",
            (f"bandit_{direction}", int(time.time()), "ok", detail[:400]),
        )
    except Exception:
        pass


# ---- 进化决策:mutation / crossover / fresh(bandit-guided)----
@dataclass
class EvolveDecision:
    origin: str  # "mutation" | "crossover" | "propose"
    direction: str
    parent_id: int | None = None
    crossover_parent_b: int | None = None
    parent_hypothesis: str | None = None
    parent_code: str | None = None
    parent_b_hypothesis: str | None = None
    parent_b_code: str | None = None
    rejection_error: str | None = None
    rejection_detail: dict[str, Any] | None = None
    knowledge_examples: list[dict[str, Any]] = field(default_factory=list)


def decide_evolve(c: sqlite3.Connection, *, direction: str | None = None, mutation_first: bool = True) -> EvolveDecision:
    """决定本轮进化的 origin 与素材。
    优先序(可调):mutation(复用失败 trajectory 的 hypothesis+修 code)> crossover(重组高 reward 父)> propose(bandit 选向 fresh)。
    mutation_first=True 时优先修最近的失败;否则优先 crossover。"""
    ensure_trajectory_schema(c)
    arm = direction or ucb_select(c)
    # 1. mutation 候选:最近被拒(优先同 direction,没有则任意)
    if mutation_first:
        rej = recent_rejected(c, limit=8)
        if rej:
            same_dir = [r for r in rej if r["direction"] == arm] or rej
            parent = same_dir[0]
            return EvolveDecision(
                origin="mutation", direction=arm, parent_id=parent["id"],
                parent_hypothesis=parent["hypothesis"], parent_code=parent["code"],
                rejection_error=parent["meta"].get("rejection_error"),
                rejection_detail=parent["meta"].get("rejection_detail"),
            )
    # 2. crossover 候选:≥2 高 reward 父
    top = top_trajectories(c, limit=10)
    if len(top) >= 2:
        # 优先同 direction 的父对;没有则取 top2
        same = [t for t in top if t["direction"] == arm]
        pool = (same + top)[:10]
        a, b = pool[0], pool[1]
        return EvolveDecision(
            origin="crossover", direction=arm, parent_id=a["id"], crossover_parent_b=b["id"],
            parent_hypothesis=a["hypothesis"], parent_code=a["code"],
            parent_b_hypothesis=b["hypothesis"], parent_b_code=b["code"],
            knowledge_examples=[a, b],
        )
    # 3. fresh propose,bandit 选向;带 top 知识作 few-shot(若有)
    return EvolveDecision(
        origin="propose", direction=arm,
        knowledge_examples=top_trajectories(c, limit=3),
    )


def trajectory_lineage(c: sqlite3.Connection, traj_id: int) -> list[dict[str, Any]]:
    """追溯一条 trajectory 的 ancestry(parent_id 链),用于审计。"""
    ensure_trajectory_schema(c)
    chain = []
    cur_id = traj_id
    seen = set()
    while cur_id and cur_id not in seen:
        seen.add(cur_id)
        row = c.execute(
            "SELECT id, origin, parent_id, crossover_parent_b, direction, outcome, reward "
            "FROM factor_trajectories WHERE id=?", (cur_id,)
        ).fetchone()
        if not row:
            break
        chain.append({"id": row[0], "origin": row[1], "parent_id": row[2],
                       "crossover_parent_b": row[3], "direction": row[4],
                       "outcome": row[5], "reward": row[6]})
        cur_id = row[2]  # 跟 parent_id 链(crossover 的 b 父在 meta,不追)
    return chain
