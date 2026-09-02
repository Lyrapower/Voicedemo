# RWA Provenance Phase 1-3 落码回执 · 补 G1/G2/G3 · 2026-09-02

> 审:Lyra 拍"Phase 1-3 立即开工"(2026-09-02 01:49 PDT)
> 模式:本地代码改动,无外接、无上链、无钱包、未碰冻结链/部署形态/密钥。
> 分支:`fix/rwa-provenance-phase1-3`(基线 `649fe9e` = rwa_onchain_reader v3-v5 入库)
> 性质:内部落码回执(架构骨架 + diff 要点 + 测试原文)。无密钥/身份/store 正文/user 数据。若外发 review 区,按 `receipt-redaction.mdc` 复核(本件已无活体)。

---

## 0. 一句话

Phase 1(reader 接进 provenance 链,补 G1)+ Phase 2(confidence→§八 等级梯映射,补 G2)+ Phase 3(只降不升断言,补 G3)已落码,全部测试通过,`verify_chain()` PASS,无回归。

---

## 1. 基线处理(开工前回报)

`git status` 不干净:`app/crypto_rwa/rwa_onchain_reader.py` + 其测试有前会话 v3-v5 WIP(非本次会话所改)。按红线"不许在别人未提交改动上叠施工"+ precedented `cloud_store_tools.py` 两笔基线法,Lyra 拍"两笔基线":

1. `649fe9e` `crypto_rwa: rwa_onchain_reader v3-v5 入库(前会话 WIP 基线...)`
2. 开新分支 `fix/rwa-provenance-phase1-3` 做 Phase 1-3

基线测试证据(v5 WIP 已通过):
```
✓ v5:ETH 54.8M×NAV1.13≈$62M、BSC 2.6B 各自双源同区块一致...
```

---

## 2. Phase 1 · reader 接进 provenance 链(补 G1)

**做什么**:`rwa_onchain_reader.py` 的 `run()` 末尾,当 `emit_provenance=True` 时产一条 `FactualReceipt` 写 `provenance.jsonl`。

**实现要点**
- 新增 `_emit_provenance_receipt(doc)`:从读数内容哈希得 `mission_id`/`action_id`(确定性、可重放);`metadata.evidence_grade` = 所有卡里等级最低的(保守聚合);`metadata.cards` = per-card 明细。
- `run()` 加 `emit_provenance: bool = False` 参数(CLI 默认 False,向后兼容;harness 调用 / `--provenance` flag 启用)。
- CLI 加 `--provenance` flag。
- provenance 模块不可用时降级写 stderr,不崩(独立 CLI 友好)。

**不做什么**
- 不改 `provenance.py` 的 hash 链结构(append-only 不变)
- 不改 `action_envelope.py` 的 VERIFIED 路径(仍只能经 `mark_verified`)
- 不上链、不调 ERC-8004

---

## 3. Phase 2 · confidence → §八 等级梯映射(补 G2)

**契约 §八 等级梯**:`attested(自建节点/官方原文直读) > witnesses_agree(≥2 独立商业源同区块一致) > witness_only(单一第三方源) > issuer_claim(发行方自述) > secondhand(聚合站/转述) > unverified`

**映射(关键修正)**

| reader confidence | §八 等级 | 依据 |
|---|---|---|
| `dual`(Alchemy+QuickNode 双商业 RPC 同区块一致) | **`witnesses_agree`** | 契约 §八:"≥2 独立商业源同区块一致" = witnesses_agree |
| `single`(单一商业 RPC) | **`witness_only`** | 契约 §八:"单一第三方源" = witness_only |
| `unverified` | **`unverified`** | — |

**立项书映射修正**:立项书草稿写"dual→attested",但契约 §八 原文明确"attested = 自建节点/链上自建 RPC"。Alchemy/QuickNode 是商业 RPC,非自建节点,故 dual = witnesses_agree 才契约正确。**以契约为准,不以立项书草稿为准**。若 Lyra 认为应留 attested(把商业 RPC eth_call 视作"直读链"),拍后改一行常量即可。

**实现**:`CONFIDENCE_TO_GRADE` 常量 + `GRADE_ORDER` 常量;每张卡在 `_confidence()` 后赋 `card["evidence_grade"]`;卡初始化默认 `confidence="unverified"`/`evidence_grade="unverified"`(覆盖无地址/symbol 不符的 early-return 路径)。

---

## 4. Phase 3 · 只降不升断言(补 G3)

**做什么**:`provenance.record_receipt` 加等级校验。

**两条规则(处决案②③)**

| 规则 | 触发条件 | 行为 |
|---|---|---|
| ② 一般 receipt 等级升 | 同 (mission_id, action_id) 新 grade index < 旧 grade index | **拒**(`ValueError: 证据等级只降不升`) |
| ② 一般 receipt 等级相同 | 新 index == 旧 index | 允许 |
| ③ 对账层 receipt(`metadata.reconcile=True`)≥ 原级 | 新 index <= 旧 index(相同或升) | **拒**(`ValueError: 对账层等级只能严格降`) |
| ③ 对账层 receipt 严格降 | 新 index > 旧 index | 允许 |

