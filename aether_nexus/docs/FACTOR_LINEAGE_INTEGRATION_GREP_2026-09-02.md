# factor_lineage v1.1 + ic_eval v1 · 接入点 grep 回执 · 2026-09-02

> 致砥。戌落码 + grep,接入 diff 待砥出(戌不自行挂)。
> 源文件(Lyra iCloud):`factor lineage v1 1.py`、`ic eval v1.py`。
> 本回执贴三行(propose_factor 签名 / metrics dict 键名 / 沙箱结果写入行)+ 两坑定案 + IC 天数问题答复。

---

## 0. 文件落位 + selftest(已执行)

| 文件 | 落位 | 字节 | selftest |
|---|---|---|---|
| `factor_lineage_v1_1.py`(替换旧 v1) | `alpha-platform/backend/factor_lineage_v1_1.py` | 19162 | **PASS 10/10**(`MAX_LIVE=12, MIN_N=60`) |
| `ic_eval_v1.py`(新) | `alpha-platform/backend/ic_eval_v1.py` | 13494 | **PASS**(oracle ic=1.000 t=inf / noise ic=-0.005 t=-0.52 / n=195 days) |

- 旧 `factor_lineage_v1.py` 已删(v1_1 替换)。
- `ic_eval_v1.py` 内 `import factor_lineage_v1_1 as FL`,模块名对齐。
- 库路径:`FACTOR_LINEAGE_DB` 默认 `./state/factor_lineage.db`;`alpha-platform/.gitignore` 已含 `*.db`(line 4,无前导斜线→覆盖 `backend/state/factor_lineage.db`),无需改 .gitignore。
- 零新依赖(sqlite3 + 标准库),零链上写。

---

## 1. 两坑定案(砥拍)

### 坑 1:hypothesis 空 → 不回退、不跳过,记账即死

- 定案:hypothesis 为空时调 `FL.record_dead_proposal(expr, name, origin, proposer)`,记账并直接判死(status='rejected',进死枝,不占预算,不上榜)。
- v1_1 已落:`record_dead_proposal(expr, name, origin, proposer, reason="无经济含义(hypothesis 为空)", universe="", con=None) -> int`(v1_1 line 145-162)。同表达式已存在 → 只 reuse+1,不改其状态。selftest 第 10 条覆盖。
- 接入点:`propose_factor` 内,`hypothesis` 为空分支 → 调 `record_dead_proposal`,**不**调 `propose`(propose 会因 econ_rationale 空抛 LineageError)。

### 坑 2:ic_std + 评估天数 n

- 砥定:`ic_std = ic/ir(ir 非零),否则 None`——**仅当走 factor_sandbox 路径时**。
- **ic_eval_v1 有真 ic_std**(每日 IC 的 std,`summarize` line 117-124),不需 `ic/ir` 反推。
- 关键:见下节"IC 天数问题"。

---

## 2. IC 天数问题答复(砥第 2 问,先答)

**问:metrics 有没有评估天数 n?没有 n,evals 的 n_obs 填不出来,insufficient 判不了。**

**答:factor_sandbox 没有;ic_eval_v1 有。**

| 评估器 | n_obs 语义 | ic_std | settlement |
|---|---|---|---|
| `factor_sandbox.run_factor_review`(当前 pipeline 用) | `len(work)` = **symbol×date 总行数,非天数** | 无(只有 `ic`+`ir`) | 无 |
| `ic_eval_v1.summarize`(砥新给) | `len(ics)` = **交易天数**(每日一条 IC) | **真 ic_std**(每日 IC 的 std) | `"close_to_close"`(写死) |

**结论与建议:**
- 当前 `_run_review_job` 走 `factor_sandbox.run_factor_review`,其 `metrics["n_obs"]` 是行数(symbol×date),填进 lineage `evals.n_obs` 会让 insufficient 判错(行数≥60 但天数可能<60)。
- **IC 出数接入点(接入点 3)应调 `ic_eval_v1.evaluate(bars, factor, horizon)` → `ic_eval_v1.write_lineage(summary, lineage_id, receipt_path, verdict, reason)`**,不是拿 factor_sandbox metrics 凑。
- `factor_sandbox` 留给沙箱安全/AST 闸(接入点 2 `record_sandbox`),IC 评估(接入点 3 `record_eval`)走 ic_eval_v1。
- `ic_eval_v1.write_lineage` 已映射到 `FL.record_eval(lineage_id, summary["first"], summary["last"], f"{horizon}d", summary["n_obs"], summary["ic_mean"], summary["ic_std"], "close_to_close", None, receipt_path, verdict, reason)`——天数/真 ic_std/settlement 一次齐。
- **注意**:factor 接口不同——factor_sandbox 是 `def factor(df: pd.DataFrame) -> pd.Series`;ic_eval_v1 是 `factor(bars: dict[symbol -> list[(date,o,h,l,c,v)]) -> dict[(date,symbol) -> float]`。接入 diff 须做一次接口适配(把 LLM 产的 `code` 在 factor_sandbox 跑安全闸,在 ic_eval_v1 跑 IC 评估),或由 diff 定适配层。

---

## 3. 三行(给 diff 用)

### 3.1 propose_factor 签名(接入点 1)

```48:48:alpha-platform/backend/factory_pipeline.py
def propose_factor(idea: str, *, test: bool = False, budget_hint: str = "std") -> dict[str, Any]:
```

