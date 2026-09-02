from __future__ import annotations
import time
from typing import Any
from .db import Store

DEFAULT_AGENT_SESSIONS = {
    "local-main":"Local Resident",
    "cc-main":"Claude Code",
    "fast-on-demand":"Fast · on demand",
    "deep-on-demand":"Deep · on demand",
    "full-on-demand":"Full · on demand",
    "research-on-demand":"Research · on demand",
}

class SessionManager:
    def __init__(self, store: Store):
        self.store=store

    def ensure_resident_sessions(self):
        existing={s["agent_id"]:s for s in self.store.list_sessions(1000)}
        out=[]
        for agent_id,title in DEFAULT_AGENT_SESSIONS.items():
            out.append(existing.get(agent_id) or self.store.create_session(
                agent_id=agent_id, channel="agents", title=title))
        return out

    def create(self, agent_id: str, channel="grid", title=""):
        return self.store.create_session(agent_id=agent_id,channel=channel,title=title)

    def heartbeat(self, session_id: str, *, state=None, active_job_id=None, waiting_for=None):
        fields={"last_heartbeat":time.time()}
        if state is not None: fields["state"]=state
        if active_job_id is not None: fields["active_job_id"]=active_job_id
        if waiting_for is not None: fields["waiting_for"]=waiting_for
        return self.store.update_session(session_id,**fields)

    def mark_stale(self, stale_after=45.0, interrupted_after=180.0):
        now=time.time(); changed=[]
        for s in self.store.list_sessions(1000):
            hb=s.get("last_heartbeat")
            if not hb or s["state"] in {"idle","done","failed","cancelled"}:
                continue
            age=now-hb
            target=None
            if age>interrupted_after: target="interrupted"
            elif age>stale_after: target="stale"
            if target and target!=s["state"]:
                self.store.update_session(s["session_id"],state=target)
                self.store.append_stream_event(session_id=s["session_id"],job_id=s.get("active_job_id"),
                                               kind="session_state",payload={"state":target,"age":age})
                changed.append((s["session_id"],target))
        return changed
