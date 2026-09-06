# HARNESS_GOLIVE_2026-09-05 · 戌 → 溯/核

包：HARNESS GOLIVE PKG v1.3。分支 `fix/regime-r3r4-shift`（本包禁止切/建新分支）。未 push。

## -1 前置

`git status --porcelain | wc -l` 开工：**216**。当前分支：**fix/regime-r3r4-shift**。

| 堆 | 数 | 处置 |
|---|---|---|
| 1 运行产物 | ~187 | `.gitignore` 已加 `**/state/`、`deliver/**/evidence/`、traces/sqlite、field jsonl、`harness_resident/.env`；不提交不 stash |
| 2 RWA | 1 | `aether_nexus/docs/RWA_CHAIN_CONNECT_2026-09-05.md` 留在该分支 |
| 3 harness_resident 源 | 0 | 已在 `demo/harness_resident/` |
| 4 其余 | 28→stash | `stash@{0} pre_golive_20260905`（含 regime R3/R4 未提交稿） |

收工树仍脏：RWA 回执、已跟踪 jsonl、`grid-console/` 残留、`pipeline_doctor.env`（未读未提交）。

## A 采证

| # | 输出 | 分支 |
|---|---|---|
| A1 | `harness_resident/harness/` 有 supervisor/api/gateway/cc；`/Users/*/Projects/grid-resident-harness/` **不存在** | **收** · 无 §2.1 |
| A2 | `rg resource_gate\|ActionEnvelope\|record_receipt supervisor.py` → 开工 **MISS** | **§2.2** |
| A3 | escalate/requeue/persist/max_retries 有；escalate 目标原为 `fast\|deep\|full\|research`；persist `write_mode=gateway_owned` `attempted=False`（不写 diary）；无 `demo/aster` 启动断言 | **§2.3** |
| A4 | GatewayClient v2.1 有 `cloud_chat` / 空 content 拒 / `demo/aster` 拒；**无 ModelMismatch 类** | **§2.4** |
| A5 | local `qwen/qwen3.5-9b` / fast `glm53` / deep `glm52` / full `glm53_full` / research `deepseek_v4`；无 kimi、无 demo/aster route | **收** |
| A6 | `lsof :8630` **空** | 直接起身体 |
| A7 | 无 `com.grid.harness-api` / `com.grid.harness-supervisor`；旧脚本一只 `com.grid.resident-harness` 未 load | **§4.1** |
| A8 | `app/harness/provenance.jsonl` **无**；`state/provenance.jsonl` **114** 行；`verify_chain` 在 `app/harness/provenance.py:159` | §3.2 用本体 |
| A9 | `cc.py` 有 `disallowedTools` + `CC_TOOL_UNIVERSE` | §3.3 |
| A10 | `python3 test_security_v131.py` → **13 checks green** exit 0（改后复跑仍绿） | **收** |
| A11 | PORTS 8630 原 session-only；8631 有行；8788 **在跑且未登记** | **§4.3** |
| A12 | `StartInterval=300` · `RunAtLoad=true`；`launchctl list` **无** `qwen-substrate` | 周期型未跑 → **D9 / E** |
| A13 | 有 `POST /jobs` `GET /jobs/{id}`；**无** `POST /api/jobs` | **§2.6** |
| A14 | `launchctl list` 无 kokoro 名；8631 **LISTEN** pid 2075；`GET /` 404；`GET /api/health` `ok:true engine=kokoro`；`POST /v1/audio/speech` **200** audio/wav **12.599s** `/tmp/k8631_golive.wav` 64844B | 只记录，进 VOICE |
| A15 | 开工投任务 = Cursor 会话 / 本机命令，不经 8630 | 上线后改走 A13 |
| A16 | 1234 **LM Studio** LISTEN；11434 **ollama** LISTEN；`claude` `aster_grid_v5/.tools/...` **2.1.201** | 执行体在 |

## B 证

### §3.1 local lane

GatewayClient `qwen/qwen3.5-9b` · `reply exactly pong` → text `pong` · model=requested。

provenance：

```
action  golive-3-1  golive-3-1:run  prev=82b7141a1f7cbc5e  hash=6699baff576c85c3
receipt golive-3-1  golive-3-1:run  EXECUTED  prev=6699baff576c85c3  hash=6711dd3059773e8e
metadata model_requested=qwen/qwen3.5-9b model_resolved=qwen/qwen3.5-9b
         transport_locality=127.0.0.1:8501 model_execution_locality=local
```

### §3.2 链校验

`verify_chain` **True** n=117。改旧行一字节 → **False**。改回字节一致 → **True**。

### §3.3 cc 围栏

`--disallowedTools` 含 Bash/Write。goal=`run \`ls /\` with Bash`。

stdout 拒绝原文：无 Bash 工具、未跑 `ls /`、未写 RESULT.md。无 `/` 副作用文件。

初跑 returncode=0 被误标 EXECUTED（`J-golive33`）。补丁后 `J-golive33c`：`ok=False` receipt **DENIED** hash `d570fa28a190d3ef`。

### §3.4 ModelMismatch

请求 `nonexistent/fake-xyz` → 抛 `ModelMismatch: requested 'nonexistent/fake-xyz' resolved 'qwen/qwen3.5-9b'`（D3 静默 fallback 兜住）。receipt **FAILED**。job 未走 done。

### §3.5 sanitizer

local 带 think 提示 → `completion_tokens_details.reasoning_tokens=0` · content=`pong` **无** `<think>` · resp JSON 含子串 think（提示词回声/字段，不是 content）。**未**见到 `reasoning_tokens>0` 的 raw 泄漏；8501 侧已干净或模型未吐 think。不标红，据实。

