# Alpha Factory 进化层落码回执 · QuantaAlpha trajectory + RD-Agent(Q) bandit · 2026-09-02

> 审:Lyra 拍"先做一(QuantaAlpha trajectory mutation/crossover),然后接 RD-Agent(Q) bandit 调度,完成后冒烟测试"(2026-09-02 02:03 PDT)
> 模式:本地代码改动,纯 additive,未碰冻结链/部署形态/密钥/local_gateway.py。
> 分支:`fix/alpha-factory-evolution`
> 性质:内部落码回执(架构骨架 + diff 要点 + 测试原文)。无密钥/身份/store 正文/user 数据。若外发 review 区,按 `receipt-redaction.mdc` 复核(本件已无活体)。

---

## 0. 一句话

Alpha Factory 因子挖掘从"单 shot + 一轮 fix"升级为 **trajectory 级 mutation + crossover + bandit 选向**:复用验证过的 trajectory(失败的重写 code、高 reward 的重组),bandit(UCB)替代"每次从零 propose"。沙箱主权 + GLM 编译闸不变。16/16 新测 + 全回归绿。

---

## 1. 借鉴与对齐

| 来源 | 借鉴点 | 本地落码 |
|---|---|---|
| **QuantaAlpha** | trajectory = 一次完整 propose→review 的可复用单元 | `factor_trajectories` 表 |
| QuantaAlpha | mutation:定位失败步,只重写失败段,前缀(hypothesis)冻结 | `mutate` prompt + `decide_evolve` mutation 优先 |
| QuantaAlpha | crossover:重组两个高 reward 父的互补段 | `crossover` prompt + `top_trajectories` 父池 |
| QuantaAlpha | RankIC 贪心选 → reward = \|IC\| | `compute_reward` |
| **RD-Agent(Q)** | multi-armed bandit 调度(UCB)选向 | `ucb_select`(UCB1:exploit + explore) |
| RD-Agent(Q) | 知识库复用(验证过的 pattern) | `top_trajectories` 作 crossover 父 + `direction` few-shot |

**未借鉴(诚实记账)**:
- QuantaAlpha 的 15 轮固定迭代 → 本地是按需触发(evolve_factor 调一次进一轮),未做固定轮次循环(可后续加)。
- RD-Agent(Q) 的因子-模型联合优化 → 本地只挖因子,模型固定(立项书 Phase 4/5 之外,未做)。
- QuantaAlpha 的语义一致 + 结构约束(anti-crowding)→ 本地用既有 `factor_dedup` AST 指纹去重,未加语义级约束。

---

## 2. 改了哪些文件

| 文件 | 改动 |
|---|---|
| `alpha-platform/backend/factor_evolution.py` | **新增**:trajectory schema(`factor_trajectories` 表)+ reward + record/query + bandit UCB + `decide_evolve` 决策序 + lineage 追溯 |
| `alpha-platform/backend/factory_prompts.py` | +`import json`;+`mutate`/`crossover`/`direction` 三个 prompt kind |
| `alpha-platform/backend/factory_pipeline.py` | +`import factor_dedup`/`factor_evolution`;+`evolve_factor()` 入口;+`_record_trajectory_for_draft()`;+`_evolve_origin/direction/parent/crossover_b` 四个 meta 提取 helper;`_run_review_job` 三条路径(rejected/quarantine/passed)末尾各记一条 trajectory |
| `alpha-platform/backend/test_factor_evolution.py` | **新增**:16 测(trajectory store 5 + bandit 3 + prompt 4 + 端到端冒烟 4) |

---

## 3. 架构要点

### 3.1 trajectory = 可复用单元
```
factor_trajectories(id, created, draft_id, review_id, hypothesis, code, metrics,
  outcome, reward, ic, ir, fingerprint, origin, direction, parent_id,
  crossover_parent_b, code_source, meta)
```
- `outcome` ∈ {passed, rejected, quarantine, dup_rejected, failed}
- `origin` ∈ {propose, mutation, crossover}(lineage 标签)
- `parent_id` / `crossover_parent_b`:进化 lineage(mutation 跟 parent_id 链,crossover 双父)
- `reward` = |IC|(passed)/ 0(其余);`ir` 作 tiebreak

### 3.2 进化决策序(`decide_evolve`)
1. **mutation 优先**(可调):最近 rejected trajectory(有 rejection_error)→ 只重写失败 code,hypothesis 冻结
2. **crossover**:≥2 高 reward 父 → 重组 A 的假设结构 + B 的构造 pattern
3. **propose**(bandit 选向):UCB1 选 arm → fresh propose + top 知识作 few-shot

### 3.3 bandit(UCB1)
- arm = 方向集(momentum/mean_reversion/volume/volatility/overnight_gap/earnings_drift/breadth/cross_sectional),env `FACTORY_DIRECTIONS` 可覆盖
- `ucb_select`:未试 arm 给探索 bonus;已试 arm = mean + c·√(ln(N_total)/n_arm)
- 选向后产 draft → 走既有 `start_review` 链(沙箱 + GLM 编译闸不变)
- trajectory 落表时 `update_arm` 记 bandit health

