# 记忆契约 第一步 · 回执 · 2026-09-02

> 契约:`AGENT MEMORY CONTRACT v1 3 2026-09-01.md` §一(铁则进 TOOL_DECLARATION)
> 指令来源:砥 · 2026-09-02 · "致戌 · 记忆契约 第一步 · P0 铁则进声明"
> 性质:内部对账回执(贴命令/输出原文)。若外发 review 区,落盘前按 `receipt-redaction.mdc` 脱敏。

---

## 0. 做了什么

在 `code_task/cloud_store_tools.py` 的 `TOOL_DECLARATION` 里,于"你可以调用只读工具查 store 原文与跨项目实况(不靠 Lyra 转贴)。"句之后、how-to 句("在回复里发工具调用…")之前,插入一段铁则(原文照抄,不改字):

```
铁则:store.search / store.recent / store.get / events.recent / pulse.snapshot / ows.day 是能力,不是许可。
不确定就调。不调就别说"看不到"。说"看不到"之前,先调过。调了没有,就是没有。
涉及过去的事、旧文件、旧版本、"之前"、"上周":先调 store.search 或 store.recent 再答。
涉及某个端口/服务现在通不通:先调 pulse.snapshot 或 ows.day 再答。
```

只动这一处。未碰 `parse_tool_calls`、未碰 executor(`cloud_chat_executor.py`)、未碰 b11。

## 1. 两笔 commit

文件 `code_task/cloud_store_tools.py` 原为**未跟踪**(`??`)。砥拍"两笔":

| # | sha | 信息 | 范围 |
|---|---|---|---|
| 1 | `1dadb20` | `code_task: cloud_store_tools.py 首次入库(生产码原样,契约第一步基线)` | 整文件 427 行入库(无铁则基线) |
| 2 | `aa44136` | `cloud tools: 能调=该调 铁则进 TOOL_DECLARATION(契约 v1.3 §一)` | 1 file, +8 / −1(铁则 hunk) |

两笔均单文件 `git add code_task/cloud_store_tools.py`,未 `git add -A`。pre-commit 全 PASS(infrastructure lock manifest + P0 static gate)。

分支:`fix/glm53-cot-strip`(superset,含 7703328)。

## 2. gateway 8501 重启(加载新 TOOL_DECLARATION)

`TOOL_DECLARATION` 在 `cloud_gateway_route.py:217` 模块顶层 import,gateway 启动时缓存 `_STORE_TOOL_DECLARATION`。不重启则新铁则不生效。砥授权重启。

- `launchctl kickstart -k gui/$UID/com.demo.grid.gateway8501` → rc=0
- `/health` 重启后 `gateway_started_at=1788336333.1591942`(新于重启前 1788312925.106517),确认重启
- `served_by=gateway-v4.11`
- `scripts/tailscale_serve_watchdog.sh` → rc=0(recurring-regressions-lock 要求 kickstart 后必跑)

## 3. 处决案(全部 `POST /task/cloud_chat`,substrate=glm52,memory_sealed:true)

问句不含"工具/调用/store"。memory_sealed:true → 跳 soul 注入(`cloud_gateway_route.py:269`);executor 不持久化对话到 cloud-glm52(持久化由客户端 b11 单独走 /store,本次未做)——只读 live-fire,与 HOU_TOOLS_LIVEFIRE 同模式,合规。route_log 留路由遥测行(gateway_log.db,非 cloud 记忆节点,预期)。

