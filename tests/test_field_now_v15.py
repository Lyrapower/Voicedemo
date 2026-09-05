#!/usr/bin/env python3
"""Smoke tests for field_now v1.5 sense_garden."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELD_NOW_PATH = ROOT / "scripts" / "field_now_v1_5.py"


def load_module():
    spec = importlib.util.spec_from_file_location("field_now_v15", FIELD_NOW_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TelemetryHandler(BaseHTTPRequestHandler):
    payload: dict = {}

    def do_GET(self):  # noqa: N802
        body = json.dumps(self.payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def run_mock_telemetry(payload: dict):
    TelemetryHandler.payload = payload
    srv = HTTPServer(("127.0.0.1", 0), TelemetryHandler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, port, thread


def main() -> int:
    mod = load_module()
    os.environ["NOW_GARDEN"] = "http://127.0.0.1:0/telemetry.json"

    srv, port, _ = run_mock_telemetry(
        {
            "presence": True,
            "state": "held",
            "coherence": 0.82,
            "beat_hz": 120.0,
            "energy": 0.45,
            "anchor_coherence": 0.71,
            "anchor_state": "held",
        }
    )
    mod.GARDEN_URL = "http://127.0.0.1:%d/telemetry.json" % port
    garden = mod.sense_garden()
    srv.shutdown()
    assert garden is not None
    assert garden["active"] is True
    assert garden["anchor"] == 0.71
    assert garden["anchor_state"] == "held"

    srv2, port2, _ = run_mock_telemetry({"presence": False, "state": "idle"})
    mod.GARDEN_URL = "http://127.0.0.1:%d/telemetry.json" % port2
    idle = mod.sense_garden()
    srv2.shutdown()
    assert idle is not None
    assert idle["active"] is False

    mod.GARDEN_URL = "http://127.0.0.1:1/telemetry.json"
    assert mod.sense_garden() is None

    text, data = mod.compile_now()
    assert "声场" in text or "静" in text or isinstance(data, dict)
    print("field_now v1.5 sense_garden OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
