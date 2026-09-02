# evolve_loop + 8501 联调回执 · 2026-09-02

> 审:Lyra 拍"先做 evolve_loop(rounds=15) 自动循环,然后 8501/factory/task 联调一轮"(2026-09-02 02:15 PDT)
> 模式:本地代码 + 一次真 8501 LLM 联调(temp db,不碰生产 platform.db)。未碰冻结链/部署形态/密钥/local_gateway.py(只作客户端调 :8501/factory/task,未改 gateway)。
> 分支:`fix/alpha-factory-evolution`(续上一批进化层)
> 性质:内部落码回执(架构 + diff + 测试原文 + 联调证据)。无密钥/身份/store 正文/user 数据。若外发 review 区,按 `receipt-redaction.mdc` 复核(本件已无活体)。

---

## 0. 一句话

`evolve_loop(rounds=15)` 自动循环已落码(stub 测 18/18 PASS);真 8501/factory/task 联调一轮 PASS(qwen3.5-9b 经 gateway 产真因子,3086 字代码含 `def factor()`,draft 落 temp db)。

---

## 1. evolve_loop(rounds=N) 自动循环

**做什么**:QuantaAlpha 风格固定轮次循环。每轮:`evolve_factor`(bandit 选向 + mutation/crossover/propose 决策)→ `start_review`(异步线程)→ 轮询 jobs 表至 done → trajectory 自动落表(`_run_review_job` 末尾记)→ 汇总。

**实现**(`factory_pipeline.py`)
- `evolve_loop(rounds=15, test=False, budget_hint="std", poll_timeout=120.0, mutation_first=True, on_round=None)`
- `_poll_job_done(job_id, timeout, interval)`:轮询 jobs 表至 status=done 或超时
- 每轮捕获 outcome(passed/rejected/quarantine/dup_rejected/factory_error/review_timeout),记 `outcomes` Counter
- 追 best_reward/best_direction/best_traj_id;lineage 深度 = `trajectory_lineage` 链长
- `on_round` 回调:每轮注入进度(可接 UI/日志)
- 容错:`factory_task` 抛 `FactoryGridError` → 记 factory_error,不崩,继续下一轮

**返回汇总**
```python
{"rounds": 15, "outcomes": {"passed": N, "rejected": M, ...},
 "best_reward": 0.05, "best_direction": "momentum", "best_traj_id": 42,
 "lineage_depth": 3, "last_draft_id": 99}
```

**不做什么**
- 不自动 approve proposal(approval 仍由 Lyra 拍,`decide_proposal` 不变)
- 不破沙箱主权(metrics 仍由 `factor_sandbox` 算)
- 不破 GLM 编译闸(进化层只产 draft,落盘走既有 review→proposal 链)
- 不固定轮次硬跑到底:每轮独立,单轮失败不影响后续

---

## 2. 测试证据(stub)

### evolve_loop(18/18 PASS,含上一批 16 + 本批 2)
```
test_evolve_loop_15_rounds ... ok          (15 轮 stub,trajectory 落表,best_reward>0,lineage≥1)
test_evolve_loop_handles_factory_error ... ok   (factory_task 抛错 → factory_error,不崩,继续)
Ran 18 tests in 1.648s
OK
```

### 回归:sandbox 10/10 PASS(无回归)
```
Ran 10 tests in 0.761s
OK
```

---

## 3. 8501/factory/task 联调一轮(真 LLM)

**前置**:`curl http://127.0.0.1:8501/health` → `{"status":"ok","served_by":"gateway-v4.11","model":"qwen/qwen3.5-9b",...}` gateway 在(未重启,只作客户端调)。

**联调脚本**:`scripts/alpha_factory_8501_smoke.py`(temp db,`PLATFORM_DB_DIRECT_WRITE=1`,不碰生产 platform.db)

**联调结果**(原文)
```
=== 8501 联调:propose_factor(真 LLM) ===
PLATFORM_DB=/var/folders/.../tmpsg216m4o.db
WATCHLIST=AAPL,MSFT,NVDA,TSLA
[step1] propose_factor(idea='动量:过去5日收益截面排名', test=True) ...
[step1 OK] draft_id=1 status=draft route=local trace_id=061bd2db-8ef0-438f-8c73-b18d8553b1d6
  hypothesis: 动量因子捕捉价格惯性,短期(5 日)截面排名反映强者恒强特征,对流动性较好的资产在横截面上更显著;top 20% 做多旨在剔除近期弱势资产的尾部风险。
  code (前 400 字):
import pandas as pd
import numpy as np

def factor(df: pd.DataFrame) -> pd.Series:
    # meta: {name: "momentum_5d", hypothesis: "Top 20% of daily returns over the last 5 days drive alpha via price inertia", universe: "All symbols in df", cadence: "Daily"}
    df = df.sort_values(['symbol', 'ts']).reset_index(drop=True)
    ...
  code 长度: 3086
  含 def factor: True
[联调结论] PASS — 真 8501 LLM propose 路径通,draft 落表,code 含 factor()
```

