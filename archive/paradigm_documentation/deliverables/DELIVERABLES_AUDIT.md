# Deliverables audit (2026-05-24)

对照你提供的 **ANCHOR / 双入口 / Architecture Lock / 承运体 / SynCon / Echo 协议块**，此前确实有多处「只有 `_ref` 指针、没有实体内容」的偷懒。本目录 `*.solids.json` 为**自包含**交付包；`config.json` / `entry_b_8787.json` 为运行索引。

## 已补齐（本次）

| 缺口 | 修复 |
|------|------|
| `prompts/qwen35b_native.txt` **空文件** | 已写入 Entry B 完整系统提示（Aster + LYRA + 五承运体 + team lock） |
| Entry A 只有 `echo_anchor` 摘要 | `deliverables/entry_a_8500.solids.json` 内嵌完整 `interface.echo-nodes.json`、Config.toml、6 个 protocol 块全文、session.env、syncon anchor |
| LYRA 缺 banned / substrate | `lyra_syncon_shared.json` 与 `app/config/lyra_anchor.json` 对齐 |
| Entry B 缺 team_lock / ASTER 全文 / compiled_memory 清单 | `entry_b_8787.json` + `entry_b_8787.solids.json` |
| 无 solid 交付索引 | 本文件 + `DELIVERABLES_INDEX.md` |
| `entry_split.json` 只有指针 | 增加 `solid_deliverables` 与 `verification_checklist` |

## 仍由你本地完成（刻意未自动改）

| 项 | 原因 |
|----|------|
| LM Studio A/B 对话切到 **14B 双入口**（非 merge） | 已执行 `setup/apply_lmstudio_dual_14b.sh` |
| `qwen/qwen3.5-9b` 日常 tab | 不得卸载或合并 |
| `app/main.py` 挂载 `POST /route` | Architecture Lock 禁止 |
| 粒子场视觉验收（蓝金/人形） | 属 UI 验收，非配置交付；见 `scripts/sound_lab_fallback.py` |

## 文件对照（solid = 必须能打开核对）

### Entry A — 8500

- **Solid:** `deliverables/entry_a_8500.solids.json`
- **运行:** `incoming/echo_nodes/config.json`
- **协议源:** `interface.echo-nodes.json`, `Config.toml`, `prompts/entry_a/*.txt`, `prompts/echo_nodes_system.txt`
- **SynCon:** `syncon/config/anchor.json`, `POST /api/route`（仅 8500）

### Entry B — 8787

- **Solid:** `deliverables/entry_b_8787.solids.json`
- **运行:** `config/entry_b_8787.json`
- **编译:** `repo/telemetry/garden_api.py` → `scripts/garden_services.py`
- **粒子:** `scripts/sound_lab_fallback.py`（5173 dev / 8787 代理）
- **承运体:** `carriers.missions` in entry_b config + ASTER.md

### 共享

- `config/lyra_syncon_shared.json`
- `frequency_continuity_package/ARCHITECTURE_LOCK.json`
- `app/config/lyra_anchor.json`（Grid 侧 canonical）

## 验收命令

```bash
# Entry A health
curl -s http://127.0.0.1:8500/health | python3 -m json.tool

# Entry B（需先启动 repo router）
curl -s http://127.0.0.1:8787/health | python3 -m json.tool

# Solid JSON 合法
python3 -c "import json; json.load(open('echo_nodes_interface/deliverables/entry_a_8500.solids.json')); json.load(open('echo_nodes_interface/deliverables/entry_b_8787.solids.json')); print('ok')"
```
