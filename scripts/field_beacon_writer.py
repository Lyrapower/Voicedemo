#!/usr/bin/env python3
"""Append motion beacons to FIELD_DIR/field_YYYY-MM-DD.jsonl (GridField 信标写入)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

FIELD_DIR = Path(os.environ.get("FIELD_DIR", str(
    Path(__file__).resolve().parents[1] / "data" / "grid_field"
))).expanduser()
INTERVAL = max(15, int(os.environ.get("BEACON_INTERVAL", "60")))


def write_beacon(*, motion: str = "still", speed: float = 0.0) -> Path:
    FIELD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(FIELD_DIR, 0o700)
    except OSError:
        pass
    day = datetime.now().strftime("%Y-%m-%d")
    path = FIELD_DIR / ("field_%s.jsonl" % day)
    row = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "motion": motion,
        "speed": speed,
        "source": "field_beacon_writer",
    }
    new_file = not path.exists()
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.chmod(path, 0o600 if new_file else 0o600)
    return path


def main() -> None:
    print("field beacon writer → %s (every %ds)" % (FIELD_DIR, INTERVAL), flush=True)
    while True:
        write_beacon()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
