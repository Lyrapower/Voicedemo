# 段三 接线回执 · 2026-09-02 11:50 · 戌 → 砥

> 紧收测试面后执行:3 个 bounded local smoke(max-time 15s,无 retry)+ 静态 reachability + port registration + cc.py cloud path provenance。不主动 outage / 不 no-egress / 不扩大矩阵。

## A. LOCAL PATH

```
Grid
→ :8501 /v1/chat/completions
→ local_gateway.py  backend_chat(backend_id="lm_studio",
                                   openai_endpoint=http://localhost:1234/v1)
→ LM Studio :1234  (qwen/qwen3.5-9b,本地 loaded)
→ raw response
→ airlock_bridge.process_lm_studio_body      (response 侧,line 721)
→ substrate_sanitizer.sanitize_response      (line 505,strip reasoning_content)
→ substrate_gate.gate_clean_content          (line 50 import,内联)
→ cleaned content + route_id + grid_meta(factual receipt)
→ Grid
```

**T1 DEFAULT(不传 model)** — **PASS**
```
POST :8501/v1/chat/completions  {messages:[{content:"reply exactly pong"}],max_tokens:16}
→ 200, time=2.69s
→ model=qwen/qwen3.5-9b, content="pong", served_by=gateway-v4.11
→ route_id=a1b2ebe8-8302-4b34-a3b1-2fc9a065b828
→ grid_meta.route_class=unsafe_debug, routed_to=unsafe_debug:compat,
   computed_verdict=DRAFT_ECHO, draft_only=true, blocked=false
→ substrate_usage: prompt_tokens=60, completion_tokens=2, reasoning_tokens=0
→ raw_text_preview="pong", sanitized_text_preview="pong"
```
默认解析到 qwen3.5-9b,非 demo/aster,非 Ollama cloud。provenance(route_id+grid_meta)在响应里。

## B. CLOUD PATH

```
Grid/Harness
→ CCExecutor(harness_resident/harness/cc.py)
→ claude CLI subprocess(--model cc_model, ANTHROPIC_BASE_URL=:11434, ANTHROPIC_AUTH_TOKEN=ollama)
→ Ollama :11434 native Anthropic /v1/messages
→ selected :cloud model(glm-5.3:cloud 等)
→ ActionEnvelope + FactualReceipt → app/harness/provenance.jsonl(append-only, hash-chained)
→ Grid
```

既有 Claude/Ollama evidence(段三运行回执 SEG3_RUNTIME_RECEIPT_2026-09-02.md):
- Ollama v0.33.0 native Anthropic Messages API(POST /v1/messages 200)
- `claude --model glm-5.3:cloud -p 'reply pong'` 经 Ollama 200 有字

## C. MODEL SAFETY

| 测试 | 结果 | evidence |
|---|---|---|
| **default → qwen3.5-9b** | **PASS** | T1:不传 model → model=qwen/qwen3.5-9b,非 demo/aster,非 Ollama |
| **nonexistent truthful fail** | **FAIL** | T2:请求 `nonexistent/fake-xyz` → 200 model=qwen/qwen3.5-9b content="Hello!..." — **静默 fallback 到默认 qwen** |
| **explicit Aster** | **PASS** | T3:`model=demo/aster` → 403 `grid_chain_verification_required` missing 5 layers(schema/route/signer/keyholder/hmac/payload_hash)— 走五层闸,truthful deny,非默认 substrate |

**T2 FAIL 上报(不擅自修)**:`:8501 local_gateway.py` 对不存在 model 静默 fallback 到默认 qwen,违反「no silent fallback」。但 `local_gateway.py` 是 **frozen 红线文件**(grid-infrastructure-immutable.mdc / local-gateway-absolute-redline.mdc),agent 无授权不得改。**需用户逐字授权 + GRID_INFRASTRUCTURE_UNLOCK=1 才能修**。本轮如实上报,不擅动。

## D. SHADOW / LEGACY MATRIX

