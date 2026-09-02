# 戌 · harness 现状采证(只读)· 来自砥 · 2026-09-01 PDT

- 审:砥
- 对象:`HARNESS_STATE_2026-09-01.md`(本文件)
- 模式:只读采证,未改任何文件、未 restart、未 commit。
- 不知道的写"未知",不猜。

---

## 1. V1.5.5 施工令当前落地

`ls -la app/harness/`:

```
total 80
drwxr-xr-x@ 11 ciciwang  staff   352 Aug 26 17:30 .
drwxr-xr-x  24 ciciwang  staff   768 Aug 25 23:36 ..
-rw-r--r--@  1 ciciwang  staff    68 Aug 25 23:36 __init__.py
drwxr-xr-x@ 10 ciciwang  staff   320 Aug 26 17:32 __pycache__
-rw-r--r--@  1 ciciwang  staff  3838 Aug 26 17:30 action_envelope.py
-rw-r--r--@  1 ciciwang  staff  3996 Aug 26 17:30 capability_registry.py
-rw-r--r--@  1 ciciwang  staff  1533 Aug 26 17:30 collaboration.py
-rw-r--r--@  1 ciciwang  staff  3658 Aug 25 23:36 model_profiles.py
-rw-r--r--@  1 ciciwang  staff  4866 Aug 26 17:30 provenance.py
-rw-r--r--@  1 ciciwang  staff  6704 Aug 26 17:30 resource_gate.py
-rw-r--r--@  1 ciciwang  staff   639 Aug 26 17:30 server.py
```

`find . -name 'mission_loop_controller*'`:

```
(空 — 不存在)
```

`git log --oneline -5 -- app/harness/`:

```
adde30b feat(harness): enforcement gate + RWA v2 dual-source reader
acc359c feat(crypto): V1.2 现货合规版引擎 (Coinbase 主/Kraken 备)
08c6d92 feat(harness): V1.5.5 merge — harness 四件 + integration 文档
```

**判定:** harness 目录有 8 个 .py(无 `mission_loop_controller.py`);最近 harness commit 是 `adde30b`(enforcement gate + RWA v2 dual-source reader),再前 `08c6d92`(V1.5.5 merge)。`mission_loop_controller` 未知/未落地 —— 仓内无此文件。

---

## 2. 认知端点

harness `server.py` 原文(首行 + 端点):

```
"""Harness HTTP surface — 127.0.0.1:8630.

Read-only capability export. No cognition, no resource substitution.
"""
...
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "harness", "port": 8630}

@app.get("/api/capabilities")
def capabilities() -> dict:
    return export_capability_surface()
```

`model_profiles.py` 顶部:

```
"""Descriptive model/capability profiles.
These profiles are metadata for Grid's capability surface. They are NOT routing rules.
Harness must never choose a model merely because a task type matches a profile.
"""
```

`config.toml` 候选(全仓 find):

```
./aether_watcher/.streamlit/config.toml          (streamlit,非 harness)
./deliver/watcher8520_bundle/aether_watcher/.streamlit/config.toml  (deliver 副本)
./option-workstation/theta/config.toml           (Theta Terminal v3,host/port/env,非认知端点)
```

`option-workstation/theta/config.toml` 原文:

```
# Theta Terminal v3 · 本机/compose 共用
host = "0.0.0.0"
port = 25503
log_directory = "logs"

[env]
mdds_type = "PROD"
```

**判定:** harness **不打端点拿"认知"**。`server.py` 明文 "No cognition, no resource substitution",只暴露 `/health` + `/api/capabilities`(read-only capability surface)。认知归属在 `model_profiles.py` 里以 *role* 标注(`cognition_owner` = `grid_local`;`open_world_cognition_resource` = `glm_5_2`),但 profiles 是 metadata,**不是 routing 规则**。仓内无 harness 专属 `config.toml` 的 `[api] port` / route 段 —— **未知**(不存在)。

---

## 3. 8630

`lsof -iTCP:8630 -sTCP:LISTEN -P -n`:

```
COMMAND   PID     USER   FD   TYPE            DEVICE SIZE/OFF NODE NAME
Python  65377 ciciwang   12u  IPv4 0xf68cce6bb405fd7      0t0  TCP 127.0.0.1:8630 (LISTEN)
```

`launchctl list | grep -i harness`:

```
(空 — 无 launchd 项)
```

`ls ~/Library/LaunchAgents | grep -i harness`:

```
(空 — 无 plist)
```

