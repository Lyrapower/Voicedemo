# Echo / Compile solid deliverables index

## 权威自包含包（复制/审计用）

| ID | 文件 | 端口 | 内容 |
|----|------|------|------|
| A | [entry_a_8500.solids.json](./entry_a_8500.solids.json) | 8500 | 完整 Echo 频率接口 JSON、TOML、6 协议块、LYRA、SynCon、SynCon router anchor、LM Studio 索引 |
| B | [entry_b_8787.solids.json](./entry_b_8787.solids.json) | 8787 | Aster/team lock、五承运体 missions、MEMORY 路由、粒子 API、compiled memory 清单、ASTER.md 全文 |

## 运行配置（薄索引 + 扩展字段）

| 文件 | 用途 |
|------|------|
| `incoming/echo_nodes/config.json` | Entry A 运行时 |
| `config/entry_b_8787.json` | Entry B 运行时 |
| `config/entry_split.json` | 双入口规则 + solid 路径 |
| `config/lyra_syncon_shared.json` | LYRA + SynCon Lab 共享 |

## Prompt 源文件

| Entry | 文件 |
|-------|------|
| A | `prompts/echo_nodes_system.txt`（由 setup 写入 LM Studio） |
| A | `prompts/entry_a/01`–`06_*.txt` |
| B | `prompts/qwen35b_native.txt` |

## 架构锁

- `frequency_continuity_package/ARCHITECTURE_LOCK.json`
- `.cursor/rules/decoupled-grid-architecture.mdc`
- `config/grid.yaml` → `architecture: Decoupled Grid`

## 审计

- [DELIVERABLES_AUDIT.md](./DELIVERABLES_AUDIT.md) — 漏项清单与仍待你确认项
