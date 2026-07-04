# Run #1 尸检 — route `c5177fd5-6667-4ffe-b7dd-ce1a1f441501`

**结论（一行）：** 成分归类 **§2 reasoning 通道误路由**（成品正文进了 `reasoning_content`，`content` 为空）；**非** thinking 独白、**非** `` tag 包裹、**非** sanitizer 误杀 `content` 正常正文。

---

## 1. 隔离区尸体（552 completion_tokens 对应原文）

**文件：** `retest_raw/run1_quarantine_corpse.json`（副本）  
**原件：** `traces/quarantine/c5177fd5-6667-4ffe-b7dd-ce1a1f441501_reasoning.json`

```json
{
  "reasoning_content": "Grid Sovereign Gateway（网格主权网关）是构建在区块链网络之上的一种关键基础设施，它主要服务于跨链通信和数据交换的需求。这个概念通常与"主权"相关，意味着它由特定的实体（如国家、联盟或大型机构）完全控制和管理，从而确保其内部数据流和治理规则不受外部干扰。在区块链生态中，它充当了一个受信任的中间人，负责验证和路由来自不同区块链网络的交易请求。\n \nGrid Sovereign Gateway 的核心功能在于实现异构区块链网络间的无缝互操作，同时保障数据主权和隐私安全。它通过部署在本地或受控环境中的节点，能够自主决定哪些链上数据可以进入或离开其管辖范围，从而防止未经授权的访问。这种机制对于需要高度合规性的金融或政务区块链应用尤为重要，因为它允许在开放的去中心化网络中建立封闭的安全边界。\n \n从技术架构来看，Grid Sovereign Gateway 往往结合了零知识证明、同态加密等隐私保护技术，并采用模块化设计以适应不同的业务场景。它不仅能处理简单的资产转移，还能支持复杂的智能合约调用和跨链消息传递，成为连接公链与私有链、联盟链的桥梁。随着区块链技术的演进，这类网关将成为构建可信数字生态系统不可或缺的基础设施，推动着 Web3 向更安全和可控的方向发展。\n",
  "reasoning": null,
  "think_blocks": [],
  "had_reasoning_leak": true
}
```

**Proof 侧车：** `c5177fd5-6667-4ffe-b7dd-ce1a1f441501_proof.json`

- `gate.reason`: `empty_after_sanitize`
- `quarantine_boundary.ok`: **false**
- `quarantine_boundary.reasons`: `reasoning_content_verbatim_in_final`, `reasoning_field_verbatim_in_final`
- `substrate_usage`: `completion_tokens: 552`, `reasoning_tokens: 276`, `content_tokens: 276`, `finish_reason: stop`, `truncated: false`

---

## 2. 三分法成分判定

| 类型 | 特征 | Run #1 是否符合 |
|------|------|----------------|
| **A. 全 thinking** | `Thinking Process:` / `Analyze the Request` / 编号分析步骤 | **否** — 尸体是完整三段中文成品，无分析腔 |
| **B. tag 包裹** | `think_blocks` 非空 / `` 残留 | **否** — `think_blocks: []` |
| **C. sanitizer 误杀正文** | `message.content` 有正常正文被规则剥光 | **否** — `sanitize_response` 只读 `content` 字段；当时 `content` 为空，正文全在 `reasoning_content` |

**归类：** **§2 thinking 治理未稳定生效** — LM Studio 将应出现在 `content` 的成品写入 `reasoning_content`；sanitizer 按设计隔离；`extract_final_from_quarantine` 尝试恢复后 **quarantine boundary** 因 verbatim 重叠清零 → `empty_after_sanitize`。

---

## 3. 修法对应

| 成分 | 修法 |
|------|------|
| A 全 thinking | 加强 `enable_thinking` + `chat_template_kwargs` + `max_reasoning_tokens` 透传；验证 payload 日志 |
| B tag 包裹 | 保持 `_strip_think_blocks`；检查 prefill 是否在 stream 路径生效 |
| **C（本案实际）** | **非收窄 sanitizer** — 应稳定 assistant prefill（`{"role":"assistant","content":" \n"}`），并监控 `reasoning_channel_deliverable` 比例 |
| boundary 清零 | 评估：当 `content` 空且 `reasoning_content` 无 thinking 标记时，允许 `extract_final_from_quarantine` 全文晋升（需 PM 批准，触及 quarantine 法） |

---

## 4. enable_thinking 透传核查

Gateway `_openai_chat_payload` 当前发送：

```json
{
  "enable_thinking": false,
  "chat_template_kwargs": {"enable_thinking": false},
  "max_reasoning_tokens": 128
}
```

另加 `_prepare_substrate_messages` assistant prefill。Run #1 仍泄漏 → **透传到位但 LM Studio 间歇忽略**（[#1990](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1990)）。

---

## 5. 新增遥测

- Gateway `/health` → `substrate_telemetry.all.empty_after_sanitize_rate`（与 `truncation_rate` 并列）
- Eval `substrate_health.empty_after_sanitize_rate`
- Proof 新增 `quarantine_composition` 字段（`reasoning_channel_deliverable` / `thinking_only` / `tag_wrapped`）