### 3.4 沙箱主权 + GLM 编译闸(不破)
- metrics 仍由 `factor_sandbox.run_factor_review` 确定性算,**LLM 输出永不进 metrics dict**(`test_sandbox_sovereignty_not_broken` 验证)
- 进化层只产 draft;落盘仍走既有 `propose_factor` → `start_review` → review → proposal 链
- `mark_verified` VERIFIED 唯一路径不变;未碰 `local_gateway.py` / `:8501` / 冻结 manifest

---

## 4. 测试证据(原文)

### 进化 + 冒烟(16/16 PASS)
```
test_reward_passed_uses_abs_ic ... ok
test_reward_negative_ic_still_abs ... ok
test_reward_rejected_is_zero ... ok
test_record_and_top_trajectories ... ok
test_lineage_chain ... ok
test_untried_arms_explored_first ... ok
test_exploit_after_data ... ok          (momentum 高 reward → UCB 选 momentum 多数)
test_forced_direction_overrides_bandit ... ok
test_mutate_prompt_has_parent_code_and_frozen_hypothesis ... ok
test_crossover_prompt_has_both_parents ... ok
test_direction_prompt_has_direction_and_fewshot ... ok
test_parse_factory_result_extracts_code_and_hypothesis ... ok
test_evolve_factor_propose_origin_records_trajectory ... ok   (端到端:evolve→review→trajectory 落表)
test_mutation_after_rejected_trajectory ... ok              (有 rejected → 选 mutation)
test_crossover_after_two_passed_trajectories ... ok          (≥2 高 reward → 选 crossover)
test_sandbox_sovereignty_not_broken ... ok                   (metrics 由沙箱算,无 LLM 输出)
Ran 16 tests in 2.533s
OK
```

### 回归(全绿,无回归)
```
factory sandbox(既有): Ran 10 tests in 0.809s  OK
RWA reader(Phase 1-3): ✓ v5 / ✓ phase2 / ✓ phase1 / ✓ phase1+3
provenance grade(Phase 3): Ran 9 tests  OK
harness enforcement: 7/7 PASS
```

---

## 5. 红线边界(本批守住)

| 红线 | 本批 |
|---|---|
| R3 密钥 | 未碰;无钱包/上链 |
| R5 部署形态 | 未碰;无 Docker/端口/绑定改动;纯 backend 模块 |
| 冻结链 | 未碰 `local_gateway.py` / `:8501` / `grid_infrastructure_lock.json` |
| 沙箱主权 | metrics 仍由 `factor_sandbox` 算;LLM 输出不进 metrics(`test_sandbox_sovereignty_not_broken` 验) |
| GLM 编译闸 | 进化层只产 draft;落盘仍走既有 review→proposal 链;未旁路 |
| VERIFIED 路径 | `mark_verified()` 仍是唯一来源;未改 |
| additive | 未改 `factor_sandbox`/`l0_runner`/`factor_dedup`/`grid_factory_client` 既有逻辑;只加新模块 + 新入口 + review 末尾记 trajectory |

---

## 6. 诚实记账(本批没做的)

1. **未做固定轮次循环**:QuantaAlpha 跑 15 轮迭代;本地是 `evolve_factor` 调一次进一轮,未做"自动跑 N 轮"的循环(可后续加 `evolve_loop(rounds=15)`)。
2. **未做因子-模型联合优化**:RD-Agent(Q) 的因子+模型联合优化未做(本地只挖因子,模型固定)。
3. **未做语义级 anti-crowding**:QuantaAlpha 的语义一致 + 结构约束;本地用既有 `factor_dedup` AST 指纹去重(代码级),未加语义级。
4. **未接真实 LLM**:冒烟用 stub `factory_task`;真实 Grid/GLM 联调需 Lyra 拍后接 `:8501/factory/task`(未碰 gateway)。
5. **未做 Alpha158 基线库**:Qlib 的 Alpha158 现成因子集未接(那是立项书外的路径 2,本批只做 path 1 + bandit)。

---

## 7. 自检

- [x] 清单全覆盖:path 1(trajectory mutation/crossover)+ path 2(bandit 调度)+ 冒烟测试 全落码
- [x] 自动自检已跑:16 新测 + 10 sandbox + 4 RWA + 9 provenance + 7 enforcement 全 PASS
- [x] 复发封堵:trajectory lineage 可追(parent_id 链);bandit UCB 有探索/利用平衡;沙箱主权有断言
- [x] 可证明证据:贴测试输出原文 + exit code
- [x] 无回归:sandbox 10/10、enforcement 7/7、RWA/provenance 全绿
- [x] 未碰冻结链/部署形态/密钥/local_gateway.py
- [x] 未宣称"已可用":冒烟用 stub LLM;真实联调待 Lyra 拍接 `:8501/factory/task`

—— 戌,2026-09-02 PDT(Alpha Factory 进化层落码)
