# GATE_FIX V1.2 · 三端总览与验收五问

> 日期 2026-07-27 · 落点 `~/Projects/demo`（launchd 实际副本）  
> V1.2 修订：**保留** wire 字段名 `artifact`（零改名）；用 `compile_semantics` 标记 strict / parse_only。

---

## 三端关系（简图）

```text
8501 Grid gateway
  ├─ STUDIO chat → field-particle
  ├─ C 模式 compile_json → field-compile · compile_semantics: parse_only · UI「draft」
  ├─ POST /compile（九字段）→ compile_semantics: strict（文档；不经手 store 写入）
  └─ /store/* · health.store_auth · distill/coach 闸

8515 b11 workbench
  └─ Cloud 旁路 tab → /cloud/chat · **无** compile_semantics · **无** store · 旁路角标

8790 FIELD
  ├─ compile_json → chat 路径 · artifact 字段保留 · parse_only + draft 标
  ├─ diaryAuthFetch（原 signedFetch 已改名）
  └─ coach tab · latest_compile 透传 semantics · parse_only 显示 draft
```

---

## compile_semantics 消费规则（Phase 2 核心）

| 路径 | 自动 coach/distill | 手动 force |
|------|-------------------|------------|
| `strict` | ✅ 可进（task 匹配时） | ✅ |
| `parse_only` | ❌ 拒绝 | ❌ 除非 `allow_draft: true` |
| 历史无字段 | 按原行为（compile task 可进，schema:loose 仍挡） | force 仍受 parse_only 规则约束 |
| `test: true` 或 content `[test] ` 前缀 | ❌ 一律跳过 | ❌ |

---

## A2 · 测试写入标记（本单选用）

**store `messages` 表无 metadata 列** → 验收写入采用 **双轨**：

1. **distill JSONL 记录**：字段 `test: true`（自由 JSON 键，不改表结构）
2. **store 消息 content**：统一前缀 `[test] `（doctor / content 检测可过滤）

回执须逐条列出 message id / record_id。

---

## b11 Cloud 旁路（Phase 3 标注）

**Cloud 旁路 tab**（8515 `/cloud/chat`）直连 Ollama cloud，**不经** 8501 gateway / contract_gate / grid_store / 双向禁词表。**此面无门。** 交易相关词汇与指令勿经此面。

（原 GLM 独立 tab 已合并为 Cloud + lane 切换。）

---

## 验收五问（每条改动必答）

1. 落在 **8501 / 8515 / 8790** 哪一面？
2. 写的是 **field-particle / field-compile / workbench-b11** 哪个 store？（本单禁止 workbench-b11 验收写）
3. compile 验的是 **/compile 九字段** 还是 **chat parse**？产物标了哪种 **compile_semantics**？
4. **页面第一屏 / store 读回** 是否与预期一致？（不接受 health 字符串代答）
5. 该路径失配时 **fail-open 还是 fail-closed**？现在是否 **可见**（`store_auth` 横幅 / health）？

---

## Phase 4 · Epoch

Phase 0 实测：anchor `2026-07-16`，7 天滚动窗；2026-07-27 落在 epoch_idx=1（2026-07-23 ~ 2026-07-29）。**正常，本 Phase 关闭。**

---

## 相关脚本

- `scripts/verify_grid_store_auth.sh` — store 鉴权探针
- `scripts/verify_field_truncation_fix.sh` — 8790 artifact wire（**未改名**，V1.2 仍读 `done.artifact`）
