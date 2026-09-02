# ERC-8004 Validation Registry 立项书 · 补 RWA G1/G3 · 2026-09-02

> 审:Lyra 拍"可以"立项(2026-09-02 01:48 PDT)
> 模式:**立项书(规划件),非实现**。本件不写一行代码、不上链、不装钱包、不碰冻结链/部署形态/密钥。
> 性质:内部规划回执(架构骨架 + 阶段划分 + 红线边界 + 验收门槛)。无密钥/身份/store 正文/user 数据。若外发 review 区,按 `receipt-redaction.mdc` 复核(本件已无活体)。

---

## 0. 一句话

把 harness `mark_verified()` 的**确定性谓词**与 ERC-8004 **Validation Registry** 对齐:reader 链上读数 → FactualReceipt + provenance(补 G1)→ 等级梯映射(补 G2)→ 只降不升断言(补 G3)→ ERC-8004 validation entry 作**可读见证源**(read-only),让 RWA 证据从"本地可信"升级到"链上可验"。

**关键红线**:agent **永不签名上链**。任何上链注册需 Lyra 本机钱包人工签;agent 只读 validation registry 当 witness。

---

## 1. 为什么是 ERC-8004

ERC-8004(2025-08 MetaMask + EF + Google + Coinbase 提)定义链上 agent 三注册表:

| 注册表 | 是什么 | harness 对齐 |
|---|---|---|
| Identity | agent 链上身份 | harness agent id(可选,非本立项) |
| Reputation | agent 声誉 | 非本立项 |
| **Validation** | **验证记录**:stake-secured re-execution / zkML / TEE oracle,任何人可重跑验证 | **本立项核心**——harness `mark_verified()` 的确定性谓词 = 一个 validation |

Validation Registry 的关键性质:**可重跑、可审计、链上可验**。这正好补 RWA 缺口:

- **G1(reader 没接 provenance)**:reader 读数现在只落本地 JSON,无 receipt;立项后 reader → FactualReceipt → provenance.jsonl,**且** validation entry 可作为 receipt 的链上见证。
- **G3(只降不升断言未实现)**:validation registry 的 stake-secured re-execution = 天然的"只降不升"机制——一个被 slash 的 validation 不能再用来提级;harness `record_receipt` 可把"该等级是否仍在 registry 有效"作为断言条件。

---

## 2. 阶段划分(每阶段独立可拍,不捆绑)

> 原则:G1/G2/G3 是**本地**代码改动,可先做、独立验;ERC-8004 集成是**只读**外接,后做;上链注册是**用户签**的人工动作,agent 不参与。

### Phase 1 · reader 接进 provenance 链(补 G1)— 本地,无外接

**做什么**
- `rwa_onchain_reader.py` 的 `run()` 在产出 JSON 后,**额外**产 `FactualReceipt`(经 `action_envelope.py`),写 `provenance.jsonl`(经 `provenance.record_receipt`)。
- receipt 带 `event_id` / `mission_id` / `receipt_hash` / `prev_hash` 链上。
- reader 的 `source_url`(Alchemy/QuickNode/Ankr RPC endpoint)落 receipt metadata。

**不做什么**
- 不改 `provenance.py` 的 hash 链结构(append-only 不变)
- 不改 `action_envelope.py` 的 VERIFIED 路径(仍只能经 `mark_verified`)
- 不上链、不调 ERC-8004

**验收**
- reader 跑一次 → `provenance.jsonl` 多一行,`verify_chain()` PASS
- receipt 含 `evidence_grade` 字段(Phase 2 填值,先留空槽)
- `tests/crypto_rwa/test_rwa_onchain_reader.py` 仍 1/1 过 + 新增 provenance 接入测试

### Phase 2 · 信心词映射到 §八 等级梯(补 G2)— 本地,无外接

**做什么**
- reader 现有 `dual/single/unverified` → 映射:
  - `dual`(链上自建 RPC 双源一致)→ `attested`
  - `single` → `witness_only`
  - `unverified` → `unverified`
- 注册表 issuer 自填地址 → `issuer_claim`
- rwa.xyz 参考 → `secondhand`
- 映射在 reader 产出 receipt 时填 `evidence_grade` 字段(Phase 1 留的空槽)

**验收**
- reader 输出 receipt 的 `evidence_grade` ∈ 契约 §八 六档
- 等级与 confidence 对应关系有单元测试

### Phase 3 · 只降不升断言(补 G3)— 本地,无外接

**做什么**
- `provenance.record_receipt` 加等级校验:
  - 同一 mission/action 的 receipt 等级**不得高于**前序(只降不升)
  - 对账层提级 → 拒
  - EGRESS.md 新源未填等级 → 拒(待 EGRESS.md 落码,Phase 5)
- `validate_external_receipt` 加等级校验(现在只查认知泄漏 + VERIFIED 谓词)

**不做什么**
- 不改 `mark_verified()` 的确定性谓词定义(谓词本身不变,只加"该谓词是否仍在 registry 有效"的查询,Phase 4)

**验收**
- 单元测试:secondhand 标 attested → 拒;对账提级 → 拒
- 现有 `verify_chain()` 仍 PASS

### Phase 4 · ERC-8004 只读集成(见证源)— 外接,只读

**做什么**
- 新增只读工具 `erc8004.validation_lookup(agent_id, predicate_id)`:
  - 查 ERC-8004 Validation Registry:该 validation 是否存在、是否有效(未被 slash)、stake 多少、谁重跑过
  - 结果作为 `witness_only` 或更高(若 stake-secured 重跑成功)等级的**见证源**进 receipt
