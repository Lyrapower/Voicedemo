# 系统简化与记忆连贯 · 本对话完整总账（复核补齐版）

> 本文件为外发 review 脱敏版。敏感段按 `receipt-redaction.mdc` 替换为 `# [REDACTED: <类别>]`,保留结构与接口。原版在 iCloud CloudDocs(本机内部,不入外发区)。


**日期：** 2026-08-03（同日复核重写；**替代**同文件上一版疏漏稿）  
**范围：** 本对话约 70 条用户指令所覆盖的全部主题 + 直接相关红线债  
**目的：** 简化/强化；节点连贯；记忆持续；**禁止**「叠系统再修 bug」  
**约束：** 无密钥、无鉴权材料、无主机私密串；可给外部强模型 review  

**诚实声明（上一版哪里混过去了）**  
上一版偏记忆+Option+Alpha+Jarvis 提纲，**漏写或写浅**：Console 舱位/doctor/watchdog、模型实况名、工作日志修订④、因子工厂不可达、附件（长 py/html）、Mac 睡眠→Tailscale 断、harden/Echo、谁 purge 了 STUDIO、脏仓库、CC CLI 舱、Entry A/B、日记边界、交易「谁在跑」、验收未闭环清单。本版按对话流水账补齐；**未经验证的仍标「未闭环」**，不把 UNIT/方案当完成。

---

## 0. 模式判决（先于一切功能）

| 错误模式 | 正确模式 |
|----------|----------|
| 每个入口各有「记忆/状态/意图」 | **少数契约**：对话魂 / 任务合同 / 交易数据源 / 运维灯 |
| 出 bug → 新层、新文档、新旁路 | **改契约或删面**；禁止临时架构 |
| HTTP 200 / 单测绿 = 可用 | 只有用户可见路径 + 约定验收口径才算 |
| 「记忆持续」口头承诺 | UI 标明：窗 / 召回 / 冷库 / 哪颗魂 |
| Agent 写生产 node「再让你删」 | 硬红线；验收用 smoke |

---

## 1. 本对话主题覆盖表（防再漏）

| 主题块 | 对话中出现 | 上一版 | 本版 |
|--------|------------|--------|------|
| 拉起全栈 + Tailscale 多入口 | ✓ | 浅 | §8–9 |
| Console oneshot / 舱位红灯 | ✓ | 漏 | §8 |
| doctor / watchdog 只读诊断 | ✓ | 漏 | §8 |
| Echo Nodes / firewall harden | ✓ | 漏 | §8–10 |
| Console↔b11 Cloud 同魂方案 | ✓ | 有 | §2 |
| 模型名实况（不造名） | ✓ | 漏 | §2.4 |
| 真双限 15∩10k + 修订④工作日志 | ✓ | 半 | §2.2–2.3 |
| 修订⑤冷库召回（非全量） | ✓ | 有 | §2.2 |
| Tailscale 断 / Mac 睡眠 | ✓ | 漏 | §9 |
| Aether↔Alpha 同步·热力·排序 | ✓ | 半 | §5 |
| 谁驱动：router vs GLM | ✓ | 漏 | §5.3 |
| 因子工厂不可达 | ✓ | 漏 | §8 |
| Option + Evening Scout 安装 | ✓ | 有 | §4 |
| STUDIO/Cloud/Grid 记忆消失 | ✓ | 有 | §2–3 |
| epoch 硬删 + after_turn 仅 hash | ✓ | 半 | §3 |
| Console 附件（图 vs 长文件） | ✓ | 半 | §2.5 |
| 脏 git 树（只报告） | ✓ | 漏 | §11 |
| INTENT / 极性 / 假闭环 | ✓ | 有 | §6 |
| 简化：留/砍/并 Jarvis | ✓ | 浅 | §10 |

---

## 2. 记忆系统（完整真相）

### 2.1 魂器地图（不是一个「Grid 记忆」）

