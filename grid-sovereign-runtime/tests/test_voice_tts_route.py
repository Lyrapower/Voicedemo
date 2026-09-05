"""Unit tests for per-sentence TTS routing (code_switch_specialist)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gateway.voice_engines import VoiceEngines, classify_tts_locale  # noqa: E402


def test_classify_tts_locale():
    assert classify_tts_locale("Hello world.") == "en"
    assert classify_tts_locale("The return type should be Optional.") == "en"
    assert classify_tts_locale("打开Grid的voice测试模式") == "mixed"
    assert classify_tts_locale("打开测试模式") == "zh"
    assert classify_tts_locale("帮我把 function 的 return type 改成 Optional") == "mixed"
    assert classify_tts_locale("好。") == "zh"
    assert classify_tts_locale("") == "mixed"


def test_resolve_tts_engine_primary_all_cosyvoice():
    eng = VoiceEngines({})
    eng._warmup_stats = {"tts_decision": "primary"}
    eng._kokoro = object()
    chosen, route = eng.resolve_tts_engine("Hello world.", engine="auto")
    assert chosen == "cosyvoice2"
    assert route.reason == "primary"


def test_resolve_tts_engine_code_switch_en_kokoro():
    eng = VoiceEngines({})
    eng._warmup_stats = {"tts_decision": "code_switch_specialist"}
    eng._kokoro = object()
    chosen, route = eng.resolve_tts_engine("Hello world.", engine="auto")
    assert chosen == "kokoro"
    assert route.reason == "code_switch_specialist:en"


def test_resolve_tts_engine_code_switch_zh_cosyvoice():
    eng = VoiceEngines({})
    eng._warmup_stats = {"tts_decision": "code_switch_specialist"}
    eng._kokoro = object()
    chosen, route = eng.resolve_tts_engine("打开Grid测试", engine="auto")
    assert chosen == "cosyvoice2"
    assert route.reason == "code_switch_specialist:mixed"


def test_resolve_tts_engine_code_switch_mixed_cosyvoice():
    eng = VoiceEngines({})
    eng._warmup_stats = {"tts_decision": "code_switch_specialist"}
    eng._kokoro = object()
    chosen, route = eng.resolve_tts_engine(
        "帮我把 function 改成 Optional", engine="auto"
    )
    assert chosen == "cosyvoice2"
    assert route.reason == "code_switch_specialist:mixed"


def test_resolve_tts_engine_explicit_override():
    eng = VoiceEngines({})
    eng._warmup_stats = {"tts_decision": "code_switch_specialist"}
    eng._kokoro = object()
    chosen, route = eng.resolve_tts_engine("Hello.", engine="cosyvoice2")
    assert chosen == "cosyvoice2"
    assert route.reason == "explicit"
