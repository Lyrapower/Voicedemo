# watcher_bridge 部署 + 配套修改

## 组件

| 路径 | 作用 |
|------|------|
| `aether_watcher/watcher_bridge.py` | 8520 state → 8501 store（只 POST） |
| `scripts/aether/start_watcher_bridge.sh` | 启动桥 |
| `scripts/aether/install_watcher_bridge_launchagent.sh` | token + launchd |
| `grid-sovereign-runtime/config/bridge_store.token` | 专用 token（吊销即断桥） |
| `gateway/watcher_snapshot.py` | changyu 读 8520 本地 state |
| `static/aether.html` v3.5.0 | watcher 异动/health/alert |
| `static/changyu.html` | 8520 实时 + 8501 每日任务 |

## 安装

```bash
/Users/ciciwang/Projects/demo/scripts/aether/install_watcher_bridge_launchagent.sh
```

gateway 会从 `grid-sovereign-runtime/config/bridge_store.token` 读 `BRIDGE_STORE_TOKEN`（`start_grid_gateway.sh` 已支持）。

## 验收

1. momentum 异动 → 30s 内到 store，aether 异动区带 `[8520]`
2. kill 桥 → watcher 正常
3. 重启桥 → 不重发历史（`bridge_cursor.json`）
4. detail 含「买入」→ blocked，不入 store
5. 吊销 token → deadletter
6. 心跳停 120s → aether 顶部琥珀 health 条

```bash
/Users/ciciwang/Projects/demo/scripts/aether/verify_watcher_bridge.sh
```