| 入口 | Store / 载体 | 注入模型 | 与谁共享 | 本对话结论 |
|------|----------------|----------|----------|------------|
| b11 **Cloud** GLM | 8501 `cloud-glm52` | **15∩10k** 对话窗 + 工作日志块 + 修订⑤召回 **≤2k**（总 **≤12k**） | Console chat（目标同魂） | **不是全量注入** |
| b11 **Cloud** Kimi | 8501 `cloud-kimi` | 同上构 | 同上 | DeepSeek **不对称**（可有 inbound 前缀；Kimi 不加） |
| b11 **STUDIO** | 8501 `workbench-b11` | 约 6 轮活跃；HOME/EXPANDED | **不与 Cloud 共享** | epoch 曾硬删正文 → 不可恢复 |
| **Grid app** | 8501 `field-particle` 等 | chat 多轮；可走 8515 验签代理 | ≠ b11 | 「记忆没了」≠ Cloud 丢了 |
| **8790 FIELD** | field / 日记边界 | 场域链路 | ≠ b11 | 禁止当 b11 历史 |
| **Console** chat | 应对齐 `cloud-*` | 与 b11 Cloud 同构 | 同 Cloud 魂 | 任务产出走 `lane_memory`，**chat 禁写**之 |
| DeepSeek 等 | 常 localStorage 或另约定 | 不稳定 | — | 勿计入「已持续」 |

### 2.2 注入契约（必须写进 UI，禁止空话）

| 层 | 内容 | 不是 |
|----|------|------|
| L1 对话窗 | 最近 15 轮 **且** ≤10k tok；超限裁最旧**对** | 全历史 |
| L1b 工作日志 | 最近约 5 条 `[工作日志]`，占 10k 预算，**不占** 15 轮计数 | 对话正文 |
| L2 召回 | 冷库词法 top-4，≤2k，标题标明「检索注入非对话窗」 | 全量 dump |
| L3 冷库 | store / archive 保留 | 自动等于「模型记得」 |

用户问「为何只记得对话框」→ **契约如此**；修订⑤只「捞」相关旧档，不是全记。  
用户问「#3 还是 #4」→ 口头编号已废；以 **窗+日志+修订⑤** 为准。

### 2.3 修订④ 工作日志（对话内已施工方向）

- 任务 done → digest 单向 POST 入对应 `cloud-*`（先过 SIGNAL_RE）  
- chat **禁止**写 `lane_memory`  
- 金丝雀验收、两端同源前缀——交接要求贴原文；**浏览器终验「记得侯/Jarvis」仍标未闭环**

### 2.4 模型名（曾造名事故）

| 错 | 对 |
|----|-----|
| 注册表写 `cloud-glm52` 当 model | **model** = gateway 实况如 `glm-5.2:cloud` / `kimi-k2.6:cloud` |
| | **store node** = `cloud-glm52` / `cloud-kimi`（魂主键，≠ model 字符串） |

混用 → 路由错 / 「没记忆」假象。

### 2.5 附件（Console GLM）

| 能力 | 状态 |
|------|------|
| 图片 | 有（`accept=image/*` 一类） |
| 长 `.py` / `.html` 附件当文件注入 | **无**；需粘贴正文 |
| 与记忆注入 | **无关**——附件不是「第几号记忆修订」 |

### 2.6 GLM 空回复 / 超长

- 服务端有「长对话强制 no_think、裁对再试」策略；store 不因空回复自动清空  
- 仍可能 502；**未**等于记忆丢失  
- 禁止在 b11 用「只 retry 一次」冒充服务端策略

### 2.7 记忆简化裁决（留 / 砍）

| 裁决 | 内容 |
|------|------|
| **留 Mem-A 双魂** | Cloud 魂（console+b11 Cloud）· Studio 魂（仅 STUDIO）· UI 标注魂+预算 |
| **砍** | 「全量注入」话术；8515 Cloud sqlite 心智；`/task/candidate` 假记忆；agent 写生产 node |
| **未批准不做** | Mem-B 全球一魂；跨魂自动「你还记得 STUDIO」 |

---

## 3. STUDIO / epoch / 不可恢复（本对话爆发点）

