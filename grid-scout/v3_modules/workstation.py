"""模块④ · Option Workstation :8620 读数照抄。"""
from __future__ import annotations
import os
from .http_util import http_get_json

OWS = os.getenv("OWS_URL", "http://localhost:8620").rstrip("/")


def fetch_workstation() -> dict:
    try:
        dates = http_get_json(OWS + "/api/dates", timeout=5)
        if not dates:
            return {"ok": False, "error": "dates empty", "items": {}}
        latest = dates[-1]
        d = http_get_json(OWS + "/api/day/" + latest, timeout=10)
        snap = d.get("snap") or {}
        gex = d.get("gex") or {}
        feat = d.get("features") or {}
        source = snap.get("source") or "unknown"
        # O7: reject synthetic snapshots outright (consistent with scout_agent.py:65-67),
        # not just flag them. Previously the battle card ④ rendered fake GEX/IVP with
        # only a markdown disclaimer — now return ok=False so the caller blocks it.
        if "synthetic" in str(source).lower():
            return {"ok": False, "error": f"workstation 仅合成演示数据({source})——不作数,不喂 battle card", "items": {}}
        items = {
            "date": latest,
            "underlying": snap.get("underlying"),
            "spot": snap.get("spot"),
            "net_gex": gex.get("net_gex_musd_per_1pct"),
            "gamma_flip": gex.get("gamma_flip"),
            "ivp": feat.get("ivp"),
            "ivr": feat.get("ivr"),
            "vrp20": feat.get("vrp20"),
            "atm_iv30": feat.get("atm_iv30"),
            "source": source,
            "data_stale": False,
            "data_source": source,
            "chain": d.get("chain") or [],
        }
        return {"ok": True, "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300], "items": {}}
