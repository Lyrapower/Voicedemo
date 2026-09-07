#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
场域编译器 field_now v1.6 — 把散落的感官编译成一块「此刻」,给 Grid 核心注入。

    信标 jsonl(身体)   ─┐
    Garden 8787(声场) ─┼─▶  GET /now(纯文本 ≤600字)   ─▶ gateway 注入
    router jsonl(网格) ─┘    GET /now.json(结构化)

    (眼睛/拾字簿:v1.4 摘除,见下)

Mac 上运行:
    python3 field_now_v1.1.py          # 监听 127.0.0.1:8795

gateway 侧接法(唯一改动,一行拉取 + 拼进 system,拉不到就跳过):

    try:
        now_block = urllib.request.urlopen(
            "http://127.0.0.1:8795/now", timeout=1).read().decode()
        system_prompt = now_block + "\n\n" + system_prompt
    except Exception:
        pass   # 场域不可用时核心照常,感知是增益不是依赖

设计约束:
  * 压缩在边缘完成 —— 核心只收编译过的文本,不收原始数据(视网膜原则)。
  * 诚实的时效 —— 每路感官都标注新鲜度;信标超过 30 分钟就明说「无近信号」,
    绝不让核心把旧场当此刻。
  * 感知是增益不是依赖 —— 任何一路缺失都静默降级,/now 永远能返回(最少含时间)。
  * 30 秒缓存,gateway 高频调用不产生扫描成本。

环境变量:FIELD_DIR(信标)/ ROUTER_DIR(路由)
          NOW_PORT(8795)/ NOW_BIND(默认 127.0.0.1,见 v1.1 说明)
纯 stdlib。

v1.1(2026-07-20):
  F1 跨文件统计修复 —— sense_body 原来只读最后一个信标文件的尾部,
     午夜换文件后「近一小时分布」会丢上一个文件里的样本。
     现改为合并最后两个文件的行再筛,统计诚实(诚实时效是本文件立身之本)。
  F2 监听收窄 —— 原 0.0.0.0 无鉴权对全网开放,而 /now 含运动状态、
     位置节奏、当日笔记预览,是全链路里最贴身的数据。
     默认改 127.0.0.1(gateway 同机拉取,不需要对外)。
     确需跨设备(如 iPhone 终端)时,显式 NOW_BIND=0.0.0.0 并自担边界,
     或走 Tailscale 绑定具体 tailnet IP。场域数据,窗要最小。

v1.2(2026-07-20)—— 哨兵层(Sentinel):
  诚实定位:这不是「防监听」——应用层防不了 OS 级截获,那是
  LuLu/Little Snitch + 系统加固的领地,声称能防就是伪造因果。
  这一层做的是:场域数据有门、门上有锁、锁上有记录、撬锁会响。
  S1 访问留痕 —— /now 每次访问记 jsonl(时间/来源/路径/放行否),
     落 FIELD_DIR/access_YYYY-MM-DD.jsonl。看不见的访问才是监听,
     被记录的访问只是访问。GET /sentinel 可查今日访问汇总。
  S2 白名单拒答 —— 默认仅应答 127.0.0.1;NOW_ALLOW 逗号分隔追加
     (如 Tailscale 网段前缀 100.)。名单外一律 403,并重点留痕。
  S3 异常告警 —— 名单外访问尝试、或访问频率突变(60s 窗口超阈值),
     经 Bark 推送到手机(NOW_BARK_URL,不设则跳过)。告警走后台线程,
     绝不阻塞 /now 应答;推送失败静默(哨兵是增益不是依赖)。
  S4 权限自检 —— 启动时将信标/拾字目录 chmod 700;若发现权限比 700 宽,
     启动横幅警告(防止某个 app 顺手扫了桌面目录)。

