#!/usr/bin/env python3
"""CosyVoice MPS monkeypatch bench — 3-run median warm RTF + device fingerprint."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GS = ROOT / "grid-sovereign-runtime"
sys.path.insert(0, str(GS))

from gateway.voice_engines import VoiceEngines, WARMUP_TEXT  # noqa: E402


def _load_voice_cfg() -> dict:
    cfg_path = GS / "configs" / "gateway_config.json"
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    return data.get("voice") or {}


def main() -> int:
    eng = VoiceEngines(_load_voice_cfg())
    eng._init_cosyvoice()
    if eng._tts_active != "cosyvoice2":
        print(json.dumps({"error": "cosyvoice2 not active", "blockers": eng.blockers}, indent=2))
        return 1
    stats = eng.warmup_tts(WARMUP_TEXT, runs=3)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if stats.get("error"):
        return 1
    eligible = stats.get("mps_primary_eligible")
    rtf = stats.get("warm_rtf_median")
    dev = (stats.get("devices") or {}).get("llm_param_device")
    print(f"\nVERDICT: median_rtf={rtf} device={dev} primary_eligible={eligible}")
    return 0 if eligible else 2


if __name__ == "__main__":
    raise SystemExit(main())
