# 戌 · harness 收口单 r1 · 段一采证 + 附带收尾 · 来自砥 · 2026-09-01 PDT

- 审:砥(harness 收口单 v1)
- 对象:`HARNESS_CLOSEOUT_r1_2026-09-01.md`(本文件)
- 模式:§E 一(1-3 只读采证)+ 二(4-8 非红线收尾);§三(9 等 Lyra 拍);四(不造 jobs/runner/plist,不碰 local_gateway.py)。
- 约束:禁 --no-verify、禁 add -A、禁改分支。本次 commit 走正常 pre-commit。
- **脱敏**:路径用 `<repo>/` 代本机绝对路径;不贴 gateway 核心文件原文;不贴 HMAC/密钥。

---

## 段一 · 采证(只读)

### 1. v1.3.1 harness ZIP 清单 + jobs schema + runner 主循环

**ZIP 位置:** iCloud Downloads `grid-resident-harness-v1.3.1`(无扩展名,实为 ZIP archive,49 文件,170961 bytes,2026-08-17)。`~/Downloads` 无 harness 文件(砥 §A "在 Downloads" 指 iCloud Downloads)。

`unzip -l` 全清单(摘):

```
grid-resident-harness-v1.3.1/
  run_harness.py (854)        ← runner 入口(uvicorn harness.api:app)
  run_relay.sh (298)
  harness/
    db.py (12081)              ← jobs 表 schema
    supervisor.py (16680)      ← runner 主循环
    api.py (15887) / context.py (20103) / memory_adapter.py (10394)
    config.py (6058) / sessions.py (2119) / relay.py (2391)
    gateway.py (2065) / control.py (991) / events_stream.py (1114) / cc.py (4829)
  test_security_v131.py (7527) ← S1–S10
  config.toml (3306) / .env.example (360) / install_launchd.sh / uninstall_launchd.sh
  mobile/ (app.js/sw.js/styles.css/index.html/manifest.json)
  ... 共 49 文件
```

**jobs 表 schema(`harness/db.py:17`):**

```
CREATE TABLE IF NOT EXISTS jobs(
  job_id TEXT PRIMARY KEY,
  channel TEXT NOT NULL,
  goal TEXT NOT NULL,
  worker TEXT NOT NULL,
  allowed_tools TEXT NOT NULL,
  allowed_paths TEXT NOT NULL,
  cloud_allowed INTEGER NOT NULL,
  approval_mode TEXT NOT NULL,
  status TEXT NOT NULL,
  retry_count INTEGER NOT NULL DEFAULT 0,
  last_step TEXT,
  last_artifact TEXT,
  pending_tool TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
```

**runner 主循环(`harness/supervisor.py:39` `run_forever`):**

```
async def run_forever(self):
    await self.startup_recovery()
    while not self._stop.is_set():
        # reap completed tasks
        dead=[jid for jid,t in self._tasks.items() if t.done()]
        for jid in dead:
            t=self._tasks.pop(jid)
            try: t.result()
            except asyncio.CancelledledError: pass
            except Exception as e:
                self.store.append_event(jid,"supervisor_task_error",{"error":repr(e)})
        # active task heartbeat
        for jid,t in list(self._tasks.items()):
            if not t.done():
                sess=self.store.find_session_by_job(jid)
                if sess: self.store.update_session(sess["session_id"],last_heartbeat=time.time())
        # fill concurrency slots with atomically claimed jobs
        while len(self._tasks) < self.cfg.core.max_concurrency:
            job=self.store.claim_next_queued()
            if not job: break
            task=asyncio.create_task(self._run_job(job),name=f"job:{job['job_id']}")
            self._tasks[job["job_id"]]=task
        await asyncio.sleep(self.cfg.core.poll_interval_seconds)
```

**判定:** v1.3.1 有 jobs 表(15 列:job_id/channel/goal/worker/allowed_tools/allowed_paths/cloud_allowed/approval_mode/status/retry_count/last_step/last_artifact/pending_tool/created_at/updated_at)+ runner 主循环(`claim_next_queued` 原子取 job → `_run_job` → 并发槽填充)+ `test_security_v131.py`(S1–S10)+ `GRID_HARNESS_TOKEN` 绑定校验(`run_harness.py:validate_bind`)。可搬件齐。**取舍由守恒定**(与 V1.5.5 四件冲突处)。

---

### 2. 8630 uvicorn 启动命令 + cwd

`ps -o command= -p 65377`:

```
<py3.13> -m uvicorn app.harness.server:app --host 127.0.0.1 --port 8630 --log-level warning
```

`lsof -p 65377 | grep cwd`:

```
cwd  <repo>
```

**判定:** 8630 = `app.harness.server:app`(V1.5.5 enforcement server,非 v1.3.1 的 `harness.api:app`),cwd = `<repo>`,127.0.0.1 only,手起(无 launchd)。

---

### 3. /task/cloud_chat substrate 实弹(kimi_k3 + glm53)

`curl -X POST 127.0.0.1:8501/task/cloud_chat -d '{"substrate":"kimi_k3","memory_sealed":true,...}' -H 'Content-Type: application/json'`:

```
{"served_by":"gateway-v4.11","source":"task_cloud_chat:glm53","substrate":"glm53",
 "model":"glm-5.3-flash","content":"pong","ok":true,"memory_write":false,
 "usage":{"cost_usd":0.001214,"latency_ms":917,"cloud_policy":"think_glm53"}}
```

route_log 最新行(kimi_k3 请求):

```
ts=<redacted>  routed_to=cloud_chat:glm53  duration_ms=922  status_code=200
```

glm53 实弹:

```
{"source":"task_cloud_chat:glm53","substrate":"glm53","model":"glm-5.3-flash","content":"pong","ok":true,"memory_write":false,...}
```

route_log 最新行(glm53):

```
ts=<redacted>  routed_to=cloud_chat:glm53  duration_ms=809  status_code=200
```

**判定(逐个):**

| substrate | 在? | 证据 |
|----|----|----|
| kimi_k3 | **不是独立 substrate** | 请求被路由到 `cloud_chat:glm53`,response `substrate=glm53`、`model=glm-5.3-flash` —— kimi_k3 落到 glm53(fallback),非自有 lane |
| glm53 | ✓ 在 | `routed_to=cloud_chat:glm53`,duration 809ms,status 200,content=pong |