新增环境变量:NOW_ALLOW(白名单前缀,逗号分隔)
              NOW_BARK_URL(Bark 推送地址,如 http://127.0.0.1:8088/key)
              NOW_RATE_MAX(60s 窗口访问上限,默认 30)

v1.3(2026-07-20)—— 静默时段(Quiet Hours):
  Q1 夜间场域静默 —— NOW_QUIET(默认 00:00-08:00,本地时区)内,
     /now 只返回时刻与「夜间,场域静默」,不读任何感官、不编译。
     这不是省资源,是边界:睡觉是你的时间,不欠任何系统一份编译。
     静默也是一种如实的状态 —— 它照样诚实标注,不装作有信号。
     /now.json 返回 {"quiet": true};/sentinel 审计在静默期照常工作
     (门卫不下班,只有编译器休息)。
     格式 NOW_QUIET=HH:MM-HH:MM,支持跨午夜;NOW_QUIET= 置空即关闭。

v1.4(2026-07-20)—— 摘除眼睛(拾字簿):
  E1 sense_eyes 整体移除 —— 拾字簿数据未整理完,且「截图流 ≈ 注意力」
     这个前提未经验证。感官不是越多越好,是每一路都得真。
     「读了但没筛过」和「没读」是两回事:未整理的 OCR 内容不该被
     任何进程打开,一次都不该。摘除 = 代码不再触碰 OCR_INBOX 目录,
     权限自检(S4)也不再管它。
     重新接入的条件(届时另立版本):数据清理完成,且回答了
     「我的截图流到底反映什么」—— 反映注意力则接,是杂物抽屉则另找信号源。
     两路真感官的场,好过三路里掺一路假的。

v1.6(2026-07-22)—— FIELD_SENSE_PIPELINE 第 2 步:
  G2 sense_garden 重写 —— 只读拉 8787/telemetry.json,fail-soft 返回 idle 态;
     ts 超过 30s 按 idle;garden live↔idle 翻转各记一行日志;zone 字段透传。
  G3 /now.json 扁平输出 anchor_coherence/anchor_state/breath_sync/zone 供前端场感知。

v1.5(2026-07-20)—— 接入声场(Voice Garden 8787):
  G1 sense_garden —— 拉 Garden 的 /telemetry.json(127.0.0.1,超时 1s),
     编译成「声场」一行:活跃时报 presence/coherence/beat/energy;
     idle 时如实报「静」;anchor 字段存在且非空时一并报出
     (anchor 是 Garden 侧后续功能,本文件零改动自动兼容)。
     拉不到 → 静默降级,声场整行消失(感知是增益不是依赖)。
     数据不落盘 —— Garden 自己有 anchor_log,此处只做实时编译。
  规矩沿用:静默时段覆盖此路;哨兵留痕照旧;肥波哥的 Live Analyzer
  就是这一路感官的源头 —— 有消费者才活,它今天等到了。
"""

import json
import os
import re
import stat
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIELD_DIR = Path(os.environ.get("FIELD_DIR", "~/Desktop/GridField")).expanduser()
ROUTER_DIR = Path(os.environ.get("ROUTER_DIR", "~/Desktop/GridRouter")).expanduser()
PORT = int(os.environ.get("NOW_PORT", "8795"))
BIND = os.environ.get("NOW_BIND", "127.0.0.1")  # v1.1 F2:默认只听本机
# v1.2 哨兵层配置
ALLOW = ["127.0.0.1"] + [p.strip() for p in
                         os.environ.get("NOW_ALLOW", "").split(",") if p.strip()]
BARK_URL = os.environ.get("NOW_BARK_URL", "").strip()
RATE_MAX = int(os.environ.get("NOW_RATE_MAX", "30"))  # 60s 窗口访问上限
GARDEN_URL = os.environ.get("NOW_GARDEN",
                            "http://127.0.0.1:8787/telemetry.json")
GARDEN_TIMEOUT = float(os.environ.get("NOW_GARDEN_TIMEOUT", "1.5"))
GARDEN_STALE_SEC = float(os.environ.get("NOW_GARDEN_STALE_SEC", "30"))
_garden_live_prev = None


def _parse_quiet(s):
    """'00:00-08:00' → ((0,0),(8,0));置空/非法 → None(关闭)。"""
    try:
        a, b = s.split("-")
        ha, ma = (int(x) for x in a.split(":"))
        hb, mb = (int(x) for x in b.split(":"))
        return ((ha, ma), (hb, mb))
    except Exception:
        return None


QUIET = _parse_quiet(os.environ.get("NOW_QUIET", "00:00-08:00"))


def in_quiet(now=None):
    """本地时间是否在静默时段内;支持跨午夜(如 23:00-07:00)。"""
    if QUIET is None:
        return False
    now = now or datetime.now().astimezone()
    cur = now.hour * 60 + now.minute
    (ha, ma), (hb, mb) = QUIET
    a, b = ha * 60 + ma, hb * 60 + mb
    if a == b:
        return False
    if a < b:
        return a <= cur < b
    return cur >= a or cur < b      # 跨午夜

ZH_MOTION = {"still": "静", "fidget": "微动", "walking": "行",
             "cycling": "骑", "driving": "驰", "unknown": "?"}
WEEK = "一二三四五六日"

_cache = {"t": 0.0, "text": "", "data": {}}

# ---------------------------------------------------------------- 哨兵层 v1.2

_rate = {"win_start": 0.0, "count": 0, "alerted": False}
_rate_lock = threading.Lock()


def _sentinel_log(entry):
    """访问留痕:FIELD_DIR/access_YYYY-MM-DD.jsonl,一次访问一行。"""
    try:
        FIELD_DIR.mkdir(parents=True, exist_ok=True)
        f = FIELD_DIR / ("access_%s.jsonl" % datetime.now().strftime("%Y-%m-%d"))
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _bark(title, body):
    """异常告警经 Bark 推手机;后台线程,失败静默(哨兵是增益不是依赖)。"""
    if not BARK_URL:
        return

    def _push():
        try:
            url = "%s/%s/%s" % (BARK_URL.rstrip("/"),
                                urllib.parse.quote(title),
                                urllib.parse.quote(body))
            urllib.request.urlopen(url, timeout=5)
        except Exception:
            pass
    threading.Thread(target=_push, daemon=True).start()


def _ip_allowed(ip):
    return any(ip == a or ip.startswith(a) for a in ALLOW)


def sentinel_check(ip, path):
    """返回 True=放行。名单外拒答并告警;频率突变告警(仍放行,只是响)。"""
    allowed = _ip_allowed(ip)
    _sentinel_log({"ts": datetime.now(timezone.utc)
                   .strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "ip": ip, "path": path, "allowed": allowed})
    if not allowed:
        _bark("场域·陌生访问被拒", "%s → %s" % (ip, path))
        return False
    # 频率窗:60s 计数,超阈值告警一次(本窗口内不重复响)
    now = time.time()
    with _rate_lock:
        if now - _rate["win_start"] > 60:
            _rate.update(win_start=now, count=0, alerted=False)
        _rate["count"] += 1
        if _rate["count"] > RATE_MAX and not _rate["alerted"]:
            _rate["alerted"] = True
            _bark("场域·访问频率异常",
                  "60s 内 %d 次(阈值 %d),来源 %s"
                  % (_rate["count"], RATE_MAX, ip))
    return True


def sentinel_today():
    """今日访问汇总:按 IP 聚合,拒答单列。GET /sentinel 用。"""
    f = FIELD_DIR / ("access_%s.jsonl" % datetime.now().strftime("%Y-%m-%d"))
    if not f.exists():
        return {"date": datetime.now().strftime("%Y-%m-%d"),
                "total": 0, "by_ip": {}, "denied": []}
    by_ip, denied, total = {}, [], 0
    for l in f.read_text(encoding="utf-8").strip().splitlines():
        try:
            e = json.loads(l)
        except Exception:
            continue
        total += 1
        by_ip[e.get("ip", "?")] = by_ip.get(e.get("ip", "?"), 0) + 1
        if not e.get("allowed", True):
            denied.append({"ts": e.get("ts"), "ip": e.get("ip"),
                           "path": e.get("path")})
    return {"date": datetime.now().strftime("%Y-%m-%d"),
            "total": total, "by_ip": by_ip, "denied": denied[-20:]}


def sentinel_harden():
    """S4 权限自检:私有目录收到 700;发现比 700 宽则横幅警告。"""
    warns = []
    for d in (FIELD_DIR,):
        if not d.exists():
            continue
        try:
            mode = stat.S_IMODE(d.stat().st_mode)
            if mode & 0o077:            # group/other 有任何位
                warns.append("%s 权限 %o(比 700 宽)" % (d, mode))
            os.chmod(d, 0o700)
        except Exception as e:  # noqa: BLE001
            warns.append("%s 权限自检失败: %s" % (d, e))
    return warns


def _parse_iso(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")\
            .replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _age_str(dt):
    sec = (datetime.now(timezone.utc) - dt).total_seconds()
    if sec < 90:
        return "刚刚"
    if sec < 3600:
        return "%d 分钟前" % (sec // 60)
    if sec < 86400:
        return "%d 小时前" % (sec // 3600)
    return "%d 天前" % (sec // 86400)


# ---------------------------------------------------------------- 三路感官

def sense_body():
    """信标:最后一条样本 + 近一小时运动分布。
    v1.1 F1:合并最后两个文件的尾部行,跨午夜统计不丢样本。"""
    files = sorted(FIELD_DIR.glob("field_*.jsonl"))
    if not files:
        return None
    lines = []
    for f in files[-2:]:                       # 最后两个文件,老的在前
        lines.extend(f.read_text(encoding="utf-8").strip().splitlines())
    lines = lines[-240:]                       # 尾部封顶,扫描成本不变量级
    samples = []
    for l in lines:
        try:
            samples.append(json.loads(l))
        except Exception:
            pass
    if not samples:
        return None
    last = samples[-1]
    last_dt = _parse_iso(last.get("ts", ""))
    if last_dt is None:
        return None
    stale = (datetime.now(timezone.utc) - last_dt).total_seconds() > 1800
    hour_ago = datetime.now(timezone.utc).timestamp() - 3600
    dist = {}
    for s in samples:
        dt = _parse_iso(s.get("ts", ""))
        if dt and dt.timestamp() >= hour_ago:
            m = s.get("motion", "unknown")
            dist[m] = dist.get(m, 0) + 1
    return {"motion": last.get("motion", "unknown"),
            "speed": last.get("speed"), "age": _age_str(last_dt),
            "stale": stale,
            "hour_dist": {ZH_MOTION.get(k, k): v for k, v in
                          sorted(dist.items(), key=lambda x: -x[1])}}



def _log_garden_flip(state: str) -> None:
    global _garden_live_prev
    if _garden_live_prev == state:
        return
    _garden_live_prev = state
    print("[field_now] garden → %s" % state, flush=True)


def sense_garden():
    """读 Garden anchor 遥测。只读;任何失败返回 idle 态,不抛异常。"""
    idle = {
        "garden": "idle",
        "anchor_coherence": None,
        "anchor_state": "idle",
        "breath_sync": None,
        "zone": None,
    }
    try:
        req = urllib.request.Request(
            GARDEN_URL,
            headers={"User-Agent": "field_now/1.6"},
        )
        with urllib.request.urlopen(req, timeout=GARDEN_TIMEOUT) as resp:
            if resp.status != 200:
                _log_garden_flip("idle")
                return idle
            j = json.loads(resp.read().decode("utf-8"))
    except Exception:
        _log_garden_flip("idle")
        return idle
    if not isinstance(j, dict):
        _log_garden_flip("idle")
        return idle
    ts = j.get("ts")
    if ts is None:
        _log_garden_flip("idle")
        return idle
    try:
        if time.time() - float(ts) > GARDEN_STALE_SEC:
            _log_garden_flip("idle")
            return idle
    except (TypeError, ValueError):
        _log_garden_flip("idle")
        return idle
    live = {
        "garden": "live",
        "anchor_coherence": j.get("anchor_coherence"),
        "anchor_state": j.get("anchor_state", "idle"),
        "breath_sync": j.get("breath_sync"),
        "zone": j.get("zone"),
    }
    _log_garden_flip("live")
    return live


def sense_mesh():
    """网格:router 今日决策分布 + 最近一次扫描。"""
    out = {}
    f = ROUTER_DIR / ("router_%s.jsonl" % datetime.now().strftime("%Y-%m-%d"))
    if f.exists():
        dist = {}
        for l in f.read_text(encoding="utf-8").strip().splitlines():
            try:
                dist_k = json.loads(l).get("route", "?")
                dist[dist_k] = dist.get(dist_k, 0) + 1
            except Exception:
                pass
        if dist:
            out["routes"] = dist
    scans = []
    for kind in ("pool", "offpool"):
        sf = ROUTER_DIR / ("scan_%s.jsonl" % kind)
        if sf.exists():
            lines = sf.read_text(encoding="utf-8").strip().splitlines()
            if lines:
                try:
                    ts = _parse_iso(json.loads(lines[-1]).get("ts", ""))
                    if ts:
                        scans.append("%s %s" % (kind, _age_str(ts)))
                except Exception:
                    pass
    if scans:
        out["scans"] = scans
    return out or None


# ---------------------------------------------------------------- harness_events

_HARNESS_RING = []
_HARNESS_LOCK = threading.Lock()
_HARNESS_WS = os.environ.get("HARNESS_EVENTS_WS", "ws://127.0.0.1:8630/ws/events")


def _harness_token():
    for name in ("GRID_HARNESS_PAGE_TOKEN", "GRID_HARNESS_TOKEN"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    p = Path.home() / ".config" / "grid" / "harness_resident.env"
    if not p.is_file():
        return ""
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, val = s.split("=", 1)
        if k.strip() in ("GRID_HARNESS_PAGE_TOKEN", "GRID_HARNESS_TOKEN"):
            t = val.strip().strip('"').strip("'")
            if t:
                return t
    return ""


def _harness_push(line, ctx=""):
    line = str(line or "").strip()
    if not line:
        return
    with _HARNESS_LOCK:
        _HARNESS_RING.append({"context_hash": str(ctx or ""), "receipt_line": line})
        del _HARNESS_RING[:-5]


def _harness_block():
    with _HARNESS_LOCK:
        rows = list(_HARNESS_RING)
    if not rows:
        return ""
    out = ["[harness 此刻]"]
    for r in rows:
        out.append(r["receipt_line"])
    return "\n".join(out)


def _ws_recv_loop():
    import base64, struct, hashlib as _hl
    tok = _harness_token()
    if not tok:
        return
    url = urllib.parse.urlparse(_HARNESS_WS)
    host, port = url.hostname or "127.0.0.1", url.port or 80
    path = url.path or "/ws/events"
    q = "since=0&token=" + urllib.parse.quote(tok)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    req = (
        "GET %s?%s HTTP/1.1\r\nHost: %s:%s\r\nUpgrade: websocket\r\n"
        "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ) % (path, q, host, port, key)
    import socket
    while True:
        try:
            s = socket.create_connection((host, port), timeout=8)
            s.sendall(req.encode("ascii"))
            hdr = b""
            while b"\r\n\r\n" not in hdr:
                chunk = s.recv(4096)
                if not chunk:
                    raise OSError("closed")
                hdr += chunk
            s.settimeout(30)
            buf = hdr.split(b"\r\n\r\n", 1)[1]
            while True:
                while len(buf) < 2:
                    more = s.recv(4096)
                    if not more:
                        raise OSError("closed")
                    buf += more
                b1, b2 = buf[0], buf[1]
                ln = b2 & 0x7F
                off = 2
                if ln == 126:
                    while len(buf) < 4:
                        buf += s.recv(4096)
                    ln = struct.unpack(">H", buf[2:4])[0]
                    off = 4
                elif ln == 127:
                    while len(buf) < 10:
                        buf += s.recv(4096)
                    ln = struct.unpack(">Q", buf[2:10])[0]
                    off = 10
                while len(buf) < off + ln:
                    more = s.recv(4096)
                    if not more:
                        raise OSError("closed")
                    buf += more
                payload = buf[off:off + ln]
                buf = buf[off + ln:]
                if (b1 & 0x0F) == 0x1:
                    try:
                        ev = json.loads(payload.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    line = ""
                    ctx = ""
                    if isinstance(ev, dict):
                        pld = ev.get("payload") if isinstance(ev.get("payload"), dict) else ev
                        line = str(pld.get("receipt_line") or "")
                        ctx = str(pld.get("context_hash") or ev.get("context_hash") or "")
                        if not line and ev.get("kind") in ("receipt", "job_done", "job_result"):
                            line = json.dumps(ev, ensure_ascii=False)
                    if line:
                        _harness_push(line, ctx)
        except Exception:
            time.sleep(5)


def _start_harness_events():
    t = threading.Thread(target=_ws_recv_loop, name="harness_events", daemon=True)
    t.start()


# ---------------------------------------------------------------- 编译

def compile_now():
    now = datetime.now().astimezone()
    head = "「此刻」 %s 周%s %s(%s)" % (
        now.strftime("%Y-%m-%d"), WEEK[now.weekday()],
        now.strftime("%H:%M"), now.tzname() or "local")
    if in_quiet(now):                    # v1.3 Q1:静默期不读感官不编译
        return head + "\n夜间,场域静默。", {"ts": now.isoformat(),
                                            "quiet": True}
    lines = [head]
    data = {"ts": now.isoformat()}

    body = sense_body()
    if body:
        data["body"] = body
        if body["stale"]:
            lines.append("身体:无近信号(最后一条 %s)" % body["age"])
        else:
            seg = "身体:%s(信标 %s" % (
                ZH_MOTION.get(body["motion"], body["motion"]), body["age"])
            if body.get("speed") is not None:
                seg += ",%.1f m/s" % body["speed"]
            seg += ")"
            if body["hour_dist"]:
                seg += " 近一小时 " + "·".join(
                    "%s×%d" % (k, v) for k, v in body["hour_dist"].items())
            lines.append(seg)

    garden = sense_garden()
    if garden:
        data["garden"] = garden
        for k in ("garden", "anchor_coherence", "anchor_state", "breath_sync", "zone"):
            if k in garden:
                data[k] = garden[k]
        st = garden.get("anchor_state", "idle")
        ac = garden.get("anchor_coherence")
        if garden.get("garden") == "live" and st not in ("idle",) and ac is not None:
            seg = "声场:%s anchor %.2f" % (st, float(ac))
            bs = garden.get("breath_sync")
            if isinstance(bs, (int, float)):
                seg += " breath %.0f%%" % (float(bs) * 100)
            zn = garden.get("zone")
            if zn in ("green", "yellow", "red"):
                seg += " zone=%s" % zn
            lines.append(seg)
        elif garden.get("garden") == "live":
            lines.append("声场:静(%s)" % st)
        else:
            lines.append("声场:失联(idle)")

    mesh = sense_mesh()
    if mesh:
        data["mesh"] = mesh
        segs = []
        if "routes" in mesh:
            segs.append("router 今日 " + " ".join(
                "%s×%d" % (k, v) for k, v in mesh["routes"].items()))
        if "scans" in mesh:
            segs.append("扫描 " + ";".join(mesh["scans"]))
        lines.append("网格:" + ",".join(segs))

    text = "\n".join(lines)
    if len(text) > 600:
        text = text[:600]
    extra = _harness_block()
    if extra:
        text = text + "\n" + extra
    return text, data


def get_now():
    if time.time() - _cache["t"] > 30:
        _cache["text"], _cache["data"] = compile_now()
        _cache["t"] = time.time()
    return _cache["text"], _cache["data"]


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "FieldNow/1.6"

    def _send(self, code, body, ctype):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # 高频拉取不刷屏;留痕走 sentinel jsonl,不走 stderr

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        ip = self.client_address[0]
        if not sentinel_check(ip, p):
            return self._send(403, {"error": "not on allow list"},
                              "application/json; charset=utf-8")
        try:
            if p == "/sentinel":
                return self._send(200, sentinel_today(),
                                  "application/json; charset=utf-8")
            text, data = get_now()
            if p in ("/", "/now"):
                return self._send(200, text, "text/plain; charset=utf-8")
            if p == "/now.json":
                return self._send(200, {"text": text, **data},
                                  "application/json; charset=utf-8")
            return self._send(404, {"error": "not found"},
                              "application/json; charset=utf-8")
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)},
                              "application/json; charset=utf-8")


def main():
    warns = sentinel_harden()
    _start_harness_events()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print("场域编译器 v1.6 %s:%d" % (BIND, PORT))
    print("  信标 %s / 路由 %s" % (FIELD_DIR, ROUTER_DIR))
    print("  声场 %s" % GARDEN_URL)
    q = ("%02d:%02d-%02d:%02d" % (QUIET[0][0], QUIET[0][1],
                                  QUIET[1][0], QUIET[1][1])) if QUIET else "关闭"
    print("  哨兵:白名单 %s · 频率阈值 %d/60s · Bark %s · 静默 %s"
          % (ALLOW, RATE_MAX, "已接" if BARK_URL else "未设", q))
    for w in warns:
        print("  ⚠ 权限警告:%s" % w)
    text, _ = get_now()
    print("---- 当前编译 ----\n%s\n------------------" % text)
    print("gateway 注入:GET http://127.0.0.1:%d/now → 拼进 system 头部" % PORT)
    print("访问审计:GET http://127.0.0.1:%d/sentinel" % PORT)
    srv.serve_forever()


if __name__ == "__main__":
    main()
