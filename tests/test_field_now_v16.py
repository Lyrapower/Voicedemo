#!/usr/bin/env python3
"""Smoke tests for field_now v1.6 sense_garden (FIELD_SENSE_PIPELINE step 2)."""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELD_NOW_PATH = ROOT / "scripts" / "field_now_v1_6.py"


def _load():
    spec = importlib.util.spec_from_file_location("field_now_v16", FIELD_NOW_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _GardenHandler(BaseHTTPRequestHandler):
    payload: dict = {"ts": time.time(), "anchor_coherence": 0.62,
                     "anchor_state": "held", "breath_sync": 0.7, "zone": "yellow"}

    def do_GET(self):
        body = json.dumps(self.payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def test_sense_garden_live_and_stale():
    mod = _load()
    srv = HTTPServer(("127.0.0.1", 0), _GardenHandler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    mod.GARDEN_URL = f"http://127.0.0.1:{port}/telemetry.json"
    mod._garden_live_prev = None
    live = mod.sense_garden()
    assert live["garden"] == "live"
    assert live["anchor_state"] == "held"
    assert live["zone"] == "yellow"
    _GardenHandler.payload["ts"] = time.time() - 4000
    stale = mod.sense_garden()
    assert stale["garden"] == "idle"
    srv.shutdown()


def test_sense_garden_fail_soft():
    mod = _load()
    mod.GARDEN_URL = "http://127.0.0.1:1/telemetry.json"
    mod._garden_live_prev = None
    idle = mod.sense_garden()
    assert idle["garden"] == "idle"
    assert idle["anchor_state"] == "idle"


if __name__ == "__main__":
    test_sense_garden_live_and_stale()
    test_sense_garden_fail_soft()
    print("field_now v1.6 sense_garden OK")