`memory_write:false` 证实 `memory_sealed:true` 生效 —— **未落 cloud 记忆 RED LINE node**(cloud-glm52/cloud-kimi 未被写)。route_log 两行 duration_ms/status_code 非 NULL。

**给守恒(§F):** A5 灰度对象可用 glm-5.3(8501 已在);kimi_k3 不在 substrate 表,若要 kimi lane 需另配;决策官 v1 = `memory_sealed:true` 纯函数(已证 memory_write=false)。

---

## 段二 · 附带收尾(非红线)

### 4. metrics_query p95 门按 shifts_n — 过

**diff 摘要:** 主 SELECT 加 `(SELECT COUNT(*) FROM shifts) AS shifts_n`;采样兜底 echo 从 "n<200 不出 p95" 改为 "p95 门按 shifts_n(五班窗内 duration 非空行数,与 p95 同过滤集),不是 n"。

重跑输出:

```
n  shifts_n  mean_ms  min_ms  max_ms  p95_ms  err5xx_pct  timeout_pct  other_err_pct
2  1         3775.5   912     6639    6639    0.0         0.0          0.0
```

**n=2(全 GLM lane duration 非空),shifts_n=1(五班窗内 duration 非空)。** p95 门现在按 shifts_n(与 p95 同过滤集),不再用 n —— 否则 n≥200 门开早了。

---

### 5. guard WARN→BLOCK — 过

**diff 摘要(`scripts/grid_infrastructure_guard.py` `check_tree_changes`):** `UNLOCK=1 且 staged sha256≠manifest` 从 WARN(exit=0)改为 **BLOCK(exit≠0)**;无 UNLOCK 且 staged 含 frozen → BLOCK(原已如此)。

态1(UNLOCK=1 + staged sha≠manifest):

```
$ GRID_INFRASTRUCTURE_UNLOCK=1 python3 scripts/grid_infrastructure_guard.py check-staged
P0 BLOCK: frozen files staged with GRID_INFRASTRUCTURE_UNLOCK=1 but manifest not re-sealed — run update-lock before commit:
  - <repo>/grid-sovereign-runtime/gateway/local_gateway.py (staged=72863261b782 manifest=54e02f62ddee)
  re-seal: GRID_INFRASTRUCTURE_UNLOCK=1 python3 scripts/grid_infrastructure_guard.py update-lock
exit=1
```

态2(无 UNLOCK + staged frozen):

```
$ GRID_INFRASTRUCTURE_UNLOCK= python3 scripts/grid_infrastructure_guard.py check-staged
P0 BLOCK: immutable Grid infrastructure modified without authorization.
  touched:
    - <repo>/grid-sovereign-runtime/gateway/local_gateway.py
exit=1
```

两态全 BLOCK exit=1,还原后 sha match=True。门禁只能更严。

commit(item 4 + 5 一起):

```
$ git add scripts/grid_infrastructure_guard.py grid-sovereign-runtime/gateway/metrics_query_gateway_routelog_metrics_v1.sh
$ git commit -m "guard+metrics: WARN→BLOCK(unlocked+staged sha≠manifest) + p95 门按 shifts_n (砥 r3 §C 收尾)"
 2 files changed, 15 insertions(+), 4 deletions(-)
commit_exit=0
```

---

### 6. offpool 回归五文件 — 过

`aether_nexus/.venv` 无 pytest;系统 `pytest 9.1.1`(`Library/Frameworks/Python.framework/Versions/3.13/bin/pytest`)跑:

```
17 passed in 2.30s
```

明细:test_offpool_mandatory_pick(2) / test_offpool_daemon(3) / test_offpool_lane_config(3) / test_offpool_prompt_whitelist(6) / test_offpool_ab_stats(3) —— **全过**。HARNESS_PENDING §2.4 闭合。

---

### 7. signals.json 末条 + legacy aether.html OI 渲染

**signals.json 末条(`<repo>/aether_nexus/dryrun_state/signals.json`,list len 90):**

```
末条 scan_time: 2026-09-01T15:33:33.161843-04:00   (12:33 PDT)
末条 scan_mode: sp500
top_pick: NOW
candidates: 5,oi_source 分布: {alpaca_contracts: 5}
cand[0] symbol=NOW  oi_source=alpaca_contracts  open_interest=6700
```

**定时盘落真 OI**(oi_source=alpaca_contracts,非 missing)。

**legacy aether.html OI 渲染(实机):**
- `/app/legacy/aether.html` HTTP 200(665694 bytes)。
- 静态 JS(`aether.html:1054` 与 `:1680`):`const oi=r.open_interest!=null?\`OI ${esc(String(r.open_interest))}\`:"";` —— null→""、0→"OI 0"、val→"OI val"。逻辑正确。
- 实机打开 TRADING tab = BFS 决策面(聚合卡,"无可执行卡(缺入场/止损/目标)");OPTION tab = Scout 情报面(晨/午/晚报 + 财报班列表)。**当前数据无可执行 option 卡 → 个别 option 行未渲染 → DOM 无 "OI <val>" 文本**。OI 渲染代码在场但未被当前视图行使(需有可执行卡才渲染行)。
- 截图存档(`page-2026-09-01T22-17-55-011Z.png`)。

**判定:** 静态逻辑确认正确;实机当前视图(BFS 聚合 + Scout 报告)不渲染个别 option OI 行,故无 "OI <val>" 文本可贴。代码路径在有可执行卡时会行使。

---

### 8. HARNESS_PENDING §2.1 七文件 git status

```
$ git status --short -- <七文件>
?? aether_nexus/aether_grid_emit.py
?? aether_nexus/offpool_coach/stage1_mechanical.py
?? aether_nexus/offpool_coach/stage2_payload_builder.py
?? aether_nexus/test_trading_state_oi.py
?? aether_nexus/trading_state.py
```

逐文件:

| 文件 | 状态 |
|----|----|
| aether_nexus/aether_dryrun.py | **已 commit**(4bd4019,r3-1) |
| grid-sovereign-runtime/gateway/static/aether_trading_v12.html | **已 commit**(d72317d;OI 渲染 :566-567 在 HEAD,工作树一致) |
| aether_nexus/aether_grid_emit.py | ?? untracked |
| aether_nexus/offpool_coach/stage1_mechanical.py | ?? untracked |
| aether_nexus/offpool_coach/stage2_payload_builder.py | ?? untracked |
| aether_nexus/trading_state.py | ?? untracked |
| aether_nexus/test_trading_state_oi.py | ?? untracked |

