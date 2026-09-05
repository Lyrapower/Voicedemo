#!/usr/bin/env python3
"""
Pack Jarvis workbench into a portable zip (source bundle + run/install scripts).

Usage:
  python3 scripts/jarvis/pack_jarvis_bundle.py
  python3 scripts/jarvis/pack_jarvis_bundle.py -o ~/Downloads/jarvis-bundle.zip

Extract anywhere as DEMO_ROOT, then:
  pip install -r requirements-jarvis.txt
  bash scripts/jarvis/install_launchagent.sh   # KeepAlive :8686
  open http://127.0.0.1:8686/ui/overview
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Paths relative to repo root — Jarvis sole entry + automation tasks + UI.
BUNDLE_PATHS: list[str] = [
    "app/platform_main.py",
    "app/__init__.py",
    "app/system_prompt.py",
    "app/jarvis",
    "app/router",
    "app/adapters",
    "app/crypto_rwa",
    "app/local_ai_nodes",
    "compiler",
    "models",
    "state",
    "logs",
    "jarvis",
    "config/jarvis_automation.yaml",
    "config/routing_policy.yaml",
    "budgets.yaml",
    "knowledge/compiled",
    "knowledge/source",
    "scripts/start_jarvis.sh",
    "scripts/jarvis_run_task.sh",
    "scripts/jarvis",
    "scripts/compile_memory.py",
    "scripts/compile_memory.sh",
    "scripts/scan_crypto_rwa_public.py",
    "templates",
    "static",
    "deliver/jarvis",
    "data/execution",
]

SKIP_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "node_modules",
    ".git",
}
SKIP_SUFFIXES = (".pyc", ".pyo", ".DS_Store")

README_RUN = """# Jarvis Bundle

Sole entry: **app.platform_main:app** → http://127.0.0.1:8686/ui/overview

## Quick start (macOS)

```bash
# 1. Merge into your demo repo (or use this folder as ~/Projects/demo)
cd ~/Projects/demo   # or: unzip -o jarvis-bundle.zip -d ~/Projects/demo

# 2. Dependencies
python3 -m pip install -r requirements-jarvis.txt

# 3. Compile memory (optional refresh)
bash scripts/compile_memory.sh

# 4. Run once
bash scripts/start_jarvis.sh

# 5. KeepAlive (survives reboot — recommended)
bash scripts/jarvis/install_launchagent.sh
```

## Ports (sidecars — not Jarvis chat backend)

| Port | Service |
|------|---------|
| 8686 | **Jarvis** (this bundle) |
| 11434 | Ollama — `/transmit` chat default `qwen3:8b` |
| 8501 | Grid gateway / demo/aster |
| 8510/8520 | Aether Nexus / Watcher dashboards |
| 8790 | ASTER FIELD |

## Task API

- GET http://127.0.0.1:8686/api/jarvis/tasks
- POST http://127.0.0.1:8686/api/jarvis/tasks/{{task_id}}/run?dry_run=true

See deliver/jarvis/JARVIS_MERGE_MAP.md

Generated: {stamp}
"""

REQUIREMENTS_JARVIS = """# Jarvis workbench minimal deps
fastapi>=0.110
uvicorn>=0.29
aiohttp>=3.9
requests>=2.31
pyyaml>=6.0
jinja2>=3.1
python-multipart>=0.0.9
anthropic>=0.25
openai>=1.0
numpy>=1.26
"""

INSTALL_SH = """#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
python3 -m pip install -q -r requirements-jarvis.txt
bash scripts/compile_memory.sh 2>/dev/null || true
if [[ "${1:-}" == "--launchd" ]]; then
  bash scripts/jarvis/install_launchagent.sh
else
  echo "Manual: bash scripts/start_jarvis.sh"
  echo "KeepAlive: bash install.sh --launchd"
fi
"""


def should_skip(path: Path) -> bool:
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return True
    return path.name.endswith(SKIP_SUFFIXES)


def collect_files() -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for rel in BUNDLE_PATHS:
        src = ROOT / rel
        if not src.exists():
            continue
        if src.is_file():
            if not should_skip(src):
                out.append(src)
                seen.add(src.resolve())
            continue
        for p in src.rglob("*"):
            if not p.is_file() or should_skip(p):
                continue
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                out.append(p)
    return sorted(out)


def write_bundle(staging: Path, files: list[Path]) -> dict:
    manifest: list[dict] = []
    for src in files:
        rel = src.relative_to(ROOT)
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        manifest.append({"path": str(rel), "bytes": src.stat().st_size})
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (staging / "README_RUN.md").write_text(README_RUN.format(stamp=stamp), encoding="utf-8")
    (staging / "requirements-jarvis.txt").write_text(REQUIREMENTS_JARVIS, encoding="utf-8")
    install = staging / "install.sh"
    install.write_text(INSTALL_SH, encoding="utf-8")
    install.chmod(0o755)
    meta = {
        "generated_at": stamp,
        "demo_root": str(ROOT),
        "entry": "app.platform_main:app",
        "bind": "127.0.0.1:8686",
        "file_count": len(manifest),
        "files": manifest,
    }
    (staging / "pack_manifest.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta


def make_zip(staging: Path, out_zip: Path) -> None:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(staging.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(staging.parent))


def default_outputs() -> list[Path]:
    stamp = datetime.now().strftime("%Y%m%d")
    paths = [ROOT / "deliver" / "jarvis" / f"jarvis-bundle-{stamp}.zip"]
    icloud = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Downloads"
    if icloud.is_dir():
        paths.append(icloud / f"jarvis-bundle-{stamp}.zip")
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description="Pack Jarvis workbench zip")
    ap.add_argument("-o", "--output", type=Path, help="Output zip path")
    ap.add_argument("--no-icloud", action="store_true", help="Skip iCloud Downloads copy")
    args = ap.parse_args()

    files = collect_files()
    if not files:
        raise SystemExit("No files matched — run from ~/Projects/demo")

    with tempfile.TemporaryDirectory(prefix="jarvis-bundle-") as tmp:
        staging = Path(tmp) / "jarvis-bundle"
        staging.mkdir()
        meta = write_bundle(staging, files)
        outputs: list[Path] = []
        if args.output:
            outputs = [args.output.expanduser().resolve()]
        else:
            outputs = default_outputs()
            if args.no_icloud and len(outputs) > 1:
                outputs = outputs[:1]

        for out in outputs:
            make_zip(staging, out)
            print(f"wrote {out} ({out.stat().st_size:,} bytes, {meta['file_count']} files)")

    print("README inside zip: README_RUN.md")
    print("Install: unzip → cd jarvis-bundle → bash install.sh --launchd")


if __name__ == "__main__":
    main()
