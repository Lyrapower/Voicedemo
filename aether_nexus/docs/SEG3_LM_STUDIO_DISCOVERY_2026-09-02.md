# 段三 LM Studio 本地模型面 · 真实 runtime discovery 回执

> 2026-09-02 11:25 · 戌 · 致 砥
> 纠正前提:Ollama 无本地模型 ≠ 系统无本地模型。本地模型历史上/架构上在 LM Studio(:1234)。只认 live runtime evidence,不替历史架构图找解释。

## 1. LM Studio 进程/端口

**LM_STUDIO_PROCESS = LIVE** · 自 2026-08-25 起在跑。
- `lsof -i :1234 -sTCP:LISTEN` → `LM\x20Studio 73271 ... localhost:search-agent (LISTEN)`(`search-agent` 是 1234 的 service 名)。
- 多个 LM Studio node 进程:73271(主 app/listen)、74358(llmworker)、73560(systemresourcesworker)、73687(`lms dev`)、73572(renderer)。

## 2. LM Studio loaded/available models(exact IDs)

**LM_STUDIO_MODELS = 4 个本地模型**(GET :1234/v1/models):

| model id | 类型 |
|---|---|
| `qwen/qwen3.5-9b` | 本地 LLM(gateway 默认) |
| `qwen/qwen2.5-vl-7b` | 本地 VLM |
| `demo/aster` | 本地 Aster 身份模型 |
| `text-embedding-nomic-embed-text-v1.5` | 本地 embedding |

## 3. 本地模型最小 inference smoke

**LOCAL_INFERENCE_SMOKE = PASS**

```
POST :1234/v1/chat/completions model=qwen/qwen3.5-9b
→ content="pong", model="qwen/qwen3.5-9b"
→ usage: completion_tokens=2, reasoning_tokens=0
```

本地进程 + 本地模型 + loopback 推理响应。

## 4. execution locality 证据等级

**NO_EGRESS_EVIDENCE = NOT_PROVEN**
- 未做断网 smoke(不安全,未执行)。
- LOCALITY_EVIDENCE 实际等级 = **LOCAL_PROCESS_AND_MODEL_CONFIRMED**(:1234 loopback + 本地 loaded 模型 + 本地推理响应)。
- 不过报为 NO_EGRESS_PROVEN。

## 5. :1234 → sanitizer → gate → :8501/compile 历史路径 live?

**1234→SANITIZER→GATE→8501 STATUS = LIVE(内联,非独立进程)**

- `:8501` gateway(`local_gateway.py`,PID 6232)经 `backend_chat(backend_id="lm_studio")` 发 HTTP 到 `http://localhost:1234/v1`(`openai_endpoint`,line 143)。
- 响应回来后(response 侧)依次经:
  - `airlock_bridge.process_lm_studio_body`(line 721)
  - `substrate_sanitizer.sanitize_response`(line 505)
  - `substrate_gate.gate_clean_content`(import line 50,调用 1173/1515/1534/1661)
- sanitizer/gate 是 **:8501 gateway 进程内联 import 的模块**,不是独立 listener 进程。:1234↔:8501 之间无独立 proxy 监听。
- `:8501/compile` live(POST 空 body → 400 = 端点存在)。`:8501/health` → 200 `served_by=gateway-v4.11 model=qwen/qwen3.5-9b`。

## 6. LM Studio sanitizer/proxy 状态

**LM_STUDIO_PROXY/SANITIZER STATUS = INLINE/CANONICAL(sanitizer) + SHADOW(独立 proxy 脚本)**

| 文件 | 进程? | live? | canonical? |
|---|---|---|---|
| `substrate_sanitizer.py` | 被 :8501 import | live(内联) | canonical(作为 import) |
| `substrate_gate.py` | 被 :8501 import | live(内联) | canonical(作为 import) |
| `airlock_bridge.py`(`process_lm_studio_body`) | 被 :8501 import | live(内联) | canonical(作为 import) |
| `lmstudio_aster_proxy.py` | **无独立进程**(无 listener) | **not live as process** | **shadow/legacy**(代码存在 ≠ runtime) |

## 7. cc.py 真实职责

**cc.py = `CCExecutor`,纯 Claude Code executor**。
- `class CCExecutor` → `asyncio.create_subprocess_exec("claude", ...)` 起 `claude` CLI 子进程。
- 设 `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` → Ollama :11434(Anthropic Messages 协议)。
- **不是本地模型路由器**。LM Studio 本地模型能力**不经 cc.py**;走 :8501 gateway `backend_chat lm_studio`。
- 砥 item 9 成立:不把 LM Studio 硬塞进 cc.py。两条路径各走各的。

## 8. demo/aster 是否被默认 local route 静默选中?

**否**。
- `:8501/health` default `model=qwen/qwen3.5-9b`(非 demo/aster)。
- `config/aster.toml`:`api_model_id="qwen/qwen3.5-9b"`(line 53)、`vl_model_id="qwen/qwen3.5-9b"`(line 62)。
- `demo/aster` 仅在 `virtual_model_id`/`gateway_plugin`(line 58/61)——Aster 身份插件;**只有显式 `model=demo/aster` 才命中**,且触发五层 `grid_verification` 闸(无 HMAC → 403,无 Aster 输出)。无静默选中。