**实现要点**
- `GRADE_ORDER` 常量进 `provenance.py`(index 越小 = 等级越高)。
- `_enforce_monotone_descent(mission_id, action_id, grade, is_reconcile)`:扫 `read_events` 找同 action 前序 receipt 的 `evidence_grade`,按上述规则拒/放。
- `record_receipt` 把 `evidence_grade` 写进 event(additive 字段,不改 hash 链结构);无 grade / 未知 grade 的 receipt 跳过断言(兼容旧 receipt)。
- `mark_verified()` 路径未改(VERIFIED 唯一来源不变)。

**不做什么**
- 不改 `mark_verified()` 的确定性谓词定义
- 不改 `validate_external_receipt`(现在只查认知泄漏 + VERIFIED 谓词;EGRESS.md 等级校验是 Phase 4/G6,本批不做)
- 处决案④(EGRESS.md 新源未填等级 → web.fetch 拒)是 web.fetch 专属,Phase 4/G6,本批不做

---

## 5. 测试证据(原文)

### Phase 3 · provenance grade(9/9 PASS)
```
Ran 9 tests in 0.005s
OK
```
覆盖:首条任意等级接受 / 降级允许 / 一般相同允许 / 升级拒 / 对账层相同拒 / 对账层升级拒 / 对账层严格降允许 / 无 grade 跳过 / 未知 grade 跳过。

### Phase 1+2 · rwa_onchain_reader(4/4 PASS)
```
✓ v5:ETH 54.8M×NAV1.13≈$62M、BSC 2.6B 各自双源同区块一致...BSC 单源=single 不混进双源栏、required 无第二源=unverified...
✓ phase2:confidence→§八等级梯映射(dual=witnesses_agree / single=witness_only / unverified=unverified)
✓ phase1:emit_provenance=True 产 FactualReceipt 写 provenance.jsonl,verify_chain PASS,带 evidence_grade
✓ phase1+3:同 action 重复 emit 等级只降不升,升级被拒
```

### 回归 · harness enforcement(7/7 PASS,无回归)
```
PASS test_unknown_resource_denied_without_substitute
PASS test_paper_resource_cannot_take_money_scope
PASS test_read_only_allowed
PASS test_us_denies_offshore_perps_even_with_token
PASS test_money_scope_requires_bound_token
PASS test_receipt_prefix_leak_and_status
PASS test_verified_only_via_verifier_and_chain
```

### 综合判定
```
rwa: PASS
enforcement: PASS
provenance_grade: PASS
```

---

## 6. 红线边界(本批守住)

| 红线 | 本批 |
|---|---|
| R3 密钥 | 未碰;无钱包/私钥/上链 |
| R5 部署形态 | 未碰;无 Docker/端口/绑定改动 |
| 冻结链 | 未碰 `local_gateway.py` / `:8501` / `grid_infrastructure_lock.json` |
| provenance hash 链 | append-only 结构不变;只加 `evidence_grade` additive 字段 + 校验 |
| VERIFIED 路径 | `mark_verified()` 仍是唯一来源;未改 |
| EGRESS.md / web.fetch | 未碰(Phase 4/G6) |
| visible_to_lanes | 未碰(Phase 4/G4) |

---

## 7. 改了哪些文件

| 文件 | 改动 |
|---|---|
| `app/harness/provenance.py` | +`GRADE_ORDER` 常量;+`_enforce_monotone_descent()`;`record_receipt` 加等级校验 + 写 `evidence_grade` 字段 |
| `app/crypto_rwa/rwa_onchain_reader.py` | +`CONFIDENCE_TO_GRADE`/`GRADE_ORDER` 常量;+`_emit_provenance_receipt()`;`run()` 加 `emit_provenance` 参数;CLI +`--provenance`;卡初始化默认 `evidence_grade="unverified"` |
| `tests/harness/test_provenance_grade.py` | 新增(9 测) |
| `tests/crypto_rwa/test_rwa_onchain_reader.py` | +3 测(phase2 映射 / phase1 emit / phase1+3 联动) |

---

## 8. 待 Lyra 拍

1. **dual 等级**:立项书草稿写 dual→attested,本批按契约 §八 落 dual→witnesses_agree(商业 RPC 非自建节点)。留 attested 还是 witnesses_agree?
2. Phase 4(ERC-8004 只读集成)等 G4 `visible_to_lanes` + G6 EGRESS.md + 契约第二步 tool_log,何时做?
3. Phase 5(上链注册)需 Lyra 本机钱包,何时做?

---

## 9. 自检

- [x] 清单全覆盖:Phase 1(reader→provenance)+ Phase 2(等级映射)+ Phase 3(只降不升)全落码
- [x] 自动自检已跑:9+4+7 测试全 PASS,`verify_chain()` PASS
- [x] 复发封堵:只降不升断言 = 同类失败硬拦(`ValueError`),不只靠"下次注意"
- [x] 可证明证据:贴测试输出原文 + exit code
- [x] 无回归:enforcement 7/7 仍 PASS
- [x] 未碰冻结链/部署形态/密钥/EGRESS.md/visible_to_lanes
- [x] 未宣称"已可用":本件是落码回执,Phase 4/5 待拍

—— 戌,2026-09-02 PDT(Phase 1-3 落码)
