# harness agents RWA chain 缺口审计 · 回执 · 2026-09-02

> 审:Lyra 问"harness agents RWA chain 还有什么缺口"
> 模式:只读采证,未改任何文件、未 restart、未 commit。
> 性质:内部对账回执(架构骨架 + 文件:行 证据)。无密钥/身份/store 正文/user 数据;repo 相对路径。若外发 review 区,按 `receipt-redaction.mdc` 复核(本件已无活体)。

---

## 0. 一句话

RWA chain 的硬缺口是 **G1(两半断开)+ G2(等级梯没接)**——`rwa_onchain_reader.py` 读得对但读数没进 harness 的 provenance/证据等级链;其余 G3–G8 是契约 §三/§七/§八/§九 第二步起的落码项(砥:等拍),G9 是数据缺口。

---

## 1. 现状(已稳,有测试/断言)

`app/harness/` 四件稳:

| 文件 | 职责 | 证据 |
|---|---|---|
| `app/harness/action_envelope.py` | ActionEnvelope/FactualReceipt,认知泄漏硬拦(FORBIDDEN 前缀类),VERIFIED 只能由 `mark_verified()` 经确定性谓词产生 | `FORBIDDEN_RECEIPT_PREFIXES` / `VALID_RECEIPT_STATUS` |
| `app/harness/provenance.py` | append-only JSONL hash 链(prev_hash/event_hash),`verify_chain()` 可校 | `_write()` / `verify_chain()` |
| `app/harness/resource_gate.py` | deny 不替换,jurisdiction blocklist,money-moving 须 (mission:action) 绑定 token | `gate()` / `JURISDICTION_POLICY` |
| `app/crypto_rwa/rwa_onchain_reader.py` v5 | 双源 eth_call、NAV oracle、dual/single/unverified 信心词 | 测试 `tests/crypto_rwa/test_rwa_onchain_reader.py` 1/1 过 |

---

## 2. 核心缺口:RWA chain 断链

### G1 · reader 没接进 harness provenance 链(最严重)

`rwa_onchain_reader.py` 是独立 CLI 脚本,输出自己的 `rwa-onchain-*.json` 文档,**不**产 FactualReceipt、不写 `provenance.jsonl`、无 event_id/mission_id/receipt_hash。

证据:`rg "rwa_onchain_reader|read_token|run_chain|from app.crypto_rwa" app/`(排除 reader 自身)只命中 `app/platform_main.py:18` 引的是 `generator`(旧网页标题打包法),不是 reader。reader 文档头明写"写成证据卡(替代此前五张网页标题)",但 platform_main 仍用旧法。

**两半断开:reader 的链上读数在 harness 的 action/receipt/provenance 链里不可追。**

### G2 · 信心词与契约 §八 证据等级梯不对齐

reader 用 `dual/single/unverified`;契约 §八 全系统共用梯:`attested > witnesses_agree > witness_only > issuer_claim > secondhand > unverified`。

映射本应:链上自建 RPC 双源一致 = `attested`(§八原文"链上自建 RPC"= attested);单源 = `witness_only`;注册表 issuer 自填地址 = `issuer_claim`;rwa.xyz 参考 = `secondhand`。

证据:`rg "evidence_grade" --glob '*.py'` **全 repo 零命中**——§八整节未落码,reader 的 confidence 停在自己 JSON 里,没进等级梯。

---

## 3. 契约层缺口(§八/§三/§七 未落码)

### G3 · "只降不升"断言未实现

§八处决案:secondhand 标 attested → `record_receipt` 拒;对账层提级 → 拒;EGRESS.md 新源未填等级 → 拒。

证据:`provenance.py` 的 `record_receipt`/`mark_verified` 无等级校验;`validate_external_receipt` 只查认知泄漏 + VERIFIED 谓词,不查等级。任何等级都能写。

### G4 · capability_registry 缺 `visible_to_lanes` 字段

§三:每条 capability 加 `visible_to_lanes: [...]`(空=所有 lane),实况行按 lane 裁剪(RWA lane 看链上 RPC 双源,glm52 看交易面)。

证据:`capability_registry.py` 的 `Capability` dataclass 无此字段;`rg "visible_to_lanes" app/` 全 repo 零命中。`crypto.rwa.scan_public` 现在对所有 lane 可见,无法按 lane 裁剪。

### G6 · 出网工具层(§七)未落码,reader 绕过登记

§七:`web.fetch` + `EGRESS.md` 登记表,"未登记域名一律拒"。

