# nexus-dryrun Bootstrap 回执 · 2026-09-02 00:20 PDT

> 第一人称。P0 第一动作(nexus-dryrun daemon bootstrap 回)的验收回执。证据贴命令原文 + 输出原文,不空口。
> 出:戌(Cursor GLM 5.2 新窗口)· Lyra 令

---

## 0. 任务

HARNESS_PENDING_2026-09-01.md §6 补记:戌在 §D.4 验收时 `launchctl bootout` 停了旧 daemon(pid 88265,3:38AM 起)后未 bootstrap 回 → daemon 没在跑,明早那盘不会自动跑。本回执执行 §6 的 P0 第一动作:bootstrap + enable + 验。

---

## 1. 执行的命令 + 输出原文

### 1.1 bootstrap + enable

```
$ launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.demo.aether.nexus-dryrun.plist
exit=0
$ launchctl enable gui/$(id -u)/com.demo.aether.nexus-dryrun
exit=0
```

### 1.2 验收:launchctl list + ps

bootstrap 后立即 `ps` 空是 bash→python 启动有延迟;sleep 3s 后:

```
$ launchctl list | grep nexus-dryrun
75494	0	com.demo.aether.nexus-dryrun

$ ps aux | grep aether_dryrun | grep -v grep
ciciwang  75494  0.0  0.3  435458096  43888  ??  S  12:20AM  0:00.92 /Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python aether_dryrun.py

$ pgrep -fl aether_dryrun
75494 /Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python aether_dryrun.py
```

- pid 75494,状态 `S`(sleeping,等调度),启动 12:20AM(=bootstrap 时刻)
- launchctl list 第二列 `0` = last exit 0

### 1.3 日志确认干净启动

`~/Library/Logs/demo-aether/nexus-dryrun.err.log` 末尾:

```
2026-09-02 00:20:53,094 - INFO - ============================================================
2026-09-02 00:20:53,095 - INFO - Aether Nexus R5.4.1 — Data-Hardened Dry Run (integrated)
2026-09-02 00:20:53,095 - INFO - Stock providers: ['fmp', 'alpaca']
2026-09-02 00:20:53,095 - INFO - Option providers: ['alpaca']
2026-09-02 00:20:53,095 - INFO - Alpaca configured: YES | stock_feed=iex option_feed=indicative
2026-09-02 00:20:53,095 - INFO - BFS mode: SP500 @ 09:40 / 15:30 EST
2026-09-02 00:20:53,095 - INFO - Pool scan: 09:35 / 15:20 EST (18 symbols)
2026-09-02 00:20:53,095 - INFO - Perilla scan: 08:30 EST (reminder 08:25)
2026-09-02 00:20:53,095 - INFO - Buy reminders: 09:40 / 15:25 EST
2026-09-02 00:20:53,095 - INFO - ============================================================
```

- 新实例 00:20:53 起(匹配 bootstrap 时刻),banner R5.4.1
- `BFS mode: SP500 @ 09:40 / 15:30 EST` → 调度模式,**未立即扫**(`DRYRUN_SCAN_ON_START=false` 生效)
- 无 crash、无 traceback
- 12:33 PDT 那批旧日志是 bootout 前的旧实例(pid 88265)留下,新实例不继承其状态

### 1.4 plist 内容(确认 RunAtLoad+KeepAlive,无 StartCalendarInterval)

```
Label: com.demo.aether.nexus-dryrun
ProgramArguments: /bin/bash /Users/ciciwang/Projects/demo/scripts/aether/start_nexus_dryrun.sh
WorkingDirectory: /Users/ciciwang/Projects/demo/aether_nexus
RunAtLoad: true / KeepAlive: true
(无 StartCalendarInterval — 定时在 aether_dryrun.py 内部 while True 轮询 EST)
```

---

## 2. P0 验收结论

| 验收项 | 结果 | 证据 |
|---|---|---|
| bootstrap exit 0 | ✅ | §1.1 |
| enable exit 0 | ✅ | §1.1 |
| launchctl list 有 pid | ✅ pid 75494 | §1.2 |
| ps 有 aether_dryrun 进程 | ✅ pid 75494 状态 S | §1.2 |
| 干净启动无 crash | ✅ | §1.3 |
| 未立即扫(等调度) | ✅ BFS @ 09:40 EST | §1.3 |
| 重载 §D.4 新 emit 码 | ✅ 磁盘 aether_dryrun.py mtime Sep 1 13:48,signals.json entry[88] 已带 oi_source(见 §3) | §3 |

**P0 动作完成。daemon 常驻,明早 09:40 EST 那盘会自动跑,用新 emit 码。**