### §3.6 壳入口（戌代投）

无 token `GET /api/capabilities` → **401**。

`POST /api/jobs` read_only `reply exactly pong` → `J-074eaaa2e57d` queued → **3s done** · `receipt_event_id=J-074eaaa2e57d:run`。

### §3.7 platform.db 四尾

| 项 | 值 |
|---|---|
| PRICE_BASIS | `first_real_ic_v1.py:24` 已是 `split-adjusted close (FMP historical-price-eod/full), not dividend-adjusted` · **收** |
| D4 每周重拉 sp500 / stored/fresh≠1 拆股 | **代码未落** · 本包未写 `platform.db` · 仍债 |
| WATCHLIST ⊆ pulse equity | pulse `watchlist` = `equity` = SPY,QQQ,INTC,ANET,NBIS,NOW,HOOD,CRCL,USO · 差集 **∅** · sources 全 `watchlist` · nomination `overflow_n=0` `scan_n=0` · **无「多出 8 个」**（今日座位即 9 只 env/heat 名单） |
| D5 写 0 行 | `first_real_ic_v1.py:140-145` `written==0` → `return 1` · **收**（未对生产库实跑） |

### §4.4 常驻处决案

| 条 | 实测 |
|---|---|
| T8 零自生 | 清表后 600s `jobs count=0`（`/tmp/harness_t8_result.json` n=0 t=1788669234） |
| N7 `worker=nope` | `J-5ba84258c996` **blocked** `UNKNOWN_WORKER` · 不重试 |
| kill -9 supervisor | 69386 被杀 → 30s 内 pid **71210** · `runs=2` `state=running` · 两 PID 非 `-` · 当时无 running job |
| 无 token 401 / 有 token 200 · `web.fetch=DENIED` | **是** |
| 跨夜 ≥8h | **8h 后补一行** |

`validate_bind('0.0.0.0','')` → `RuntimeError`（未真绑 0.0.0.0）。

## C 债表

| # | 债 | 修法 | 归属 |
|---|---|---|---|
| D3 | gateway T2 静默 fallback | 解锁 local_gateway 才修 | Lyra |
| D6 | 段二哨兵首负载 | GRID_VOICE 包 | 溯 |
| D7 | Telegram 出站 | bot token/chat_id 归 Lyra；GRID_VOICE 包 | Lyra |
| D8 | 8788 stub | 已关（`com.demo.garden.telemetry8788` bootout+disable） | — |
| D9 | watchdog 周期型未跑 | 按 A12 | 戌 |
| D10 | cc lane 不经 8501 | 已登记例外；透传解锁归 Lyra | Lyra |
| D11 | OS 级隔离 | cc job 累计 50 条后再定；不前置 | 核 |
| D12 | 执行体不在 | 本次 A16 在；不代起 | Lyra |
| platform.db D1/D2/D4/D5 | D5/头 收；**D4 未施工** | PLATFORM_DB_CLOSEOUT | — |

## D commit

分支 `fix/regime-r3r4-shift`。**未 push**（origin=`Lyrapower/Voicedemo.git`；本分支还叠着 RWA/regime，未擅自推）。

| hash | 项 |
|---|---|
| `21dc928` | pile1 gitignore |
| `6462d0f` | §2.8/2.9 GRID_TZ + .env loader |
| `feb480e` | §2.4 ModelMismatch |
| `646ce23` | §2.2/2.3 gate + escalate glm + receipt |
| `6b0a1f4` | §2.6 `/api/jobs` + `/api/capabilities` |
| `ef4c5e4` | §4.1 两只 launchd |
| `d602aa1` | §2.7 PORTS + L5/L7 |
| `a31b07e` | §3.3 DENIED 收据 |

`.env` 已写 `harness_resident/.env`（gitignore 第 84 行 `check-ignore` 命中）。**未打印 token。** plist 无 token。

## E 停下的事

- 无四类真停。S1–S10 未红。`validate_bind` 生效。
- A12 watchdog **周期型未跑** → D9 断环，本包未 `bootstrap` 该 plist。
- 围栏存在；3.3 拒 Bash。
- 执行体在（A16）。
- D4 未改 backfill / 未写 `platform.db`。
- 跨夜 8h 未到。
- `grid-resident-harness/` 独立目录不存在，无改名。
- 首条 F job 为 **戌代投**（包允许 pong）。
- `.env` 在仓库树内；read_only cc 的 `--add-dir` 是 demo 根，**文件级剔 .env 做不到**（残量）。

## F 上线判定

| 项 | 值 |
|---|---|
| `com.grid.harness-api` | pid **69377** |
| `com.grid.harness-supervisor` | pid **71210**（杀 69386 后拉起） |
| 8630 lsof | `Python 69377 … TCP 127.0.0.1:8630 (LISTEN)` |
| 8788 | closed |

首条真实 job（**戌代投** read_only pong）：

```
action  J-074eaaa2e57d  J-074eaaa2e57d:job.run  prev=d570fa28a190d3ef  hash=76fde4ac736a1976
receipt J-074eaaa2e57d  J-074eaaa2e57d:run      EXECUTED  prev=76fde4ac736a1976  hash=39a11dd51598e0dd
        model_requested=qwen/qwen3.5-9b
```

## G 打勾表

本机 **无** `STATUS_CHECKLIST_2026-09-05.md`（Desktop / demo / 家目录均未找到）。不另出表。GOLIVE 一行记此：

`GOLIVE v1.3 · 2026-09-05 · 两 PID 在 · 8630 听 · 壳 /api/jobs 通 · T8 count=0 · 8h 后补 · 未 push`

—— 戌
