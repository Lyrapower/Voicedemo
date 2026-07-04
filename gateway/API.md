# API 说明（最小）

- 基址：`http://127.0.0.1:8000`
- 鉴权：所有需鉴权接口均需 `Authorization: Bearer <token>`
- 未授权请求返回 `401`；权限不足返回 `403`；超限返回 `429`；Kill-switch 开启返回 `503`

## 路由与 Scope

| 方法 | 路径 | 所需 scope |
|------|------|------------|
| POST | /chat | chat |
| POST | /tts | tts |
| POST | /vision | vision |
| GET | /admin/health | 无 |
| GET | /admin/tokens | admin |

## 请求/响应与错误码

### POST /chat

- **Body**（JSON）  
  - `prompt` (string, 必填)  
  - `context` (object, 可选)  
  - `provider` (可选): `"claude"` \| `"openai"` \| `"gemini"` \| `"mock"`  
  - `mode` (可选): `"companion"` \| `"help"` \| `"compile"` \| `"debug"`  
  - `task_type` (可选): `"chat"` \| `"spec"` \| `"contract"` \| `"code"` \| `"summary"`  
- **Header**  
  - `X-Provider`（可选）：覆盖 body 中的 `provider`  
- **响应**  
  - `reply` (string)  
  - `provider` / `selected_provider` (string)  
  - `provider_fallback` (boolean)  
- **默认路由**：无 override 时，`mode==compile` 或 `task_type in {spec, contract, code}` 走 OpenAI，否则走 DEFAULT_CHAT_PROVIDER（默认 Claude）。失败时按 failover 链回退并写审计。

### POST /tts

- **Body**  
  - `text` (string, 必填)  
  - `lang` (string, 默认 `"zh"`)  
  - `voice` (string, 默认 `"default"`)  
  - `provider` (可选): 同上  
- **Header**  
  - `X-Provider`（可选）  
- **响应**  
  - `status`, `note`, `selected_provider`, `provider_fallback`  
- 当前默认 TTS 为 mock；可扩展真实 TTS 后通过 env 配置。

### POST /vision

- **Body**  
  - `image_base64` (string, 必填)  
  - `task` (string, 默认 `"med_label_read"`)  
  - `provider` (可选): 同上  
- **Header**  
  - `X-Provider`（可选）  
- **响应**  
  - `summary`, `parsed`, `risk_flags`, `next_steps`  
  - `selected_provider`, `provider_fallback`  
- 默认 vision 为 DEFAULT_VISION_PROVIDER（默认 Gemini），失败则 fallback mock。

### GET /admin/health

- 无鉴权。  
- 响应：`{ "status": "ok", "kill": <bool> }`（kill 表示是否开启 Kill-switch）。

### GET /admin/tokens

- 需要 scope `admin`。  
- 响应：`{ "tokens": [ { "token_id", "scopes", "enabled", "daily_used", "daily_limit" } ] }`（不返回 hash）。

## 错误码

- `401`：缺少或无效 Authorization  
- `403`：Insufficient scope  
- `429`：Daily request limit exceeded  
- `503`：Gateway temporarily disabled (GATEWAY_KILL=1)