证据:RWA reader 直接 `urllib.request.urlopen` 出网读 Alchemy/QuickNode/Ankr RPC,绕过 EGRESS.md(EGRESS.md 不存在,`web.fetch` 未实现)。结构上是 bind-before-register 的违反形态(虽是 Lyra 拍的特例,但不在登记表里)。

### G5 · 实况探针行未实现(§三)

§三:`cloud_gateway_route.py` 请求时并发探 8620/health、8600 pulse、8501 store 写回、8503 桥,300ms 超时 60s 缓存,拼 system 注入行。

证据:`cloud_gateway_route.py` 现在只有 soul inject + tool_executor,无探针行。RWA lane 看不到"链上 RPC 双源:通/断"。

### G8 · 成本读数(§九)未落码

§九:tool_log 每行带 `cost_usd` + `backend`,lane 级日预算,超即降级。

证据:tool_log 表本身不存在(见 G1),RWA reader 的 RPC 调用成本没计。

---

## 4. harness worker 段一未合身

### G7 · 契约 §四 未落码

§四 + §五顺序表:"段一后 §四 harness"。harness worker 的 node = thread_messages(memory_adapter write_mode=none),tool_log 写 harness 自己的 events 表,实况行由 harness /api/capabilities 的 health 字段给。

证据:`app/harness/server.py` 只有 `/health` + `/api/capabilities`(read-only),**无** tool_log 表、**无** tool_trace 压条、**无**探针。`memory_adapter.py` 的 write_mode 未确认设 none。harness agent 自己跑 RWA 时,没有 tool_log/tool_trace/探针行——契约对 harness worker 那半完全没落。

---

## 5. 数据缺口 + 结构限制

### G9 · 注册表地址缺口(reader 自身)

`DEFAULT_REGISTRY` 里 BUIDL(BlackRock/Securitize)、OUSG、USDY 三条 `address: None`(待官方文档核实),reader 正确拒读不猜。

证据:`rwa_onchain_reader.py` DEFAULT_REGISTRY 三条 `address: None`。RWA 实读覆盖**只有 USYC 一家**。BUIDL 是 RWA 大头,缺地址 = 链上读数覆盖不全。

### G10 · BSC 单源结构限制(非 bug)

BSC 只有 Ankr 免费档 → `policy=optional` → USYC BSC 2.6B 份永远 `single` 不进 dual 栏,汇总美元栏漏大头(v5 NAV 跨链套用部分缓解,但 supply 仍 single)。设计正确,是结构限制。

---

## 6. harness-wide(非 RWA 专属但影响)

- **8630 无 launchd plist**:`lsof -iTCP:8630` 见 pid 在 listen,但 `~/Library/LaunchAgents` 无 harness plist → 手动 uvicorn,重启不自启(HARNESS_STATE 已记)
- **`mission_loop_controller` 不存在**(HARNESS_STATE 已记)

---

## 7. 优先级建议(等拍)

| 优先 | 项 | 理由 |
|---|---|---|
| P0 | G1 reader 接进 provenance 链(产 FactualReceipt + 写 provenance.jsonl) | 断链根因;不接则 §八"每条工具回执带等级进 provenance"对 RWA 不成立 |
| P0 | G2 信心词映射到 §八 等级梯(dual→attested / single→witness_only / unverified) | 与 G1 同批;reader 已有 confidence,加一层映射即可 |
| P1 | G3 只降不升断言(provenance.record_receipt 校验) | §八处决案;守恒落码 |
| P1 | G4 visible_to_lanes 字段 | §三;RWA lane 裁剪前提 |
| P2 | G6 web.fetch + EGRESS.md(含 RWA RPC 端点登记) | §七;reader 出网合规化 |
| P2 | G5 实况探针行 | §三 |
| P2 | G8 成本读数 | §九 |
| 段一后 | G7 harness worker 合身 | §四 |
| 数据 | G9 BUIDL/OUSG/USDY 官方地址 | 数据缺口,非代码 |

注:G3–G8 多属"记忆契约第二步",砥已说"不做 tool_log/回注/过滤/探针——第二步起等拍"。G1/G2 可与第二步同批,但断链是 RWA chain 独立硬伤,可单独立项。

---

## 8. 自检

- [x] 只读采证,未改任何文件、未 restart、未 commit
- [x] 证据贴文件:行 / grep 命中原文,不空口
- [x] 不知道的写"未确认"(G7 memory_adapter write_mode)
- [x] 未宣称"已修复";只列缺口
- [x] 范围:harness agents RWA chain;未碰 local_gateway.py / 冻结链

—— 戌,2026-09-02 PDT(只读采证)
