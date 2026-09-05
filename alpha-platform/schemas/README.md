# Alpha Factory · Phase 0 钉死产物

> V1.3 · 2026-07-27 · schema 变更或沙箱规格变更须独立施工单

## 1. df 输入 schema 白名单（fix_error 灰区判定依据）

**文件:** [`factory_df_contract.json`](factory_df_contract.json)

| 字段 | 用途 |
|------|------|
| `column_whitelist` | fix_error 契约内/外列二分 |
| `columns` | 列 dtype / 含义 |
| `index` / `timezone` / `missing_values` / `universe` | worker → factor(df) 契约 |
| `template_comment` | 注入 Grid propose prompt 与因子代码模板注释 |

**加载:** `backend/factory_schema.py` → `load_contract()` / `column_whitelist()`

## 2. 沙箱规格（L0 评审执行）

**文件:** [`factory_sandbox_spec.json`](factory_sandbox_spec.json)

| 字段 | 用途 |
|------|------|
| `static_ast_scan` | AST 静态拒止规则 |
| `runtime_globals` | 受限 `__builtins__` 白名单 |
| `subprocess` | 120s CPU / 1GB 内存 |
| `filesystem` / `network_isolation` | tempdir + 网络隔离目标/降级 |
| `failure_semantics` | sandbox/resource/pipeline → failed; factor_code → 可 fix_error |

**实现:** `backend/factor_sandbox.py`  
**降级:** [`../docs/SANDBOX_DEGRADATION.md`](../docs/SANDBOX_DEGRADATION.md)

## Docker 副本

`backend/schemas/` 下为 build 镜像内同内容副本（与本文目录同步）。
