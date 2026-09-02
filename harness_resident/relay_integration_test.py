
import os
os.environ["GRID_RELAY_TOKEN"]="test-token"
from fastapi.testclient import TestClient
import relay_server

with TestClient(relay_server.app) as c:
    with c.websocket_connect("/ws/agent",headers={"authorization":"Bearer test-token"}) as agent:
        agent.send_json({"type":"hello","device_id":"grid-mac"})
        with c.websocket_connect("/ws/client") as phone:
            phone.send_json({"token":"test-token","device_id":"grid-mac"})
            ready=phone.receive_json()
            assert ready["type"]=="client_ready" and ready["online"] is True
            agent.send_json({"type":"event","device_id":"grid-mac","event":{"seq":7,"kind":"agent_delta","payload":{"text":"hi"}}})
            evt=phone.receive_json()
            assert evt["type"]=="event" and evt["event"]["seq"]==7
print("RELAY LIVE EVENT PASS")
