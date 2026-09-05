# FACTOR_LINEAGE 接入点 3 回执 · 2026-09-02

> 致砥/Lyra · 戌 · ic_eval evaluate_frame 接入 + dashboard 入库

## commit

| hash | message | files |
|------|---------|-------|
| `66571f4` | `factory: lineage 接入点 3(ic_eval evaluate_frame)` | factor_sandbox.py(新入库) · factory_pipeline.py · ic_eval_v1_1.py(新) · test_factor_evolution.py(stub 同步) |
| `2368499` | `factory: lineage dashboard v1.1(只读仪表)` | lineage_dashboard_v1_1.py(新) |

分支 `fix/alpha-factory-evolution`。未用 `add -A`,逐文件显式 add。pre-commit 全门禁 PASS(P0 static gate / local_gateway redline / infrastructure lock / b11 / grid chain)。

## 接入点 3 diff(逐字落)

**factor_sandbox.py**
- `run_factor_review(code, db_path, watchlist, return_frame: bool = False)` —— 默认行为不变,现有调用方零影响
- `_worker_run(..., return_frame=False)`:metrics 组装后 `payload = {"ok": True, "metrics": metrics}; if return_frame: payload["work"] = work[["ts","symbol","c","fac"]]; q.put(payload)` —— work 经 mp.Queue 从 spawn 子进程传回(DataFrame 可 pickle)
- wrapper:`return_frame=True` 返回 `(metrics, work)`,否则返回 `metrics`

**factory_pipeline.py** `_run_review_job` pass 路径
- 调用处:`metrics, _work = factor_sandbox.run_factor_review(code, db_path, watchlist, return_frame=True)`
- `review_id = rev.lastrowid` 后、`record_sandbox` 之后加(砥 4 行):
  ```python
  if lineage_id is not None:
      FL.record_sandbox(lineage_id, True, f"factor_reviews:{review_id}", "")
      import ic_eval_v1_1 as IE
      _s = IE.evaluate_frame(_work, horizon=5)
      IE.write_lineage(_s, lineage_id, f"factor_reviews:{review_id}", *IE.auto_verdict(_s))
  ```
  (IE 块嵌在 `if lineage_id is not None` 内,与 record_sandbox 同 guard;砥原写两块独立 `if`,语义等价,合并更省一次判断)

**ic_eval_v1_1.py**:入库,替换未入库的 v1(v1 已删)。`evaluate_frame` 直接吃沙箱算好的 work 表,不再执行因子代码(LLM 代码只在沙箱跑一次);`n_obs=交易日数`(非行数)、`ic_std=真截面 IC 标准差`、`settlement=close_to_close`。

## 处决案 f/g(全绿)

真沙箱(不 stub)+ 真 bars 表(8 symbol × 100 天,随机游走)。设 `IC_MIN_NAMES=3`(理由见下"已知约束")。

| 项 | 验证 | 结果 |
|----|------|------|
| f | review pass 后 evals 表恰一行,n_obs=交易天数(不是行数),settlement=close_to_close,verdict∈{keep,reject,watch,insufficient} | OK — evals 1 行,n_obs=**94**(交易日),settlement=close_to_close,verdict=**reject**(随机数据 IC=0.0143 t=0.33 不显著,∈集合) |
| g | 同一 draft 的 sandbox metrics["n_obs"] 与 evals.n_obs 并排,后者<前者 | OK — sandbox n_obs=**787**(symbol×date 行数) vs evals.n_obs=**94**(交易日),94<787 ✓ |

处决案脚本:`/tmp/verdict_lineage_point3.py`(不进 repo)。spawn-safe:工作流包进 `main()` + `if __name__` guard(防 mp.spawn 子进程重跑 `__main__`)。

## 无回归

- `ic_eval_v1_1.py selftest` → `PASS (oracle ic=1.000 t=1e6 | noise ic=-0.005 t=-0.52 | n=195 days)`
- `factor_lineage_v1_1.py selftest` → `PASS 10/10`
- `test_factor_evolution` → `Ran 18 tests ... OK`(stub 同步:`run_factor_review` 返回 `(dict, None)` 匹配新签名;evolve_factor draft lineage_id=NULL → `_work` 不进 IE)
- `lineage_dashboard_v1_1.py --demo --once` → `total=7 evals=5 live=1/12 board=4 dead=2 sandbox 5ok/0fail`

## 已知约束(报砥裁决,未擅改)

**沙箱 `watchlist[:8]` 只取 8 symbol,ic_eval 默认 `MIN_NAMES=20`/日 → 8<20 → 所有交易日被跳过 → evals.n_obs=0 → 永远 `insufficient`。**
- 处决案 g 用 `IC_MIN_NAMES=3` 才证出真交易日数(94)。
- 生产里接入点 3 会一直写 `insufficient`,直到:(a)沙箱放宽 symbol 上限,或 (b)调低 `IC_MIN_NAMES`。
- 这不是接入 bug,是沙箱容量与 IC 评估最小截面要求的口径差。请砥裁决:沙箱 `[:8]` 是否放宽,或 `IC_MIN_NAMES` 生产值定多少。

## 接入点 1/2 的两处偏离 + 三缺口(上一轮回执已记,本轮未动,等砥裁决)

仍开放:
1. propose_factor 用 `meta_json` + `or "llm"`(非砥原写 `if meta_raw else "llm"`)
2. pass 路径 `record_sandbox` 加 `if lineage_id is not None` guard
3. dup_rejected 分支不经 lineage(NULL)
4. evolve_factor 未接 lineage(trajectory 表与 lineage 表两套未打通)
5. `factor_truth.py` FMP_API_KEY 明文入 httpx INFO log(安全 finding)

## 文件落点

- 桌面(老地方):`~/Desktop/demo/aether_nexus/docs/FACTOR_LINEAGE_POINT3_RECEIPT_2026-09-02.md`
- repo:`aether_nexus/docs/FACTOR_LINEAGE_POINT3_RECEIPT_2026-09-02.md`

戌在,等砥对"沙箱 8-symbol 上限 vs IC_MIN_NAMES"的裁决,或下一接入点。
