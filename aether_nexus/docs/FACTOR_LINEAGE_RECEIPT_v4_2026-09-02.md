# FACTORY LINEAGE STEP0-3 收口回执 · 2026-09-02

砥 2026-09-02 指令(顺序 0→1→2→3,每步一 commit + 处决案)。全部完成。

## commits

| step | commit | 标题 |
|----|----|----|
| 0 | d3d9b17 | factory: FMP key 出日志(httpx INFO 静默 · P0) |
| 1 | b4f85ae | factory: lineage 接入点 3 收口(symbols_cap + 安全闸/评估双段 + queue 死锁修) |
| 2 | f554e5e | factory: lineage dup 分支(record_dead_proposal) |
| 3 | 7f0a00a | factory: lineage evolve_factor 接入(mutation/crossover parent_ids 解析为 lineage id) |

分支:`fix/alpha-factory-evolution`。pre-commit P0 静态闸全绿(local_gateway redline / grid infrastructure lock / grid chain integrity / b11 gateway default)。

## step 0 · FMP_API_KEY 出日志(P0)

`factor_truth.py` / `worker.py` / `grid_factory_client.py` 三处 httpx 入口加 `logging.getLogger("httpx").setLevel(logging.WARNING)`(httpx INFO 会把含 `apikey=` 的 URL 整行打出)。