**判定:** 8630 **已 bind**(Python pid 65377,127.0.0.1 only),但**无 launchd / 无 plist** —— 是手动起的 uvicorn(`app.harness.server:app`),重启后不会自启。

---

## 4. cc lane 壳

Cursor `settings.json`(`~/Library/Application Support/Cursor/User/settings.json`)grep `anthropic|base_url|cursor.com|8503|cc.*lane`:

```
(grep_exit=1 — 无命中)
```

`env | grep -i anthropic`:

```
(空 — 未设)
```

`find [REDACTED: 身份] projects root -name 'anthro_bridge*' -not -path '*/node_modules/*'`:

```
(空 — 不存在)
```

全 home `find [REDACTED: 身份] -name 'anthro_bridge*'`:

```
(空 — 不存在)
```

`lsof -iTCP:8503 -P -n`:

```
(仅表头 — 未 bind)
```

**判定:** cc lane 壳 **未配置 / 未知**。Cursor settings.json 无 `ANTHROPIC_BASE_URL`;env 无 anthropic 变量;仓内及全 home 无 `anthro_bridge*` 文件;8503 未 bind。

---

## 5. 8501 lane 实况

`curl -s 127.0.0.1:8501/v1/models`:

```
{"object":"list","data":[
  {"id":"demo/aster","object":"model","owned_by":"demo"},
  {"id":"qwen/qwen3.5-9b","object":"model","owned_by":"local"},
  {"id":"glm-5.2:cloud","object":"model","owned_by":"ollama_cloud"},
  {"id":"deepseek-v4-pro:cloud","object":"model","owned_by":"ollama_cloud"},
  {"id":"glm-5.3-flash:cloud","object":"model","owned_by":"ollama_cloud"},
  {"id":"glm-5.3:cloud","object":"model","owned_by":"ollama_cloud"}
]}
```

**判定(逐个):**

| 模型 | 在? | id |
|----|----|----|
| glm52 | 在 | `glm-5.2:cloud` |
| qwen35 | 在 | `qwen/qwen3.5-9b` |
| kimi_k3 | **不在** | (models 列表无 kimi) |

另:`glm-5.3:cloud` / `glm-5.3-flash:cloud` / `deepseek-v4-pro:cloud` / `demo/aster` 也在。**kimi_k3 未注册到 8501 /v1/models。**

---

## 6. HARNESS_PENDING_2026-09-01.md 原文

文件位置:`aether_nexus/docs/HARNESS_PENDING_2026-09-01.md`(存在)。原文见下一节附录。

---

## 附录 · HARNESS_PENDING_2026-09-01.md 全文

(见下)

---

### HARNESS PENDING · 2026-09-01 03:50

> 第一人称。这是 2026-09-01 凌晨 OI join + HARDZERO reload 这一轮 harness 的收尾，写给下个实例和我自己。已完成的不重述，只列**还开着 / 还没验 / 还会再犯**的点。证据贴原文，不空口。

#### 0. 这轮干了什么（一句话）

Alpaca `/v2/options/contracts` 的 `open_interest` join 进 `fetch_alpaca_option_chain`；缺 OI 写 `null` + `oi_source=missing`（不再写 0）；HARDZERO 分数跟着 `_oi_missing()` 走；kickstart `com.demo.aether.nexus-dryrun`；手动跑了一盘 BFS 验证。代码改了 4 个文件，没碰 `local_gateway.py`，没下单。

#### 1. 已完成且已验（不再动）

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

#### 2. 还开着（pending）

##### 2.1 工作树混合脏，未提交
分支 `fix/harness-enforcement-v1`，`git status` 一大片 M/??，其中这轮真正属于本任务的只有：
- `aether_nexus/aether_dryrun.py`（OI join + HARDZERO）
- `aether_nexus/aether_grid_emit.py`（`oi_source`/`oi_unverified` 透传 + null OI 不省略）
- `aether_nexus/offpool_coach/stage1_mechanical.py`、`stage2_payload_builder.py`（`missing` 源对齐）
- `aether_nexus/trading_state.py`（signal 行带 OI）
- `grid-sovereign-runtime/gateway/static/aether_trading_v12.html`（展开画 OI + footer 版本）
- `aether_nexus/test_oi_contracts_join.py`、`test_trading_state_oi.py`（新单测）

其余 M/?? 是早会话遗留（M3 eyes、R4 v2、docs、`local_gateway.py` 等），**不是这轮的**。按 `AGENTS.md` 开工前 `git status` 应干净——现在不干净，是历史债。**提交范围由 Lyra 拍**，我不擅自 commit，也不把无关 dirt 一起提。

