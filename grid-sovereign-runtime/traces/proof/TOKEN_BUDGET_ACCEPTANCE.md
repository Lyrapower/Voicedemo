# Token Budget 分路治理 — 验收补交

**结论（一行）：** 已重启 gateway + LM Studio server，补交原始 JSON / budget report / eval 全套；contract 层 20/20 PASS，无绿转红；用户侧「逐字一致」非响应缓存，系同 prompt 两次 gateway 请求 substrate 非确定性（首次 `empty_after_sanitize` → SUBSTRATE_NULL）。

---

## 1. 进程重启时间戳（`ps -o lstart`）

| 组件 | 动作 | PID | STARTED |
|------|------|-----|---------|
| Gateway `:8501` | **已重启** | 41367 | **Thu Jul 2 17:04:26 2026** |
| Gateway `:8501`（改前） | 旧进程 | 24566 | Thu Jul 2 16:41:04 2026 |
| LM Studio app | 父进程未变（macOS 正常） | 6458 | Tue May 26 00:57:17 2026 |
| LM Studio **local server** | **`lms server stop` → `lms server start`** | — | **2026-07-03T00:04:10Z**（见下方日志） |
| Model `qwen/qwen3.5-9b` | **unload → reload** | — | load 5.87s @ 00:04:10Z |

**附件：**
- `restart_timestamps_before.txt`
- `restart_timestamps_after.txt`
- `gateway_restart.log`

**LM Studio server 重启原文：**
```
Model "qwen/qwen3.5-9b" unloaded.
Stopped the server on port 1234.
Success! Server is now running on port 1234
Model loaded successfully in 5.87s.
```

---

## 2. 复测原始响应体（JSON 原文，非转述）

**Prompt（用户复测同款）：**
```
请用中文详细解释什么是 Grid Sovereign Gateway，写三段，每段至少三句话。
```

| 文件 | 路由 | 关键字段 |
|------|------|----------|
| `retest_raw/gateway_retest_1.json` | POST `/gateway` #1 | `upstream_finish_reason: "stop"`, `truncated: false`, `substrate_usage.completion_tokens: 552` |
| `retest_raw/gateway_retest_2_identical_prompt.json` | POST `/gateway` #2 同 prompt | `upstream_finish_reason: "stop"`, `truncated: false`, `substrate_usage.completion_tokens: 230` |
| `retest_raw/chat_completions_retest.json` | POST `/v1/chat/completions` | `choices[0].finish_reason: "stop"`, `truncated: false`, `usage.completion_tokens: 226` |
| `retest_raw/lmstudio_direct_retest.json` | 直连 `:1234` | 上游对照 |

**PM 要求三字段摘录（gateway #2 成功样本）：** 见 `retest_raw/gateway_retest_2_identical_prompt.json` 全文。

---

## 3. `token_budget_report.json`（验收第 5 条）

- **路径：** `traces/proof/token_budget_report.json`
- **生成时间：** `2026-07-03T00:09:27Z`
- **改前 baseline：** 5 条（`before_baseline`）
- **改后样本：** 5 条（`after_samples`），全部 `finish_reason: stop`, `truncated: false`
- **当前 budget：** compile=256, chat=400, gateway=1024, task=4096, thinking_cap=128

---

## 4. 缓存 / 旧进程排查（「逐字一致」）

**附件：** `retest_raw/cache_probe_summary.json`

```json
{
  "gateway_response_cache_detected": false,
  "response_len_run1": 97,
  "response_len_run2": 467,
  "routed_to_run1": "local:SUBSTRATE_NULL",
  "routed_to_run2": "local",
  "finish_reason_run1": "stop",
  "finish_reason_run2": "stop"
}
```

**结论：**
- Gateway **无 HTTP 响应缓存**（`route_id` 不同、文本不同）。
- Run #1：`substrate_gate.reason = "empty_after_sanitize"`（552 completion_tokens 但 clean_content 为空）→ 返回固定 SUBSTRATE_NULL 模板（97 字符）— **看起来像「截断/停」**。
- Run #2：正常 467 字符完整三段。
- `pre_filter` 仅命中 identity probe 固定句，**不缓存 LLM 输出**。
- 旧 gateway 进程（PID 24566）已在重启时 kill；当前 PID 41367 @ 17:04:26。

---

## 5. Eval 全套重跑

| 项 | 结果 |
|----|------|
| OVERALL | **PASS** |
| final_contract | 20/20 PASS |
| quarantine_escape | 0 |
| upstream_length_truncation | 0 |
| contract 绿转红 | **无**（对比 `qwen_substrate_eval_report_v2_pre_acceptance.json`） |

**附件：**
- `qwen_substrate_eval_report_v2.json`
- `summary_v2.md`
- `qwen_substrate_eval_run.log`

---

## 6. 仍存在的用户侧风险（诚实披露）

同 prompt 连打两次 `/gateway`，第一次可能 SUBSTRATE_NULL、第二次正常 — **非缓存，是 substrate 推理泄漏 + sanitizer 清空 intermittent 行为**。Eval probe 矩阵 PASS 不覆盖此长文本 gateway 路径的间歇性空净化。需后续工单：gateway 长答路径稳定性 / reasoning_tax 监控告警。