| 事实 | 含义 |
|------|------|
| `b11_purgedEpoch` 一类逻辑曾对 `workbench-b11` **硬删**旧 epoch 正文 | 与「走 8501 就永不丢」矛盾 |
| `after_turn` 若只留 hash | **删正文后不可恢复** |
| 用户未授权 purge | 违反 workbench-b11 红线；责任在执行方，不在「系统神秘消失」 |
| Cloud 另 node | STUDIO 清空 **≠** Cloud 清空；禁止混报 |

**留：** store 持久化 + archive；epoch 至多归档。  
**砍：** 任何自动 DELETE 生产 node 正文；hash-only 冒充「记忆层」。

---

## 4. Option Workstation + Evening Scout

### 4.1 已有
- `:8620` 研究舱、合成链、清洗/隔离/七问、数字引擎无 LLM  

### 4.2 还缺（workflow）

| 级 | 项 |
|----|-----|
| P0 | 真数据供应商+预算+宇宙拍板；真实截面对账 |
| P1 | 实时盘口；GEX 日内；腿核验；SVI/SSVI；美式股息；陈旧分档完善；指标进 doctor |
| P2 | 热力提名、earnings；明确不做 Unusual Whales |
| Scout | polymarket 类 fetch 补丁、commodities、宏观 key 可选、去 dry-run、launchd 真装 |

### 4.3 留 / 砍 / 并
- **留：** 独立研究舱（数据真之前）  
- **砍：** 并进 Alpha 热力或 Aether 信号「假装一体」  
- **并：** 仅导航链接；引擎不合

---

## 5. Alpha × Aether ×「谁在跑」

### 5.1 本对话三问
1. **不同步** → 龄徽章 + BFS 即时层 vs 热力 tick 倒计时；**禁止改 TICK 节奏**  
2. **热力总那几个** → 非全 SP500 展示；watchlist/env + 提名配额；**禁 BFS 独有标的默认灌热力**（红线）  
3. **router vs GLM** → 扫描/路由主链仍是基础设施；GLM 是任务/摘要占比（对话中问过占比——以当时统计为准，**勿用感觉数**）

### 5.2 排序三次仍乱
根因常叠加：错 tab、Tailscale/缓存旧 JS、排序键不稳。  
**留：** 运营台热力「分数降序」+ 来源标注 + no-store。  
**砍：** 无验收的「又改一版排序」。

### 5.3 合并矩阵

| 组合 | 建议 | 原因 |
|------|------|------|
| Alpha × Aether | 视图可合、写源不合 | 节奏与账本主权不同；合并引擎=假同步 |
| Alpha × Option | 不合引擎 | 因子面 ≠ 期权截面研究 |
| Alpha × Console | 灯可合、业务不合 | Console=健康/任务门 |
| Alpha × b11/Jarvis | 不合 | 对话/检索 ≠ 热力 |

### 5.4 Alpha + Aether + Option `:8620` 能否三合一（2026-08-03 拍板口径）

**可以「合并入口」，不建议「合并引擎」。**

| 层 | Alpha `:8600` | Aether | Option `:8620` |
|----|---------------|--------|----------------|
| 干什么 | 因子/热力/扫描面 | 交易节奏、账本、信号与任务面 | 期权截面研究（清洗→IV→七问） |
| 数字谁算 | 因子/行情管线 | 交易与 store 契约 | **确定性引擎**（LLM 禁算） |
| 数据节奏 | tick（如 300s）等 | 自己的 emit/读 store | EOD/回放为主；真数据未接 |
| 失败代价 | 热力看错 | 账本/节奏乱 | 研究结论错（尚未接真盘） |

**结论**

- **不要**三合为一进程 / 一库 / 一写路径。合引擎会把三种真相（因子面、交易账本、期权研究）拧成一个假同步源，更难修，也踩交易红线。
- **可以**合一「交易工作台」导航：一页三个区（或三个 tab）——Alpha 热力 | Aether 态势 | Option 研究——各自仍打自己的 API，屏上带**数据龄/来源**。
- **Option 进主导航的前提：** 真数据 + 七问可对账；现仍 `synthetic-v1` 研究舱时，合进主叙事 = 假装生产就绪。

**有限合并顺序**

