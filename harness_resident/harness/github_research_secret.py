#!/usr/bin/env python3
"""Load GitHub research secret into THIS process only.

Source is harness_resident/config/github_research.token — not the shell,
not .env.gitpush.local, not the macOS keychain. Never prints the value.
"""
from __future__ import annotations
import os, stat
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[1] / "config" / "github_research.token"
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
MAX = 4096


_LOADED = False


def token_path() -> Path:
    return DEFAULT


def loader_authorized() -> bool:
    return bool(_LOADED)


def load_into_environ(environ=None, *, path: Path | None = None) -> dict:
    global _LOADED
    _LOADED = False
    env = os.environ if environ is None else environ
    env.pop("GITHUB_TOKEN", None)
    env.pop("GRID_GITHUB_RESEARCH_LOADED", None)
    p = Path(path) if path is not None else DEFAULT
    if p.is_symlink():
        return {"ok": False, "loaded": False, "reason": "symlink"}
    if not p.exists():
        return {"ok": False, "loaded": False, "reason": "missing"}
    flags = os.O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC
    try:
        fd = os.open(str(p), flags)
    except OSError:
        return {"ok": False, "loaded": False, "reason": "unreadable"}
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.geteuid():
            return {"ok": False, "loaded": False, "reason": "untrusted"}
        if (st.st_mode & 0o777) != 0o600:
            return {"ok": False, "loaded": False, "reason": "mode"}
        raw = os.read(fd, MAX + 1)
        if len(raw) > MAX or b"\x00" in raw:
            return {"ok": False, "loaded": False, "reason": "invalid"}
        body = raw[:-1] if raw.endswith(b"\n") else raw
        if b"\n" in body or b"\r" in body:
            return {"ok": False, "loaded": False, "reason": "invalid"}
        try:
            val = body.decode("ascii")
        except UnicodeDecodeError:
            return {"ok": False, "loaded": False, "reason": "invalid"}
        if len(val) < 8:
            return {"ok": False, "loaded": False, "reason": "empty_or_short"}
        env["GITHUB_TOKEN"] = val
        env["GRID_GITHUB_RESEARCH_LOADED"] = "1"
        _LOADED = True
        return {"ok": True, "loaded": True, "reason": "loaded"}
    finally:
        os.close(fd)
