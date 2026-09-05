#!/usr/bin/env python3
"""Smoke compare Ollama VL models: text + image."""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

OLLAMA = "http://127.0.0.1:11434/api/chat"
IMG = Path(__file__).resolve().parents[1] / ".smoke_test_grid.png"

MODELS = [
    "qwen3.5:9b",
    "haervwe/GLM-4.6V-Flash-9B",
]

TEXT_PROMPT = "只回复两个汉字：收到。不要解释。"
VISION_PROMPT = "图里黑框内的英文是什么？只输出那一行英文，不要其它字。"


def chat(model: str, prompt: str, images: list[str] | None = None, timeout: int = 300) -> dict:
    msg: dict = {"role": "user", "content": prompt}
    if images:
        msg["images"] = images
    body = json.dumps(
        {"model": model, "messages": [msg], "stream": False, "options": {"num_predict": 128}}
    ).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    elapsed = time.perf_counter() - t0
    content = (data.get("message") or {}).get("content") or ""
    return {
        "elapsed_s": round(elapsed, 2),
        "content": content.strip(),
        "eval_count": (data.get("eval_count")),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "error": None,
    }


def b64_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def main() -> int:
    if not IMG.is_file():
        print(f"missing image: {IMG}", file=sys.stderr)
        return 1
    img_b64 = b64_image(IMG)
    results = {}
    for model in MODELS:
        row = {"model": model}
        print(f"\n=== {model} :: text ===", flush=True)
        try:
            row["text"] = chat(model, TEXT_PROMPT)
            print(json.dumps(row["text"], ensure_ascii=False))
        except Exception as e:
            row["text"] = {"error": str(e)}
            print(f"FAIL text: {e}")
        print(f"\n=== {model} :: vision ===", flush=True)
        try:
            row["vision"] = chat(model, VISION_PROMPT, images=[img_b64])
            print(json.dumps(row["vision"], ensure_ascii=False))
        except Exception as e:
            row["vision"] = {"error": str(e)}
            print(f"FAIL vision: {e}")
        results[model] = row
    print("\n=== SUMMARY ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
