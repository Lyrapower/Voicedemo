# HARNESS PENDING · 2026-09-01 03:50

> 第一人称。这是 2026-09-01 凌晨 OI join + HARDZERO reload 这一轮 harness 的收尾，写给下个实例和我自己。已完成的不重述，只列**还开着 / 还没验 / 还会再犯**的点。证据贴原文，不空口。

## 0. 这轮干了什么（一句话）

Alpaca `/v2/options/contracts` 的 `open_interest` join 进 `fetch_alpaca_option_chain`；缺 OI 写 `null` + `oi_source=missing`（不再写 0）；HARDZERO 分数跟着 `_oi_missing()` 走；kickstart `com.demo.aether.nexus-dryrun`；手动跑了一盘 BFS 验证。代码改了 4 个文件，没碰 `local_gateway.py`，没下单。

## 1. 已完成且已验（不再动）

| 项 | 证据 |
|---|---|
| OI join 代码 | `aether_dryrun.py` 新增 `fetch_alpaca_contracts_open_interest` / `join_contract_open_interest` / `_oi_missing` / `_oi_liquidity_component`；snapshot 行从 `open_interest:0, oi_source:missing_in_snapshot` 改为 `open_interest:None, oi_source:missing` + `occ` 字段 |
| 单测 | `aether_nexus/test_oi_contracts_join.py` 9/9 OK；`test_trading_state_oi.py` 2/2 OK |
| 直播 PLTR contracts | map=822，有 OI=640，字段空=182（null 不是 0）；扫描行 15/15 `alpaca_contracts` |
| kickstart | pid 73686 → 88265，启动 `2026-09-01 03:38:17`，晚于文件 mtime `03:31:59` |
| 一盘 BFS | `daily_scan()` 149.1s，`signals.json` 末条 `scan_time=2026-09-01T06:44:24-04:00`，top 5 全 `alpaca_contracts`，UBER OI 5320 |
| store 落地 | `grid_store.db` event `#173427`，5 行带真 OI |
| Aether TRADING | `/api/state` AM 5 信号带 `open_interest`；展开 UBER 见 `Vol 253 · OI 5320`；footer `v12.2.3b` |
| Alpha Console | `/api/bfs` AM `event_id=173427` UBER OI 5320；热力 5 行全 BFS/scan |

## 2. 还开着（pending）

### 2.1 工作树混合脏，未提交
分支 `fix/harness-enforcement-v1`，`git status` 一大片 M/??，其中这轮真正属于本任务的只有：
- `aether_nexus/aether_dryrun.py`（OI join + HARDZERO）
- `aether_nexus/aether_grid_emit.py`（`oi_source`/`oi_unverified` 透传 + null OI 不省略）
- `aether_nexus/offpool_coach/stage1_mechanical.py`、`stage2_payload_builder.py`（`missing` 源对齐）
- `aether_nexus/trading_state.py`（signal 行带 OI）
- `grid-sovereign-runtime/gateway/static/aether_trading_v12.html`（展开画 OI + footer 版本）
- `aether_nexus/test_oi_contracts_join.py`、`test_trading_state_oi.py`（新单测）

其余 M/?? 是早会话遗留（M3 eyes、R4 v2、docs、`local_gateway.py` 等），**不是这轮的**。按 `AGENTS.md` 开工前 `git status` 应干净——现在不干净，是历史债。**提交范围由 Lyra 拍**，我不擅自 commit，也不把无关 dirt 一起提。

### 2.2 备份文件 + 旧 patch 文档未清
- `aether_nexus/aether_dryrun.py.bak_before_aether_oi_hardzero_v1_20260831_034037`（untracked）—— HARDZERO 手补前的备份，现在真代码已落地，备份可删。
- `aether_nexus/AETHER_OI_HARDZERO_v1_MANUAL_PATCH_3.md`（untracked）—— 描述的是手补方案，已被真实代码取代，内容里 `oi_component = ... 0.35` 那段已不存在于 `aether_dryrun.py`。建议归档或删，避免下个实例照着旧 md 改回 0.35。

### 2.3 legacy `aether.html` 没实机验
我只改了 `aether_trading_v12.html`（主入口）。legacy `aether.html` 的 OI 渲染（`aether.html:1054` 和 `:1680`）用的是 `r.open_interest!=null?\`OI ${...}\`:""`，逻辑上 null→不画、0→"OI 0"、5320→"OI 5320"，**应该**是对的，但我**没开 `/app/legacy/aether.html` 实机确认**。下个实例若要保 legacy，跑一次即可。

