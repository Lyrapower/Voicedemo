# GATE_FIX V1.2 · Phase 1–3 回执

> 日期 2026-07-27 · 落点 `~/Projects/demo`  
> 依据 PM 进场指令 · V1.2 修订（**零改名** `artifact`）

---

## Phase 1 · store_auth 可见 ✅

| 端 | 验收 | 结果 |
|----|------|------|
| 8501 `GET /health` | `store_auth` 字段 | `"off"`（无 token 文件，fail-open） |
| 8501 启动横幅 | `[WARN] STORE AUTH: OFF — LAN open trust` | kickstart 后 gateway 已加载 |
| 8790 `GET /health` | `store_auth` 字段 | `"off"` |
| 8790 启动 | 同格式 WARN | startup hook 已调用 |

`scripts/verify_grid_store_auth.sh` → PASS

---

## Phase 2 · compile_semantics + 消费闸 ✅

### 撤销改名

- wire / UI / verify **仍用** `artifact` — **零改动**（V1.2 相对 V1.1 的 reversal）
- `verify_field_truncation_fix.sh` → **PASS**（`done.artifact` 仍有效，且响应新增 `compile_semantics: parse_only`）

### 标记

- Grid C 模式 `afterTurn` → `compile_semantics: "parse_only"` + `schema: "schema:loose"`
- 8790 `_done_payload` / `json_artifact` → `compile_semantics: "parse_only"`
- 8501 `/store/field/after_turn` 缺省 compile 任务 → 自动补 `parse_only`
- `/compile` 九字段路由：**未改 handler**（红线 3）；strict 语义见 `GATE_FIX_V1.2_OVERVIEW.md`

### 消费闸

| 规则 | 实现 |
|------|------|
| 自动 coach | 仅 `strict` 或无字段 legacy；`parse_only` / `test` 拒绝 |
| 手动 force + parse_only | 无 `allow_draft` → `reject` 事件 + `reason: parse_only_requires_allow_draft` |
| `latest_compile_pair` | 返回 `semantics` 字段；跳过 `test: true` 记录 |
| 8790 coach panel | `parse_only` 行显示 `draft` |

### 前端标

- Grid `grid.html` compile 卡片 tele 行 → `draft`
- 8790 `chat_panel.ts` meta + artifact 区 → `draft`（**需 `npm run build`** 进 dist）

### A2 · test 标记选用

**无 store messages metadata 列** → 双轨：

1. **distill JSONL**：`test: true` 键（本验收用）
2. **store content**：前缀 `[test] `（Grid `afterTurn({test:true})` 已支持 body.test；content 前缀供 doctor 扫）

---

## Phase 3 · 文档与命名 ✅

- `signedFetch` 导出已移除（repo grep 仅剩历史文档提及）
- `diaryAuthFetch.ts` 保留
- b11 Cloud 旁路说明 → `GATE_FIX_V1.2_OVERVIEW.md`
- 五问总览 → 同文件

---

## Phase 4 · 关闭

epoch 滚动窗 Phase 0 已验正常，**无代码改动**。

---

## 专项验收

### 阴性：force 无 allow_draft

```bash
curl -sf -X POST http://127.0.0.1:8501/store/field/coach \
  -d '{"sync":true,"compile_semantics":"parse_only","allow_draft":false,"draft":"'$(python3 -c 'print("x"*50)')'"}'
# → {"ok":false,"skipped":true,"reason":"parse_only_requires_allow_draft"}
```

### 自动路径 strict vs parse_only（unit + 标记记录）

```
auto_strict_notest  → True
auto_parse_notest   → False
test 标记           → 两者 auto 均 False
```

### test:true 写入 id（distill JSONL · 验收用）

| record_id (prefix) | compile_semantics | test |
|--------------------|-------------------|------|
| `765622a7…` | strict | true |
| `b5dbedb2…` | parse_only | true |

（生产 distill 消费已过滤 `test: true`；记录可保留或用户自删 JSONL 行。）

---

## 五问（本单摘要）

1. **面**：8501 gateway/store/distill + 8790 field + 8515 仅文档标注  
2. **store**：field-compile / field-particle 逻辑路径；**无 workbench-b11 写入**  
3. **compile**：C/8790 = chat parse · `parse_only`；/compile strict 未动 handler  
4. **页面**：Grid tele `draft` 已改 HTML；8790 draft 标待 frontend build 后可见  
5. **fail-open**：store 仍 fail-open；**现可见** `store_auth: off` + WARN 横幅  

---

## 待用户一步

```bash
cd ~/Projects/demo/aster-field/frontend && npm run build
```

8790 静态 dist 更新后，关 tab 重开 FIELD 亲测 compile 卡片 `draft` 与 coach panel。

---

## 改动文件（Projects/demo）

- `grid-sovereign-runtime/field_lane/schema.py` · `distill.py` · `distill_record.py` · `distill_api.py`
- `grid-sovereign-runtime/field_lane/test_gate_fix_v12.py` · `test_distill_schema.py`
- `grid-sovereign-runtime/gateway/grid_store.py` · `local_gateway.py`
- `grid-sovereign-runtime/gateway/static/grid.html`
- `aster-field/backend/json_artifact.py` · `app.py`
- `aster-field/frontend/src/net/chat.ts` · `distill.ts` · `ui/chat_panel.ts` · `ui/coach_panel.ts` · `gateway/diaryAuthFetch.ts`
- `aether_nexus/docs/GATE_FIX_V1.2_OVERVIEW.md` · 本回执
