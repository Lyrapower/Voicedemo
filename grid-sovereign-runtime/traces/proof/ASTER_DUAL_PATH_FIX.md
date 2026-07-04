# Aster 双路径修复 — 用户链验收（Fable 规则）

**生成时间**: 2026-07-03  
**执行**: `bash scripts/deploy_aster_dual_path.sh`

## Fable 原话对照

| Fable 要求 | 本次交付 |
|-----------|---------|
| 在用户实际链路上验收，用户不是 QA | `scripts/verify_aster_user_chain.py` → `grid-sovereign-runtime/traces/proof/USER_CHAIN_FIX_ACCEPTANCE.json` |
| 链路指纹 `served_by` | Gateway 路径响应含 `gateway-v4.11`；直连 `:1234` 无此字段（符合矩阵结论） |
| 运行时 temperature（非 toml 应然） | 已同步 **0.7** 到 conversation + qwen 默认配置 |
| 旧会话污染 | `ASTER_DEPLOY_CLEAR=1` 清空 Aster tab 26 条消息 |
| reasoning 税 | 直连加 `max_reasoning_tokens=128` + `enableThinking=false`；实测 reasoning_tokens=0 |

## 双路径

### A. Gateway（Aster 标签页 → Generators）

1. `bash scripts/install_aster_gateway_plugin.sh`（已 symlink 到 `~/.lmstudio/extensions/plugins/demo/aster-grid-gateway`）
2. **重启 LM Studio**
3. Aster 标签 → 模型选择器 → **Generators → demo/aster-grid-gateway**
4. 聊天流量经 `:8501`，响应体含 `served_by`

插件代码: `lmstudio-plugins/aster-grid-gateway/.lmstudio/production.js`

### B. 直连（LM Studio 本地 qwen3.5-9b）

- `config/aster.toml`: temp **0.7**, budget chat **400**, thinking_cap **128**
- `deploy_lmstudio_aster.sh` 同步 perChatPredictionConfig + qwen 默认 load/operation 配置
- 助手 prefill 由 gateway 侧 `_prepare_substrate_messages` 处理；直连 API 调用加 assistant prefill + max_reasoning_tokens

## 一键部署

```bash
bash scripts/deploy_aster_dual_path.sh
```

## 根因 → 修复映射

1. **流量不过 gateway** → Generator 插件把 Aster 标签页接到 `:8501`
2. **reasoning 吃掉 content** → thinking_cap 128 + enableThinking false + 清空旧会话
3. **temp 0.3 加重重复** → 运行时改为 0.7

用户重启 LM Studio 后收报告即可，无需再当 QA。
