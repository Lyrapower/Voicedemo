"""Shared Garden MEMORY + MUSIC helpers (5173 fallback + 8787 router)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPILED_DIR = ROOT / "knowledge" / "compiled"
MUSIC_DIR = ROOT / "scripts" / "garden_assets" / "music"
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}

BUILTIN_TRACKS = [
    {"id": "off", "label": "Off (mic only)", "type": "none", "category": "background"},
]


def _read_text(path: Path, limit: int = 12000) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > limit:
        return text[:limit] + "\n\n… (truncated)"
    return text


def compiled_memory_payload() -> dict:
    files = []
    if COMPILED_DIR.is_dir():
        for path in sorted(COMPILED_DIR.glob("*.md")):
            files.append(
                {
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "updatedAt": path.stat().st_mtime,
                }
            )
    return {
        "memory": _read_text(COMPILED_DIR / "MEMORY.md"),
        "files": files,
        "compiledDir": str(COMPILED_DIR.relative_to(ROOT)) if COMPILED_DIR.is_dir() else "",
    }


def run_memory_compile() -> dict:
    script = ROOT / "scripts" / "compile_memory.sh"
    if not script.is_file():
        return {"ok": False, "error": "compile_memory.sh missing"}
    proc = subprocess.run(
        ["bash", str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "compile failed").strip()
        return {"ok": False, "error": err[:800]}
    payload = compiled_memory_payload()
    payload["ok"] = True
    return payload


def music_catalog() -> dict:
    files: list[dict] = []
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(MUSIC_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTS:
            continue
        files.append(
            {
                "id": f"file_{path.stem}",
                "label": path.stem.replace("_", " ").replace("-", " ").title(),
                "type": "file",
                "category": "song",
                "url": f"/assets/music/{path.name}",
                "filename": path.name,
            }
        )
    return {
        "builtin": BUILTIN_TRACKS,
        "files": files,
        "musicDir": str(MUSIC_DIR.relative_to(ROOT)),
    }


def resolve_music_file(name: str) -> Path | None:
    safe = Path(name).name
    if safe != name or ".." in name:
        return None
    path = MUSIC_DIR / safe
    if path.is_file() and path.suffix.lower() in AUDIO_EXTS:
        return path
    return None
