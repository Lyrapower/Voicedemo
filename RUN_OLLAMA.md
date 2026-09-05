# Ollama — local substrate (:11434)

> **2026-08-22 更新：本地 coder 已退役。** `qwen2.5-coder:7b` 已从 Ollama 卸载（腾出 ~4.3GB），
> `gateway_config.json` 的 `coder_routing_enabled` 已翻为 `false`。compile/task 两条路由休眠
> （`code_task/registry.py` line 168 `coder_on = bool(...)` → False → 跳过 coder 路径），
> 实际流量由 `/task/cloud_chat`（云大脑 GLM/Kimi/DeepSeek）和 demo/aster 链承载。
> 评估结论：在 16GB Mac 上，没有 Grid 9B + CC 完成不了、必须靠本地 coder 的任务。
> 本地 coder 换代窗口等 64GB Mac（见 PENDING）。

Ollama 现仅承载云 lane（零本地磁盘）：`qwen3.5:397b-cloud` / `deepseek-v4-pro:cloud` / `kimi-k2.5:cloud`。

## Run server

```bash
bash /Users/ciciwang/Projects/demo/scripts/start_ollama.sh
```

Or use the Ollama menubar app (same port `:11434`).

## Routing (gateway :8501)

| Route | Backend | Model | 状态 |
|-------|---------|-------|------|
| `chat` | LM Studio `:1234` | `qwen/qwen3.5-9b` | 活跃 |
| `gateway` | LM Studio | `qwen/qwen3.5-9b` | 活跃 |
| `compile` | Ollama `:11434` | ~~`qwen2.5-coder:7b`~~ | **休眠**（coder_routing_enabled=false） |
| `task` (tools) | Ollama | ~~`qwen2.5-coder:7b`~~ | **休眠**（同上） |
| vision | LM Studio | `qwen/qwen3.5-9b` | 活跃 |
| `/task/cloud_chat` | Ollama 云 lane | GLM/Kimi/DeepSeek | 活跃（主力） |

Config: `grid-sovereign-runtime/configs/gateway_config.json` → `coder_routing_enabled`, `ollama_coder_model`.

## 重新启用本地 coder（未来，64GB Mac）

如需恢复本地 coder（例如换 64GB Mac 后上 qwen3-coder:30b 或 qwen3.8:27b）：

```bash
OLLAMA_CODER_MODEL=<new-tag> bash /Users/ciciwang/Projects/demo/scripts/install_ollama_coder.sh
# 编辑 gateway_config.json：coder_routing_enabled 改回 true，ollama_coder_model 填新 tag
# reload gateway（需用户授权）：
launchctl kickstart -k gui/$(id -u)/com.demo.grid.gateway8501
```

## Verify

```bash
curl -s http://127.0.0.1:11434/api/tags | python3 -m json.tool
curl -s http://127.0.0.1:8501/health
```