---

## 3. §四矛盾定论(r1 §7 vs §E.7)

HARNESS_PENDING §四:旧窗口两份回执互相否定。戌只读核查后定论。

### 3.1 r1 §7 — 正确

> `aether_nexus/dryrun_state/signals.json` 存在,90 条,末条 2026-09-01T15:33:33-04:00(12:33 PDT),5/5 oi_source=alpaca_contracts

戌核查:

```
$ ls -la aether_nexus/dryrun_state/signals.json
-rw-------@ 1 ciciwang  staff  465017 Sep 1 20:47 .../dryrun_state/signals.json

$ python3 -c "import json;d=json.load(open('.../dryrun_state/signals.json'));print(len(d))"
90

# entry[88] scan_time=2026-09-01T15:33:33.161843-04:00 scan_mode=sp500 ncands=5
# first candidate keys 含 'oi_source','oi_unverified','open_interest','occ'
# oi_source values: ['alpaca_contracts','alpaca_contracts','alpaca_contracts','alpaca_contracts','alpaca_contracts']
# open_interest sample: [6700, 26901, 1561, 27108, 235]
# oi_unverified: false
```

**r1 §7 属实。** signals.json 在 `dryrun_state/`(不是 `state/`),90 行,15:33:33-04:00 那条 5 candidate 全 `oi_source=alpaca_contracts` + 真 OI。§D.4 emit 代码在磁盘上且旧实例 12:33 那盘已用。

### 3.2 §E.7 — 两处错 + 一处对

§E.7 原文:"全盘找不到 signals.json;`state/candidates.json` 五行无 oi_source/open_interest 字段,scan_timestamp 15:33:33(它读作 Z=08:33 PDT);nexus-dryrun 不在 launchd,无进程。"

| §E.7 主张 | 戌核查 | 判定 |
|---|---|---|
| "全盘找不到 signals.json" | `dryrun_state/signals.json` 存在(465KB,90 行) | **错** — §E.7 漏看 `dryrun_state/` 目录,只看了 `state/` |
| "`state/candidates.json` 五行无 oi_source" | `state/candidates.json` 是 **rejection-logger 的 Candidate dump**,与 signals.json 是**两个不同文件**。Candidate dataclass(`open_interest:int`)设计上无 oi_source —— 这是 HARNESS_PENDING §2.5 已记录的 pending,不是 §D.4 修的范围 | **§E.7 把两个文件混成一个**;但"state/candidates.json 无 oi_source"本身属实(§2.5 pending,非 §D.4 缺陷) |
| "scan_timestamp 15:33:33 读作 Z=08:33 PDT" | signals.json entry[88] scan_time 带明确 `-04:00` 时区后缀(EDT),非 Z。§E.7 把 `-04:00` 当 UTC 误读 4 小时 | **错** — 时区误读 |
| "nexus-dryrun 不在 launchd,无进程" | 戌 §6 补记已记录:戌自己在 §D.4 验收时 bootout 后未 bootstrap 回造成。**本回执 §1 已修复** | **当时属实,现已修** |

### 3.3 定论

- **r1 §7 全对。** signals.json(emit 路径)在 `dryrun_state/`,§D.4 后带 `oi_source`/`oi_unverified`/`occ`/真 OI。
- **§E.7 把 `state/candidates.json`(rejection-logger dump)当成了 signals.json**,漏看 `dryrun_state/` 目录;又把 `-04:00` 时区当 UTC 误读 4 小时。
- **但 §E.7 点出的"`state/candidates.json` 无 oi_source"是真实的 §2.5 pending** —— rejection-logger 的 `Candidate` dataclass 设计上只有 `open_interest:int`、无 `oi_source`,不影响评分/emit(emit 走 `aether_grid_emit._scan_rows`),只影响 near-miss 排名日志显示。**不是 §D.4 的缺陷,§D.4 没承诺修它。**

### 3.4 附带发现:signals.json 末条是空扫描

```
entry[89] scan_time=2026-09-01T23:47:46.571345-04:00 scan_mode=sp500 candidates=[] top_pick=null
```

- 23:47 EDT = 20:47 PDT Sep 1。非调度时刻(调度 09:40/15:30 EST),疑旧实例(pid 88265)在戌 21:30 bootout 前跑的一盘盘外兜底扫描,结果空(盘外 indicative 报价陈)。
- `state/candidates.json` 当前 `rows=[]`、`scan_timestamp=2026-09-01T23:47:46` 与这条空扫描对得上 → state/candidates.json 是这条空扫描的 rejection-logger dump。
- **不影响明早 09:40 EST 调度盘**,新实例会重新扫。

