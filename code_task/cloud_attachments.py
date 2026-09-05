"""Cloud tab attachments for 8501 /task/cloud_chat.

- text / pdf / audio / video → extract to text, append to last user message
- images:
  - glm52 / glm53 / glm53_full → MiniMax M3 VL eyes (vision-only) → text; GLM audits
  - deepseek_v4 → Kimi VL bypass → text blocks (model stays text-only)
  No MiniMax Cloud tab. Pixels never go to GLM.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_GATEWAY_DIR = Path(__file__).resolve().parents[1] / "grid-sovereign-runtime" / "gateway"
if str(_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(_GATEWAY_DIR))

from code_task.m3_vl_eyes import GLM_EYES_SUBSTRATES, describe_images_m3  # noqa: E402
from code_task.vl_bypass import describe_images  # noqa: E402


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"].strip()
    return ""


def _append_to_last_user(messages: list[dict[str, Any]], block: str) -> None:
    text = (block or "").strip()
    if not text:
        return
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user" and isinstance(messages[i].get("content"), str):
            cur = messages[i]["content"].rstrip()
            messages[i] = {**messages[i], "content": (cur + "\n\n" + text).strip()}
            return
    messages.append({"role": "user", "content": text})


def _collect_images(
    images: list[Any] | None,
    vl_from_assets: list[dict[str, str]],
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for src in (vl_from_assets or []) + list(images or []):
        if not isinstance(src, dict):
            continue
        b64 = str(src.get("base64") or src.get("data") or "").strip()
        if not b64 or b64 in seen:
            continue
        seen.add(b64)
        mime = str(src.get("mime") or src.get("media_type") or "image/jpeg").strip()
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        out.append({"mime": mime, "base64": b64})
        if len(out) >= 6:
            break
    return out


async def preprocess_cloud_attachments(
    body: dict[str, Any],
    substrate: str,
    *,
    config: dict[str, Any] | None = None,
    route_id: str = "cloud",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (body_for_chat, meta). Strips assets; may set images for Kimi only."""
    cfg = dict(config or {})
    out = dict(body)
    messages = [dict(m) for m in (out.get("messages") or []) if isinstance(m, dict)]
    meta: dict[str, Any] = {"preprocess": False, "substrate": (substrate or "").strip().lower()}

    assets = [a for a in (out.get("assets") or []) if isinstance(a, dict)]
    top_images = [i for i in (out.get("images") or []) if isinstance(i, dict)]

    vl_from_assets: list[dict[str, str]] = []
    text_blocks: list[str] = []
    asset_names: list[str] = []
    if assets:
        # expanded_orchestrator.preprocess_assets — patchable in tests
        from expanded_orchestrator import preprocess_assets

        vl_from_assets, text_blocks, pmeta = preprocess_assets(assets, cfg)
        meta["assets"] = pmeta
        if text_blocks:
            _append_to_last_user(messages, "\n\n".join(text_blocks))
            meta["preprocess"] = True
        for a in assets:
            if str(a.get("kind") or "") == "image":
                asset_names.append(str(a.get("name") or ""))

    vl_images = _collect_images(top_images, vl_from_assets)
    sub = meta["substrate"] or "glm52"
    if sub in ("kimi_k3", "kimi-k3", "kimi_k3_cloud"):
        sub = "glm53"
        meta["substrate"] = sub

    if vl_images:
        meta["preprocess"] = True
        if sub in GLM_EYES_SUBSTRATES:
            names = asset_names or [str(i.get("name") or "") for i in vl_images]
            eyes = await describe_images_m3(
                vl_images, config=cfg, route_id=route_id, names=names
            )
            inject = str(eyes.get("inject") or "").strip()
            if inject:
                _append_to_last_user(messages, inject)
            meta["eyes"] = {
                "vl_backend": "minimax_m3",
                "vl_model": eyes.get("vl_model"),
                "vl_ok": eyes.get("vl_ok"),
                "vl_calls": eyes.get("vl_calls"),
                "vl_images": eyes.get("vl_images"),
                "refs": eyes.get("refs") or [],
                "records": eyes.get("records") or [],
                "hops": eyes.get("hops") or [],
            }
            meta["vl"] = {
                "vl_backend": "minimax_m3",
                "vl_ok": eyes.get("vl_ok"),
                "vl_calls": eyes.get("vl_calls"),
                "vl_images": eyes.get("vl_images"),
            }
            if eyes.get("warnings"):
                meta["warnings"] = list(eyes["warnings"])
            out.pop("images", None)
        else:
            # DeepSeek (and any non-GLM): Kimi VL bypass → text
            task = _last_user_text(messages) or "describe attachment"
            blocks, warnings, vl_meta = await describe_images(
                vl_images, task=task, config=cfg, route_id=route_id
            )
            if blocks:
                _append_to_last_user(messages, "\n\n".join(blocks))
            meta["vl"] = vl_meta
            if warnings:
                meta["warnings"] = warnings
            out.pop("images", None)
    else:
        out.pop("images", None)

    out.pop("assets", None)
    out["messages"] = messages
    return out, meta
