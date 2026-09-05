"""K2.6 VL bypass — single-hop image→text for EXPANDED tray (8501 routing layer).

Invariants:
- One hop per image; no agent loop, no persistence of image bytes in logs.
- fail-soft: K2.6 unavailable → caller continues text-only with warning.
"""
from __future__ import annotations

import time
from typing import Any

from code_task.backends.kimi_k25_cloud import execute_candidate as execute_kimi_vl
from code_task.registry import resolve_code_backend

VL_PREFIX = "[VL:k2.6]"
VL_UNAVAILABLE = "识图不可用,已按纯文本处理"


async def describe_image(
    image: dict[str, str],
    *,
    question: str | None,
    config: dict[str, Any],
    route_id: str,
    index: int = 0,
) -> tuple[str | None, dict[str, Any]]:
    """Single-hop K2.6 VL: image → text description. Logs desc length only."""
    prompt = (
        question
        or "Describe this image in detail for a text-only downstream model. "
        "Include visible text, layout, colors, and salient objects."
    )
    target = resolve_code_backend(
        config,
        route_class="candidate",
        manual_backend_id="kimi_k25_cloud",
        body={"backend_id": "kimi_k25_cloud"},
    )
    started = time.time()
    resp = await execute_kimi_vl(
        request_id=f"{route_id}-vl-{index}",
        prompt=prompt,
        endpoint=target.endpoint,
        model=target.model,
        task_label="grid_vl_bypass",
        images=[image],
        max_tokens=1024,
        temperature=0.2,
        timeout=float(config.get("vl_bypass_timeout") or 120.0),
    )
    meta: dict[str, Any] = {
        "vl_index": index,
        "vl_ok": resp.ok,
        "vl_latency_ms": int((time.time() - started) * 1000),
        "vl_desc_len": len(resp.content or "") if resp.ok else 0,
        "vl_model": resp.model or target.model,
    }
    if not resp.ok:
        return None, meta
    text = str(resp.content or "").strip()
    if not text:
        return None, meta
    return f"{VL_PREFIX} {text}", meta


async def describe_images(
    images: list[dict[str, str]],
    *,
    task: str,
    config: dict[str, Any],
    route_id: str,
) -> tuple[list[str], list[str], dict[str, Any]]:
    """Run VL bypass for each tray image. Returns (text_blocks, warnings, aggregate_meta)."""
    blocks: list[str] = []
    warnings: list[str] = []
    meta: dict[str, Any] = {"vl_calls": 0, "vl_ok": 0, "vl_images": len(images)}
    task_hint = task.strip()[:240] or "user task"
    for i, image in enumerate(images):
        desc, hop = await describe_image(
            image,
            question=f"Describe image {i + 1} in context of: {task_hint}",
            config=config,
            route_id=route_id,
            index=i,
        )
        meta["vl_calls"] += 1
        if desc:
            blocks.append(desc)
            meta["vl_ok"] += 1
        else:
            if VL_UNAVAILABLE not in warnings:
                warnings.append(VL_UNAVAILABLE)
        meta.setdefault("vl_hops", []).append(hop)
    return blocks, warnings, meta