| 路径 | CURRENT_PROCESS | REFERENCED_BY | LIVE_REACHABLE | STATUS |
|---|---|---|---|---|
| `scripts/substrate_airlock/scripts/lmstudio_aster_proxy.py` | 无(无 listener,非 server:argparse+urllib CLI,无 uvicorn/HTTPServer/bind) | 仅自身 selftest;无外部 import/launchd/subprocess/cron | NO | **LEGACY_DORMANT / NOT_ON_CANONICAL_PATH** |
| `substrate_gate.py` 独立脚本形态 | 无独立进程 | 被 :8501 local_gateway.py import 为模块(live);独立脚本形态无 launcher | 模块形态 live / 脚本形态 dormant | **CANONICAL(作为 import) / DORMANT(独立脚本)** |
| `substrate_sanitizer.py` 独立脚本形态 | 同上 | 同上 | 同上 | **CANONICAL(作为 import) / DORMANT(独立脚本)** |
| `airlock_bridge.py`(`process_lm_studio_body`) | 无独立进程 | 被 :8501 import(live) | 模块形态 live | **CANONICAL(作为 import)** |
| `com.grid.qwen-substrate-watchdog.plist` | state=not running(last exit 0) | 跑 `scripts/ensure_qwen_substrate.sh` | 启动时保 LM Studio :1234 + qwen3.5-9b(拒 demo/aster),**不拉起任何 proxy** | **CANONICAL watchdog,无 shadow proxy** |
| `run_acceptance.py` | 无 | 无 launchd/cron | 仅手动 | **MANUAL_ONLY** |

**live shadow found = NO**。所有 shadow 路径需手动 `python3 ...` 才能跑,无 launcher/import/subprocess 自动拉起,无 alternate endpoint,无法形成 shadow executor/proxy。

## E. PORTS

**1234** = LM Studio model API(local OpenAI-compatible inference endpoint;owner=LM Studio process;execution=local model inference;default model config-derived via `config/aster.toml` `api_model_id`;NOT "Aster proxy"——demo/aster 是此处一个 model,非端口身份;sanitizer/gate 内联 :8501,非此端口独立 proxy)
- canonical: `PORTS.md:12` · `PORT_PROCESS_CONVENTION.md:12-22`

**11434** = Ollama API(model transport;native Ollama + OpenAI-compat + Anthropic Messages;execution=local_or_cloud_by_selected_model;NOT "local inference"——`:cloud` model 远程执行;provenance 必须分记 transport_locality 与 model_execution_locality)
- canonical: `PORTS.md:18` · `PORT_PROCESS_CONVENTION.md:24-31`

(8504 voice daemon 亦澄清:NOT local LLM proxy——`PORTS.md:4`)

## F. PROVENANCE SAMPLES

### Local qwen receipt(T1 实弹,:8501 响应 grid_meta)
```
route_id        = a1b2ebe8-8302-4b34-a3b1-2fc9a065b828
route_class     = unsafe_debug
routed_to       = unsafe_debug:compat
computed_verdict= DRAFT_ECHO
draft_only      = true
selected_route  = chat
substrate_usage = {prompt_tokens:60, completion_tokens:2, reasoning_tokens:0}
raw_text_preview= "pong"
sanitized_text_preview = "pong"   (sanitize 未改字 → reasoning_content 已 strip 干净)
backend_id      = null  (ungated debug path 不填;production Aster path 才填)
cost_usd        = null  (同上)
transport_locality       = LOCAL_PROCESS (:1234 loopback)
model_execution_locality = LOCAL (qwen3.5-9b 本地 loaded)
```
注:local path 的 receipt 是 gateway 响应级 `grid_meta`(既有 canonical surface),非 harness provenance.jsonl。两条 lane 用各自既有 provenance surface,不造第二套。

### Cloud Claude/Ollama receipt(cc.py 实弹落盘,临时 log 验证)
```
event_id        = cc:seg3-cloud-sample-003:f62e1e08
mission_id      = seg3-cloud-sample-003
actor           = GRID_LOCAL  (envelope) / TOOL  (receipt)
decision_origin = GRID_LOCAL
executor_type   = claude_code
backend         = ollama
endpoint        = http://127.0.0.1:11434
selected_model  = glm-5.3:cloud
transport_locality       = LOCAL_PROCESS
model_execution_locality = CLOUD
bridge          = NONE
transport_protocol = anthropic_messages
request_hash    = 63efa2afe03e397d
response_hash   = 9795c5ff8937f235
status          = EXECUTED
evidence_pointer= ollama:glm-5.3:cloud
prev_hash / event_hash  (hash-chained append-only)
```

## G. cc.py

**changed** = `cc.py` 本身**未改**(已正确:cloud path only)。修的是 `app/harness/provenance.py:119`——`record_receipt` 的 `ev` dict 原本丢弃 `metadata`,现加 `"metadata": d.get("metadata") or {}`,使 executor_type/transport_locality/model_execution_locality/bridge/selected_model/hashes 落盘。