## 9. qwen/qwen3.5-9b 可从 canonical path 真实命中?

**是**。实弹:

```
POST :8501/v1/chat/completions model=qwen/qwen3.5-9b stream=false max_tokens=16
→ 200, content="pong", finish=stop, served_by=gateway-v4.11
→ route_id=2e2bffc6-a01a-4787-af09-0cf39322a78b
→ grid_meta={route_class:"unsafe_debug:compat", computed_verdict:"DRAFT_ECHO",
             draft_only:true, production:false, blocked:false}
```

裸 qwen(无五层 HMAC)→ `unsafe_debug:compat` / `DRAFT_ECHO` / `draft_only=true`(非 production Aster)。content 真实返回,无静默 fallback,无假 FINAL。符合「五重门只拦 demo/aster」。

## 10. 完整 runtime trace(canonical LOCAL path)

```
Grid/Harness
→ POST :8501/v1/chat/completions  (model=qwen/qwen3.5-9b)
→ local_gateway.py  backend_chat(backend_id="lm_studio",
                                   openai_endpoint=http://localhost:1234/v1)
→ HTTP → LM Studio :1234  (qwen/qwen3.5-9b,本地 loaded)
→ raw LM Studio response
→ airlock_bridge.process_lm_studio_body      (response 侧,line 721)
→ substrate_sanitizer.sanitize_response      (line 505,strip reasoning_content)
→ substrate_gate.gate_clean_content          (line 50 import,1173/1515/1534/1661)
→ cleaned content "pong"
→ route_id + grid_meta(provenance 字段)
→ Grid
```

- process evidence:PID 6232(:8501)、73271(:1234)。
- request/log evidence:gateway log `gateway8501.out.log` 含 :1234 backend_chat 行;响应含 route_id+grid_meta。
- exact model ID:`qwen/qwen3.5-9b`。
- no silent fallback:无 HMAC → 标 `DRAFT_ECHO`/`draft_only`,不伪装 production Aster。
- no shadow proxy::1234↔:8501 之间无独立 listener;sanitizer/gate 全内联。

## :8504 是什么

`:8504` = **grid-voice-daemon**(`gateway/voice_daemon.py`,PID 73706,Python 3.13)。
- `/health` → 200 `service=grid-voice-daemon asr=sensevoice tts=cosyvoice2`。
- **与本地 LLM 路径无关**(语音/ASR/TTS 服务)。不属于 canonical local model path。

## LEGACY/SHADOW PATHS

- `scripts/substrate_airlock/scripts/lmstudio_aster_proxy.py` — 代码存在,无独立进程 → shadow。
- `substrate_gate.py`/`substrate_sanitizer.py` 的**独立脚本形式** = shadow;**被 :8501 import 的模块形式** = canonical live。
- `:8504 grid-voice-daemon` — live 但属语音面,非 LLM 路径。
- `demo/aster` 模型 — loaded 但非默认 route,仅显式 `model=demo/aster` 命中(触发五层闸)。

---

## 重新裁决

```
OLLAMA_CLOUD_PATH        = LIVE/ACCEPTED
  claude CLI(cc.py CCExecutor) → ANTHROPIC_BASE_URL=:11434
  → Ollama v0.33.0 native Anthropic Messages API → cloud models(glm-5.3:cloud 等)
  无 local models in Ollama。

OLLAMA_LOCAL_PATH         = EMPTY/BLOCKED
  ollama list = 仅 :cloud 模型,无 local。段三不要求为 Ollama pull local。

LM_STUDIO_LOCAL_PATH      = LIVE/CANONICAL
  :8501 gateway → :1234 LM Studio → qwen/qwen3.5-9b(local) + qwen2.5-vl-7b(local VLM)
  + nomic-embed(local) + demo/aster(local, gated)。内联 sanitizer/gate。
  = 现有 local-model surface,优先复用,不另造 bridge/shim。

SYSTEM_LOCAL_MODEL_EXECUTION = LIVE(via LM Studio :1234)
  本地模型存在且可从 canonical Grid 路径(:8501)命中。
  NOT BLOCKED。(no-egress 断网 proof 未做 → LOCALITY_EVIDENCE = LOCAL_PROCESS_AND_MODEL_CONFIRMED,非 NO_EGRESS_PROVEN。)
```

## topology(分两条,不强求长得一样,不加 bridge/shim)

```
CLOUD:
  Grid → Harness → Claude Code(cc.py) → Ollama :11434 → cloud model(glm-5.3:cloud)

LOCAL:
  Grid → :8501 gateway(backend_chat lm_studio) → LM Studio :1234 → qwen/qwen3.5-9b(local)
```

## 历史文档 vs live runtime 不一致

- 历史「:1234 → sanitizer → gate → :8501/compile」叙事把 sanitizer/gate 描成独立环节 → **LEGACY TOPOLOGY STALE**:实际是 :8501 内联 import 的模块,无独立进程。
- `lmstudio_aster_proxy.py` 作为独立 proxy → **LEGACY/SHADOW**:代码在,进程不在。
- 「Ollama 无本地 → 系统无本地」→ **错误推论**:本地模型在 LM Studio,不在 Ollama。