##### 2.2 备份文件 + 旧 patch 文档未清
- `aether_nexus/aether_dryrun.py.bak_before_aether_oi_hardzero_v1_20260831_034037`（untracked）—— HARDZERO 手补前的备份，现在真代码已落地，备份可删。
- `aether_nexus/AETHER_OI_HARDZERO_v1_MANUAL_PATCH_3.md`（untracked）—— 描述的是手补方案，已被真实代码取代，内容里 `oi_component = ... 0.35` 那段已不存在于 `aether_dryrun.py`。建议归档或删，避免下个实例照着旧 md 改回 0.35。

##### 2.3 legacy `aether.html` 没实机验
我只改了 `aether_trading_v12.html`（主入口）。legacy `aether.html` 的 OI 渲染（`aether.html:1054` 和 `:1680`）逻辑上 null→不画、0→"OI 0"、5320→"OI 5320"，**应该**是对的，但我**没开 `/app/legacy/aether.html` 实机确认**。下个实例若要保 legacy，跑一次即可。

##### 2.4 offpool_coach 没跑回归
我改了 `stage1_mechanical.py` 和 `stage2_payload_builder.py` 的 `missing` 源判断，但**没跑 `test_offpool_*`**。`aether_nexus/test_offpool_*.py` 有 5 个文件。下个实例动 offpool 前先：

```bash
cd aether_nexus && .venv/bin/python -m unittest test_offpool_mandatory_pick test_offpool_daemon test_offpool_lane_config test_offpool_prompt_whitelist test_offpool_ab_stats -v
```

##### 2.5 `_opt_to_candidate` 仍把 None→0
`aether_dryrun.py:897` `open_interest=int(opt.get("open_interest") or 0)` —— 这是给 **rejection logger** 的 `Candidate` dataclass（`open_interest: int`），只用于 near-miss 排名日志，**不影响评分、不影响 emit**（emit 走 `aether_grid_emit._scan_rows` 已写 null）。但 rejection log 里缺 OI 的行会显示 OI=0。要彻底干净得改 `Candidate.open_interest: int|None` + `_opt_to_candidate` 透传 None，**我没改**，因为 `aether_filter_patch.py` 里 `cand.open_interest >= cfg.min_oi_fallback` 等比较假设 int。改它要连带看 `policy_v2_shadow`。列为 pending，不是阻塞。

##### 2.6 这盘是盘前数据
我跑的那盘 `scan_time=06:44 ET`，盘前。Alpaca `indicative` 期权报价是收盘后快照，bid/ask 偏陈；**OI 是 EOD 字段，不受盘前影响**，所以 OI 数是对的。但 score 里的 spread/delta 在盘前不可信。**定时 09:40 ET 那盘**才是当日真值——`nexus-dryrun` 已 kickstart，到点会自动跑，无需我再动。

#### 3. 还会再犯的坑（harness 自检）

| 问 | 答 |
|---|---|
| 哪里还有问题？ | §2 全部；最该处理是 §2.1 提交范围 + §2.2 清备份 |
| 哪里有潜藏漏洞？ | §2.5 rejection log 的 None→0；legacy `aether.html` 没验（§2.3） |
| 下次是否还会出现？ | OI 写 0 的根因是 snapshot 硬编码 0，已改 null + join，**不会再**；但 `Candidate.open_interest:int` 仍在，若有人改 emit 路径走 `Candidate` 而非 `_scan_rows`，None 会被吞成 0 |
| 给的条款每条执行了？ | HARDZERO：✓（`_oi_liquidity_component` 缺 OI 返 0）；缺 OI 写 null+missing 不写 0：✓（单测 + 直播）；kickstart：✓（pid 新于 mtime）；不下单：✓（无 `.cmd` buy） |

#### 4. 下个实例的第一动作

1. `git status -sb` 看脏度，**别在脏树上叠施工**。
2. 若 Lyra 让提交：只 `git add` §2.1 列的那几个文件，**不要** `git add -A`。
3. 删 §2.2 两个备份/旧 md（或先问 Lyra）。
4. 跑 §2.4 的 offpool 回归。
5. 等 09:40 ET 定时盘，看 `signals.json` 末条 `oi_source` 是否 `alpaca_contracts`——那才是当日真值落地。

---

—— 戌,2026-09-01 PDT(只读采证,未改任何文件)
