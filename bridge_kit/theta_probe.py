"""theta_probe — 戌问题 3:option.shadow 回 `unsettled:http_472`。

事实(2026-09-10 查 docs.thetadata.us v3 官方文档,非记忆):
- 25503 = Theta Terminal **v3**(v2 是 25510)。戌 docker ps 看到的 127.0.0.1:25503 就是 v3。
- 错误码:472 = NO_DATA "no data found for the specified request";471 权限;473 参数语法;474 断线。
- v3 路径:/v3/option/list/expirations?symbol=  /v3/option/list/strikes?symbol=&expiration=
  /v3/option/snapshot/quote?symbol=&expiration=&strike=&right=  /v3/terminal/mdds/status
- v3 参数:expiration YYYYMMDD 或 YYYY-MM-DD;strike 以美元写(270.000);right = call|put|both。
  (v2 的 strike 是 1/10 美分 140000 — 若 v6 影子账按 v2 口径拼 strike 打 v3,就是 472 的一种来源。)
- 快照端点官方原话:market closed for the day 返回 no data;snapshot cache 每晚 **midnight ET** 重置。
  戌本窗 8630 进程 19:35 PDT 起,job 若在 21:00 PDT(=00:00 ET)之后跑,快照就是空的 → 472。

- 结算口径(Astra v4.1 R08,对官方 at_time 页核):影子账某分钟的结算价 = 原市场日、原合约的
  /v3/option/at_time/quote?symbol=&expiration=&strike=&right=&start_date=D&end_date=D&time_of_day=HH:mm:ss.SSS(ET)。
  迟到就晚点重取同一历史日;**不用**次日 snapshot、不用 EOD 顶替指定分钟。本模块只分类 472 的来源,不结算。

用法:classify_472(symbol, expiration, strike, right, http_get) 逐级排除,返回 dict(verdict, evidence)。
http_get(url) -> (status_code:int, body:str) 可注入;__main__ 打真 Terminal(现场自证,沙箱够不着)。
零依赖,3.9 语法。
"""
import json
import re
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

BASE = "http://127.0.0.1:25503/v3"
EP_MDDS = BASE + "/terminal/mdds/status"
EP_EXPS = BASE + "/option/list/expirations?symbol={symbol}&format=json"
EP_STRIKES = BASE + "/option/list/strikes?symbol={symbol}&expiration={exp}&format=json"
EP_QUOTE = BASE + "/option/snapshot/quote?symbol={symbol}&expiration={exp}&strike={strike}&right={right}&format=json"
EP_AT_TIME = BASE + "/option/at_time/quote?symbol={symbol}&expiration={exp}&strike={strike}&right={right}&start_date={day}&end_date={day}&time_of_day={hms}&format=json"

ERROR_CODES = {
    200: "OK", 404: "NO_IMPL", 429: "OS_LIMIT", 470: "GENERAL", 471: "PERMISSION",
    472: "NO_DATA", 473: "INVALID_PARAMS", 474: "DISCONNECTED", 475: "TERMINAL_PARSE",
    476: "WRONG_IP", 477: "NO_PAGE_FOUND", 478: "INVALID_SESSION_ID",
    570: "LARGE_REQUEST", 571: "SERVER_STARTING", 572: "UNCAUGHT_ERROR",
}

_DATE8 = re.compile(r"\b(\d{4})-?(\d{2})-?(\d{2})\b")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def norm_exp(s):
    m = _DATE8.search(str(s))
    if not m:
        raise ValueError("bad expiration %r" % (s,))
    return "".join(m.groups())


def fmt_strike(x):
    """v3 口径:美元,三位小数。传 1/10 美分整数(v2 口径,>= 1000 且无小数)会被拒,不静默换算。"""
    s = str(x).strip()
    if re.fullmatch(r"\d{5,}", s):
        raise ValueError("strike %r looks like v2 tenth-of-cent integer; v3 wants dollars e.g. 270.000" % s)
    return "%.3f" % float(s)