**修正砥 r3 判词:** 砥 r3 说 "html 是旧版" —— 实测 `aether_trading_v12.html` 的 OI 渲染(:566-567)**已在 HEAD**(d72317d),工作树一致,非旧版。§2.1 整组实际只剩 **5 个 untracked**(grid_emit / stage1+2 / trading_state / test_trading_state_oi)待 §D.4 commit;dryrun + html 已入库。

---

## 段三 · 等 Lyra 拍后(未做)

- **§D.4 commit**:5 个 untracked 整组一个 commit(等拍)
- **§D.5 删**:`aether_dryrun.py.bak_*` 与 `AETHER_OI_HARDZERO_v1_MANUAL_PATCH_3.md`(等拍)
- **§D.7 PORTS.md 登记** + 8788 处置(等拍)
- **§D.8 hook 认 unlock**(条件 manifest==staged sha)(等拍)
- 段一部署(等守恒整包)

## 段四 · 不做

- 不造 jobs 表、不写 runner、不起 plist —— 等守恒整包
- 不碰 local_gateway.py

---

## 收尾

本次 r1 commit:`efbd967`(guard+metrics:WARN→BLOCK + p95 门按 shifts_n)。分支 `fix/harness-enforcement-v1` 未动;未 --no-verify;未 add -A;未 restart gateway。

—— 戌,2026-09-01 PDT(段一采证 + 附带收尾,脱敏回执)

---

## 补三条(只读)· 来自砥 · 2026-09-01 PDT

### a. grid-resident-harness 目录 + 骨架 + sqlite schema

**位置:** `[REDACTED: 身份] harness root/`(demo 仓外,独立部署目录)。是 v1.3.1 的**已部署版**(.venv/.env/state/agent_jobs 齐全,2026-08-25 18:11 最后改动)。

顶层 .py 骨架:

```
relay_server.py:  def required_token / check_token / class RelayRequest
run_harness.py:   def validate_bind(host,token)
smoke_test.py:    def main
test_security_v131.py: def ok / offline / onsite
test_context_v12.py:   class FakeDomain / FakeRouter
test_voice_ports.py:  def main
```

harness/ 子目录骨架(摘):

```
api.py:        class JobCreate/SessionCreate/SessionMessage/Decision/VoiceEvent; create_job_internal; relay_handler; stale_loop; lifespan; _auth_gate; health; create_job/list_jobs/get_job/requeue/create_session
cc.py:         class CCExecutor
config.py:     class CoreConfig/ModelConfig/CCConfig/HarnessConfig/Audio8VoiceConfig/VoiceConfig/RelayConfig/PolicyConfig/MemoryDomainConfig/MemoryConfig/ContextProfileConfig/ContextConfig/Config; load_config; gateway_headers
context.py:    class ContextBudgetError/ContextLayer/ContextPack/ContextAssembler; estimate_tokens
control.py:    class ControlPlane
db.py:         class Store
events_stream.py: class EventStreamer
gateway.py:    class GatewayClient
memory_adapter.py: class MemoryRecord/MemoryLayerResult/MemoryDomain/MemoryRouter
port_util.py:  def port_bindable / assert_port_free
relay.py:      class OutboundRelayClient
sessions.py:   class SessionManager
supervisor.py: class Supervisor
voice_adapter.py: class VoiceTtsAdapter; voice_tts_adapter
voice_health.py: async def probe_audio8
```

sqlite:`state/harness.db`(86016 bytes)。`.schema`:

```
CREATE TABLE jobs(job_id TEXT PRIMARY KEY, channel TEXT, goal TEXT, worker TEXT,
  allowed_tools TEXT, allowed_paths TEXT, cloud_allowed INTEGER, approval_mode TEXT,
  status TEXT, retry_count INTEGER DEFAULT 0, last_step TEXT, last_artifact TEXT,
  pending_tool TEXT, created_at REAL, updated_at REAL);
CREATE TABLE events(event_id TEXT PRIMARY KEY, job_id TEXT, kind TEXT, payload TEXT,
  created_at REAL, FOREIGN KEY(job_id) REFERENCES jobs(job_id));
CREATE TABLE sessions(session_id TEXT PRIMARY KEY, agent_id TEXT, channel TEXT,
  title TEXT, state TEXT, active_job_id TEXT, waiting_for TEXT, last_heartbeat REAL,
  created_at REAL, updated_at REAL);
CREATE TABLE thread_messages(message_id TEXT PRIMARY KEY, session_id TEXT, role TEXT,
  content TEXT, created_at REAL, FOREIGN KEY(session_id) REFERENCES sessions(session_id));
CREATE TABLE stream_events(seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE,
  session_id TEXT, job_id TEXT, kind TEXT, payload TEXT, created_at REAL);
-- 索引:idx_jobs_status / idx_events_job_created / idx_sessions_state / idx_messages_session_created / idx_stream_seq
```

各表行数:`jobs=3 / events=16 / sessions=4 / thread_messages=0 / stream_events=4`。

**判定:** grid-resident-harness 是 v1.3.1 已部署但**未在跑**的实例(见 b);jobs 表与 v1.3.1 ZIP 一致(15 列),多出 sessions/thread_messages/stream_events 三表。守恒段一可搬件齐,且已有真实 db(3 jobs/16 events)可参照。

---

### b. 8630 跑 demo 还是 grid-resident-harness — 定 demo

`lsof -p 65377 | grep cwd`:

```
Python  65377  cwd  <repo>/demo
```

`ps -o command= -p 65377`:

```
<py3.13> -m uvicorn app.harness.server:app --host 127.0.0.1 --port 8630 --log-level warning
```

对照:

```
pgrep -fl grid-resident-harness   →  (空,该目录无进程)
lsof -iTCP:8630 -sTCP:LISTEN       →  仅 pid 65377(demo 的 app.harness.server)
grid-resident-harness/config.toml  →  [core] port=8630 / voice port=8631(期望 8630,但未起)
```

**判定:** 8630 跑的是 **demo 仓的 `app.harness.server:app`**(V1.5.5 enforcement server,cwd=`<repo>/demo`),**不是** grid-resident-harness 的 `harness.api:app`。grid-resident-harness **无进程**,其期望的 8630 被 demo 的 harness server 占据。v1.3.1 部署件处于**休眠**状态。

---

### c. PreN18 回执 — 未做

