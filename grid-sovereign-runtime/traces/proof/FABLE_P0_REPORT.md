# Fable P0 终局验收报告

**生成时间**: 2026-07-03T00:57Z  
**验收方**: Composer（按 Fable 工单执行，证据落盘供 Fable 复核）

---

## 1. reproduction_matrix.json — 4 格齐全

路径: `traces/proof/reproduction_matrix.json`  
原始响应体: `traces/proof/reproduction_matrix/{gw_new,gw_old,lm_new,lm_old}.json` + `.txt`

| 格 | 入口 | 会话 | served_by | 响应长度 | finish_reason | 指纹 |
|----|------|------|-----------|----------|---------------|------|
| gw_new | :8501 gateway | 新 | gateway-v4.11 | 42 | stop | 有 |
| gw_old | :8501 gateway | 旧上下文 | gateway-v4.11 | 22 | stop | 有 |
| lm_new | :1234 LM Studio 直连 | 新 | **null** | 192 | stop | **无** |
| lm_old | :1234 LM Studio 直连 | 旧上下文 | **null** | 19 | stop | **无** |

**矩阵结论**: 用户实际入口为 LM Studio `:1234`；响应体无 `served_by` 字段，流量不经 `:8501` gateway。前三轮 gateway 修复未触及用户链路。

`lm_old` 格: `completion_tokens=319`，其中 `reasoning_tokens=302`，可见 `content` 仅 19 字符 —— 病灶在 LM Studio 直连层的 reasoning 税，非 gateway 缓存。

---

## 2. 链路指纹证据

- Gateway 响应含 `served_by: "gateway-v4.11"` — 见 `traces/proof/link_fingerprint_gateway.json`
- LM Studio 直连响应无 `served_by` — 见矩阵 `lm_new.json` / `lm_old.json` 顶层键列表（无 served_by）

```json
{"served_by": "gateway-v4.11", "route_id": "...", "ts": 1783040187.248884}
```

---

## 3. 温度运行时实际值（非 toml 应然值）

来源: `~/.lmstudio/conversations/17797865158102.conversation.json`（Aster tab 运行时配置）

| 参数 | 运行时值 |
|------|----------|
| temperature | **0.3** |
| top_p | 0.9 |
| max_predicted_tokens | 400 |
| enable_thinking | false |
| message_count | 26 |
| token_count | 2259 |

受控矩阵发送 temperature=0.7（工单要求 ≥0.7）；用户 UI 实际为 0.3，重复率更高。

同 prompt 在会话内出现 **7 次**（conversation JSON 行 553–2182），多次回答逐字高度相似并在「踮」处截断。

---

## 4. REPETITION_FLAG 探针

**代码位置**:
- `grid-sovereign-runtime/gateway/substrate_telemetry.py` — `check_repetition_pair()`, `text_diff_rate()`, `repetition_flag_count`
- `grid-sovereign-runtime/scripts/qwen_substrate_eval.py` — `run_repetition_probe()` 接入 `substrate_health`
- `grid-sovereign-runtime/scripts/reproduction_matrix.py` — 矩阵 twin-fire

**四个并列计数器**（`substrate_health` + `substrate_telemetry.snapshot()`）:
- `reasoning_leak_rate`
- `truncation_rate`
- `empty_after_sanitize_rate`
- `repetition_flag_count` / `repetition_flag_rate`

**触发样例 1** — 用户 LM Studio 历史相邻两次回答（截断副本）:

`traces/proof/repetition_flag_trigger_example.json`

```
similarity=0.9655 → REPETITION_FLAG=true
route=lmstudio_user_history
```

**触发样例 2** — eval 双发 gateway 同 prompt（2026-07-03 run）:

```
REPETITION_FLAG route=gateway similarity=1.000
```

见 `traces/proof/qwen_substrate_eval_report_v2.json` → `substrate_health.repetition_probe`

---

## 5. 根因陈述（≤3 行）

用户聊天走 LM Studio Aster 标签页 → `:1234` 直连，不经 `:8501` gateway；响应无 `served_by` 即证明此事实。  
Qwen 3.5 9B 在 LM Studio 将 completion 预算消耗于 `reasoning_content`（lm_old: 302 reasoning / 17 content），可见回答被截断或逐字重复。  
用户在 26 条消息的同一窗口内 7 次发送同一 prompt（temperature 0.3），相邻回答相似度 96.5%，触发 REPETITION_FLAG；非 HTTP 缓存。

---

## 6. 流程变更确认

自本工单起：**「已解决」须附用户实际链路上的复现/反证证据**（本报告 + `reproduction_matrix.json`），在用户开口之前交付。

用户角色：收报告。不是 QA。