**exact live path**:
```
CCExecutor.run(job)
→ claude CLI subprocess(--model cc_model, ANTHROPIC_BASE_URL=:11434)
→ _record_cc_provenance(job, cc_model, cc_endpoint, prompt, result, ok, status)
   → ActionEnvelope(decision_origin=GRID_LOCAL, operation=cc.execute).to_dict()
     → provenance.record_action() → provenance.jsonl(action 事件,hash-chained)
   → FactualReceipt(status=EXECUTED/FAILED/TIMEOUT, metadata={executor_type,locality,bridge,hashes}).to_dict()
     → provenance.record_receipt() → provenance.jsonl(receipt 事件,hash-chained,含 metadata)
```
失败路径:CC 版本不识别旗标 → truthful return error;timeout → provenance 记 TIMEOUT 后 return;无 fallback。

**no LM Studio contamination** = `rg '1234|lmstudio|lm_studio|LMStudio' harness_resident/harness/cc.py` → 0 命中。`cc_endpoint` 默认 `http://127.0.0.1:11434`(Ollama),从不 :1234。

**no bridge/shim** = cc.py 无 bridge/shim/proxy 实现(仅 `bridge=NONE` metadata 字段)。

**no silent fallback** = 失败 truthful return,无 qwen/lm fallback。

## H. STATUS

```
LM_STUDIO_LOCAL_PATH        = LIVE/CANONINAL(:8501→:1234→qwen3.5-9b,内联 sanitize/gate)
QWEN3.5_9B_DEFAULT           = CONFIRMED(config-derived,T1 实弹命中)
ASTER_SPECIALIZED_RESOURCE   = CONFIRMED(T3 显式 model=demo/aster→403 五层闸,非默认)
CC_CLOUD_PATH                = LIVE(claude CLI→Ollama :11434→:cloud model,provenance 落盘)
SHADOW_PATHS                 = NONE LIVE(lmstudio_aster_proxy 等 LEGACY_DORMANT,无 launcher)
PORT_REGISTRATION            = DONE(1234+11434 in PORTS.md & PORT_PROCESS_CONVENTION.md)
PROVENANCE                   = WIRED(local=grid_meta;cloud=provenance.jsonl+metadata;metadata 落盘已修)
NO_SILENT_FALLBACK           = PARTIAL — T2 nonexistent model 仍静默 fallback 到 qwen(:8501 frozen,需用户授权修)
NO_EGRESS_LOCALITY           = NOT_PROVEN(本轮不做断网;LOCAL_PROCESS_AND_MODEL_CONFIRMED=YES)
```

## 段三裁决

```
SEGMENT_3_CLOUD_PATH = ACCEPTED
  (claude CLI→Ollama native Anthropic→:cloud model,provenance 落盘含 locality 分离,无 bridge)

SEGMENT_3_LOCAL_PATH = NOT YET ACCEPTED
  阻塞:T2 nonexistent model 静默 fallback 到 qwen(:8501 local_gateway.py frozen,
       需用户逐字授权 + GRID_INFRASTRUCTURE_UNLOCK=1 才能修 no-silent-fallback)
  其余(local path live、qwen default、aster specialized、shadow none、ports)已 ACCEPTED
```

## 文件改动清单

| 文件 | 改动 | 原因 |
|---|---|---|
| `PORTS.md` | 加 1234 行;8504 notes 加 "NOT local LLM proxy" | 1234 未登记;8504 voice daemon 澄清 |
| `PORT_PROCESS_CONVENTION.md` | 加 1234 section(LM Studio model API,config-derived,NOT Aster proxy,内联 sanitize/gate) | 1234 canonical 登记 + 纠正 stale "Aster proxy" 叙事 |
| `app/harness/provenance.py:119` | `record_receipt` ev dict 加 `"metadata": d.get("metadata") or {}` | receipt metadata(executor_type/locality/bridge/hashes)原本丢弃,现落盘 |
| `harness_resident/harness/cc.py` | **未改**(已正确) | cloud path only,无 LM Studio 污染 |

**未动(红线)**:`local_gateway.py`(T2 fallback 修复需用户授权)· `.packs/aster-qwen-clean-substrate/`(Fable 守恒整包,零改动权,含 stale proxy 提及→标 HISTORICAL/FROZEN-PACK,不动)。

## 待用户裁决

**T2 silent fallback**:`:8501` 对不存在 model 静默 fallback 到默认 qwen。修复需动 `local_gateway.py`(frozen)。请用户决定:是否授权修(逐字授权 + `GRID_INFRASTRUCTURE_UNLOCK=1`),或接受当前 fallback 行为并仅靠 provenance 记录 `selected_model_requested != selected_model_resolved` 来暴露 mismatch。