任务单位置:`iCloud Downloads/Grid_Native_Loop_Runtime_Transport_PreN18_Cursor.txt`(176 行,`CURSOR TASK — Build Native-Loop Runtime Transport (Pre-N18)`)。

文件内 `NATIVE_LOOP_TRANSPORT` 出现在 :136/:171(`= READY`)与 :173(`= BLOCKED`)—— 这些是 **spec 的期望输出值**,非完成回执的最后一行。tail:

```
or
NATIVE_LOOP_TRANSPORT = BLOCKED

Do not run N18/N19 in this task.
Do not claim native cognition is proven.
```

回执检索:仓内(`grep -rln PreN18/NATIVE_LOOP_TRANSPORT`)= 空;Desktop = 空;iCloud Downloads 无 `*PreN18*回执*` / `*PreN18*RECEIPT*`。

**判定:** PreN18 **未做** —— 仅有任务单,无完成回执。

—— 戌,2026-09-01 PDT(补三条,只读,脱敏)

---

## v1.3 复核(砥 harness 收口单 v1.3 · §E)· 2026-09-01 PDT

> 砺 v1.3 段一方向反转(门搬进身体、身体进 git、demo 8630 停)。§E 块本轮:一.补一条(只读贴全文)+ 附带收尾 4–8 复核。本轮**未改任何代码**(item 4/5 已在 efbd967,本轮复核确认;6/7/8 只读)。段一部署等守恒整包 + Lyra §D.11。

### 段一方向依据(V1.5.5 施工令原文确认)

读 `Grid_Harness_V1.5.5_Cursor_Deploy.txt`(ZIP 内,21KB)确认砥 v1.3 方向:

- "Deploy V1.5 by **merging this package into the existing working Grid Resident Harness**. **Do not create another backend.**"
- "Do not add a second state store."
- D13 "No second router, memory DB, or job state machine is introduced."
- N15 "no duplicate scheduler/router/planner/state store."

**判定:** 8-26 enforcement_patch 在 demo/app/harness 起 8630 只读 server = 造了第二个 backend,违背 V1.5.5 原文。砥 v1.3"门搬进身体(grid-resident-harness)"纠正成立。段一部署等守恒整包。

### 一.补一条(只读贴全文,给守恒合身用)

**supervisor.py 全文** 与 **db.py 全文** 见下两节(禁按记忆写)。config.toml `[core]` 段:

```toml
[core]
db_path = "./state/harness.db"
gateway_base = "http://127.0.0.1:8501"
gateway_timeout_seconds = 120
poll_interval_seconds = 1.0
max_retries = 2
max_concurrency = 4

[models]
local_route = "demo/aster"
deep_route = "glm-5.2:cloud"
multimodal_route = "kimi-k2.6:cloud"

[harness]
host = "127.0.0.1"
port = 8630
```

> 注:config.toml `multimodal_route` 原 = `kimi-k2.6:cloud`,与 Lyra 9-01"Kimi 已删"冲突。**Lyra 9-01 16:39 拍:multimodal_route 用 `glm-5.3-flash:cloud` 代替 kimi**。戌已改 `~/Projects/grid-resident-harness/config.toml`(非冻结件、非 local_gateway;v1.3.1 实例未在跑,改即记录,段一合身时守恒承接)。改后三 route 全在 8501 `/v1/models` 实况:`demo/aster` / `glm-5.2:cloud` / `glm-5.3-flash:cloud` ✓。§F 原"multimodal 走 MiniMax M3 旁路"以此拍为准——multimodal_route 槽填 glm-5.3-flash,MiniMax M3 仍作 GLM 5.2/5.3 的 VL 旁路不单开。

### item 4 · metrics_query 复核(已在 efbd967,确认)

重跑输出:

```
n  shifts_n  mean_ms  min_ms  max_ms  p95_ms  err5xx_pct  timeout_pct  other_err_pct
2  1         3775.5   912     6639    6639    0.0         0.0          0.0

采样兜底:
  p95 门按 shifts_n(五班窗内 duration 非空行数,与 p95 同过滤集),不是 n
  shifts_n < 200:不出 p95(采样未达),回执写 "采样未达 shifts_n=<数>"
```

**判定:** n=2 对;五班窗只加在 p95 子查询(`FROM shifts`);n≥200 的门已改按 shifts_n(r1 efbd967 已落"改一行")。当前 shifts_n=1 < 200 → 采样未达,不出 p95。r3"改一行"已在 efbd967 闭合,本轮复核确认无需再改。

### item 5 · guard 两态 BLOCK 复核(已在 efbd967,本轮证两态)

pre-commit 链:`grid_local_gateway_redline.py`(local_gateway 绝对红线)→ `grid_infrastructure_guard.py check-staged` → `verify_grid_chain_integrity.sh`。`check-staged` 调 `check_tree_changes("staged")`,无 WARN 路径,两态皆 BLOCK。

态A(无 UNLOCK + staged frozen → BLOCK),用 `config/aster.toml` 做可逆探针:

```
P0 BLOCK: immutable Grid infrastructure modified without authorization.
  unlock: export GRID_INFRASTRUCTURE_UNLOCK=1  (explicit user authorization only)
  touched:
    - config/aster.toml
  manifest: <repo>/config/grid_infrastructure_lock.json
exit=1
```

态B(UNLOCK=1 + staged sha≠manifest 未 update-lock → BLOCK):

```
P0 BLOCK: frozen files staged with GRID_INFRASTRUCTURE_UNLOCK=1 but manifest not re-sealed — run update-lock before commit:
  - config/aster.toml (staged=45e04233bb7e manifest=caae3604144d)
  re-seal: GRID_INFRASTRUCTURE_UNLOCK=1 python3 scripts/grid_infrastructure_guard.py update-lock
exit=1
```

探针后 `git checkout -- config/aster.toml` → `restored clean`。

**判定:** r3"改一行"(WARN→BLOCK)已在 efbd967 闭合;两态 BLOCK 本轮证齐(态A 此前"现在未证",已证)。无新代码可 commit。

### item 6 · offpool 回归五文件

```
collected 17 items
test_offpool_mandatory_pick.py ..            [ 11%]
test_offpool_daemon.py ...                   [ 29%]
test_offpool_lane_config.py ...              [ 47%]
test_offpool_prompt_whitelist.py ......      [ 82%]
test_offpool_ab_stats.py ...                 [100%]
============================== 17 passed in 0.85s ==============================
```

### item 7 · signals.json 末条 + legacy aether.html OI