---

## 4. 待 Lyra 拍 / 待明早验

### 4.1 oi_source 验证目标歧义(待 Lyra 拍)

P0 指令原文:"扫描后验 candidates.json 行 oi_source = alpaca_contracts/missing,不再丢字段"。

戌发现"candidates.json"指代有歧义,不替 Lyra 选,列两解:

| 解 | 含义 | 戌已查 |
|---|---|---|
| A | 指 `dryrun_state/signals.json` 里每个 signal 的 `candidates[]` 行(emit 路径) | **已验**:entry[88] 5 行全 `oi_source=alpaca_contracts` + 真 OI(§3.1)。明早 09:40 EST 后查末条即可复验 |
| B | 指 `state/candidates.json`(rejection-logger dump) | **未修**:此文件设计上无 oi_source 字段(§2.5 pending,Candidate dataclass `open_interest:int`)。§D.4 没修它 |

戌推荐 A(emit 路径是 §D.4 的实际修复范围,且已验过)。若 Lyra 要 B 也带 oi_source,那是新任务(改 `Candidate` dataclass + `_opt_to_candidate` + `aether_filter_patch.py` 比较假设 + `policy_v2_shadow`),需另开单。**戌不擅自做 B。**

### 4.2 明早 09:40 EST 后验(延后验收)

按 P0 指令"不要再手动触发 scan",戌不手动扫。明早 09:40 EST 调度盘跑完后验:

```
# signals.json 末条 candidates[].oi_source
python3 -c "import json;d=json.load(open('aether_nexus/dryrun_state/signals.json'));e=d[-1];print(e['scan_time']);[print(c['symbol'],c.get('oi_source'),c.get('open_interest')) for c in e['candidates']]"
# 期望:oi_source = alpaca_contracts(命中)或 missing(缺),open_interest 为真值或 null
```

### 4.3 分支与脏树(报 Lyra 知)

- handoff §二.1 说开工分支应为 `fix/harness-enforcement-v1`;戌 `git status -sb` 实际在 `fix/glm53-cot-strip`。**不一致**。
- 脏树是历史债(handoff §三/§2.1 已述),戌未在脏树上叠施工,本次 P0 只动 launchd 状态(未改任何 repo 文件,除本回执)。
- 是否要切回 `fix/harness-enforcement-v1` 由 Lyra 拍;戌不擅自动分支。

### 4.4 回执存放位置(报 Lyra 知)

- XU_TRAITS 说回执放 `~/Desktop/demo/aether_nexus/docs/`;handoff §一.2 说"只留 repo 一份,Desktop 不再同步"。
- 两处冲突。戌按 handoff(更新、明确)放 repo:`/Users/ciciwang/Projects/demo/aether_nexus/docs/`。
- 若 Lyra 要同步回 Desktop 或改以 Desktop 为准,请示下。

---

## 5. 自检(harness)

| 问 | 答 |
|---|---|
| 哪里还有问题? | §4 全部;最该 Lyra 拍是 §4.1 验证目标歧义(A/B) |
| 哪里有潜藏漏洞? | §4.3 分支不一致(handoff 期望 vs 实际);§3.4 末条空扫描来源未完全定性(疑旧实例兜底,非阻塞) |
| 下次是否还会出现? | daemon bootout 后未 bootstrap 回 —— 本次已修且验;但根因(戌 §D.4 验收时手动 bootout)的防护靠戌特质"只读采证与施工分开",无机器门禁。若 Lyra 要硬门禁(如 bootstrap 后强制 health check 脚本),另开单 |
| 给的条款每条执行? | bootstrap:✓ exit 0;enable:✓ exit 0;验 launchctl list 有 pid:✓ 75494;验 ps 有进程:✓;重载 §D.4 emit:✓(磁盘代码 + signals.json entry[88] 已带 oi_source);不手动触发 scan:✓ 未触发;明早扫描后验 oi_source:延后(§4.2) |

—— 戌,2026-09-02 00:20 PDT

---

## 6. 补充:读 8 份 Desktop 回执 + offpool 回归 + 分支核查(00:33 PDT)

Lyra 拍"读 Desktop 8 份 + 跑 offpool 回归",戌执行。

### 6.1 读了的 8 份 Desktop-only 回执(都在 Desktop,repo 无)

```
B11_CLOUD_ENDPOINT_ROUTELOG / D4_CLOSEOUT_RECEIPT / GATEWAY_BASELINE_COMMIT_RECEIPT
GATEWAY_ROUTELOG_B_RECEIPT_r2 / GATEWAY_RUNNING_RECONCILE / GLM53_COT_STRIP_RECEIPT
HOU_MEMORY_AUDIT / HOU_TOOLS_LIVEFIRE
```