**联调要点**
- 真 LLM(qwen3.5-9b 经 gateway :8501/factory/task)产了真因子:3086 字代码,含 `def factor(df: pd.DataFrame) -> pd.Series`,用 pandas/numpy,带 meta 块(name="momentum_5d")
- route=`local`(本地 substrate),trace_id 落表,draft 落 temp db
- 耗时 ~197s(真 LLM 推理,符合预期)
- hypothesis 是中文动量假设,LLM 解读职权内(不含数值结论)
- **未碰生产 platform.db**(temp db);**未改 gateway**(只作客户端调);**未重启 gateway**

---

## 4. 改了哪些文件

| 文件 | 改动 |
|---|---|
| `alpha-platform/backend/factory_pipeline.py` | +`_poll_job_done()`;+`evolve_loop(rounds, test, budget_hint, poll_timeout, mutation_first, on_round)`;+`from typing import Callable` |
| `alpha-platform/backend/test_factor_evolution.py` | +`EvolveLoopTest`(2 测:15 轮 stub + factory_error 容错) |
| `scripts/alpha_factory_8501_smoke.py` | **新增**:8501 联调一次性脚本(temp db,真 propose) |

---

## 5. 红线边界(本批守住)

| 红线 | 本批 |
|---|---|
| R3 密钥 | 未碰;联调走 gateway 既有 grid_verification 签名,未读/未传密钥 |
| R5 部署形态 | 未碰;未重启/未改 gateway;只作客户端调 :8501/factory/task |
| 冻结链 | 未碰 `local_gateway.py` / `:8501` handler / `grid_infrastructure_lock.json` |
| 沙箱主权 | metrics 仍由 `factor_sandbox` 算;LLM 输出不进 metrics(上批 `test_sandbox_sovereignty_not_broken` 验) |
| GLM 编译闸 | evolve_loop 只产 draft;落盘走既有 review→proposal 链;未旁路 |
| 生产 db | 联调用 temp db;`PLATFORM_DB_DIRECT_WRITE=1` 仅 temp;未碰 `/data/platform.db` |

---

## 6. 诚实记账

1. **联调只跑 propose,未跑 review**:真 review 需 bars 数据(temp db 无 bars);沙箱 review 路径已由 stub 测覆盖。真 propose→review 闭环需先灌 bars(Alpaca)或接生产 db(红线,需 Lyra 拍)。
2. **联调 route=local**:用本地 qwen3.5-9b;未触发 glm52_cloud 升级路径(需 gateway force_cloud 解锁,未碰)。
3. **evolve_loop 真跑未做**:真 15 轮 evolve_loop 需 15×~200s ≈ 50min + 真 review 需 bars;本批只做 1 轮真 propose + stub 15 轮。真 evolve_loop 跑需 Lyra 拍(时间 + 可能 cloud 成本)。
4. **未做因子-模型联合优化**:RD-Agent(Q) 联合优化仍未做(立项书外)。

---

## 7. 自检

- [x] 清单全覆盖:evolve_loop(rounds=15) 落码 + 8501 联调一轮
- [x] 自动自检已跑:evolve_loop 18/18 PASS + sandbox 10/10 回归 + 8501 真联调 PASS
- [x] 复发封堵:evolve_loop 单轮失败不崩(factory_error/review_timeout 容错);沙箱主权断言在
- [x] 可证明证据:贴测试输出原文 + 8501 联调原文(code/hypothesis/trace_id)
- [x] 无回归:sandbox 10/10、evolution 18/18
- [x] 未碰冻结链/部署形态/密钥/生产 db/local_gateway.py
- [x] 未宣称"全闭环可用":真 evolve_loop 真跑 + 真 review 闭环待 Lyra 拍(需 bars/时间/可能 cloud 成本)

—— 戌,2026-09-02 PDT(evolve_loop + 8501 联调)
