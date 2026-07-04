from __future__ import annotations

import json
import sys
from pathlib import Path

from app.security_gate.gate import evaluate

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m app.security_gate.cli <request.json> [--non-interactive]")
        sys.exit(2)

    req_path = Path(sys.argv[1])
    non_interactive = ("--non-interactive" in sys.argv)

    if not req_path.exists():
        print(f"ERROR: request file not found: {req_path}")
        sys.exit(2)

    req = json.loads(req_path.read_text(encoding="utf-8"))

    result = evaluate(req, interactive=(not non_interactive))

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("approved") else 1)

if __name__ == "__main__":
    main()
