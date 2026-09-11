"""期权影子权利金账。数据源=Theta Terminal v3 REST(本机)。零第三方依赖。
PKG v5 核心 + 晚班 job:读 briefs,落 ledgers/option_shadow/<date>.json,收据进 harness-shared。"""
from __future__ import annotations
import json, hashlib, os, re, socket, urllib.request, urllib.parse
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
ET=ZoneInfo("America/New_York"); PT=ZoneInfo("America/Los_Angeles")
COMMISSION_PER_CONTRACT=0.65

THETA_BASE = os.getenv("THETA_BASE", "http://127.0.0.1:25503").rstrip("/")
BRIEFS = Path(os.getenv("SCOUT_BRIEFS", str(Path(__file__).resolve().parents[2] / "grid-scout" / "briefs")))
LEDGER_ROOT = Path(os.getenv("OPTION_SHADOW_LEDGER", str(Path(__file__).resolve().parents[1] / "ledgers" / "option_shadow")))


def pt_to_et_minute(d: date, hhmm: str) -> str:
    """'06:45' PT on date d → 'HH:MM:00.000' ET. 非整分输入直接拒。"""
    hh,mm=hhmm.split(":")
    if len(hhmm.split(":"))!=2: raise ValueError("minute boundary only")
    t=datetime(d.year,d.month,d.day,int(hh),int(mm),tzinfo=PT).astimezone(ET)
    return t.strftime("%H:%M:00.000")

def mid(q):
    b,a=float(q.get("bid",0) or 0),float(q.get("ask",0) or 0)
    if b<=0 or a<=0: return None, None
    return (a+b)/2, (a-b)

def settle(mid_in, spr_in, mid_out, spr_out, contracts=1):
    gross=(mid_out-mid_in)*100*contracts
    comm=COMMISSION_PER_CONTRACT*2*contracts
    slip=(spr_in/2+spr_out/2)*100*contracts
    return {"gross":round(gross,2),"commission":round(comm,2),"slippage":round(slip,2),"net":round(gross-comm-slip,2)}

def _coerce_rows(raw):
    """Theta v3 wraps lists in {response:[...]} and at_time rows as {contract,data}."""
    if isinstance(raw, dict) and "response" in raw:
        raw = raw["response"]
    if not isinstance(raw, list):
        return []
    out = []
    for r in raw:
        if isinstance(r, dict) and "contract" in r:
            c = r.get("contract") or {}
            bars = r.get("data") or [{}]
            b = bars[0] if bars else {}
            out.append({**c, **b, "strike": c.get("strike"), "bid": b.get("bid"), "ask": b.get("ask")})
        else:
            out.append(r)
    return out


class Theta:
    def __init__(self, base=None, opener=None):
        self.base=base or THETA_BASE; self.open=opener or (lambda u: urllib.request.urlopen(u,timeout=30).read().decode())
        self.log=[]
    def get(self, path, **params):
        url=f"{self.base}{path}?"+urllib.parse.urlencode({**params,"format":"json"})
        body=self.open(url); self.log.append({"url":url,"sha256":hashlib.sha256(body.encode()).hexdigest()})
        return _coerce_rows(json.loads(body) if body.strip() else [])
    def expirations(self, symbol): return [r["expiration"] if isinstance(r,dict) else r for r in self.get("/v3/option/list/expirations", symbol=symbol)]
    def at_time_quote(self, symbol, expiration, right, d: date, tod_et):
        if not tod_et.endswith(":00.000"): raise ValueError("time_of_day must be minute boundary")
        return self.get("/v3/option/at_time/quote", symbol=symbol, expiration=expiration, right=right,
                        strike_range=1, start_date=d.strftime("%Y%m%d"), end_date=d.strftime("%Y%m%d"), time_of_day=tod_et)