### 6.2 offpool 回归(17/17)

HARNESS_PENDING §2.4 命令用 `.venv/bin/python -m unittest` → **0 tests ran**(handoff §三已警告"unittest 写法无效")。换 `python3 -m pytest`(系统 9.1.1):

```
$ python3 -m pytest test_offpool_mandatory_pick test_offpool_daemon test_offpool_lane_config test_offpool_prompt_whitelist test_offpool_ab_stats -v
... collected 17 items
... 17 passed in 1.75s
```

**17/17 PASSED。** §2.4 offpool 回归干净。戌改的 stage1/stage2 `missing` 源判断没破回归。

### 6.3 分支核查(解开"分支不一致")

```
$ git rev-parse --abbrev-ref HEAD → fix/glm53-cot-strip
$ git log --oneline -1 → 5ffe989 docs: 戌锚点件 XU_TRAITS 入库
$ git merge-base --is-ancestor 7703328 HEAD → YES(§D.4 在当前分支历史)
$ git merge-base --is-ancestor 92f812f HEAD → YES(glm53 cot strip 在)
$ git merge-base --is-ancestor d72317d HEAD → YES(baseline 在)
$ git status --short .../local_gateway.py → (空,clean vs HEAD)
$ git ls-files --error-unmatch aether_nexus/test_render_oi_contract.py → tracked
```

**定论:**
- `fix/glm53-cot-strip` 是 `fix/harness-enforcement-v1` 的后裔 + 叠加 glm53 cot strip + XU_TRAITS。**当前分支是 superset,不是"不一致"**。handoff §二.1 写"应在 fix/harness-enforcement-v1"是 glm53 cot strip 工作叠加前的事,现已过时。
- `local_gateway.py` clean vs HEAD → 埋点版已 commit(baseline `d72317d`)。GATEWAY_RUNNING_RECONCILE 的"未提交 M"**已解决**。
- `test_render_oi_contract.py` tracked → §C 13 已进 `7703328`。r2 回执"§C 13/14 未 commit"**已过时**。

### 6.4 8 份回执里新冒出的跟进项(不在原 §4 清单里)

| 来源 | 项 | 红线? |
|---|---|---|
| GATEWAY_BASELINE_COMMIT note 2 | **§D.8**:`grid_local_gateway_redline.py` 不认 unlock,要让 unlock 机制真正生效需改这个 hook 认 `GRID_INFRASTRUCTURE_UNLOCK=1`(改红线 guard) | 是(改 guard) |
| GATEWAY_BASELINE_COMMIT note 3 | 全 frozen 文件 tracked+clean 体检(aster.toml 漂移是预存,其它冻结文件可能也有"改过+seal+未 commit") | 否(只读体检) |
| GATEWAY_BASELINE_COMMIT note 4 | guard 加 `--runtime-strict` 开关(staged 在 runtime 模式也算 dirty,堵边缘洞) | 否(改 guard) |
| GATEWAY_ROUTELOG_B_r2 §C 3 | metrics_query 加 `duration_ms IS NOT NULL` + 修第 6 行注释(REAL<TEXT 恒假,非"强转 0") | 否(shell) |
| GATEWAY_ROUTELOG_B_r2 §C 4 | 五班窗过滤 WHERE 落进 SQL(注释有约定,SQL 里没有) | 否(shell) |
| GATEWAY_ROUTELOG_B_r2 §C 5 | `verify_routelog_window.sh` 处决案二期望值改 400 | 否(shell) |
| GLM53_COT_STRIP 待 1 | reasoning token cap(上轮选项 A,治 thinking 吃爆回复预算)— 还做不做? | 否 |
| GLM53_COT_STRIP 待 2 | `fix/glm53-cot-strip` merge?还是 Lyra 先亲测 b11 Cloud tab? | 否(决定) |
| GLM53_COT_STRIP 待 3 | b11 Cloud tab 须关 tab 重开(静态 JS);服务端 cot_gate 须 restart gateway8501 — restart?(动 gateway 进程前问) | 是(restart) |
| HOU_MEMORY_AUDIT | 侯自诊 7 个记忆问题(id=2133:store 原文调不出/跨会话事件链/typed v1 截断/8620 连通/日记全文…)— 喂给"记忆工具接线包 v2"(§五队列)的输入,非戌直做 | 否(输入) |

—— 戌,2026-09-02 00:33 PDT 补
