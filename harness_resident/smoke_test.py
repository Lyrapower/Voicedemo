from __future__ import annotations
import tempfile
from pathlib import Path
from harness.db import Store
from harness.supervisor import Supervisor

def main():
    with tempfile.TemporaryDirectory() as td:
        s=Store(str(Path(td)/"test.db"))

        sess=s.create_session(agent_id="qwen-main",channel="grid",title="Qwen Resident")
        assert sess["state"]=="idle"
        m=s.append_message(sess["session_id"],"user","hello")
        assert s.list_messages(sess["session_id"])[0]["content"]=="hello"

        j=s.create_job(channel="grid",goal="smoke",worker="qwen",
            allowed_tools=["read"],allowed_paths=["."],
            cloud_allowed=False,approval_mode="no_deploy")
        s.bind_job_to_session(sess["session_id"],j["job_id"])

        claimed=s.claim_next_queued()
        assert claimed["job_id"]==j["job_id"]
        assert claimed["status"]=="running"
        assert s.claim_next_queued() is None

        s.append_stream_event(session_id=sess["session_id"],job_id=j["job_id"],
                              kind="agent_delta",payload={"text":"x"})
        events=s.list_stream_events(after_seq=0)
        assert any(e["kind"]=="agent_delta" for e in events)
        last=max(e["seq"] for e in events)
        assert s.list_stream_events(after_seq=last)==[]

        assert s.mark_running_interrupted()==1
        assert s.requeue_interrupted(2)==1
        assert s.get_job(j["job_id"])["status"]=="queued"

        assert Supervisor._parse_escalation(
            '{"action":"escalate","target":"glm","reason":"x"}'
        )["target"]=="glm"
        assert Supervisor._parse_escalation("normal text") is None

    print("SMOKE V1.2 PASS")

if __name__=="__main__":
    main()