def settle_leg(theta: Theta, leg: dict, d: date):
    """leg: {ticker, direction(call|put), entry_window_pst:'HH:MM-HH:MM', exit_window_pst:'HH:MM-HH:MM'}"""
    t_in=leg["entry_window_pst"].split("-")[0]; t_out=leg["exit_window_pst"].split("-")[1]
    if t_out<=t_in: return {"leg":leg,"status":"rejected:exit_before_entry"}
    exps=theta.expirations(leg["ticker"])
    if not exps: return {"leg":leg,"status":"unsettled:no_chain"}
    exp=sorted(e for e in exps if str(e).replace("-","")>=d.strftime("%Y%m%d"))
    if not exp: return {"leg":leg,"status":"unsettled:no_expiration"}
    exp=exp[0]
    q_in=theta.at_time_quote(leg["ticker"],exp,leg["direction"],d,pt_to_et_minute(d,t_in))
    if not q_in: return {"leg":leg,"status":"unsettled:no_quote"}
    row=sorted(q_in,key=lambda r: float(r["strike"]))[len(q_in)//2]
    q_out=[r for r in theta.at_time_quote(leg["ticker"],exp,leg["direction"],d,pt_to_et_minute(d,t_out)) if float(r["strike"])==float(row["strike"])]
    m_in,s_in=mid(row); m_out,s_out=mid(q_out[0]) if q_out else (None,None)
    if m_in is None or m_out is None: return {"leg":leg,"status":"unsettled:no_quote","strike":row["strike"],"expiration":exp}
    return {"leg":leg,"status":"settled","strike":row["strike"],"expiration":exp,"mid_in":m_in,"mid_out":m_out,**settle(m_in,s_in,m_out,s_out)}


def _clean_window(s: str) -> str:
    m = re.search(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", s or "")
    if not m:
        return ""
    a, b = m.group(1), m.group(2)
    def pad(x):
        h, mm = x.split(":")
        return "%02d:%02d" % (int(h), int(mm))
    return "%s-%s" % (pad(a), pad(b))


def extract_legs(brief: dict) -> list[dict]:
    legs = []
    cands = brief.get("candidates") or (brief.get("ds") or {}).get("candidates") or []
    for c in cands:
        if c.get("empty"):
            continue
        st = c.get("strategy") or {}
        if c.get("ticker"):
            legs.append({
                "ticker": c["ticker"],
                "direction": (c.get("direction") or "call").lower(),
                "entry_window_pst": _clean_window(st.get("entry_window_pst") or c.get("entry_window_pst") or ""),
                "exit_window_pst": _clean_window(st.get("exit_window_pst") or c.get("exit_window_pst") or ""),
                "source": "candidate",
            })
    for L in ((brief.get("hedge") or {}).get("legs") or []):
        if L.get("ticker"):
            legs.append({
                "ticker": L["ticker"],
                "direction": (L.get("direction") or "put").lower(),
                "entry_window_pst": _clean_window(L.get("entry_window_pst") or ""),
                "exit_window_pst": _clean_window(L.get("exit_window_pst") or ""),
                "source": "hedge",
            })
    return legs


def theta_up(port: int | None = None) -> bool:
    if port is None:
        try:
            port = int(urllib.parse.urlsplit(THETA_BASE).port or 25503)
        except Exception:
            port = 25503
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _brief_src(brief: dict) -> dict:
    if isinstance(brief.get("ds"), dict) and brief["ds"].get("candidates"):
        return brief["ds"]
    if brief.get("candidates"):
        return brief
    for v in brief.values():
        if isinstance(v, dict) and v.get("candidates"):
            return v
    return brief


def run(date_s: str, brief_path: Path | None = None, *, write_shared: bool = False, opener=None) -> dict:
    d = date.fromisoformat(date_s)
    if not theta_up() and opener is None:
        rec = {"kind": "theta_down", "date": date_s}
        if write_shared:
            _shared("theta_down", rec)
        return rec
    path = brief_path or (BRIEFS / f"{date_s}-morning.json")
    brief = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    legs_in = extract_legs(_brief_src(brief if isinstance(brief, dict) else {}))
    th = Theta(opener=opener) if opener is not None else Theta()
    settled = []
    for L in legs_in:
        if not L.get("entry_window_pst") or not L.get("exit_window_pst"):
            settled.append({"leg": L, "status": "unsettled:no_window"})
            continue
        try:
            settled.append(settle_leg(th, L, d))
        except Exception as e:
            settled.append({"leg": L, "status": "unsettled:http", "error": str(e)[:160]})
    n_unsettled = sum(1 for x in settled if str(x.get("status") or "").startswith("unsettled") or str(x.get("status") or "").startswith("rejected"))
    total = sum(float(x["net"]) for x in settled if x.get("status") == "settled")
    doc = {
        "date": date_s,
        "n_legs": len(settled),
        "n_unsettled": n_unsettled,
        "total_pnl": total,
        "legs": settled,
        "theta_log": th.log,
    }
    LEDGER_ROOT.mkdir(parents=True, exist_ok=True)
    outp = LEDGER_ROOT / f"{date_s}.json"
    outp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    doc["path"] = str(outp)
    if write_shared:
        _shared("option.shadow_ledger", {
            "date": date_s, "n_legs": doc["n_legs"], "total_pnl": total, "n_unsettled": n_unsettled,
        })
    return doc


def _shared(kind: str, rec: dict) -> None:
    try:
        from harness.config import load_config
        from harness.db import Store
        from harness.memory_bridge import MemoryBridge
        cfg = load_config()
        mb = MemoryBridge(Store(cfg.core.db_path))
        mb.offer({
            "receipt_id": f"{kind}:{rec.get('date') or rec.get('kind')}",
            "event_id": f"{kind}:{rec.get('date') or rec.get('kind')}",
            "mid": kind,
            "result": json.dumps(rec, ensure_ascii=False),
            "status": kind,
            "ts": datetime.now(PT).timestamp(),
        }, kind="工作日志")
    except Exception:
        pass
