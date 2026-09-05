"""Grid Voice Bridge · :8796 · v0.2

    GPT Voice Client ──WebRTC──▶ OpenAI Realtime
            │                          │ function call
            │  ephemeral token         ▼(浏览器中继)
            └────────────────▶ Voice Bridge :8796 ──▶ Grid 8501/8500
                                       │
                                  Grid final ──▶ Realtime TTS

三条硬约束(代码强制,不是注释愿望):
  1. API key 只在服务端。浏览器拿到的是 OpenAI 签发的 ephemeral client_secret
     (分钟级过期)。/session 响应经 _scrub 过滤,key 前缀出现即抛错不返回。
  2. 最小上下文信封。给语音模型的只有:最近一条 Grid 播报 + 待确认动作摘要。
     没有记忆、没有日记、没有历史会话、没有身份锚。ENVELOPE_ALLOW 白名单强制。
  3. Bridge 是防火墙。函数按风险分级:
       info  级 → 直通 Grid(只读问答、状态)
       high  级 → 不执行,生成待确认动作 + 四位复述码
     复述码只出现在屏幕(Voice Session 面板),不进语音模型的任何响应。
     用户念出屏幕上的码 → 模型中继 → Bridge 核对 → 才执行。
     这是跨通道二次确认:模型看不见码,就无法自我批准。

v0.2 加固:
  - 复述码改 secrets 生成;猜错 3 次即作废(封暴力试)
  - /api/fn /api/panel /api/cancel /api/utterance /api/session 全部要求
    X-Bridge-Key(挡网内其它进程直接 curl;key 由 index 页同源注入)
  - 建任务时向 Console 带 X-Console-Key
  - _scrub 简化:出站含 sk-proj-/sk-svcacct- 一律抛错,无豁免

诚实清单:
  - 不做 server-side WebSocket 中转(那会加一跳延迟);函数调用由浏览器中继,
    因此浏览器可以伪造函数调用 —— 但它伪造不了复述码,高危动作仍锁死。
  - ephemeral token 由 OpenAI 签发,过期与吊销遵循其策略,Bridge 不缓存。
  - 无多人权限模型。
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

APP = FastAPI(title="Grid Voice Bridge", version="0.2")

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-realtime")
REALTIME_VOICE = os.getenv("REALTIME_VOICE", "marin")
SESSIONS_URL = os.getenv("OPENAI_SESSIONS_URL",
                         "https://api.openai.com/v1/realtime/client_secrets")
GRID_CHAT = os.getenv("GRID_CHAT_URL",
                      "http://host.docker.internal:8500/v1/chat/completions")
CONSOLE_API = os.getenv("CONSOLE_API", "http://host.docker.internal:8610/api")
STATIC = Path(os.getenv("VOICE_STATIC", "/app/static"))
CONFIRM_TTL = int(os.getenv("CONFIRM_TTL", "180"))
CONFIRM_MAX_ATTEMPTS = 3

BRIDGE_KEY = os.getenv("VOICE_BRIDGE_KEY", "").strip()
if not BRIDGE_KEY:
    BRIDGE_KEY = secrets.token_hex(16)
    print("[bridge] VOICE_BRIDGE_KEY 未配置,本次运行临时生成:%s\n"
          "[bridge] 固定它:写入 .env 并重启" % BRIDGE_KEY, flush=True)
CONSOLE_KEY = os.getenv("CONSOLE_KEY", "").strip()


def _auth(x_bridge_key: str | None):
    if (x_bridge_key or "") != BRIDGE_KEY:
        raise HTTPException(401, "X-Bridge-Key 缺失或不符")
GRID_TIMEOUT = int(os.getenv("GRID_TIMEOUT", "180"))

# 信封白名单 —— 只有这些键允许进入给语音模型的上下文
ENVELOPE_ALLOW = {"last_broadcast", "pending_action", "workspace_list"}

# 会话状态(单用户单机,内存即可;重启即清空 = 待确认动作不跨重启存活,是特性)
_STATE = {
    "last_broadcast": "",
    "pending": None,        # {id, kind, summary, code, created, payload}
    "transcript": [],       # [{ts, role, text}]
}


# ---------------------------------------------------------------- 工具

def _now() -> int:
    return int(time.time())


def _scrub(obj):
    """任何要发往浏览器的东西过这一关:命中 key 前缀立刻炸,不静默泄露。"""
    blob = json.dumps(obj, ensure_ascii=False)
    if OPENAI_KEY and OPENAI_KEY[:12] in blob:
        raise RuntimeError("拒绝返回:响应体内含 API key 前缀")
    for pref in ("sk-proj-", "sk-svcacct-"):
        if pref in blob:
            raise RuntimeError("拒绝返回:响应体内疑似含长期密钥 %s…" % pref)
    return obj


def _log(role: str, text: str) -> None:
    _STATE["transcript"].append({"ts": _now(), "role": role, "text": text[:600]})
    _STATE["transcript"][:] = _STATE["transcript"][-60:]


def _envelope() -> dict:
    """给语音模型的极小上下文。注意:复述码不在其中。"""
    p = _STATE["pending"]
    env = {
        "last_broadcast": _STATE["last_broadcast"][:400],
        "pending_action": ({"summary": p["summary"], "kind": p["kind"]}
                           if p else None),
        "workspace_list": ["quant", "crypto", "garden", "ip", "corp",
                           "software", "trade"],
    }
    bad = set(env) - ENVELOPE_ALLOW
    if bad:
        raise RuntimeError("信封越界字段: %s" % bad)
    return env


# ---------------------------------------------------------------- 函数表

TOOLS = [
    {
        "type": "function",
        "name": "grid_ask",
        "description": "把纯信息类问题交给 Grid 回答(只读,不产生任何副作用)。"
                       "用于:查状态、问结论、要解释。",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "type": "function",
        "name": "grid_status",
        "description": "读取 Console 仪表与任务分布。只读。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "grid_propose_task",
        "description": "提议创建一个任务。注意:这不会执行,只会生成一个待确认动作,"
                       "屏幕上会显示一个四位复述码。请让用户念出屏幕上的码来确认。",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "title": {"type": "string"},
                "owner_node": {"type": "string"},
                "risk_level": {"type": "string"},
            },
            "required": ["workspace", "title"],
        },
    },
    {
        "type": "function",
        "name": "grid_confirm",
        "description": "用户念出屏幕上的四位复述码后调用此函数确认执行。"
                       "你看不到这个码,必须由用户口述。",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
]

INSTRUCTIONS = """你是 Grid 的语音入口,不是 Grid 本身。你的职责只有两件:发起与确认。

