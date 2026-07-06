import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.relay import derive_event, coherence_proxy

D = lambda **kw: {"choices": [{"delta": kw}]}
F = lambda r: {"choices": [{"delta": {}, "finish_reason": r}]}

def run(chunks):
    state, states, text, finish = "thinking", ["thinking"], [], None
    for c in chunks:
        ev = derive_event(c, state)
        finish = ev["finish"] or finish
        if ev["state"] != state:
            state = ev["state"]; states.append(state)
        if ev["token"]:
            text.append(ev["token"])
    return states, "".join(text), finish

def test_standard_flow():
    s, txt, fin = run([D(reasoning_content="x")]*5 + [D(content="露"), D(content="水"), F("stop")])
    assert s == ["thinking", "output"] and txt == "露水" and fin == "stop"

def test_tool_call_inserts_working():
    s, _, _ = run([D(reasoning_content="x"), D(tool_calls=[{}]), D(content="ok"), F("stop")])
    assert s == ["thinking", "working", "output"]

def test_truncated_empty_lowers_coherence():
    s, txt, fin = run([D(reasoning_content="x")]*10 + [F("length")])
    assert txt == "" and coherence_proxy(fin, bool(txt), 5) == 0.50

def test_truncated_with_text_not_semantic_failure():
    s, txt, fin = run([D(content="partial"), F("length")])
    assert txt == "partial" and coherence_proxy(fin, bool(txt), 5) >= 0.75

def test_pure_output():
    s, txt, _ = run([D(content="hi"), F("stop")])
    assert s == ["thinking", "output"] and txt == "hi"

def test_garden_coherence_priority():
    assert coherence_proxy("stop", True, 5, garden_coh=0.61) == 0.61