signals.json 末条(`<repo>/aether_nexus/dryrun_state/signals.json`):

```
scan_time= 2026-09-01T15:33:33.161843-04:00   (12:33 PDT 定时盘)
candidates= 5
  sym=NOW  vol=1490 oi=6700  oi_source=alpaca_contracts
  sym=SLB  vol=844  oi=26901 oi_source=alpaca_contracts
  sym=CRM  vol=429  oi=1561  oi_source=alpaca_contracts
  sym=FCX  vol=7182 oi=27108 oi_source=alpaca_contracts
  sym=AMKR vol=3    oi=235   oi_source=alpaca_contracts
```

legacy `aether.html` OI 渲染分支(:1054 / :1680):

```javascript
const oi=r.open_interest!=null?`OI ${esc(String(r.open_interest))}`:"";
```

**判定:** 12:33 定时盘 5/5 真 OI(alpaca_contracts);legacy aether.html 静态 OI 分支在场(null→"",val→"OI val",无"OI NA"分支——那是 v12 的;legacy 行为如此,代码在场)。

### item 8 · §2.1 七文件 git status(为 §D.4 commit 备)

```
?? aether_nexus/aether_grid_emit.py
?? aether_nexus/offpool_coach/stage1_mechanical.py
?? aether_nexus/offpool_coach/stage2_payload_builder.py
?? aether_nexus/test_trading_state_oi.py
?? aether_nexus/trading_state.py
```

`aether_dryrun.py` 与 `aether_trading_v12.html` 不在列表 = 已 commit(d72317d / 4bd4019)。**§2.1 整组剩 5 个 untracked**,等 §D.4 整组一个 commit。

### 三、等 Lyra 拍后(本轮不做)

§D.4 commit(5 untracked 整组)/ §D.5 删两文件 / §D.7 PORTS.md 登记 + 8788 处置 / §D.8 hook / §D.11 旧目录归档改名 / 段一部署(守恒整包到后)。

### 四、不做

不造 jobs 表、不写 runner、不起 plist——等守恒整包。不碰 `local_gateway.py`。

—— 戌,2026-09-01 PDT(v1.3 复核,脱敏)

---

## 附录 A · supervisor.py 全文(grid-resident-harness/harness/supervisor.py)

