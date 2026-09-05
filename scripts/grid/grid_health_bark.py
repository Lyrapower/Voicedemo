"""Grid 8501 health bark monitor — 主动推送扫描池/数据池过期告警。

定时 curl 8501/api/state,检查 health 4 项(加密/美股/名单/因子)+ am 扫描状态,
过期则 bark 推送。去重:同状态冷却内不重复推(默认 30 min),恢复则清。

用法:python3 grid_health_bark.py(单次检查)
launchd 定时跑(每 5 分钟)。

Env: GRID_GATEWAY_URL(http://127.0.0.1:8501), GRID_HEALTH_BARK_COOLDOWN(秒,1800),
DOCTOR_BARK_URL(复用 pipeline_doctor.env)。
"""
import os, sys, json, time, urllib.request, urllib.parse, ssl, datetime

GATEWAY = os.getenv("GRID_GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
STATE_FILE = os.getenv("GRID_HEALTH_BARK_STATE", "/tmp/grid_health_bark_state.json")
COOLDOWN_S = int(os.getenv("GRID_HEALTH_BARK_COOLDOWN", "1800"))
# health 项 age 超此秒数 = 过期(alpha worker tick=300s,2*tick=600s 为 stale 线)
AGE_STALE_S = int(os.getenv("GRID_HEALTH_AGE_STALE_S", "600"))


def _age_to_seconds(age):
    """解析 8501 _age_str 格式:'45s'/'3m'/'2h'/'—' → 秒。"""
    if age is None or age == "—" or age == "":
        return None
    s = str(age).strip()
    try:
        if s.endswith("s"):
            return int(s[:-1])
        if s.endswith("m"):
            return int(s[:-1]) * 60
        if s.endswith("h"):
            return int(s[:-1]) * 3600
        return int(s)
    except (TypeError, ValueError):
        return None


def _bark_url() -> str:
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline_doctor.env")
    if os.path.isfile(env):
        for line in open(env, encoding="utf-8"):
            s = line.strip()
            if s.startswith("DOCTOR_BARK_URL="):
                return s.split("=", 1)[1].strip().strip('"').strip("'").rstrip("/")
    return os.getenv("DOCTOR_BARK_URL", "").strip().rstrip("/")


def _us_market_open():
    """美股交易时段(ET 周一-周五 09:30-16:00)。非交易时段 美股 ok=False 正常,不报。"""
    et = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-4)))
    if et.weekday() >= 5:
        return False
    t = et.hour * 60 + et.minute
    return 570 <= t <= 960  # 09:30-16:00 ET


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _fetch_state():
    try:
        with urllib.request.urlopen(GATEWAY + "/api/state", timeout=20, context=_ssl_ctx()) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}


def _load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}


def _save_state(s):
    try:
        json.dump(s, open(STATE_FILE, "w"))
    except Exception:
        pass


def send_bark(title: str, body: str) -> str:
    bark = _bark_url()
    if not bark:
        return "未配置 DOCTOR_BARK_URL"
    try:
        req = urllib.request.Request(bark, data=json.dumps(
            {"title": title, "body": body, "group": "grid-health"}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        with urllib.request.urlopen(req, timeout=12, context=_ssl_ctx()) as r:
            return "已推送" if r.status == 200 else f"HTTP {r.status}"
    except Exception:
        try:
            url = f"{bark}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
            with urllib.request.urlopen(url, timeout=12, context=_ssl_ctx()) as r:
                return "已推送(GET)" if r.status == 200 else f"GET {r.status}"
        except Exception as e:
            return f"失败:{e}"


def check_and_push() -> str:
    state = _fetch_state()
    if "_error" in state:
        # gateway 不可达也推送(严重)
        now = time.time()
        prev = _load_state()
        if now - prev.get("gateway_down", 0) > COOLDOWN_S:
            prev["gateway_down"] = now
            _save_state(prev)
            return send_bark("Grid 8501 不可达", f"gateway 无响应:{state['_error']}\n{datetime.datetime.now():%H:%M:%S}")
        return f"gateway 不可达(冷却中):{state['_error']}"
    prev = _load_state()
    prev.pop("gateway_down", None)  # 恢复
    health = state.get("health") or []
    am = state.get("am") or {}
    now = time.time()
    alerts = []
    for h in health:
        name = h.get("name", "?")
        ok = h.get("ok")
        age = h.get("age", "—")
        age_s = _age_to_seconds(age)
        # 告警条件:ok=False / age="—" / age 超阈值(worker 死后 status 仍 ok 但 age 涨)
        age_stale = (age in ("—", "", None)) or (age_s is not None and age_s > AGE_STALE_S)
        stale = (not ok) or age_stale
        # 美股非交易时段:ok=False 正常(收盘),仅 age 真过期(worker 死)才报
        if name == "美股" and not _us_market_open():
            stale = age_stale
        if stale:
            key = f"stale:{name}"
            if now - prev.get(key, 0) > COOLDOWN_S:
                alerts.append(f"{name} 过期(age={age}{' >%ds' % AGE_STALE_S if age_s and age_s > AGE_STALE_S else ''})")
                prev[key] = now
        else:
            prev.pop(f"stale:{name}", None)  # 恢复则清
    am_status = (am.get("status") or "").strip()
    if am_status and am_status not in ("scanned", "fresh", "ok", "waiting"):
        key = f"am:{am_status}"
        if now - prev.get(key, 0) > COOLDOWN_S:
            alerts.append(f"扫描状态={am_status}")
            prev[key] = now
    # syncAge: store 同步年龄过大
    # 600s 阈值对过夜/pre-market 正常稀疏 cadence(aether/watcher gap 可达 10-15min)太敏感,
    # store_age_s 在 187s↔600s+ 震荡会反复误报 "store 同步过期"。提到 1800s(30min,=冷却),
    # 只在 store 真的 30min 没写时才报;age_level=="red" 兜底保留。
    sync = state.get("syncAge") or {}
    store_age = sync.get("store_age_s")
    if isinstance(store_age, (int, float)) and store_age > 1800:
        key = "sync:store_age"
        if now - prev.get(key, 0) > COOLDOWN_S:
            alerts.append(f"store 同步过期 {int(store_age)}s (age_level={sync.get('age_level','?')})")
            prev[key] = now
    elif sync.get("age_level") == "red":
        key = "sync:red"
        if now - prev.get(key, 0) > COOLDOWN_S:
            alerts.append("sync age_level=red")
            prev[key] = now
    # quarantine
    if state.get("quarantine"):
        key = "quarantine"
        if now - prev.get(key, 0) > COOLDOWN_S:
            alerts.append("quarantine=True(隔离区有项)")
            prev[key] = now
    # brief 退役 — 边沿触发:同 retired_reason 只报一次,新退役才再报(防 level-trigger 重复推)
    brief = state.get("brief") or {}
    if brief.get("retired"):
        reason = brief.get("retired_reason", "?")
        if reason != prev.get("last_retired_reason"):
            key = "brief:retired"
            if now - prev.get(key, 0) > COOLDOWN_S:
                alerts.append(f"简报退役: {reason}")
                prev[key] = now
                prev["last_retired_reason"] = reason
    else:
        prev.pop("last_retired_reason", None)  # 恢复则清,下次退役再报
    _save_state(prev)
    if not alerts:
        return "全部正常"
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    body = "\n".join(alerts) + f"\n{ts}"
    return send_bark(f"Grid 8501 告警·{len(alerts)}项", body)


if __name__ == "__main__":
    print(check_and_push())
