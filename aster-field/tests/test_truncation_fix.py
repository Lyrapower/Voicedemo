import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.task_route import classify_task, max_tokens_for
from backend.json_artifact import parse_json_artifact

def test_classify_handoff():
    assert classify_task("Run handoff_protocol and output valid JSON") == "handoff_protocol"

def test_classify_compile_json():
    assert classify_task("compile_json schema for round pack") == "compile_json"

def test_classify_chat_default():
    assert classify_task("你好") == "chat"
    assert max_tokens_for("chat") == 400
    assert max_tokens_for("handoff_protocol") == 4096

def test_parse_complete_json():
    r = parse_json_artifact('{"status":"PASS","round_id":"r1"}')
    assert r["ok"] and r["merged_json_valid"]

def test_parse_incomplete_json():
    r = parse_json_artifact('{"status":"PASS",')
    assert not r["ok"] and r["status"] == "INCOMPLETE_ARTIFACT"

def test_parse_fenced_json():
    raw = 'note\n```json\n{"a":1}\n```'
    assert parse_json_artifact(raw)["ok"]