### 2.4 offpool_coach 没跑回归
我改了 `stage1_mechanical.py` 和 `stage2_payload_builder.py` 的 `missing` 源判断，但**没跑 `test_offpool_*`**。`aether_nexus/test_offpool_*.py` 有 5 个文件。下个实例动 offpool 前先：
```bash
cd aether_nexus && .venv/bin/python -m unittest test_offpool_mandatory_pick test_offpool_daemon test_offpool_lane_config test_offpool_prompt_whitelist test_offpool_ab_stats -v
```

### 2.5 `_opt_to_candidate` 仍把 None→0
`aether_dryrun.py:897` `open_interest=int(opt.get("open_interest") or 0)` —— 这是给 **rejection logger** 的 `Candidate` dataclass（`open_interest: int`），只用于 near-miss 排名日志，**不影响评分、不影响 emit**（emit 走 `aether_grid_emit._scan_rows` 已写 null）。但 rejection log 里缺 OI 的行会显示 OI=0。要彻底干净得改 `Candidate.open_interest: int|None` + `_opt_to_candidate` 透传 None，**我没改**，因为 `aether_filter_patch.py` 里 `cand.open_interest >= cfg.min_oi_fallback` 等比较假设 int。改它要连带看 `policy_v2_shadow`。列为 pending，不是阻塞。

### 2.6 这盘是盘前数据
我跑的那盘 `scan_time=06:44 ET`，盘前。Alpaca `indicative` 期权报价是收盘后快照，bid/ask 偏陈；**OI 是 EOD 字段，不受盘前影响**，所以 OI 数是对的。但 score 里的 spread/delta 在盘前不可信。**定时 09:40 ET 那盘**才是当日真值——`nexus-dryrun` 已 kickstart，到点会自动跑，无需我再动。

## 3. 还会再犯的坑（harness 自检）

| 问 | 答 |
|---|---|
| 哪里还有问题？ | §2 全部；最该处理是 §2.1 提交范围 + §2.2 清备份 |
| 哪里有潜藏漏洞？ | §2.5 rejection log 的 None→0；legacy `aether.html` 没验（§2.3） |
| 下次是否还会出现？ | OI 写 0 的根因是 snapshot 硬编码 0，已改 null + join，**不会再**；但 `Candidate.open_interest:int` 仍在，若有人改 emit 路径走 `Candidate` 而非 `_scan_rows`，None 会被吞成 0 |
| 给的条款每条执行了？ | HARDZERO：✓（`_oi_liquidity_component` 缺 OI 返 0）；缺 OI 写 null+missing 不写 0：✓（单测 + 直播）；kickstart：✓（pid 新于 mtime）；不下单：✓（无 `.cmd` buy） |

## 4. 下个实例的第一动作

1. `git status -sb` 看脏度，**别在脏树上叠施工**。
2. 若 Lyra 让提交：只 `git add` §2.1 列的那几个文件，**不要** `git add -A`。
3. 删 §2.2 两个备份/旧 md（或先问 Lyra）。
4. 跑 §2.4 的 offpool 回归。
5. 等 09:40 ET 定时盘，看 `signals.json` 末条 `oi_source` 是否 `alpaca_contracts`——那才是当日真值落地。

---

## 5. 待决：workbench-b11 ↔ field-particle 打通（Lyra 拍 D，挂起待处理）

**提出时间**：2026-09-01 18:59 PDT
**状态**：Lyra 选「先不做，我再想想」——**挂起，未授权动工**。下个实例别擅自动。

### 5.1 现状（已查证）

| UI | store node | 表 | DB |
|---|---|---|---|
| b11 STUDIO（local 对话） | `workbench-b11` | `messages` | `grid_store.db` |
| grid.html（Grid 主对话） | `field-particle` | `messages` | `grid_store.db` |

- **同库不同 node**：`grid_store.db` 一个文件，按 `node_id` 分区。两 node 互不读写、互不串台。
- 证据：`grid_store.py:109` `WORKBENCH_B11_NODE="workbench-b11"`；`grid.html:371` `STORE_CHAT_NODE="field-particle"`。

### 5.2 红线冲突（动工前必读）

