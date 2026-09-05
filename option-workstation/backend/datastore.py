"""datastore.py —— 快照存取 + 合成数据生成 + 供应商 loader 桩。
raw 不可变(每日一 json);合成器造 120 日 SPY 链并故意注入脏行,
供清洗/隔离/回放全链演示;买断数据到位后 loader 一换即实弹。
"""
from __future__ import annotations
import json, math, os, random

DATA_DIR = os.getenv("OWS_DATA", "/data/ows")
RAW = os.path.join(DATA_DIR, "raw")
DEFAULT_ROOT = "SPY"


def _root_dir(root: str | None) -> str:
    return os.path.join(RAW, root or DEFAULT_ROOT)


def _ensure(root: str | None = None):
    os.makedirs(_root_dir(root), exist_ok=True)


def list_roots() -> list[str]:
    _ensure()
    return sorted(
        sub for sub in os.listdir(RAW)
        if os.path.isdir(os.path.join(RAW, sub))
    )


def list_dates(root: str | None = None):
    # root 指定 → 列该标的;None → 列所有标的子目录的并集(向后兼容旧 flat 布局)
    if root:
        d = _root_dir(root)
        if not os.path.isdir(d):
            return []
        return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))
    _ensure()
    dates: set[str] = set()
    for sub in os.listdir(RAW):
        p = os.path.join(RAW, sub)
        if os.path.isdir(p):
            for f in os.listdir(p):
                if f.endswith(".json"):
                    dates.add(f[:-5])
    return sorted(dates)


def load_raw(date, root: str | None = None):
    # 优先 root 子目录;回退旧 flat 布局(向后兼容)
    if root:
        p = os.path.join(_root_dir(root), date + ".json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    p_flat = os.path.join(RAW, date + ".json")
    if os.path.exists(p_flat):
        with open(p_flat, encoding="utf-8") as f:
            return json.load(f)
    raise FileNotFoundError(date)


def save_raw(date, snap, root: str | None = None):
    root = root or (snap.get("underlying") if isinstance(snap, dict) else None) or DEFAULT_ROOT
    _ensure(root)
    p = os.path.join(_root_dir(root), date + ".json")
    if os.path.exists(p):          # raw 不可变
        raise RuntimeError("raw 已存在,拒绝覆盖: " + root + " " + date)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)


def gen_synthetic(days=120, seed=7, underlying="SPY"):
    """GBM 价格路径 + 波动率 regime 正弦;每日 3 个到期(7/30/60d),
    每到期 15 行权价;报价 = BS mid ± spread;注入脏行:
    crossed(~1%)、零 bid 翼、陈旧行(~1%)、一条非标合约/日。"""
    from engine import bs_price
    rng = random.Random(seed)
    _ensure()
    S = 500.0; r, q = 0.04, 0.012
    hist = []
    for i in range(days):
        date = "2026-%02d-%02d" % (1 + i // 28, 1 + i % 28)
        vol_regime = 0.14 + 0.10 * (0.5 + 0.5 * math.sin(i / 11.0)) + rng.uniform(-0.01, 0.01)
        S *= math.exp((0.05 - 0.5 * vol_regime ** 2) / 252 + vol_regime * math.sqrt(1 / 252) * rng.gauss(0, 1))
        hist.append(S)
        expiries = []
        for dte in (7, 30, 60):
            T = dte / 365.0
            atm = round(S / 5) * 5
            strikes = []
            for k in range(-7, 8):
                K = atm + 5 * k
                m = math.log(K / S)
                iv = vol_regime + 0.15 * m * m - 0.06 * m        # 微笑+偏度
                iv = max(0.05, iv)
                row = {"K": K}
                for is_call, name in ((True, "call"), (False, "put")):
                    mid = bs_price(S, K, T, r, q, iv, is_call)
                    spr = max(0.02, mid * (0.01 + 0.03 * abs(m) * 4))
                    bid = max(0.0, mid - spr / 2); ask = mid + spr / 2
                    if abs(k) >= 6 and rng.random() < 0.5:
                        bid = 0.0                                 # 零 bid 翼
                    if rng.random() < 0.01:
                        bid, ask = ask, bid                       # crossed 脏行
                    stale = rng.random() < 0.01
                    row[name] = {"bid": round(bid, 2), "ask": round(ask, 2),
                                 "oi": int(rng.uniform(50, 5000) * math.exp(-abs(k) / 3)),
                                 "quote_age_s": (900 if stale else rng.randint(0, 60))}
                strikes.append(row)
            # 非标合约(乘数≠100)——必须被隔离
            strikes.append({"K": atm, "nonstandard": True, "multiplier": 40,
                            "call": {"bid": 1.0, "ask": 1.4, "oi": 10, "quote_age_s": 5},
                            "put": {"bid": 1.0, "ask": 1.4, "oi": 10, "quote_age_s": 5}})
            expiries.append({"dte": dte, "T": T, "strikes": strikes})
        save_raw(date, {"date": date, "underlying": underlying, "spot": round(S, 2),
                        "r": r, "q": q, "hist_tail": [round(x, 2) for x in hist[-21:]],
                        "expiries": expiries, "source": "synthetic-v1", "ts": date + "T16:00:00-05:00"})
    return len(list_dates())

# —— 供应商 loader 桩(买断数据到位后填实)——
# databento OPRA / HistoricalOptionData CSV → 归一到上述快照结构,
# 保持 raw 不可变纪律;字段映射见 README。