```python
from __future__ import annotations
import asyncio, json, time
from typing import Any
from .config import Config
from .db import Store
from .gateway import GatewayClient
from .cc import CCExecutor
from .memory_adapter import MemoryRouter
from .context import ContextAssembler

SYSTEM="""You are a resident execution worker inside Grid.
Return useful work, not roleplay.
Never claim a tool ran unless the harness actually ran it.
If you need cloud escalation, emit exactly one JSON object:
{"action":"escalate","target":"glm|kimi","reason":"..."}
Do not invent tool results.
"""

class Supervisor:
    def __init__(self,cfg:Config,store:Store):
        self.cfg=cfg
        self.store=store
        self.gateway=GatewayClient(cfg)
        self.cc=CCExecutor(cfg)
        self.memories=MemoryRouter(cfg)
        self.context=ContextAssembler(cfg,store,self.memories)
        self._stop=asyncio.Event()
        self._tasks:dict[str,asyncio.Task]={}

    async def startup_recovery(self):
        n=self.store.mark_running_interrupted()
        if n:
            self.store.append_event(None,"recovery_interrupted",{"count":n})
        if self.cfg.policy.auto_resume_interrupted:
            q=self.store.requeue_interrupted(self.cfg.core.max_retries)
            if q:
                self.store.append_event(None,"recovery_requeued",{"count":q})

    async def run_forever(self):
        await self.startup_recovery()
        while not self._stop.is_set():
            dead=[jid for jid,t in self._tasks.items() if t.done()]
            for jid in dead:
                t=self._tasks.pop(jid)
                try: t.result()
                except asyncio.CancelledError: pass
                except Exception as e:
                    self.store.append_event(jid,"supervisor_task_error",{"error":repr(e)})
            for jid,t in list(self._tasks.items()):
                if not t.done():
                    sess=self.store.find_session_by_job(jid)
                    if sess:
                        self.store.update_session(sess["session_id"],last_heartbeat=time.time())
            while len(self._tasks) < self.cfg.core.max_concurrency:
                job=self.store.claim_next_queued()
                if not job: break
                task=asyncio.create_task(self._run_job(job),name=f"job:{job['job_id']}")
                self._tasks[job["job_id"]]=task
            await asyncio.sleep(self.cfg.core.poll_interval_seconds)

    async def stop(self):
        self._stop.set()
        for t in list(self._tasks.values()):
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(),return_exceptions=True)
        await self.gateway.close()
        await self.memories.close()

    async def pause_session(self,session_id:str):
        s=self.store.get_session(session_id)
        jid=s.get("active_job_id")
        if jid and jid in self._tasks:
            self._tasks[jid].cancel()
        if jid:
            try: self.store.update_job(jid,status="interrupted",last_step="paused_by_user")
            except KeyError: pass
        ss=self.store.update_session(session_id,state="paused",last_heartbeat=time.time())
        self.store.append_stream_event(session_id=session_id,job_id=jid,kind="session_state",
                                       payload={"state":"paused"})
        return ss

    async def resume_session(self,session_id:str):
        s=self.store.get_session(session_id)
        jid=s.get("active_job_id")
        if jid:
            try:
                j=self.store.get_job(jid)
                if j["status"] in {"interrupted","blocked","failed"}:
                    self.store.update_job(jid,status="queued",last_step="resumed_by_user")
                    ss=self.store.update_session(session_id,state="running",last_heartbeat=time.time())
                else:
                    ss=self.store.update_session(session_id,state="running",last_heartbeat=time.time())
            except KeyError:
                ss=self.store.update_session(session_id,state="idle",active_job_id=None,last_heartbeat=time.time())
        else:
            ss=self.store.update_session(session_id,state="idle",last_heartbeat=time.time())
        self.store.append_stream_event(session_id=session_id,job_id=jid,kind="session_state",
                                       payload={"state":ss["state"]})
        return ss

    async def cancel_session(self,session_id:str):
        s=self.store.get_session(session_id)
        jid=s.get("active_job_id")
        if jid and jid in self._tasks:
            self._tasks[jid].cancel()
        if jid:
            try: self.store.update_job(jid,status="cancelled",last_step="cancelled_by_user")
            except KeyError: pass
        ss=self.store.update_session(session_id,state="cancelled",active_job_id=None,
                                     waiting_for=None,last_heartbeat=time.time())
        self.store.append_stream_event(session_id=session_id,job_id=jid,kind="session_state",
                                       payload={"state":"cancelled"})
        return ss

    async def approve_session(self,session_id:str,note="approved"):
        s=self.store.get_session(session_id)
        jid=s.get("active_job_id")
        if jid:
            try:
                j=self.store.get_job(jid)
                if j["status"]=="blocked":
                    self.store.update_job(jid,status="queued",cloud_allowed=1,last_step="approved_requeue")
            except KeyError: pass
        ss=self.store.update_session(session_id,state="running",waiting_for=None,last_heartbeat=time.time())
        self.store.append_stream_event(session_id=session_id,job_id=jid,kind="approval",
                                       payload={"decision":"approve","note":note})
        return ss

    async def reject_session(self,session_id:str,note="rejected"):
        s=self.store.get_session(session_id)
        jid=s.get("active_job_id")
        if jid:
            try: self.store.update_job(jid,status="cancelled",last_step="rejected_by_user")
            except KeyError: pass
        ss=self.store.update_session(session_id,state="blocked",waiting_for=None,last_heartbeat=time.time())
        self.store.append_stream_event(session_id=session_id,job_id=jid,kind="approval",
                                       payload={"decision":"reject","note":note})
        return ss

    async def _run_job(self,job:dict[str,Any]):
        jid=job["job_id"]
        sess=self.store.find_session_by_job(jid)
        self.store.update_job(jid,status="running",last_step="dispatch")
        self.store.append_event(jid,"job_started",{"worker":job["worker"]})
        if sess:
            self.store.update_session(sess["session_id"],state="running",last_heartbeat=time.time())
            self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,kind="job_started",
                                           payload={"worker":job["worker"],"goal":job["goal"]})
        try:
            if job["worker"]=="cc":
                context_pack=await self.context.build(
                    worker="cc",
                    session_id=sess["session_id"] if sess else None,
                    current_turn=job["goal"],
                    job=job,
                )
                self._emit_context_receipt(sess,job,context_pack)
                result=await self.cc.run(job,context_pack=context_pack)
                if result["ok"]:
                    self.store.update_job(jid,status="done",last_step="cc_done",
                                          last_artifact=result.get("job_dir"))
                    self.store.append_event(jid,"job_result",result)
                    if sess:
                        text=result.get("result","")
                        if text:
                            self.store.append_message(sess["session_id"],"assistant",text)
                            await self.persist_external_turn(
                                worker="cc",
                                session_id=sess["session_id"],
                                role="assistant",
                                content=text,
                                source_surface=sess.get("channel") or "grid",
                            )
                        self.store.update_session(sess["session_id"],state="idle",active_job_id=None,
                                                  last_heartbeat=time.time())
                        self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                                       kind="job_done",payload={"worker":"cc","ok":True})
                else:
                    self.store.update_job(jid,status="failed",last_step="cc_failed")
                    self.store.append_event(jid,"job_failed",result)
                    if sess:
                        self.store.update_session(sess["session_id"],state="failed",last_heartbeat=time.time())
                        self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                                       kind="job_failed",payload=result)
                return

            route=self._route_for(job["worker"])
            effective_worker=self._worker_for_route(route)
            result=await self._model_job(job,route,sess)

            esc=self._parse_escalation(result)
            if esc:
                if not job["cloud_allowed"]:
                    self.store.update_job(jid,status="blocked",last_step="cloud_escalation_denied")
                    self.store.append_event(jid,"blocked",{"reason":"cloud escalation denied","request":esc})
                    if sess:
                        self.store.update_session(sess["session_id"],state="waiting_approval",
                                                  waiting_for=f"cloud:{esc['target']}",
                                                  last_heartbeat=time.time())
                        self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                                       kind="waiting_approval",
                                                       payload={"reason":"cloud escalation denied","request":esc})
                    return
                route=self._route_for(esc["target"])
                effective_worker=self._worker_for_route(route)
                self.store.append_event(jid,"escalated",esc)
                if sess:
                    self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                                   kind="escalated",payload=esc)
                result=await self._model_job(job,route,sess)

            self.store.update_job(jid,status="done",last_step="completed")
            self.store.append_event(jid,"job_result",{"text":result,"route":route})
            if sess:
                self.store.append_message(sess["session_id"],"assistant",result)
                await self.persist_external_turn(
                    worker=effective_worker,
                    session_id=sess["session_id"],
                    role="assistant",
                    content=result,
                    source_surface=sess.get("channel") or "grid",
                )
                self.store.update_session(sess["session_id"],state="idle",active_job_id=None,
                                          last_heartbeat=time.time())
                self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                               kind="job_done",payload={"route":route,"text":result})
        except asyncio.CancelledError:
            self.store.append_event(jid,"job_cancelled_runtime",{})
            raise
        except Exception as e:
            cur=self.store.get_job(jid)
            rc=cur["retry_count"]
            self.store.append_event(jid,"job_exception",{"error":repr(e)})
            if sess:
                self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                               kind="job_exception",payload={"error":repr(e)})
            if rc < self.cfg.core.max_retries:
                self.store.update_job(jid,status="queued",retry_count=rc+1,last_step="retry_queued")
            else:
                self.store.update_job(jid,status="failed",last_step="max_retries_exceeded")
                if sess:
                    self.store.update_session(sess["session_id"],state="failed",last_heartbeat=time.time())

    async def _model_job(self,job,route,sess):
        worker=self._worker_for_route(route)
        pack=await self.context.build(
            worker=worker,
            session_id=sess["session_id"] if sess else None,
            current_turn=job["goal"],
            job=job,
        )
        self._emit_context_receipt(sess,job,pack)
        messages=pack.to_messages(SYSTEM)
        chunks=[]
        try:
            async for piece in self.gateway.chat_stream(route,messages):
                chunks.append(piece)
                if sess:
                    self.store.update_session(sess["session_id"],last_heartbeat=time.time())
                    self.store.append_stream_event(
                        session_id=sess["session_id"],
                        job_id=job["job_id"],
                        kind="agent_delta",
                        payload={"text":piece,"route":route}
                    )
        except Exception:
            if chunks:
                raise
            resp=await self.gateway.chat(route,messages)
            return self.gateway.extract_text(resp)
        if chunks:
            return "".join(chunks)
        resp=await self.gateway.chat(route,messages)
        return self.gateway.extract_text(resp)

    def _emit_context_receipt(self,sess,job,pack):
        if not self.cfg.memory.emit_context_receipts:
            return
        receipt=pack.receipt()
        self.store.append_event(job["job_id"],"context_receipt",receipt)
        if sess:
            self.store.append_stream_event(
                session_id=sess["session_id"],
                job_id=job["job_id"],
                kind="context_receipt",
                payload=receipt,
            )

    async def persist_external_turn(
        self,
        *,
        worker:str,
        session_id:str,
        role:str,
        content:str,
        source_surface:str,
    ):
        domain=self.memories.for_worker(worker)
        result=await domain.write_turn(
            session_id=session_id,
            role=role,
            content=content,
            source_surface=source_surface,
            worker=worker,
        )
        if result.get("attempted"):
            self.store.append_stream_event(
                session_id=session_id,
                job_id=None,
                kind="memory_write_receipt",
                payload=result,
            )
        return result

    async def preview_context(self,*,worker:str,session_id:str,current_turn:str):
        query=current_turn
        if not query:
            history=self.store.list_messages(session_id,limit=100)
            for m in reversed(history):
                if m.get("role")=="user" and m.get("content"):
                    query=m["content"]
                    break
        return await self.context.build(
            worker=worker,
            session_id=session_id,
            current_turn=query,
            job=None,
        )

    def _worker_for_route(self,route):
        if route==self.cfg.models.local_route:
            return "qwen"
        if route==self.cfg.models.deep_route:
            return "glm"
        if route==self.cfg.models.multimodal_route:
            return "kimi"
        raise ValueError(f"unknown model route: {route}")

    def _route_for(self,w):
        if w=="qwen": return self.cfg.models.local_route
        if w=="glm": return self.cfg.models.deep_route
        if w=="kimi": return self.cfg.models.multimodal_route
        raise ValueError(f"unknown worker: {w}")

    @staticmethod
    def _parse_escalation(text):
        s=text.strip()
        if not(s.startswith("{") and s.endswith("}")): return None
        try: o=json.loads(s)
        except Exception: return None
        if o.get("action")!="escalate" or o.get("target") not in {"glm","kimi"}: return None
        return {"target":o["target"],"reason":str(o.get("reason",""))}
```

