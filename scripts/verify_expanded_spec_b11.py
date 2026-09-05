#!/usr/bin/env python3
"""EXPANDED ORCHESTRATION SPEC acceptance (b11 companion) — live :8501 checks."""
from __future__ import annotations

import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

GW = "http://127.0.0.1:8501"
ROOT = Path(__file__).resolve().parents[1]
TELEMETRY = ROOT / "grid-sovereign-runtime" / "data" / "expanded_orchestration.jsonl"

# 1x1 red JPEG
TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////"
    "//////////////////////2wBDAf//////////////////////"
    "//////////////////////wAARCAABAAEDAREAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAb/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAGfAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQIBAT8Cf//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQMBAT8Cf//Z"
)
MIN_PDF_B64 = "JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PC9UeXBlL0NhdGFsb2c+PgplbmRvYmoKMSAwIG9iago8PC9UeXBlL1BhZ2VzL0tpZHNbMiAwIFJdPj4KMiAwIG9iago8PC9UeXBlL1BhZ2UvUGFyZW50IDEgMCBSL01lZGlhQm94WzAgMCA2MTIgNzkyXT4+CmVuZG9iago="
fail = 0


def post(path: str, body: dict, *, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        f"{GW}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def ok(label: str, cond: bool, detail: str = "") -> None:
    global fail
    tag = "PASS" if cond else "FAIL"
    if not cond:
        fail += 1
    extra = f" — {detail}" if detail else ""
    print(f"  [{tag}] {label}{extra}")


def skip(label: str, reason: str) -> None:
    print(f"  [SKIP] {label} — {reason}")


def last_telemetry() -> dict | None:
    if not TELEMETRY.is_file():
        return None
    lines = [ln for ln in TELEMETRY.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return None


def main() -> int:
    print("=== EXPANDED spec acceptance (b11) ===\n")

    try:
        urllib.request.urlopen(f"{GW}/health", timeout=8)
    except Exception as exc:
        print(f"  [FAIL] :8501 health — {exc}")
        return 1

    # 1. Normal → local, no cloud
    r = post("/task/expanded", {"task": "1+1等于几？只答数字。", "assets": [], "client_context": ""})
    ok("普通问题 substrate=local", r.get("substrate") == "local", f"got {r.get('substrate')}")
    ok("orchestrator=8501", r.get("provenance", {}).get("orchestrator") == "8501")
    ok("final 非空", bool(str(r.get("final") or "").strip()))

    # 2. Image task
    r = post(
        "/task/expanded",
        {
            "task": "描述这张图的色调，一句话。",
            "assets": [{"name": "img0", "kind": "image", "mime": "image/jpeg", "base64": TINY_JPEG_B64}],
            "client_context": "",
        },
    )
    prov = r.get("provenance") or {}
    ok("图片 final 非空", bool(str(r.get("final") or "").strip()))
    ok("图片 provenance.candidate 存在", "candidate" in prov)
    ok("图片 timing_ms 存在", bool(prov.get("timing_ms")))

    # 3. PDF local preprocess — document task hits glm-5.2:cloud (slow vs image/VL)
    r = post(
        "/task/expanded",
        {
            "task": "这份 PDF 有什么？",
            "assets": [{"name": "t.pdf", "kind": "pdf", "mime": "application/pdf", "base64": MIN_PDF_B64}],
            "client_context": "",
        },
        timeout=360,
    )
    ok("PDF substrate 有值", r.get("substrate") in ("local", "glm52_cloud", "glm52_cloud_error", "local(candidate rejected)"))
    tel = last_telemetry()
    if tel:
        kinds = (tel.get("preprocess") or {}).get("kinds") or []
        ok("PDF preprocess 标记 pdf", "pdf" in kinds, f"kinds={kinds}")
    else:
        skip("PDF telemetry", "no jsonl")

    # 4. Sanitizer — path in client_context
    r = post(
        "/task/expanded",
        {
            "task": "你好",
            "assets": [],
            "client_context": "用户: 文件在 /Users/secret/project.txt\nGrid: ok",
        },
    )
    tel = last_telemetry()
    hits = (tel or {}).get("sanitizer_hits") or []
    ok("脱敏器拦截路径", len(hits) > 0, f"hits={hits[:2]}")

    # 5. Unplug Kimi
    r = post(
        "/task/expanded",
        {
            "task": "描述若可。",
            "assets": [{"name": "img0", "kind": "image", "mime": "image/jpeg", "base64": TINY_JPEG_B64}],
            "client_context": "",
            "kimi_enabled": False,
        },
    )
    ok("拔除 kimi → substrate=local", r.get("substrate") == "local", f"got {r.get('substrate')}")

    # 6. Audio / video — depends on ffmpeg
    if not shutil.which("ffmpeg"):
        skip("音频 transcript", "ffmpeg missing")
        skip("视频抽帧", "ffmpeg missing")
    else:
        # minimal silent wav base64 (44 byte header + minimal) — may fail ASR but preprocess path runs
        silent_wav = (
            "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA="
        )
        r = post(
            "/task/expanded",
            {
                "task": "音频说了什么？",
                "assets": [{"name": "a.wav", "kind": "audio", "mime": "audio/wav", "base64": silent_wav}],
                "client_context": "",
                "kimi_enabled": False,
            },
            timeout=120,
        )
        ok("音频路径不崩溃", bool(r.get("final")))
        tel = last_telemetry()
        audio_meta = (tel or {}).get("preprocess", {}).get("audio")
        ok("音频 preprocess 记录", bool(audio_meta), str(audio_meta)[:80])

    # 7. Impersonation / path — unit-level via subprocess in gateway dir
    unit = ROOT / "grid-sovereign-runtime" / "tests" / "test_expanded_orchestrator.py"
    if unit.is_file():
        import subprocess
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_expanded_orchestrator.ExpandedOrchestratorTests.test_sanitize_blocks_path", "-v"],
            cwd=str(ROOT / "grid-sovereign-runtime"),
            capture_output=True,
            text=True,
            timeout=30,
        )
        ok("sanitize 绝对路径(单元)", proc.returncode == 0, proc.stderr.strip()[:80] or "ok")
    else:
        skip("sanitize 单元", "test file missing")

    print()
    if fail:
        print(f"EXPANDED SPEC FAIL ({fail} item(s))")
        return 1
    print("EXPANDED SPEC PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
