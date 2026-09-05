# CC CLI 退役归档 (2026-07-24)

拍板: **D1b** (保留 DeepSeek off-pool) + **D2b** (量化补跑精简 launchd)

## 归档 plist

| 文件 | 原 Label | 说明 |
|------|----------|------|
| `com.grid.poolscan.plist` | `com.grid.poolscan` | Grid+CC pool scan (Runner B) — 已 bootout |
| `com.grid.offpoolscan.plist` | `com.grid.offpoolscan` | Grid+CC offpool scan (Runner C) — 本就未加载 |

## 仍运行

| Label | 说明 |
|-------|------|
| `com.demo.aether.offpool` | DeepSeek-only (`OFFPOOL_LANES=deepseek-v4\|ollama_cloud\|...`) |
| `com.demo.aether.pool-quant-gate` | 仅 `ensure_pool_scan.py` 量化补跑，无 CC / :8500 |

## 回滚

```bash
cp com.grid.poolscan.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.grid.poolscan.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.demo.aether.pool-quant-gate.plist
```