规则:
- 判断意义、给结论、做决策 —— 一律交给 grid_ask,不要自己回答专业问题。
- 任何会产生副作用的请求(建任务/部署/写盘/下单/转账)—— 只能调用
  grid_propose_task,它不会执行,只生成待确认动作。
- 确认必须由用户念出屏幕上显示的四位码。你看不到那个码,不要猜、不要复述你以为的码,
  只要把用户说出的数字原样传给 grid_confirm。
- 说话简短。播报 Grid 的回答时保持原意,不要添加你自己的判断。
- 如果 Grid 不可达,如实说不可达,不要编造答案。"""


# ---------------------------------------------------------------- Grid 调用

def _grid_ask(question: str) -> dict:
    env = _envelope()
    try:
        with httpx.Client(timeout=GRID_TIMEOUT) as cli:
            r = cli.post(GRID_CHAT, json={
                "model": "grid", "max_tokens": 600,
                "messages": [
                    {"role": "system", "content":
                     "你是 Grid。经语音入口收到一个只读问题,简明回答。"
                     "禁产任何交易信号(方向/入场/目标价/仓位)。"
                     "上下文信封(仅本回合):" + json.dumps(env, ensure_ascii=False)},
                    {"role": "user", "content": question},
                ]})
            r.raise_for_status()
            body = r.json()
        out = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
        _STATE["last_broadcast"] = out
        _log("grid", out)
        return {"ok": True, "answer": out[:1500]}
    except Exception as exc:
        msg = "Grid 不可达:%s" % str(exc)[:200]
        _log("bridge", msg)
        return {"ok": False, "error": msg}


def _grid_status() -> dict:
    out = {}
    for name, path in (("gauges", "/gauges"), ("stats", "/stats")):
        try:
            with httpx.Client(timeout=8) as cli:
                out[name] = cli.get(CONSOLE_API + path).json()
        except Exception as exc:
            out[name] = {"no_reading": True, "error": str(exc)[:160]}
    bays = (out.get("gauges") or {}).get("bays", {})
    up = [k for k, v in bays.items() if v.get("ok")]
    down = [k for k, v in bays.items() if not v.get("ok")]
    brief = "在线 %s;无读数或异常 %s" % (",".join(up) or "无", ",".join(down) or "无")
    _STATE["last_broadcast"] = brief
    return {"ok": True, "brief": brief, "detail": out}


def _new_code() -> str:
    return "%04d" % secrets.randbelow(10000)


def _propose(kind: str, summary: str, payload: dict) -> dict:
    """高危动作 —— 不执行,挂起 + 生成复述码。码不进返回值。"""
    _STATE["pending"] = {
        "id": "p%d" % _now(), "kind": kind, "summary": summary,
        "code": _new_code(), "created": _now(), "payload": payload,
        "attempts": 0,
    }
    _log("bridge", "挂起待确认:" + summary)
    return {"ok": True, "pending": True, "summary": summary,
            "instruction": "已挂起,未执行。屏幕上显示了一个四位码,"
                           "请让用户念出来,然后调用 grid_confirm。"}


def _confirm(code: str) -> dict:
    p = _STATE.get("pending")
    if not p:
        return {"ok": False, "error": "没有待确认动作"}
    if _now() - p["created"] > CONFIRM_TTL:
        _STATE["pending"] = None
        return {"ok": False, "error": "确认已超时(%ds),动作作废" % CONFIRM_TTL}
    if (code or "").strip() != p["code"]:
        p["attempts"] = p.get("attempts", 0) + 1
        if p["attempts"] >= CONFIRM_MAX_ATTEMPTS:
            _STATE["pending"] = None
            _log("bridge", "复述码 %d 次不符,动作作废(封暴力试)" % CONFIRM_MAX_ATTEMPTS)
            return {"ok": False,
                    "error": "复述码三次不符,动作已作废,请重新发起"}
        _log("bridge", "复述码不符,拒绝(%d/%d)"
             % (p["attempts"], CONFIRM_MAX_ATTEMPTS))
        return {"ok": False, "error": "复述码不符,未执行(剩 %d 次机会)"
                % (CONFIRM_MAX_ATTEMPTS - p["attempts"])}
    payload = p["payload"]
    _STATE["pending"] = None
    try:
        with httpx.Client(timeout=30) as cli:
            r = cli.post(CONSOLE_API + "/tasks", json=payload,
                         headers={"X-Console-Key": CONSOLE_KEY})
            body = r.json()
        ok = bool(body.get("ok"))
        msg = ("任务已建 #%s" % body.get("task_id")) if ok else \
              ("被拒:%s" % body.get("rejected"))
        _STATE["last_broadcast"] = msg
        _log("bridge", msg)
        return {"ok": ok, "result": msg}
    except Exception as exc:
        msg = "Console 不可达,未建任务:%s" % str(exc)[:200]
        _log("bridge", msg)
        return {"ok": False, "error": msg}


DISPATCH = {
    "grid_ask": lambda a: _grid_ask(a.get("question", "")),
    "grid_status": lambda a: _grid_status(),
    "grid_propose_task": lambda a: _propose(
        "create_task",
        "在 %s 建任务:%s(节点 %s,风险 %s)" % (
            a.get("workspace", "?"), a.get("title", "?"),
            a.get("owner_node", "grid_local"), a.get("risk_level", "read")),
        {"workspace": a.get("workspace", ""), "title": a.get("title", ""),
         "owner_node": a.get("owner_node", "grid_local"),
         "risk_level": a.get("risk_level", "read")}),
    "grid_confirm": lambda a: _confirm(a.get("code", "")),
}


# ---------------------------------------------------------------- HTTP

class FnCall(BaseModel):
    name: str
    arguments: dict = {}


class Utterance(BaseModel):
    role: str = "user"
    text: str = ""


@APP.get("/api/health")
def health():
    return {"ok": True, "version": "0.1",
            "key_loaded": bool(OPENAI_KEY), "model": REALTIME_MODEL}


@APP.post("/api/session")
def session(x_bridge_key: str | None = Header(default=None)):
    _auth(x_bridge_key)
    """签发 ephemeral token 给浏览器。长期 key 绝不出服务端。"""
    if not OPENAI_KEY:
        raise HTTPException(500, "OPENAI_API_KEY 未配置(只放服务端 .env)")
    payload = {
        "session": {
            "type": "realtime",
            "model": REALTIME_MODEL,
            "audio": {"output": {"voice": REALTIME_VOICE}},
            "instructions": INSTRUCTIONS,
            "tools": TOOLS,
            "tool_choice": "auto",
        }
    }
    try:
        with httpx.Client(timeout=20) as cli:
            r = cli.post(SESSIONS_URL, headers={
                "Authorization": "Bearer " + OPENAI_KEY,
                "Content-Type": "application/json"}, json=payload)
            r.raise_for_status()
            body = r.json()
    except Exception as exc:
        raise HTTPException(502, "签发 ephemeral token 失败: %s" % str(exc)[:200])
    secret = body.get("value") or (body.get("client_secret") or {}).get("value")
    if not secret:
        raise HTTPException(502, "OpenAI 未返回 client_secret")
    return _scrub({"client_secret": secret,
                   "expires_at": body.get("expires_at"),
                   "model": REALTIME_MODEL,
                   "envelope": _envelope()})


@APP.post("/api/fn")
def fn(call: FnCall, x_bridge_key: str | None = Header(default=None)):
    _auth(x_bridge_key)
    """浏览器把 Realtime 的 function call 中继到这里执行。"""
    if call.name not in DISPATCH:
        return JSONResponse({"ok": False, "error": "未注册函数 %s" % call.name},
                            status_code=400)
    _log("model", "call %s %s" % (call.name, json.dumps(call.arguments,
                                                        ensure_ascii=False)[:200]))
    out = DISPATCH[call.name](call.arguments or {})
    return _scrub(out)


@APP.post("/api/utterance")
def utterance(u: Utterance, x_bridge_key: str | None = Header(default=None)):
    _auth(x_bridge_key)
    """转写文本回传,只为 Voice Session 面板可见性。"""
    _log(u.role, u.text)
    return {"ok": True}


@APP.get("/api/panel")
def panel(x_bridge_key: str | None = Header(default=None)):
    _auth(x_bridge_key)
    """Voice Session 面板数据 —— 复述码只在这里出现(屏幕通道)。"""
    p = _STATE["pending"]
    return {
        "transcript": _STATE["transcript"][-30:],
        "last_broadcast": _STATE["last_broadcast"],
        "pending": ({"summary": p["summary"], "code": p["code"],
                     "kind": p["kind"],
                     "expires_in": max(0, CONFIRM_TTL - (_now() - p["created"]))}
                    if p else None),
        "envelope": _envelope(),
    }


@APP.post("/api/cancel")
def cancel(x_bridge_key: str | None = Header(default=None)):
    _auth(x_bridge_key)
    _STATE["pending"] = None
    _log("bridge", "用户在面板取消了待确认动作")
    return {"ok": True}


@APP.get("/")
def index():
    f = STATIC / "voice.html"
    if not f.exists():
        return JSONResponse({"error": "static not mounted"}, status_code=500)
    html = f.read_text(encoding="utf-8").replace(
        "</head>",
        '<meta name="bridge-key" content="%s"/></head>' % BRIDGE_KEY, 1)
    return HTMLResponse(html)