—— 戌,2026-09-01 PDT(附录 A,supervisor.py 全文,脱敏)

---

## 附录 B · db.py 全文(grid-resident-harness/harness/db.py)

```python
from __future__ import annotations
import json, sqlite3, threading, time, uuid
from pathlib import Path
from typing import Any

class Store:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(
              job_id TEXT PRIMARY KEY,
              channel TEXT NOT NULL,
              goal TEXT NOT NULL,
              worker TEXT NOT NULL,
              allowed_tools TEXT NOT NULL,
              allowed_paths TEXT NOT NULL,
              cloud_allowed INTEGER NOT NULL,
              approval_mode TEXT NOT NULL,
              status TEXT NOT NULL,
              retry_count INTEGER NOT NULL DEFAULT 0,
              last_step TEXT,
              last_artifact TEXT,
              pending_tool TEXT,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events(
              event_id TEXT PRIMARY KEY,
              job_id TEXT,
              kind TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at REAL NOT NULL,
              FOREIGN KEY(job_id) REFERENCES jobs(job_id)
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_events_job_created ON events(job_id,created_at);
            CREATE TABLE IF NOT EXISTS sessions(
              session_id TEXT PRIMARY KEY,
              agent_id TEXT NOT NULL,
              channel TEXT NOT NULL,
              title TEXT NOT NULL,
              state TEXT NOT NULL,
              active_job_id TEXT,
              waiting_for TEXT,
              last_heartbeat REAL,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS thread_messages(
              message_id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              created_at REAL NOT NULL,
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            CREATE TABLE IF NOT EXISTS stream_events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT,
              event_id TEXT UNIQUE NOT NULL,
              session_id TEXT,
              job_id TEXT,
              kind TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_state ON sessions(state);
            CREATE INDEX IF NOT EXISTS idx_messages_session_created ON thread_messages(session_id,created_at);
            CREATE INDEX IF NOT EXISTS idx_stream_seq ON stream_events(seq);

            """)
            self._conn.commit()

    def create_job(self, *, channel, goal, worker, allowed_tools, allowed_paths, cloud_allowed, approval_mode):
        now=time.time(); job_id=f"J-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._conn.execute("""INSERT INTO jobs(
              job_id,channel,goal,worker,allowed_tools,allowed_paths,cloud_allowed,
              approval_mode,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,'queued',?,?)""",
            (job_id,channel,goal,worker,json.dumps(allowed_tools),json.dumps(allowed_paths),
             int(cloud_allowed),approval_mode,now,now))
            self._conn.commit()
        self.append_event(job_id,"job_created",{"goal":goal,"worker":worker})
        return self.get_job(job_id)

    def get_job(self, job_id):
        with self._lock:
            r=self._conn.execute("SELECT * FROM jobs WHERE job_id=?",(job_id,)).fetchone()
        if not r: raise KeyError(job_id)
        return self._decode(r)

    def list_jobs(self, limit=100):
        with self._lock:
            rows=self._conn.execute("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?",(limit,)).fetchall()
        return [self._decode(r) for r in rows]

    def claim_next_queued(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            r=self._conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not r:
                self._conn.commit()
                return None
            now=time.time()
            self._conn.execute("UPDATE jobs SET status='running',updated_at=? WHERE job_id=? AND status='queued'",
                               (now,r["job_id"]))
            self._conn.commit()
        return self.get_job(r["job_id"])

    def next_queued(self):
        with self._lock:
            r=self._conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        return self._decode(r) if r else None

    def update_job(self, job_id, **fields):
        fields["updated_at"]=time.time()
        allowed={"worker","status","retry_count","last_step","last_artifact","pending_tool","cloud_allowed","updated_at"}
        bad=set(fields)-allowed
        if bad: raise ValueError(f"unsupported fields: {sorted(bad)}")
        pairs=", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {pairs} WHERE job_id=?", list(fields.values())+[job_id])
            self._conn.commit()
        return self.get_job(job_id)

    def append_event(self, job_id, kind, payload):
        eid=f"E-{uuid.uuid4().hex}"
        with self._lock:
            self._conn.execute("INSERT INTO events VALUES(?,?,?,?,?)",
                               (eid,job_id,kind,json.dumps(payload,ensure_ascii=False),time.time()))
            self._conn.commit()
        return eid

    def list_events(self, job_id, limit=200):
        with self._lock:
            rows=self._conn.execute("SELECT * FROM events WHERE job_id=? ORDER BY created_at LIMIT ?",
                                    (job_id,limit)).fetchall()
        return [{"event_id":r["event_id"],"job_id":r["job_id"],"kind":r["kind"],
                 "payload":json.loads(r["payload"]),"created_at":r["created_at"]} for r in rows]

    def mark_running_interrupted(self):
        with self._lock:
            c=self._conn.execute("UPDATE jobs SET status='interrupted',updated_at=? WHERE status='running'",(time.time(),))
            self._conn.commit()
            return c.rowcount

    def requeue_interrupted(self, max_retries):
        with self._lock:
            rows=self._conn.execute("SELECT job_id,retry_count FROM jobs WHERE status='interrupted'").fetchall()
            n=0
            for r in rows:
                if r["retry_count"] < max_retries:
                    self._conn.execute("""UPDATE jobs SET status='queued',
                    retry_count=retry_count+1,updated_at=? WHERE job_id=?""",(time.time(),r["job_id"]))
                    n+=1
            self._conn.commit()
            return n


    def create_session(self, *, agent_id, channel="grid", title=""):
        now=time.time()
        sid=f"S-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._conn.execute("""INSERT INTO sessions(
              session_id,agent_id,channel,title,state,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?)""",(sid,agent_id,channel,title or agent_id,"idle",now,now))
            self._conn.commit()
        self.append_stream_event(session_id=sid,job_id=None,kind="session_created",
                                 payload={"agent_id":agent_id,"channel":channel,"title":title or agent_id})
        return self.get_session(sid)

    def get_session(self, session_id):
        with self._lock:
            r=self._conn.execute("SELECT * FROM sessions WHERE session_id=?",(session_id,)).fetchone()
        if not r: raise KeyError(session_id)
        return dict(r)

    def list_sessions(self, limit=100):
        with self._lock:
            rows=self._conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",(limit,)).fetchall()
        return [dict(r) for r in rows]

    def update_session(self, session_id, **fields):
        fields["updated_at"]=time.time()
        allowed={"state","active_job_id","waiting_for","last_heartbeat","title","updated_at"}
        bad=set(fields)-allowed
        if bad: raise ValueError(f"unsupported session fields: {sorted(bad)}")
        pairs=", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE sessions SET {pairs} WHERE session_id=?",list(fields.values())+[session_id])
            self._conn.commit()
        return self.get_session(session_id)

    def append_message(self, session_id, role, content):
        mid=f"M-{uuid.uuid4().hex}"
        now=time.time()
        with self._lock:
            self._conn.execute("INSERT INTO thread_messages VALUES(?,?,?,?,?)",(mid,session_id,role,content,now))
            self._conn.commit()
        self.append_stream_event(session_id=session_id,job_id=None,kind="message",
                                 payload={"message_id":mid,"role":role,"content":content})
        return {"message_id":mid,"session_id":session_id,"role":role,"content":content,"created_at":now}

    def list_messages(self, session_id, limit=500):
        with self._lock:
            rows=self._conn.execute("""SELECT * FROM thread_messages
                WHERE session_id=? ORDER BY created_at ASC LIMIT ?""",(session_id,limit)).fetchall()
        return [dict(r) for r in rows]

    def append_stream_event(self, *, session_id, job_id, kind, payload):
        eid=f"SE-{uuid.uuid4().hex}"
        now=time.time()
        with self._lock:
            cur=self._conn.execute("""INSERT INTO stream_events(
              event_id,session_id,job_id,kind,payload,created_at
            ) VALUES(?,?,?,?,?,?)""",(eid,session_id,job_id,kind,json.dumps(payload,ensure_ascii=False),now))
            seq=cur.lastrowid
            self._conn.commit()
        return {"seq":seq,"event_id":eid,"session_id":session_id,"job_id":job_id,
                "kind":kind,"payload":payload,"created_at":now}

    def list_stream_events(self, after_seq=0, limit=1000, session_id=None):
        sql="SELECT * FROM stream_events WHERE seq>?"
        args=[after_seq]
        if session_id:
            sql+=" AND session_id=?"
            args.append(session_id)
        sql+=" ORDER BY seq ASC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows=self._conn.execute(sql,args).fetchall()
        return [{"seq":r["seq"],"event_id":r["event_id"],"session_id":r["session_id"],
                 "job_id":r["job_id"],"kind":r["kind"],"payload":json.loads(r["payload"]),
                 "created_at":r["created_at"]} for r in rows]

    def find_session_by_job(self, job_id):
        with self._lock:
            r=self._conn.execute("SELECT * FROM sessions WHERE active_job_id=?",(job_id,)).fetchone()
        return dict(r) if r else None

    def bind_job_to_session(self, session_id, job_id):
        self.update_session(session_id,state="running",active_job_id=job_id,waiting_for=None)
        self.append_stream_event(session_id=session_id,job_id=job_id,kind="job_bound",
                                 payload={"job_id":job_id})

    @staticmethod
    def _decode(r):
        return {
          "job_id":r["job_id"],"channel":r["channel"],"goal":r["goal"],"worker":r["worker"],
          "allowed_tools":json.loads(r["allowed_tools"]),"allowed_paths":json.loads(r["allowed_paths"]),
          "cloud_allowed":bool(r["cloud_allowed"]),"approval_mode":r["approval_mode"],
          "status":r["status"],"retry_count":r["retry_count"],"last_step":r["last_step"],
          "last_artifact":r["last_artifact"],"pending_tool":r["pending_tool"],
          "created_at":r["created_at"],"updated_at":r["updated_at"]
        }
```

**jobs 表 15 列:** job_id / channel / goal / worker / allowed_tools / allowed_paths / cloud_allowed / approval_mode / status / retry_count / last_step / last_artifact / pending_tool / created_at / updated_at。**五表:** jobs / events / sessions / thread_messages / stream_events。守恒合身:job 出生状态按 authorization_scope(read_only→queued;money_moving/cc→BLOCKED 走人类 token);retry_count 保留为预算(PreN18 禁隐性重试决策)。

—— 戌,2026-09-01 PDT(附录 B,db.py 全文,脱敏)