`rg -c "apikey=" <所有 *.log>`:0(alpha-platform/data/*.log 全 0,无持久化泄漏)。前次泄漏为 httpx INFO 透传 stdout(瞬态),已封。key 换不换是 Lyra 的决定,未动 key。

## step 1 · 接入点 3 收口(symbols_cap + 安全闸/评估双段 + queue 死锁修)

**factor_sandbox.run_factor_review** 加 `symbols_cap`(默认 8)+ `timeout` 参数;row_limit 随 cap 缩放 `max(8000, cap*400)`(cap 8→8000 不变;cap 500→200000 让评估段拿足天数)。

**queue 死锁修(关键)**:原 `p.join(timeout)` 再 `q.get()`——`return_frame=True` 时 worker `q.put` 大 DataFrame 撑爆 OS pipe 缓冲(~16-64KB),worker 阻塞 q.put、parent 阻塞 join → 死锁超时。改并发排空 queue(`q.get` 带超时轮询 + `p.is_alive` 探活),拿到即返。in-process 计 0.01s;30 symbol×120 天 3565 行修复后 0.6s 返(修前 20s+ 超时)。

**factory_pipeline._run_review_job pass 路径拆两段**:
- 安全闸 `run_factor_review(code, db, watchlist)` cap 8 不要 frame(沙箱校验,失败走原 fail 路径);
- 评估段(仅 GLM pass)`run_factor_review(code, db, universe_symbols, symbols_cap=FACTOR_EVAL_SYMBOLS 默认 500, return_frame=True, timeout=FACTOR_EVAL_TIMEOUT 默认 120)`。超时/失败不算沙箱失败(安全闸已过)→ `record_eval verdict=insufficient reason="eval timeout"`,review 仍 pass。
- `universe_symbols = factor_truth.load_sp500_symbols()`。`IC_MIN_NAMES` 生产值 20 不动。
- 加 `import os`(eval 段读 env)。

**处决案 h**(真 sp500 501 symbol 列表 + 30 symbol 合成 bars,默认 IC_MIN_NAMES=20):
```
propose draft=1 lineage=1
review job=1 status=done
evals: id=1 n_obs=114 settlement=close_to_close verdict=reject ic=-0.0158 t=-1.006
names_avg(IE 重算)=29.96  n_obs_check=115
h_evals_one_row: OK  h_nobs_ge_60: OK  h_names_avg_ge_20: OK
h_settlement_close_to_close: OK  h_verdict_in_set: OK  → ALL PASS
```
lineage show:#1 status=sandbox_ok,sandbox ok=1 receipt=factor_reviews:1,evals 1 行。
回归:test_factor_evolution 18/18、FL selftest 10/10、ic_eval selftest PASS。

## step 2 · dup 分支(record_dead_proposal)

`propose_factor` dup_rejected 分支(factor_dedup 命中、match_id 非空)在 `record_dup_rejected + c.commit()` 后加 `FL.record_dead_proposal(code, name, "llm", proposer, reason=f"dup of draft {match_id}")`。

**处决案 i**(同 code 提案两次):
```
第一次 propose draft=1 lineage=1 status=proposed
第二次 propose draft=2 status=dup_rejected match_id=1 dup_rejected=True
第二次 lineage: id=1 status=proposed reuse_count=1 reject_reason=''
i_dup_branch_taken: OK  i_reuse_incremented: OK
i_known_FL_dedup_status_unchanged: OK  i_known_FL_dedup_reason_empty: OK → ALL PASS
```

**FL dedup 设计冲突(已报 Lyra 定案)**:`record_dead_proposal` 同 expr 已存在只 reuse+1、不改状态、不存 reason(砥写的 FL docstring「同表达式已存在 → 只 reuse+1,不改其状态」)。第一次 propose(带 hypothesis)已建 lineage status=proposed,第二次 record_dead_proposal 命中同 expr 返回旧 id 不翻 rejected、reject_reason 空。**Lyra 2026-09-02 定案:接受 FL dedup 现状**,处决案 i 放宽为「dup 分支命中 + reuse+1」(status/reason 不翻为已知 FL 设计,不计失败)。若要 dup 翻 rejected,需改 FL.record_dead_proposal(砥出 diff)或 dup 分支额外调 FL.reject——均待砥定案,本 commit 不动 FL。

## step 3 · evolve_factor lineage(mutation/crossover parent_ids 解析为 lineage id)

`evolve_factor` 主分支 draft 落库后加 lineage 接入(接入点 1 同段):
- `origin = _evolve_origin(meta_json) or "llm"`;`decision.origin ∈ {mutation,crossover,propose}`,FL ORIGINS 不含 "propose"(fresh direction 走 LLM)→映射 "propose"→"llm"。
- `parent_ids` 需 FL factor id(非 trajectory id)——`FL.lineage` 按 parent_ids 递归 `SELECT * FROM factors WHERE id=?`,trajectory id 解析不到祖先。故从 `decision.parent_id` / `crossover_parent_b`(trajectory id)→ `factor_trajectories.draft_id` → `factor_drafts.lineage_id` 解析(砥要「dashboard 链能显示祖先」)。
- hypothesis 空 → `record_dead_proposal`。
- 加 `_ensure_lineage_column`(evolve_factor 原未调,fresh DB 缺列 → OperationalError)。
- 返回 dict 加 `lineage_id`。

**处决案 j**(父 propose → seed rejected trajectory → evolve_factor mutation):
```
父 propose draft=1 lineage=1 status=proposed
seeded rejected trajectory: recent_rejected=1 条
子 evolve draft=2 origin=mutation lineage=2
子 lineage parent_ids=[1] ancestors=[1]
j_origin_mutation: OK  j_child_lineage_parent_ids_eq_parent_lid: OK
j_ancestors_include_parent: OK → ALL PASS
```
注:dashboard board 只列有 evals(n_obs≥MIN_N)的因子,子刚 propose 未 review → 不在 board(预期);砥要的「链能显示祖先」由 lineage ancestors 验,通过。

**偏离砥字面**:砥说「parent=_evolve_parent」,但 `_evolve_parent` 返回 `evolve_parent_id`(trajectory id),`FL.lineage` 解析不到祖先。本 commit 改为从 trajectory→draft→lineage 解析 parent lineage id。若砥要 trajectory id 作 parent_ids,回退本段即可。

回归:test_factor_evolution 18/18(2 次稳定)。

## 待砥定案

1. **dup 翻 rejected**:FL dedup 现状下 record_dead_proposal 不翻状态/不存 reason。选项:(a) 改 FL.record_dead_proposal 存在 expr 也置 rejected+存 reason(砥出 FL diff);(b) dup 分支额外调 FL.reject(lineage_id, ...);(c) 维持现状(Lyra 已选 c)。
2. **evolve_factor parent_ids**:本 commit 用 lineage id(祖先链可解析)。若砥要 trajectory id,回退 step 3 该段。
3. **LIMIT 8000 生产约束**:eval 段 cap 500 → row_limit 200000,需 bars 表有足量历史(≥60 交易日 × ≥20 symbol)。生产 FMP/Alpaca 灌 bars 后处决案 h 可复跑验。
