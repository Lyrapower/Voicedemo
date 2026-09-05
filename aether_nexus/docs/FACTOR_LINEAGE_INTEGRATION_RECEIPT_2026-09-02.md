# FACTOR_LINEAGE 接入点 1/2 回执 · 2026-09-02

> 致砥/Lyra · 戌 · factory_pipeline.py lineage 接入(接入点 1 propose + 接入点 2 sandbox)

## commit

`f85b205  factory: lineage 接入点 1/2(propose + sandbox)`  · 分支 `fix/alpha-factory-evolution`
2 files changed, 463 insertions(+), 3 deletions(-)
- `M  alpha-platform/backend/factory_pipeline.py`
- `A  alpha-platform/backend/factor_lineage_v1_1.py`(依赖,一并入库;`ic_eval_v1.py` 属接入点 3,未接,未入 commit)

未用 `git add -A`;仅显式 add 上述两文件。

## 接入点 1 · propose_factor

`draft_id = cur.lastrowid` 后插入:
```python
_origin = _evolve_origin(meta_json) or "llm"
_parents = _evolve_parent(meta_json) or []
_proposer = resp.get("substrate") or "grid-extended"
if (hypothesis or "").strip():
    lineage_id = FL.propose(code, name, _origin, _parents, _proposer, hypothesis, notes=f"draft_id={draft_id}")
else:
    lineage_id = FL.record_dead_proposal(code, name, _origin, _proposer)
c.execute("UPDATE factor_drafts SET lineage_id=? WHERE id=?", (lineage_id, draft_id))
```

## 接入点 2 · _run_review_job

- SELECT 加 `lineage_id`:`SELECT name, code, hypothesis, test, meta, lineage_id FROM factor_drafts WHERE id=?`
- fail 路径:`_p = write_rejection_record(...)`(接住返回值)→ `if lineage_id is not None: FL.record_sandbox(lineage_id, False, str(_p), err)`
- pass 路径:`review_id = rev.lastrowid` 后 → `if lineage_id is not None: FL.record_sandbox(lineage_id, True, f"factor_reviews:{review_id}", "")`

## 迁移

幂等 `_ensure_lineage_column(c)`:`PRAGMA table_info(factor_drafts)` guard + `ALTER TABLE factor_drafts ADD COLUMN lineage_id INTEGER`。在 propose_factor 与 _run_review_job 的 `ensure_l0_schema(c)` 后各调一次。
未改 `db.py` FACTORY_SCHEMA(砥 diff 文件范围只含 factory_pipeline.py);fresh DB 靠运行时 ALTER 兜底。如砥要让 fresh DB 建表即带 lineage_id,可后续在 db.py FACTORY_SCHEMA 加一列(单行),我未擅改。

## 偏离砥原 diff(已记,请砥裁决)

1. **`meta_raw` → `meta_json`**:propose_factor 作用域内无 `meta_raw` 变量(meta 是新建的 `meta_json`)。用 `meta_json` + `or "llm"` / `or []` fallback,同 `_run_review_job` 里 `_evolve_origin(meta_raw) or "propose"` 的惯例。砥原写 `if meta_raw else "llm"` 在 propose_factor 会因 `_evolve_origin` 返回 None 而把 `None` 传进 FL.propose → `LineageError(origin 不在 ORIGINS)`,故改。
2. **pass 路径加 `if lineage_id is not None` guard**:砥 diff 原写 1 行无 guard,但砥另文要求"为 NULL(旧草稿)则跳过两处调用"。故两处都加 guard(旧草稿 / dup_rejected / evolve_factor draft 的 lineage_id 为 NULL)。

## 处决案 a-e(全绿 11/11)

stub `factory_task`(propose/review_explain/fix_error)+ `factor_sandbox.run_factor_review`(fail=raise SandboxRejection / pass=返回 metrics),temp PLATFORM_DB + temp FACTOR_LINEAGE_DB。