def _extract_dates(body):
    return set("".join(m) for m in _DATE8.findall(body or ""))


def _extract_strikes(body):
    out = set()
    for tok in _NUM.findall(body or ""):
        try:
            out.add(round(float(tok), 3))
        except ValueError:
            pass
    return out


def et_clock(now_utc=None):
    if ZoneInfo is None:
        return None
    tz = ZoneInfo("America/New_York")
    dt = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    return dt


def snapshot_window_open(dt_et):
    """RTH 内且工作日 → True。周末 / 09:30 前 / 16:00 后 → False。节假日本函数不知道,留给 evidence。"""
    if dt_et.weekday() >= 5:
        return False
    hm = dt_et.hour * 60 + dt_et.minute
    return 9 * 60 + 30 <= hm <= 16 * 60


def classify_472(symbol, expiration, strike, right, http_get, now_utc=None):
    ev = {}
    exp = norm_exp(expiration)
    try:
        stk = fmt_strike(strike)
    except ValueError as e:
        return {"verdict": "PARAM_STRIKE_FORMAT_V2", "evidence": {"error": str(e)}}

    code, body = http_get(EP_MDDS)
    ev["mdds"] = (code, (body or "").strip()[:40])
    if code != 200 or "CONNECTED" not in (body or "").upper() or "DISCONNECTED" in (body or "").upper():
        return {"verdict": "TERMINAL_NOT_CONNECTED", "evidence": ev}

    code, body = http_get(EP_EXPS.format(symbol=symbol))
    ev["expirations"] = (code, ERROR_CODES.get(code, "?"))
    if code != 200:
        return {"verdict": "LIST_EXPIRATIONS_FAILED", "evidence": ev}
    if exp not in _extract_dates(body):
        ev["exp_wanted"] = exp
        return {"verdict": "PARAM_EXPIRATION_NOT_LISTED", "evidence": ev}

    code, body = http_get(EP_STRIKES.format(symbol=symbol, exp=exp))
    ev["strikes"] = (code, ERROR_CODES.get(code, "?"))
    if code != 200:
        return {"verdict": "LIST_STRIKES_FAILED", "evidence": ev}
    if round(float(stk), 3) not in _extract_strikes(body):
        ev["strike_wanted"] = stk
        return {"verdict": "PARAM_STRIKE_NOT_LISTED", "evidence": ev}

    code, body = http_get(EP_QUOTE.format(symbol=symbol, exp=exp, strike=stk, right=right))
    ev["quote"] = (code, ERROR_CODES.get(code, "?"))
    if code == 200:
        return {"verdict": "QUOTE_OK_NOW", "evidence": ev}
    if code != 472:
        return {"verdict": "QUOTE_%s" % ERROR_CODES.get(code, str(code)), "evidence": ev}

    dt = et_clock(now_utc)
    if dt is not None:
        ev["now_et"] = dt.isoformat()
        if not snapshot_window_open(dt):
            return {"verdict": "TIME_WINDOW_SNAPSHOT_EMPTY",
                    "evidence": ev,
                    "note": "official: snapshot returns no data when market closed; cache resets midnight ET. "
                            "settle from at_time/quote on the original day, not next-day snapshot"}
    return {"verdict": "NO_DATA_IN_RTH_UNEXPLAINED", "evidence": ev,
            "note": "contract listed, terminal connected, RTH open, still 472 — escalate with exact URL"}


def _real_http_get(url, timeout=10.0):
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError, URLError
    try:
        with urlopen(Request(url), timeout=timeout) as r:
            return r.getcode(), r.read().decode("utf-8", "replace")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except URLError as e:
        return 0, str(e)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 5:
        print("usage: theta_probe.py SYMBOL EXPIRATION(YYYYMMDD) STRIKE(dollars) RIGHT(call|put)")
        sys.exit(2)
    res = classify_472(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], _real_http_get)
    print(json.dumps(res, ensure_ascii=False, default=str))