1. **Alpha ↔ Aether** 先做（龄徽章、拓扑说明、热力语义）——视图近、写源仍分。  
2. **再链 Option**——只加入口/深链，引擎独立。  
3. **永不合并：** 账本写入、期权 raw 不可变层、Alpha watchlist 语义、Option 七问红灯逻辑。

一句话：**壳可以并，心不能并。**

---

## 6. INTENT / 编译（本对话后半）

| 项 | 状态 |
|----|------|
| 对话是否经 SemanticMapper | **不在** grid/8790/b11 |
| 极性 A–D | **POLARITY_LINE_CLOSED（UNIT）**；`executable_meaning` 唯一进 core |
| 称闭环 | **禁止**；缺 E2E_BOUND_PASS |
| 下一活 | POOL/OFFPOOL → MEM_PHASE0 → schema/execute… |
| 债（并入 schema 轮，不开旁支） | 合词、引用启发式、词表漏、：/！切分、任务级 guard |

**留：** 任务链 raw→canonical→execute→result（仅交付物任务）。  
**砍：** chat 接 compiler；平行 intent AST；用单测绿冒充闭环。

---

## 7. Jarvis

| | |
|--|--|
| Jarvis 是什么（本仓语境） | 偏本地路由 / 编译记忆**只读**，不是 Cloud 魂 |
| **可对齐** | 少入口的「问基础设施/编译笔记」 |
| **禁止并入** | Cloud/STUDIO 魂、交易信号、diary、Option 数字、Alpha 热力 |
| **可去掉的壳** | 第二套假装永久记忆的 chat；与 b11 重复的「总管」UI |

---

## 8. 运维面（上一版大漏）

| 问题 | 状态/漏洞 | 留或砍 |
|------|-----------|--------|
| Console `:8610` 舱位红 | 曾：alpha 探错路径、garden telemetry 类型、scanner/doctor **挂载路径错**（文件在但容器找不到） | **留** Console 作灯；修探测/挂载，不叠新监控产品 |
| pipeline_doctor 仍红 | 路径好了仍可能 **内容** FAIL（如规则项）——与「文件缺失」要分报 | 分报；勿混 |
| watchdog | 只读诊断：进程/路径/是否停写——等裁决再改 doctor | 观测可配；禁擅自改架构 |
| 因子工厂 / factory task | 对话中「Grid factory 不可达」 | **留**工厂需独立健康契约；勿并进 chat 记忆叙事 |
| Echo Nodes `:8500` | 已 archived；现 `:8500` 常为 Router 角色 | **不要**当 Echo 健康舱 |
| firewall harden | 非 console 舱；脚本级；本机防火墙状态需实跑确认 | 运维动作，不进「记忆」 |
| 5173 vs 5713 | 用户笔误端口 | 以实听端口为准 |

---

## 9. 网络 / 睡眠 / Tailscale

| 漏洞 | 原因 | 处置 |
|------|------|------|
| 手机全断 | 常见：Mac 睡眠 → Serve 后端不可达 | **留**「防睡眠」为机器策略；agent 口头「已设置」不够——要可验证 |
| Serve 路径少报 | `/` `/workbench` `/alpha`；console 曾未进 Serve | 入口表单一来源；禁口头少发 |
| 改 UI 三次仍旧 | 缓存 / 错入口 / 无 no-store | grid/运营台强制缓存纪律 |

**砍：** 靠「再 kickstart 一次」当架构。

---

## 10. 系统留 / 砍 / 并（总表 + 原因）

### 10.1 建议保留（核心承重）

| 系统 | 原因 |
|------|------|
| **8501 gateway + store** | 唯一可信 API/魂器宿主；Cloud/STUDIO/Grid 都落这里（分 node） |
| **b11（8515 静态）** | 工作台 UI；API 仍回 8501 |
| **Cloud 魂 `cloud-*`** | Console+b11 Cloud 同魂目标；持续对话的主叙事 |
| **Studio 魂 `workbench-b11`** | 实验/EXPANDED 与 Cloud 隔离（在未批一魂前） |
| **Alpha `:8600`** | 因子/热力业务面 |
| **Aether 交易链路** | 账本/节奏主权；与 Alpha 分源 |
| **8790 场域** | 日记/场；与对话魂隔离（神圣边界） |
| **Console `:8610`** | 运维灯+任务审批门（减肥后） |
| **Option `:8620`** | 研究舱（真数据前降级主导航） |
| **意图编译（任务向）** | 仅交付物任务；chat 永不接 |