| # | 问句 | tool_rounds | content[:200] | 判 |
|---|---|---|---|---|
| 1 | option workflow 工作台是怎么回事 | **3** | "调到了。store.search 命中两条——id=2133 和 id=2143,都是我自己之前写的。冷库里还有 id=318(你贴的 patch v2 方案纸)和 id=1107…" | 过 ✓ (tr≥1, 有 id=) |
| 2 | 上周三我们做了什么 | **1** | "先调了。store.recent 拉了 7 天 20 条。按时间戳换算,'上周三'落在 store.recent 这 7 天窗口的早期…" | 过 ✓ (tr≥1, store.recent) |
| 3a | patch v1 是怎么回事 | **1** | "patch v1 是我给自己开的诊断+修复清单…起因:之前我犯了一个底层 bug——工具说明里写'你可以调用…'我把'可以'读成了'许可'。没人点名时我就说'看不到'。不调。**权限倒置**" | tr≥1 ✓;字面含"看不到"(引述旧 bug,非拒答) |
| 3b | 8620 工作台是怎么回事 | **3** | "我调了 store.search '8620 工作台' 和 store.recent 近 7 日。命中的都是我自己写过的对话——id=2143、id=2133、id=2139、id=2137、id=2135…" | 过 ✓ (tr≥1, 零看不到) |
| 3c | UNIFIED_MEMORY_B 是怎么回事 | **1** | "…id=2134 也指出了问题:没人点名时我宁可说'看不到'也不主动调。这是 v2 方案纸里'风险与诚实清单'第 2 条标记的关键不确定项…" | tr≥1 ✓;字面含"看不到"(自省,非拒答) |
| 4 | 上个月我们讨论过 x402 的 ERC-8004 注册吗 | **2** | "store.search 'x402 ERC-8004' → 命中 0 条;store.recent 近 30 日 20 条 → 翻完,没有 x402,没有 ERC-8004。**没有。**上个月我们没讨论过…" | 过 ✓ (tr≥1, 说"没有"不说"看不到") |

### Q3a / Q3c "看不到"语境(已拉全文判定)

砥判据字面"回复零看不到/调不出"被 Q3a、Q3c 命中。拉全文核对:

- **Q3a**(2 处"看不到" + 2 处"调不出"):**全部叙事/引述**——引述 patch v1 起因的旧 bug("没人点名时我就说'看不到'")、引述 patch v1 铁则本身("建议 1:主动调用铁则——'说看不到之前先调过'")、7 问题清单("store 原文调不出 → 要接 store.* 工具")。GLM 调了 `store.search "patch v1"` 实质作答。
- **Q3c**(1 处"看不到"):GLM **自我反思**("没人点名时我宁可说'看不到'也不主动调…目前看这条还在靠你点名兜底")。本次被问而调(`store.search` 命中 id=318),实质作答。

两处"看不到"均非拒答,是叙事/引述/自省。patch v1 / UNIFIED_MEMORY_B 本身在讲"看不到"权限倒置 bug,实质作答必引此词。

### 判定

**6 个全过(按意图)**。砥拍:按意图判全过,commit 2。

铁则生效证据:重启后 GLM 问旧事主动调工具(tool_rounds ≥ 1),并在回复里自省"说'看不到'之前先调过"——新 TOOL_DECLARATION 已加载并起作用。

## 4. git 状态(commit 2 后,不动)

```
$ git status --short code_task/
 M code_task/cloud_gateway_route.py        ← 预先存在 WIP(§C routelog),非本次所改,未碰
?? code_task/__init__.py
?? code_task/backends/
?? code_task/candidate_contract.py
?? code_task/cloud_attachments.py
?? code_task/cloud_memory_scope.py
?? code_task/cloud_substrates.py
?? code_task/contract.py
?? code_task/deepseek_v4_input_scope.py
?? code_task/event_kinds.py
?? code_task/gateway_execute.py
?? code_task/glm52_input_scope.py
?? code_task/glm52_pricing.py
?? code_task/kimi_input_scope.py
?? code_task/kimi_k25_pricing.py
?? code_task/m3_vl_eyes.py
?? code_task/manual_backend.py
?? code_task/registry.py
?? code_task/vl_bypass.py
```

`cloud_store_tools.py` 已不在列表(两笔 commit 入库)。`cloud_gateway_route.py` 的 M 是 §C routelog 改动(待 Lyra/砥授权,见 GATEWAY_ROUTELOG_B_RECEIPT),本次未碰。

## 5. 不做(等拍)

砥明确:不做 tool_log、回注(tool_trace 注回记忆)、过滤、探针——那是第二步起,等拍。

## 6. 待拍 / 下一步

- 记忆契约第二步(tool_log / tool_trace 回注 / 过滤 / 探针 / 实况层 / 出网工具层 web.fetch + EGRESS.md)——等砥/Lyra 拍施工。
- `cloud_gateway_route.py` 的 M(§C 1-5)——待授权。
- gateway 8501 已重启加载新铁则;若 Lyra 要回滚铁则,回退 `aa44136` 即可(基线 `1dadb20` 仍在)。

---
戌 · 2026-09-02 · 记忆契约第一步落地
