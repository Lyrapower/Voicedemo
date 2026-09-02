"""Offline checks: harness :8630 vs Audio8 TTS :8631 port separation."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from harness.config import load_config
from harness.port_util import port_bindable


def main() -> None:
    cfg = load_config(str(ROOT / "config.toml"))
    assert cfg.harness.port == 8630, cfg.harness.port
    assert cfg.voice.audio8.port == 8631, cfg.voice.audio8.port
    assert cfg.harness.port != cfg.voice.audio8.port
    assert cfg.voice.audio8.port != 8630
    assert cfg.voice.provider == "audio8_onnx"
    print(f"harness port={cfg.harness.port} audio8 port={cfg.voice.audio8.port}")
    print(f"audio8 port free={port_bindable(cfg.voice.audio8.host, cfg.voice.audio8.port)}")
    print("VOICE PORTS OK")


if __name__ == "__main__":
    main()