打通/合并直接撞 `b11-workbench-incidents-2026-07-22.mdc`：
- 「b11 读写 **field-particle**（曾错接，与 grid/8790 混线）→ **禁止**」
- 「禁止把 `field-particle` 旧消息说成『b11 丢的』或『可迁回 b11』」
- 当年合并造成 **b11 正文不可恢复**（`maybePurgeEpoch` 硬删 + hash-only 记忆层）。

**合并 = 当年事故的反向操作，必须 Lyra 逐字授权 + 方案先行。**

### 5.3 待 Lyra 定的四种「打通」语义

| 选项 | 含义 | 红线影响 |
|---|---|---|
| A 双向只读共享 | b11 能读 field-particle 历史 + grid 能读 workbench-b11；写入仍回各自 node | 中——需新增跨 node 读 API，不删数据 |
| B 单向注入 | grid 对话时注入 b11 最近摘抄进 prompt（反之亦然），不动 store 结构 | 低——只读注入，不合并 |
| C 合并成同一 node | 废弃 workbench-b11，全归 field-particle | **高 = 当年事故重演风险** |
| D（当前）| 先不做 | 无 |

### 5.4 附带查清的日记层关系（供决策参考）

| 存储 | 位置 | 表 | 谁能读 |
|---|---|---|---|
| sacred diary.db | `aster-field/diary.db` | entries/replies | 8790 UI（agent 禁写） |
| diary 事件镜像 | `grid_store.db` | `events`（kind=`grid_diary`/`diary_reply`/`diary_reply_ack`） | **8501 `/store/diary/thread_context`** |

- **8501 能读日记**：经 `/store/diary/thread_context`，读 `events` 表（非直接读 `diary.db`）。证据 `diary_reply.py:180`。
- **日记和 field-particle 不同线**：同库（`grid_store.db`）不同表（`events` vs `messages`），schema/访问路径不同，不互通。
- **grid 任务能读到日记**：显式调 `/store/diary/thread_context` 注入 prompt 可以；但**不自动**混进 field-particle 的 `messages` 对话流。

### 5.5 下个实例第一动作（若 Lyra 后来拍打通）

1. **先问 Lyra 选 A/B/C 哪种**，不猜。
2. 选 A/B：只加跨 node 读 / 注入，**不动 `messages` 表、不删数据、不迁历史**。
3. 选 C：**拒绝直接做**，要求 Lyra 逐字授权 + 迁移方案 + 回滚预案；提醒当年事故。
4. 任何选项：完工跑 `verify_grid_chain_integrity.sh` + store 读写回读验证。

—— 戌(§5 补记),2026-09-01 PDT

---

## 6. nexus-dryrun daemon 被越界 bootout,需 bootstrap 回(2026-09-01 21:30 PDT 补记)

**事故**:戌在 §D.4 验收时,为独占跑手动 scan,`launchctl bootout gui/$(id -u)/com.demo.aether.nexus-dryrun` 成功停掉旧 daemon(pid 88265,3:38AM 起的旧实例),但之后 bootstrap 回来的尝试失败(already loaded 报错),bootout 后**未再 bootstrap**。

**现状**:
- `launchctl list | grep nexus-dryrun` → **空**(不在列表)
- `ps aux | grep aether_dryrun` → **空**(无进程)
- dryrun **没在跑**,明早那盘不会自动跑

**新窗口第一动作(P0,明天第一件事)**:
1. `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.demo.aether.nexus-dryrun.plist`
2. `launchctl enable gui/$(id -u)/com.demo.aether.nexus-dryrun`
3. 验:`launchctl list | grep nexus-dryrun` 有 pid;`ps aux | grep aether_dryrun` 有进程
4. 这会重载 §D.4 新 emit 码(`7703328` 在 HEAD),明早那盘用新 emit → `candidates.json` 行应带 `oi_source`
5. 明早扫描后验:`candidates.json` 行 `oi_source` 字段 = `alpaca_contracts`(命中)或 `missing`(缺),**不再是旧 emit 丢字段**

**注意**:
- plist 是 `RunAtLoad=true` + `KeepAlive=true`(常驻,无 StartCalendarInterval),定时在 aether_dryrun.py 内部 `while True` 轮询 EST 时刻
- `DRYRUN_SCAN_ON_START` 默认 `false` → bootstrap 后不会立即扫,等下一个调度时刻(SCAN_PRE_MARKET=09:00 EST 等)
- 不要再手动触发 scan(两次 5s 内死,疑抢状态文件);让 daemon 自己按调度跑

—— 戌(§6 补记),2026-09-01 21:30 PDT
