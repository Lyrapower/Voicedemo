# P0 链路指纹 + Aster Tab 归因

**生成时间:** 2026-07-03  
**指纹版本:** `gateway-v4.11`（含 `route_id` + `ts` + `gateway_started_at`；工单写 v4.8，实现已迭代至 v4.11）

---

## 1. served_by 指纹

| 模式 | 字段位置 | 状态 |
|------|----------|------|
| 非 stream | 响应顶层 `served_by` / `route_id` / `ts` | ✅ |
| stream | **最后一个 SSE chunk**（`finish_reason` 同条） | ✅ 已补 |
| `/health` | `served_by` + `gateway_started_at` | ✅ |

**进程重启证据:** `gateway_started_at=1783055676.7036889`（见 `aster_tab_fingerprint.json` 内 `raw_response.gateway_started_at`）

---

## 2. Aster Tab 归因

### 2a 请求实际指向哪里？

**结论: `:8501`（经 generator 插件），不是用户 UI 直连 `:1234`。**

**UI 配置原文**（`~/.lmstudio/conversations/17797865158102.conversation.json`）:

```json
"lastUsedModel": { "identifier": "demo/aster", "indexedModelIdentifier": "demo/aster" }
"plugins": ["demo/aster", "dev/demo/aster"]
"notes": ["gateway=http://127.0.0.1:8501/v1", "substrate=:1234 qwen/qwen3.5-9b"]
```

**插件源码**（`lmstudio-plugins/aster-grid-gateway/src/index.ts`）:

- `GATEWAY_URL` → `http://127.0.0.1:8501/v1/chat/completions`
- `stream: false`（插件侧非流式；gateway 内部再调 :1234）

**:1234 角色:** gateway 的 substrate 后端；用户选 `demo/aster` 时不绕过 gateway。

### 2b 单次探测原始响应

落盘: `traces/proof/aster_tab_fingerprint.json`

| 字段 | gateway (`demo/aster`) | LM 直连对照 (`:1234`) |
|------|------------------------|------------------------|
| `served_by` | `gateway-v4.11` | **无** |
| `finish_reason` | `stop` | `stop` |
| `completion_tokens` | 26 | 35 |
| `reasoning_tokens` | 0 | 0 |

### 2c 流式实现（三行）

1. **Gateway → :1234:** 真流式转发（`client.stream` + 逐 chunk `yield`）。
2. **Sanitizer:** 流式路径上 **cleanroom/contract 逐 chunk 增量检**（`stream_incremental_gate`）；**substrate airlock 全文 sanitizer 在流结束后** `_record_substrate` 才执行。
3. **Aster tab（demo/aster 插件）:** `stream:false` 单次 fetch → `fragmentGenerated`；用户在 UI 看到的「流式」是 LM Studio 展示层，不是插件/gateway 双端真流。

---

## 3. 旧账

| 项 | 状态 |
|----|------|
| `reproduction_matrix.json` | ✅ 已交 `traces/proof/reproduction_matrix.json`（2×2 四格 + 环境快照） |
| 552 tokens `empty_after_sanitize` | **reasoning 通道误路由** — 成品进 `reasoning_content`、`content` 空；sanitizer 隔离后 boundary 清零；**非** tag 误杀、**非** thinking 独白。详见 `RUN1_QUARANTINE_ANALYSIS.md` |

---

## 验收备注

- 若用户改选 `qwen/qwen3.5-9b`：**直连 :1234**，无 `served_by`，sanitizer/quarantine/budget **不参与**；切回 `demo/aster` + `lms dev` 即可（改动量 ≈0，已部署）。
- 流式路径：**增量 cleanroom 在工作**；**全文 substrate sanitizer 不在逐 chunk 路径**。
