# 安全说明

## 威胁模型（本机 self-hosted）

- **边界**：服务默认只监听 `127.0.0.1`，不对外网暴露。  
- **密钥**：所有 API keys（Anthropic/OpenAI/Gemini）仅存在于本机 gateway 的 `.env` 中，**不下发客户端**；客户端只使用 gateway 签发的 **Bearer token** 访问 gateway。  
- **最小权限**：通过 scope（chat/tts/vision/admin）限制每个 token 可访问的 endpoint；admin 仅用于查询 token 列表与健康检查。

## 实践

- 不在 repo 中提交 `.env`；`.env` 已在 `.gitignore`。  
- Token 生成后只显示一次；存库仅存 hash（sha256 + salt）。  
- 审计：每次请求（含 401/403/429/503）写入 sqlite，含 endpoint、status、latency、selected_provider、provider_fallback 等。  
- Kill-switch：`GATEWAY_KILL=1` 时所有业务 endpoint 直接返回 503，并写入审计。  
- CORS 默认拒绝所有；不对外暴露 Swagger（本机可访问 `/docs`）。  
- 异常响应不泄露敏感信息（如 key、内部路径）。
