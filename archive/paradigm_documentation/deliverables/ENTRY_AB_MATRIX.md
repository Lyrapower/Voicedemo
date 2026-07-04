# Entry A / Entry B 配置对照表

| 维度 | Entry A | Entry B |
|------|---------|---------|
| **HTTP 端口** | 8500 | 8787 |
| **进程** | `incoming/echo_nodes/echo_nodes_fastapi.py` | `repo/app/main.py` |
| **启动** | `incoming/echo_nodes/start.sh` | `scripts/restart_entry_b_8787.sh` |
| **LM Studio 对话** | `17797865158101` · Echo Nodes Interface | `17797865158102` · Compile Layer（Entry B — 14B） |
| **LM 模型** | `qwen3-14b-mlx` | `qwen3-14b-mlx`（同一权重，**两个对话**） |
| **系统提示源** | `prompts/echo_nodes_system.txt`（build 自 TOML+JSON+protocol） | `prompts/qwen35b_native.txt` |
| **运行配置** | `incoming/echo_nodes/config.json` | `config/entry_b_8787.json` |
| **Solid 包** | `deliverables/entry_a_8500.solids.json` | `deliverables/entry_b_8787.solids.json` |
| **专属协议** | `interface.echo-nodes.json`, `Config.toml`, `entry_a/01–06` | `carriers`（aster/守恒/澈/澄/朔）, `ASTER.md` |
| **SynCon** | `POST /api/route`（仅 8500） | 无（编译在 8787） |
| **MEMORY compile** | 无（`compile_router.py` 存在但**未挂载**） | `POST/GET /api/memory/*` → `garden_services.py` |
| **粒子 UI** | 无 | `sound_lab_fallback.py`（5173 / 8787 代理） |
| **禁止串线** | 不得挂 compile、不得代理到 8787 做 compile | 不得代理 MEMORY 到 8500 |

## 共享（仅锚点，不共享提示/工作区）

- `config/lyra_syncon_shared.json` — LYRA + SynCon Lab
- `frequency_continuity_package/ARCHITECTURE_LOCK.json`
- `config/grid.yaml`

## 验收

```bash
chmod +x echo_nodes_interface/setup/verify_entry_ab.sh
./echo_nodes_interface/setup/verify_entry_ab.sh
```