- 该工具进 `capability_registry.py`,带 `visible_to_lanes: ["rwa"]`(待 G4 落码)
- 该工具的 RPC 端点进 EGRESS.md(待 G6 落码)

**不做什么**
- **不上链写**(无钱包、无私钥、无签名)
- 不改 `mark_verified()` 谓词本身
- 不改部署形态(只读 RPC,走现有出网路径,待 EGRESS.md 登记)

**验收**
- `validation_lookup` 返回 registry 状态(存在/有效/stake/重跑者)
- receipt 的 `evidence_grade` 可因 registry 见证**保持或降**(不升,Phase 3 断言)
- 单元测试:registry 无效 → 等级降到 `unverified`;registry 有效 + 重跑成功 → 保持

### Phase 5(可选,用户签)· 上链注册 harness 谓词 — 人工,agent 不参与

**做什么**
- Lyra 本机钱包签:把 harness `mark_verified()` 的某个确定性谓词注册成 ERC-8004 validation
- 注册后该谓词的 receipt 可被任何人链上重跑验证

**红线(硬)**
- **agent 永不签名上链**(R3 密钥 + R5 部署形态)
- 钱包/私钥/助记词**永不进对话、永不进容器、永不进代码**
- 注册动作 = Lyra 本机人工,agent 只能产注册 proposal(待 Lyra 签)

**验收**
- 注册后链上 validation id 与 harness 谓词 id 对应表落 `EGRESS.md`(只读对照)
- `validation_lookup` 能查到该 validation

---

## 3. 红线边界(立项即锁,违反 = 立项作废)

| 红线 | 锁 |
|---|---|
| **R3 密钥** | agent 永不签上链;钱包/私钥/助记词不进对话/容器/代码 |
| **R5 部署形态** | 不改 Docker↔本机进程、端口、绑定地址;ERC-8004 集成走现有出网路径 |
| **R6 宿主机** | 不改网络栈/DNS/launchd |
| **冻结链** | 不改 `local_gateway.py` / `:8501` 推理链 / `grid_infrastructure_lock.json` manifest |
| **provenance hash 链** | append-only 结构不变;只加字段/校验,不改链结构 |
| **VERIFIED 路径** | `mark_verified()` 仍是 VERIFIED 唯一来源;ERC-8004 不绕过 |
| **EGRESS.md** | Phase 4 RPC 端点必须登记(待 G6 落码);未登记一律拒 |
| **visible_to_lanes** | Phase 4 工具按 lane 裁剪(待 G4 落码);RWA lane 专属 |

---

## 4. 依赖与前置

| 依赖 | 状态 | 阻塞哪个 Phase |
|---|---|---|
| G4 `visible_to_lanes` 字段 | 未落码 | Phase 4(工具按 lane 裁剪) |
| G6 `web.fetch` + EGRESS.md | 未落码 | Phase 4(RPC 端点登记) |
| 契约第二步 tool_log/tool_trace | 砥说"等拍" | 不阻塞 Phase 1-3(本地),阻塞 Phase 4 的 tool_log 落码 |
| ERC-8004 标准最终状态 | 2025-08 提案,可能变 | Phase 4/5;Phase 1-3 不依赖标准最终态 |

**结论**:Phase 1-3 可**立即开工**(本地,无外接,无标准依赖);Phase 4 等 G4/G6 + 契约第二步;Phase 5 等 Lyra 本机钱包。

---

## 5. 不做什么(立项范围外)

- 不做 agent 链上身份(ERC-8004 Identity Registry)——非本立项
- 不做 agent 声誉(ERC-8004 Reputation Registry)——非本立项
- 不做 zkML / TEE oracle 集成——Phase 4 只读 registry 状态,不跑 zkML
- 不做 G4/G6/G5/G7/G8(契约第二步,砥说等拍)——本立项只补 G1/G2/G3 + ERC-8004 只读
- 不改 `alpha-platform` factor_sandbox——非本立项
- 不装任何 HF 模型——非本立项

---

## 6. 验收门槛(立项完成定义)

立项本身 = 本文件落盘 + Lyra 拍"可以"。**立项完成 ≠ 任何 Phase 完成。**

每个 Phase 完成的定义(按 `verification-before-complete.mdc`):
- 代码改完 → 单元测试过 → `verify_chain()` PASS → 贴命令输出原文
- Phase 4 额外:`validation_lookup` 实跑返回 registry 状态(只读 RPC)
- Phase 5 额外:链上 validation id 可查 + 与 harness 谓词 id 对应表落 EGRESS.md

未跑验收 → 只能说"代码已改,待验收"。

---

## 7. 待 Lyra 拍

1. **Phase 1-3 是否立即开工**?(本地,无外接,无标准依赖)
2. Phase 4 等 G4/G6 + 契约第二步,还是先做 G4/G6 再回 Phase 4?
3. Phase 5(上链注册)何时做?需 Lyra 本机钱包,agent 只产 proposal

---

## 8. 自检

- [x] 立项书,非实现;未写一行代码、未上链、未装钱包
- [x] 红线边界明确:agent 永不签上链;不改冻结链/部署形态/密钥
- [x] 阶段独立可拍,不捆绑;Phase 1-3 可立即开工,Phase 4/5 有依赖
- [x] 与 RWA_CHAIN_GAP_AUDIT G1/G2/G3 对齐;不混淆 G4-G8(契约第二步)
- [x] 未宣称"已修复/可用";只立项
- [x] 范围:ERC-8004 Validation Registry 补 RWA G1/G3;未碰 local_gateway.py / 冻结链 / 部署形态

—— 戌,2026-09-02 PDT(立项书)
