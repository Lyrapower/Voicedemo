# GRID Workbench b11 — 交接文件

**日期:** 2026-07-28  
**PAGE_VER:** `3.23.2-b11-cloud8501-lock`  
**状态:** Cloud tab 已改回 **8501 only**（store + chat）；STUDIO 仍走 8515→8501 验签代理。**用户未浏览器实机终验 Cloud 记忆 recall。**

---

## 1. 产品是什么

| 项 | 说明 |
|----|------|
| **b11** | GRID Workbench UI — **8515 只发 HTML/JS** |
| **源稿（用户指定）** | `~/Library/Mobile Documents/com~apple~CloudDocs/Downloads/grid workbench b11.html` |
| **仓库部署** | `grid-sovereign-runtime/workbench/static/grid_workbench_b11.html` |
| **本机入口** | http://127.0.0.1:8515/ → `grid_workbench_b11.html` |
| **Tailscale 入口** | https://`<host>`.ts.net/workbench/grid_workbench_b11.html |

**不是 b11：** `grid_multimodal.html`、multimodal v3、8790 FIELD、8501 `grid.html`。

---

## 2. 端口分工（锁死 — agent 勿再搞混）

| 端口 | 角色 | b11 怎么用 |
|------|------|------------|
| **8515** | Workbench **静态 UI** · LaunchAgent `com.demo.workbench.ui8515` | 用户打开 b11 **页面** |
| **8501** | **全部 API** + store + Cloud | b11 JS **直连**（CORS 已放行 8515→8501） |
| **8790** | FIELD | **与 b11 无关** |

### STUDIO tab（HOME / EXPANDED）

- 聊天/EXPANDED：**8515 `/gateway/*` 服务端验签** → 转发 **8501**
- Store node：**`workbench-b11`**（≠ Cloud，≠ `field-particle`）

### Cloud tab（GLM / Kimi）

| 层 | 必须走 | 禁止走 |
|----|--------|--------|
| **记忆读** | `GET 8501/store/conversations/cloud-glm52` | ~~8515 `/cloud/memory`~~ · ~~8515 sqlite~~ |
| **记忆写** | `POST 8501/store/conversations/cloud-glm52/messages` | 同上 |
| **推理** | `POST 8501/task/cloud_chat`（多轮 messages） | ~~8515 `/cloud/chat`~~ · ~~8501 `/task/candidate` 单包 prompt~~ |
| **归档** | `POST 8501/store/field/after_turn` · `node_id=cloud-glm52` | — |

**8515 对 Cloud tab = 零 API。** 代码里有 `rejectCloud8515()`，误指 8515 会直接 throw。

---

## 3. Cloud 架构（2026-07-28 最终态）

```
用户浏览器 (8515 b11 页面)
    │
    ├─ Cloud 读/写 store ──► 8501 /store/conversations/cloud-glm52
    │
    └─ Cloud 发 GLM ──────► 8501 /task/cloud_chat
                              │
                              ├─ cloud_memory_scope.py（system: 允许回忆历史）
                              └─ Ollama Cloud glm-5.2:cloud
```

| UI | 值 |
|----|-----|
| 活跃窗（界面） | 15 轮 |
| 请求注入 | store 全量 → `buildCloudStoreMessages()` → multi-turn（最多 80 条，单条 cap 4000 字） |
| Store node GLM | **`cloud-glm52`** |
| Store node Kimi | **`cloud-kimi`** |
| DeepSeek | 无 8501 store · 仅 localStorage |

### 为何不用 `/task/candidate`

旧路径 `build_task_scoped_messages` 的 system prompt 含：

- `Do not claim private memory`
- `Answer only the scoped task below`

GLM **会故意忽略**塞在 prompt 里的「记忆块」。用户看到「什么都不记得」是 **prompt 设计问题**，不是 store 没数据。

### 为何不用 8515 `/cloud/memory`

2026-07-28 前 agent 曾错接 8515 `cloud_memory.db` + 写验收垃圾 `u0/a0`…  
用户要求：**记忆只在 8501 `cloud-glm52`**。8515 路径已废弃给 b11（`workbench_app.py` 仍留着路由，**b11 不得调用**）。

---

## 4. 关键代码位置

| 文件 | 作用 |
|------|------|
| `workbench/static/grid_workbench_b11.html` | Cloud UI · `cloud8501Base()` · `fetchCloudStoreAll` · `cloudChat` |
| `gateway/local_gateway.py` | **`POST /task/cloud_chat`**（2026-07-28 新增） |
| `code_task/cloud_memory_scope.py` | Cloud 专用 system prompt + multi-turn sanitize |
| `code_task/cloud_chat_executor.py` | Ollama Cloud 多轮执行 |
| `workbench/cloud_store.py` | 8515 sqlite — **b11 Cloud 不用** |
| `workbench/gateway_verify_proxy.py` | STUDIO 8515→8501 验签 — **Cloud 不用** |
| `gateway/grid_store.py` | 8501 store · `cloud-glm52` 节点 |

### b11 必查函数

- `cloud8501Base()` / `rejectCloud8515()` — Cloud 硬锁
- `fetchCloudStoreAll()` — 读 store
- `pushCloudStoreMsgs()` — 写 store
- `buildCloudStoreMessages()` — 组装 multi-turn
- `cloudChatUrl()` → `/task/cloud_chat`

---

## 5. RED LINE（agent 违反 = 用户爆发）

### workbench-b11

见 `.cursor/rules/workbench-b11-store-redline.mdc` — **禁止 DELETE/purge/验收写入 `workbench-b11`**

