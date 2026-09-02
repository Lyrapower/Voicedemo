
from fastapi.testclient import TestClient
import harness.api as api

with TestClient(api.app) as c:
    r=c.get("/")
    assert r.status_code==200
    r=c.get("/sessions")
    assert r.status_code==200
    sessions=r.json()
    ids={x["agent_id"] for x in sessions}
    assert {"qwen-main","cc-main","glm-on-demand","kimi-on-demand"} <= ids

    q=next(x for x in sessions if x["agent_id"]=="qwen-main")
    sid=q["session_id"]
    r=c.post(f"/sessions/{sid}/message",json={"text":"hello durable thread","spawn_job":False})
    assert r.status_code==200
    r=c.get(f"/sessions/{sid}")
    assert any(m["content"]=="hello durable thread" for m in r.json()["messages"])

    r=c.get("/events?after_seq=0")
    assert r.status_code==200 and len(r.json())>0

    r=c.post(f"/sessions/{sid}/pause",json={})
    assert r.status_code==200 and r.json()["state"]=="paused"
    r=c.post(f"/sessions/{sid}/resume",json={})
    assert r.status_code==200 and r.json()["state"] in {"idle","running"}

print("FASTAPI CONTROL PASS")