| 项 | 验证 | 结果 |
|----|------|------|
| a | propose 带 hypothesis → `factor_drafts.lineage_id` 非空,`FL.lineage(id).factor.status='proposed'` | OK(draft=1 lineage=1 status=proposed) |
| b | propose 空 hypothesis → lineage status='rejected',dead 列表含它 | OK(draft=2 lineage=2 status=rejected, in_dead=True) |
| c | review fail → sandbox 表 ok=0,receipt_path 以 .jsonl 结尾 | OK(job=1 status=done, sandbox ok=0, receipt=.jsonl) |
| d | review pass → sandbox 表 ok=1,receipt_path 形如 factor_reviews:N | OK(draft=3 lineage=3 job=2 status=done, sandbox ok=1, receipt=factor_reviews:N) |
| e | `python3 factor_lineage_v1_1.py budget` 输出 live=0 | OK(`{"live": 0, "max_live": 12, "total": 0}`) |

处决案脚本:`/tmp/verdict_lineage_integration.py`(不进 repo,跑完即弃)。

## 无回归

- `factor_lineage_v1_1.py selftest` → `SELFTEST PASS 10/10 (MAX_LIVE=12, MIN_N=60)`
- `test_factor_evolution` → `Ran 18 tests ... OK`
- pre-commit 全绿:P0 static gate / local_gateway redline / infrastructure lock verify-runtime / b11 gateway / grid chain integrity

## 接入点 3 待砥(已 grep,贴回)

砥要的 grep:`rg -n 'work\b|work\[' factor_sandbox.py | head -30`

```
314:        work = df.copy()
315:        work["fac"] = pd.to_numeric(fac, errors="coerce")
316:        work = work.dropna(subset=["fac", "c"])
317:        work["fwd"] = work.groupby("symbol")["c"].pct_change().shift(-1)
318:        work = work.dropna(subset=["fwd"])
335:        work["rank"] = work.groupby("ts")["fac"].rank(pct=True)
336:        top = work[work["rank"] >= 0.8]["fwd"].mean()
337:        bot = work[work["rank"] <= 0.2]["fwd"].mean()
340:        turnover = float(work.groupby("symbol")["fac"].diff().abs().mean() / (work["fac"].abs().mean() + 1e-9))
347:            "n_obs": int(len(work)),
```

**结论**:
- `work` 是 `run_factor_review` 内部局部 DataFrame,**不返回**。
- 因子列名 = **`"fac"`**(`work["fac"] = pd.to_numeric(fac)`),不是 "factor"/"value"。
- `run_factor_review` 返回 metrics dict,keys:`ic` / `ir` / `quintile_spread` / `turnover_proxy` / `n_obs` / `symbols` / `data_window` / `computed_by` / `computed_at`。
- **无"评估天数 n"**:`metrics["n_obs"] = int(len(work))` = symbol×date 行数,**非交易日**。
- → 印证接入点 3(`record_eval`)的 `n_obs` / `ic_std` / `settlement` 必须由 `ic_eval_v1.evaluate` 算(交易日 n + 真 ic_std + close_to_close),不能用 sandbox 的 `n_obs`。`ic_eval_v1.summarize` 的 `n_obs` 才是交易日数。

## 已知缺口(未接,报砥)

- **dup_rejected 分支不经 lineage**:propose_factor 的 `factor_dedup.check_duplicate_or_none` 命中时走 `record_dup_rejected` 提前 return,不经接入点 1 → dup draft 的 `lineage_id` 为 NULL。处决案 d 初版撞此(case d 复用 case a 的 code → dup → lineage None)。砥 diff 只指明主 propose 路径,故未补;若要 dup 也记 dead/复用,需另加一行。请砥裁决。
- **evolve_factor 未接 lineage**:砥 diff 接入点 1 只指 propose_factor。evolve_factor(mutation/crossover/direction)产 draft 但不经 lineage 记录 → 这些 draft 的 `lineage_id` NULL,review 时 sandbox 表也不记。trajectory 表(factor_evolution)与 lineage 表(FL)目前是两套,未打通。请砥裁决是否要接 evolve_factor。
- **`factor_truth.py` FMP_API_KEY 明文入 httpx INFO log**(本会话早先发现,未在本次范围):`HTTP Request: GET ...apikey=...`。安全 finding,待修。