### 10.2 建议去掉或冻结（降复杂度）

| 项 | 原因 |
|----|------|
| 8515 Cloud sqlite / `/cloud/memory` 主路径 | 第二真理；已酿污染 |
| `/task/candidate` 假记忆块 | 模型按 prompt 拒绝「私记忆」 |
| epoch **硬删**生产正文 | 不可恢复；违红线 |
| hash-only after_turn 当「记忆层」 | 骗「有层」 |
| map_intent 第二套 ast/echo 当意图真理 | 与 canonical 重复（INTENT 后删） |
| chat 接 SemanticMapper | 总包禁止；假主链 |
| Echo Nodes 当现网健康 | 已归档 |
| 平行「总管」chat 壳 / 重复 Jarvis UI | 心智重复 |
| Unusual Whales 等未批源 | 明确不做 |
| Agent 验收写生产 node | 红线 |
| 旁支架构文档增殖 | 总包已禁；契约进 UI/schema |

### 10.3 可合并（有限）

| 合并 | 方式 | 不可合并的 |
|------|------|------------|
| Console chat × b11 Cloud | **已定同魂** store+注入算法 | 与 STUDIO/Grid 自动同魂 |
| Alpha × Aether | **一页分栏 + 龄** | 写节奏/账本 |
| Alpha × Aether × Option | **仅导航壳**（见 §5.4） | 三引擎/一库/一写路径 |
| 运维灯 | 集中 Console | 业务数据面 |
| Jarvis × 只读笔记检索 | 问答入口 | 魂器与交易 |

---

## 11. 仓库与工程债（对话内「只看不改」）

- 工作区曾有 **大片未提交** 杂改（alpha、nexus、规则、diag…）——与极性线 commits 分离  
- 风险：误 stage 外项目（已发生过）→ **任务级 staged guard** 仅 polarity 白名单  
- **留：** 白名单提交纪律  
- **砍：** 在脏树上叠无关「顺手修」

---

## 12. 未闭环验收清单（禁止对用户说「好了」）

1. 浏览器实机：Cloud「还记得…」是否命中召回而非胡编  
2. Console↔b11 同请求 messages：窗≤15、日志块、召回块原文  
3. STUDIO：关 tab 重开后 `workbench-b11` 读回；**无**自动 purge  
4. Grid app：`field-particle` 行为与文案一致（不叫「b11 记忆」）  
5. Alpha 热力：排序+来源+龄在 **运营台 tab + Tailscale** 双验  
6. Option：真数据前标 research-only  
7. 防睡眠：睡眠后手机 Serve 是否仍通  
8. INTENT：仅 UNIT；无 E2E_BOUND_PASS  
9. 因子工厂：可达性与健康口单一契约  
10. 长附件：明确「不支持文件，只支持粘贴」写在 UI  

---

## 13. 建议执行顺序（仍是少即是多）

1. **UI 契约钉死**（魂名 + 15∩10k + 召回2k + 非全量）  
2. **冻结/摘掉第二记忆路径**（8515 cloud、硬删、candidate）  
3. **入口减肥**（手机主导航 ≤5）  
4. **Alpha↔Aether 龄与热力语义**（用户认可前不算完）  
5. **运维灯诚实分报**（路径红 vs 内容红）  
6. **Option/Scout** 真数据前不进「主系统完成」  
7. **INTENT** 等 POOL/OFFPOOL + MEM_PHASE0  

---

## 14. 一句话

上一版混过去的是「运维与契约细节」；真正不能混的是：  
**多个入口共用「记忆」一词，却指向不同 store、不同预算、不同删除策略。**  
先定魂与注入契约并写进 UI，再砍面——否则每一轮「修复」都在制造下一轮失忆。

—— 复核补齐 · `[REDACTED: 身份]/SYSTEM_SIMPLIFY_MEMORY_COHERENCE_2026-08-03.md` · 2026-08-03