### cloud-glm52 / cloud-kimi

见 `.cursor/rules/cloud-memory-agent-redline.mdc` — **禁止 agent 写 uN/aN 验收循环到生产 node**

### Cloud 架构

1. **禁止**把 Cloud 记忆迁到 8515 `/cloud/memory` 或 sqlite
2. **禁止**Cloud 推理走 8515 `/cloud/chat`（用户明确不要 8515 代理层）
3. **禁止**用 `/task/candidate` 单 prompt 冒充 Cloud 多轮记忆
4. **禁止**动 `workbench-b11` 冒充 Cloud 历史
5. **禁止**未验收宣称「Cloud 记忆好了」

### 8501 gateway

- `/task/cloud_chat` 是 **新增** 路由；改 `local_gateway.py` 后需 **gateway 进程重启**（Python 不热加载）
- 若 `grid_infrastructure_guard` 报 hash drift：`GRID_INFRASTRUCTURE_UNLOCK=1 python3 scripts/grid_infrastructure_guard.py update-lock`
- STUDIO 推理链 frozen — 勿动 `/v1/chat/completions` handler 本体

---

## 6. 验收（agent 自跑 — 用户不是 QA）

```bash
bash scripts/verify_b11_workbench.sh
```

最低手动检查：

```bash
# store 有数据（只读）
curl -sf 'http://127.0.0.1:8501/store/conversations/cloud-glm52?limit=5' | python3 -m json.tool | head

# cloud_chat 多轮记忆（勿写垃圾到生产 — 用短测试后可由用户删）
curl -sf -X POST http://127.0.0.1:8501/task/cloud_chat \
  -H 'Content-Type: application/json' \
  -d '{"substrate":"glm52","messages":[{"role":"user","content":"ping"}],"max_tokens":8}'

# b11 页面版本
curl -sf http://127.0.0.1:8515/grid_workbench_b11.html | rg 'PAGE_VER="3.23.2'
```

浏览器：**关 tab 重开 b11**，DevTools Network 发 Cloud 消息时确认：

- ✅ `8501/store/conversations/cloud-glm52`
- ✅ `8501/task/cloud_chat`
- ❌ 任何 `:8515/cloud` 或 `:8515/cloud/memory`

---

## 7. 启动

```bash
launchctl kickstart -k "gui/$(id -u)/com.demo.workbench.ui8515"
launchctl kickstart -k "gui/$(id -u)/com.demo.grid.gateway8501"
```

Tailscale b11：`tailscale serve --set-path=/workbench http://127.0.0.1:8515`（见 `RUN_WORKBENCH.md`）

---

## 8. grid.html（8501 app — 与 b11 Cloud 无关）

2026-07-28：`grid.html` demo/aster 改走 **8515 `/gateway/v1/chat/completions` 服务端验签**（无需浏览器 GridKeyholder）。  
入口：`8501/app/grid.html` 或 ts.net `/app/grid.html` · `PAGE_VER=2026-07-28-grid-8515verify`

---

## 9. 本窗口 agent 事故清单（勿再犯）

| 事故 | 后果 |
|------|------|
| Cloud 记忆接到 8515 `cloud_memory.db` | 与 8501 真数据分裂 |
| 验收循环 POST `u0/a0`… 到生产 lane | 用户 Cloud 页污染 |
| `/task/candidate` +「记忆块」prompt | GLM system 拒绝记忆 → 「什么都不记得」 |
| 只说「hover 注入 N 条」不验证 recall | 用户认为在撒谎 |
| 让用户配 GridKeyholder | 用户暴怒 — grid 已改服务端验签 |
| kickstart gateway 后不说明 / 反复要求用户重启 | 用户暴怒 |

---

## 10. 未闭环（下一 agent）

1. **用户浏览器实机** — Cloud 问「你还记得侯 / Jarvis / …」是否基于 store 真实 recall
2. **超长历史** — 80 条 cap 可能仍丢早期轮；自动 `cloud_trim_dropped` 会再裁最旧 user/assistant 对
3. **8515 `cloud_store.py`** — 死代码对 b11 仍 exist；可文档化 deprecated，**勿删除非用户要求**
4. **gateway 是否已 reload** — 若 `/task/cloud_chat` 404 → 一次 `kickstart gateway8501`

### GLM `empty after thinking strip` — 永久策略（8501 服务端，非 b11 一次性）

`code_task/cloud_chat_executor.py` · **`cloud_attempt_plan()`**

| 条件 | 行为 |
|------|------|
| 记忆 ≥3 轮 **或** 正文 ≥4000 字 | **只用 `no_think`**（不开 think，避免 token 全进 thinking） |
| 短对话 | `think` → 空则 `no_think_fallback` |
| 仍空 | 自动裁最旧 2/4/6 条 user/assistant 再 `no_think`（最多 4 档） |
| 仍失败 | 502 + 明确 reason；**store 不丢** |

验收：`python3 -m unittest tests/test_cloud_chat_executor.py`

---

## 11. 相关规则 / 文档

- `grid-sovereign-runtime/RUN_WORKBENCH.md`
- `.cursor/rules/b11-workbench-incidents-2026-07-22.mdc`
- `.cursor/rules/cloud-memory-agent-redline.mdc`
- `.cursor/rules/workbench-b11-store-redline.mdc`
- `.cursor/rules/verification-before-complete.mdc`

---

*2026-07-28 交接 — Cloud 只存 8515 UI · 只读写 8501 cloud-glm52 · 只推理 8501 /task/cloud_chat。*