内部变量(接入点 1 用):
- `code`(line 79)= `resp.get("code")` → 因子表达式/代码
- `name`(line 81)= `_extract_name(code, hypothesis)`
- `hypothesis`(line 80)= `resp.get("hypothesis")` → 经济含义(空 → 走 record_dead_proposal)
- `draft_id = cur.lastrowid`(line 140,`INSERT INTO factor_drafts` 后)
- origin:新提="llm";evolve 走 `_evolve_origin(meta_raw)`;parent:`_evolve_parent(meta_raw)`(新提=[]);proposer:`resp.get("substrate")` 或 meta `"author":"grid-extended"`(line 121)

### 3.2 metrics dict 键名(接入点 3 用)

**factor_sandbox.run_factor_review 返回**(`factor_sandbox.py:343-351`):

```343:343:alpha-platform/backend/factor_sandbox.py
            "ic": round(ic, 6),
            "ir": round(ir, 6),
            "quintile_spread": ...,
            "turnover_proxy": ...,
            "n_obs": int(len(work)),          # ← 行数,非天数
            "symbols": len(work["symbol"].unique()),
            "data_window": {"from_ts": int(...), "to_ts": int(...)},
            "computed_by": "alpha-platform/factor_sandbox",
            "computed_at": int(time.time()),
```

**ic_eval_v1.summarize 返回**(砥新给,接入点 3 应走这条):
`n_obs`(=天数)、`ic_mean`、`ic_std`(真)、`ic_t`、`ir`、`hit`、`roll20`、`first`、`last`、`names_avg`、`horizon`

### 3.3 沙箱结果写入行(接入点 2 用)

两条路径(`factory_pipeline.py` `_run_review_job`):

**fail 路径**(line 309-316):

```309:309:alpha-platform/backend/factory_pipeline.py
            write_rejection_record(    # → 返回 Path = L0_REJECTION_DIR/{day}.jsonl
                draft_id=draft_id, review_id=None, glm_code=glm_original,
                rejection_error=err, rejection_detail=reject_detail,
                note="L0 sandbox rejection during review",
            )
```

**pass 路径**(line 410-421):

```410:410:alpha-platform/backend/factory_pipeline.py
        rev = c.execute(
            "INSERT INTO factor_reviews(draft_id, job_id, created, status, metrics, grid_explain, error, "
            "code_source, lane, quarantine) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ...
        )
        review_id = rev.lastrowid   # line 421 — pass 路径收据 id
```

**收据路径汇总:**
- fail = `write_rejection_record(...)` 返回 `Path`(`l0_runner.py:147` `-> Path`,值 = `L0_REJECTION_DIR/{day}.jsonl`,默认 `$PLATFORM_DB.parent/store/l0_rejections/`)
- pass = `review_id`(`factor_reviews` 表 id,line 421)

---

## 4. 三个接入点(真实变量名,给 diff)

| 接入点 | 位置 | 表达式变量 | 名称 | 经济含义 | origin/parent/proposer | ok/error | receipt_path | IC 变量 |
|---|---|---|---|---|---|---|---|---|
| **1 propose** | `propose_factor` line 127-140(INSERT factor_drafts 后) | `code` | `name` | `hypothesis`(空→record_dead_proposal) | origin:新提="llm"/evolve=`_evolve_origin`;parent=`_evolve_parent`(新提=[]);proposer=`resp.get("substrate")`或"grid-extended" | — | — | — |
| **2 sandbox** | `_run_review_job` line 303/305-356 | — | — | — | — | ok=无异常;fail=`SandboxError`;error=`err`(line 306) | fail=`write_rejection_record` 返回 Path;pass=`review_id`(line 421) | — |
| **3 IC 出数** | `_run_review_job` line 303 后 | — | — | — | — | — | pass=`review_id` | **走 ic_eval_v1**:`ic_mean`=`summary["ic_mean"]`;`ic_std`=`summary["ic_std"]`(真);`n_obs`=`summary["n_obs"]`(天);`settlement`="close_to_close";`window`=`summary["first"]/["last"]`;`horizon`=`f"{horizon}d"`;`verdict`=`auto_verdict(s)`;`receipt_path`=`review_id` |

---

## 5. 待砥 diff 的开放点

1. **接口适配**:factor_sandbox 接口 `factor(df)->pd.Series` vs ic_eval_v1 接口 `factor(bars)->dict[(date,symbol)->float]`。接入点 3 须把 LLM 产的 `code` 在两处分别跑(沙箱安全闸 + IC 评估),或加一层 bars↔df 适配。砥定。
2. **接入点 3 触发时机**:是在 `_run_review_job` pass 后立即跑 ic_eval,还是异步另起一个 eval job?砥定。
3. **receipt_path 统一**:fail 用 jsonl Path,pass 用 review_id(数字)。lineage `receipt_path` 字段是 TEXT,两种异构——diff 须统一(都转 str)。
4. **horizon 默认值**:ic_eval_v1 `--horizon` 默认 5;lineage `evals.horizon` 是 TEXT。砥定默认 horizon。

---

## 6. 状态

- ✅ 两文件已落位 + selftest 绿(10/10 + PASS)
- ✅ 两坑定案已落进 v1_1(record_dead_proposal)+ ic_eval_v1(真 ic_std + 天数 n_obs)
- ✅ IC 天数问题已答(factor_sandbox 无,ic_eval_v1 有)
- ✅ 三行已贴(propose_factor 签名 / metrics 键名 / 沙箱写入行)
- ⏸ 接入 diff 待砥出(戌不自行挂)

---

戌,2026-09-02。本回执不替代红线;接入 diff 未出前不挂代码。
