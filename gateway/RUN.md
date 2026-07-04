# 一键启动（本机 127.0.0.1）

## 从零到跑起来

### 1) 环境（二选一）

**uv（推荐）**

```bash
cd gateway
uv venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

**venv fallback**

```bash
cd gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2) 配置

```bash
cp .env.example .env
# 按需编辑 .env（API keys 可选；缺则走 mock）
```

### 3) 初始化 DB 与 Token

```bash
python scripts/init_db.py
python scripts/create_token.py --scopes "chat,tts,vision,admin" --daily-limit 200
# 把输出的 token 和 token_id 存好，只显示一次
```

### 4) 启动服务

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

---

## 自测

把下面 `YOUR_TOKEN` 换成上面 create_token 输出的 token。

**1) /chat 默认 Claude（无 key 时自动 fallback 到 mock）**

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"你好"}' | jq .
```

**2) /chat compile 强制走 OpenAI（无 key 时 fallback mock）**

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"compile this","mode":"compile"}' | jq .
```

**3) /vision 默认 Gemini（无 key 时 fallback mock）**

```bash
curl -s -X POST http://127.0.0.1:8000/vision \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"image_base64":"'$(echo -n "dummy" | base64)'","task":"med_label_read"}' | jq .
```

**显式指定 provider（body 或 X-Provider）**

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Provider: mock" \
  -d '{"prompt":"hi"}' | jq .
```

---

## 一条命令启动（示例）

```bash
cd gateway && source .venv/bin/activate && python scripts/init_db.py && uvicorn app.main:app --host 127.0.0.1 --port 8000
```

（首次需先 create_token 并写好 .env）
