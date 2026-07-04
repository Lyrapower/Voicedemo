from __future__ import annotations
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Set
import yaml

LOG = Path("logs/egress_audit.log")
POLICY = Path("config/egress_policy.yaml")

def _utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def load_allowlist() -> Set[str]:
    if not POLICY.exists():
        return set()
    cfg = yaml.safe_load(POLICY.read_text(encoding="utf-8")) or {}
    doms = cfg.get("egress", {}).get("allow_domains", []) or []
    return {d.strip().lower() for d in doms if str(d).strip()}

def log_attempt(domain: str, allowed: bool):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": _utc(), "domain": domain, "allowed": allowed}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# V1 hook: use this wrapper for any outbound resolution attempt
def resolve(domain: str) -> str:
    allow = load_allowlist()
    d = domain.strip().lower()
    allowed = (d in allow) or any(d.endswith("." + x) for x in allow if "." in x)
    log_attempt(d, allowed)
    # log_only mode: still resolves, but we have audit trail + alerting surface
    return socket.gethostbyname(domain)
