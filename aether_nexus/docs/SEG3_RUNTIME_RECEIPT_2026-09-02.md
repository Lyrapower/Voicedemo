# 段三运行回执 · 2026-09-02

> 砥段三改裁决后取证。Ollama v0.14.0+ 原生 Anthropic Messages,不造桥。
> 前一版"Claude CLI 与 Ollama 协议不匹配需换 executor"判断撤回——成立。

## 1) OLLAMA_VERSION

```
ollama version is 0.33.0
```

≥ 0.14.0 → 原生 Anthropic Messages API 支持。PROTOCOL_MISMATCH 不成立。

## 2) ANTHROPIC_NATIVE_ENDPOINT_TEST = PASS

- exact command:
```
curl -s -o /tmp/anthr_body.txt -w "HTTP_STATUS=%{http_code}\n" \
  -X POST http://127.0.0.1:11434/v1/messages \
  -H "x-api-key: ollama" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"glm-5.3:cloud","max_tokens":16,"messages":[{"role":"user","content":"reply exactly pong"}]}'
```
- HTTP status: **200**
- endpoint: `http://127.0.0.1:11434/v1/messages`
- body:
```json
{"id":"msg_d4671b80bd2ff4ae34e0d181","type":"message","role":"assistant","model":"glm-5.3",
 "content":[{"type":"thinking","thinking":"The user is asking me to reply exactly \"pong\". This appears to be a"}],
 "stop_reason":"max_tokens","usage":{"input_tokens":15,"output_tokens":16}}
```
- Ollama server evidence (`~/.ollama/logs/server.log`):
```
[GIN] 2026/09/02 - 11:00:42 | 200 | 514.181292ms | 127.0.0.1 | POST "/v1/messages"
```

## 3) CLAUDE_CODE_NATIVE_OLLAMA_TEST = PASS

- exact command:
```
ANTHROPIC_BASE_URL=http://127.0.0.1:11434 ANTHROPIC_AUTH_TOKEN=ollama \
  claude --model glm-5.3:cloud -p 'reply exactly pong'
```
- stdout:
```
⚠ claude.ai connectors are disabled because ANTHROPIC_API_KEY or another auth source is set and takes precedence over your claude.ai login · Unset it to load your organization's connectors
pong
```
（⚠ 行是 benign 提示:ANTHROPIC auth 设了 → claude.ai connectors 关;不影响执行）
- exit: **0**
- exact selected model: `glm-5.3:cloud`
- Ollama server evidence:
```
[GIN] 2026/09/02 - 11:00:58 | 200 | 1.784736417s | 127.0.0.1 | POST "/v1/messages?beta=true"
[GIN] 2026/09/02 - 11:00:58 | 200 | 2.111144292s | 127.0.0.1 | POST "/v1/messages?beta=true"
```
（claude CLI 直发 Anthropic Messages 到 Ollama 11434,200）

## 4) LOCAL_MODELS = []（空）

`ollama list` 全是 `:cloud`,SIZE 列全 `-`(无本地权重文件)。

## 5) CLOUD_MODELS

```
minimax-m3:cloud
glm-5.3:cloud
glm-5.3-flash:cloud
qwen3.5:397b-cloud
deepseek-v4-pro:cloud
kimi-k2.5:cloud
```

全部 `remote`(ollama.com 代理),非本地 inference。

## 6) 11434_REGISTRATION = NOT REGISTERED

- `PORTS.md`:无 `11434|ollama`
- `PORT_PROCESS_CONVENTION.md`:无 `11434|ollama`
- 命中 `11434` 的其它文件(`scripts/grid/grid_router.py`、`tests/test_*.py`、`scripts/install_ollama_launchagent.sh`、`RUN_OLLAMA.md`)均非 canonical port registry
- `RUN_OLLAMA.md` 是运行文档(头部 "Ollama — local substrate (:11434)"),非 registry;且载:**2026-08-22 本地 coder `qwen2.5-coder:7b` 已卸载退役**(腾 ~4.3GB),本地 coder 路由休眠,等 64GB Mac 再起

无第三份 canonical source。11434 未登记。

## 7) CURRENT EXACT PATH

```
Grid
→ Harness
→ Claude Code executor (claude CLI 2.1.201)
→ Ollama native Anthropic /v1/messages (127.0.0.1:11434)
→ glm-5.3:cloud  (CLOUD execution)
→ receipt
```

## 8) bridge/shim process = NO

- `lsof :11434 -sTCP:LISTEN`:仅 `ollama` (PID 74589)
- `8080/8000/11435/anthr/shim/bridge` 端口无监听
- Ollama 日志显示 claude 发的 `POST /v1/messages?beta=true` 直达 11434,中间无代理

## 9) 段三状态分别

| 状态 | 值 |
|---|---|
| CLAUDE_CODE_OLLAMA_TRANSPORT | **PASS**(实弹 pong,claude→ollama 原生 anthropic,无桥) |
| LOCAL_MODEL_EXECUTION | **BLOCKED / UNPROVEN**(无本地模型;唯一本地 coder `qwen2.5-coder:7b` 已 2026-08-22 卸载;16GB Mac,~13Gi 磁盘 avail) |
| PORT_REGISTRATION | **NOT REGISTERED**(11434 未在 PORTS.md / PORT_PROCESS_CONVENTION.md) |

## 附:机器现状(砥 item 4 要,因无本地模型)

- 磁盘:`/` 228Gi,57% used,~13Gi avail
- 内存:16 GB
- 已有模型:6 个,全 `:cloud`
- 原计划段三应调用的本地模型:**无**——RUN_OLLAMA.md 载本地 coder 已退役,等 64GB Mac

## 结论

- CLAUDE_CODE_OLLAMA_TRANSPORT 已实弹证明 PASS(无桥)。
- LOCAL_MODEL_EXECUTION BLOCKED:无本地模型,且 16GB/13Gi 空间不适合随便 pull 大模型。是否补本地模型由砥定。
- 11434 未在 canonical registry 登记,待补登(语义须含 native Ollama + OpenAI compat + Anthropic Messages compat + execution=local_or_cloud_by_model)。
- cc.py 暂未改(砥 item 2:不大改 executor architecture)。

段三整体:**NOT YET ACCEPTED / BLOCKED**(LOCAL_MODEL_EXECUTION + PORT_REGISTRATION 两项未过;TRANSPORT 已过)。
