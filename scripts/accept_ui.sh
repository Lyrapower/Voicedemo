#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

for f in static/jarvis.css static/jarvis.js templates/base_shell.html templates/workbench.html templates/workspace.html; do
  test -f "$f" || { echo "FAIL missing $f"; exit 1; }
done

python3 <<'PY'
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined

root = Path(".")
env = Environment(
    loader=FileSystemLoader(str(root / "templates")),
    undefined=StrictUndefined,
)
for name in ("base_shell.html", "workbench.html", "workspace.html", "partials/nav_shell.html", "partials/stat_card.html", "partials/detail_card.html"):
    env.get_template(name)
print("JINJA_TEMPLATES_OK")
PY

python3 scripts/verify_trading_module.py

echo "ACCEPT_UI_PASS"
