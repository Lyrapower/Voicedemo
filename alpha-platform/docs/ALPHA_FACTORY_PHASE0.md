# Alpha Factory GRID · Phase 0 inventory · 2026-07-27 (V1.3)

## Phase 0 钉死产物（文件）

| 产物 | 路径 | 说明 |
|------|------|------|
| **df schema 白名单** | [`schemas/factory_df_contract.json`](../schemas/factory_df_contract.json) | `column_whitelist` = fix_error 灰区依据; 含 index/时区/universe/模板注释 |
| **沙箱规格** | [`schemas/factory_sandbox_spec.json`](../schemas/factory_sandbox_spec.json) | AST + runtime builtins + 120s/1GB + 失败语义 |
| 索引 | [`schemas/README.md`](../schemas/README.md) | 两文件用途与加载点 |
| 沙箱降级 | [`SANDBOX_DEGRADATION.md`](SANDBOX_DEGRADATION.md) | macOS/Docker unshare/seccomp 不可得时的残余风险 |

**实现加载:**

- Schema → `backend/factory_schema.py`
- Sandbox → `backend/factor_sandbox.py`（规格以 JSON 为 SSOT; 代码须对齐）

## 部署副本

| 组件 | 路径/端口 | 状态 |
|------|-----------|------|
| alpha-platform API | `alpha-platform/backend` · **8600** | docker-compose |
| ALPHA 工坊 UI | `#/alpha` · React `Alpha.jsx` | Grid 因子工坊 |
| Grid gateway | **8501** | `POST /factory/task` (additive) |
| b11 Cloud | 8515 | 与工坊分离 |

## 数据资产(只读)

- **bars**: `platform.db` · Alpaca 1-min IEX
- **因子 v0 占位**: ret_5m / ret_30m / vol_1m / range_pos
- **jobs + /ws/stream**: 评审进度复用 Phase 0.5

## Grid `/factory/task`

- 记忆 node: `alpha-factory`
- 唯一工坊出口: `grid_factory_client.py` → 8501

## 审批队列

- 因子提案: `factor_proposals` · 卡型 `factor`
- #46467 policy 同屏: **待接**

## 工坊 grep 红线

- frontend + pipeline 不得出现 `glm-5.2` / `ollama` / `kimi` / `qwen`（工作树 grep）
