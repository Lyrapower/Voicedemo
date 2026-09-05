"""MiniMax M3 VL eyes — vision-only bypass for GLM 5.2 / 5.3 Cloud.

M3 reports what is on the image (objects, visible numbers, anomalies).
It does not judge pipeline meaning, aether-scan alignment, or trades.
GLM is the audit layer. No MiniMax Cloud tab.

Provenance (store.search-able, no image bytes):
  [眼睛·provenance] image_ref + M3 reading
  [眼睛·glm_audit]  GLM opinion linked by image_ref
"""
from __future__ import annotations

import base64
import hashlib
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

DEFAULT_M3_MODEL = os.environ.get("MINIMAX_M3_CLOUD_MODEL", "minimax-m3:cloud").strip()
DEFAULT_M3_ENDPOINT = os.environ.get(
    "MINIMAX_M3_CLOUD_ENDPOINT", "http://localhost:11434/api/chat"
).strip()

GLM_EYES_SUBSTRATES = frozenset({"glm52", "glm53", "glm53_full"})
EYES_STORE_NODES = frozenset({
    "cloud-glm52",
    "cloud-glm53",
    "cloud-glm53-full",
    "smoke_node",
    "smoke",
})
FORBIDDEN_STORE_PREFIXES = ("workbench", "field-", "diary")

EYES_PREFIX = "[眼睛·provenance]"
M3_SECTION = "[眼睛·m3]"
AUDIT_PREFIX = "[眼睛·glm_audit]"
VL_PREFIX = "[VL:minimax-m3]"
VL_UNAVAILABLE = "M3 识图不可用,已按纯文本交给 GLM"

M3_SYSTEM = (
    "你是 MiniMax M3，只做视觉转述，不报判断。\n"
    "只写：图上有什么、关键可见数字（价格、OI、成交量、坐标轴刻度、时间戳、图例文字）、"
    "异常点（缺口、尖刺、遮挡、模糊、缺轴、标注框）。\n"
    "不要解释这张 K 线在交易 pipeline 里意味着什么。\n"
    "不要判断 OI 是否与 aether scan 对得上。\n"
    "不要给出买卖、仓位、入场、方向建议。\n"
    "看不清就写看不清，不要编数字。"
)

GLM_INJECT_HEADER = (
    "【眼睛·M3 视觉转述 · 非判断 · execution_authority=NONE】\n"
    "下列是 MiniMax M3 对附图的视觉报告（图上有什么 / 可见数字 / 异常点）。\n"
    "这是 M3 的解释，不是已审计事实。"
    "K 线在 pipeline 里意味着什么、OI 是否对得上 aether scan，由你（GLM）判断。\n"
    "不要把 M3 读数写成「图上已证实」。\n"
)

_GATEWAY_DIR = Path(__file__).resolve().parents[1] / "grid-sovereign-runtime" / "gateway"
_DEMO_ROOT = Path(__file__).resolve().parents[1]


def _m3_model(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    return str(cfg.get("minimax_m3_cloud_model") or DEFAULT_M3_MODEL).strip() or DEFAULT_M3_MODEL


def _m3_endpoint(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    return str(
        cfg.get("minimax_m3_cloud_endpoint")
        or cfg.get("ollama_endpoint")
        or DEFAULT_M3_ENDPOINT
    ).strip()


def image_ref(image: dict[str, str], *, name: str = "") -> dict[str, Any]:
    """Hash-only citation. Never returns pixels."""
    b64 = str(image.get("base64") or image.get("data") or "").strip()
    mime = str(image.get("mime") or image.get("media_type") or "image/jpeg").strip()
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        raw = b64.encode("utf-8", "replace")
    digest = hashlib.sha256(raw).hexdigest()
    return {
        "sha256": digest,
        "sha12": digest[:12],
        "mime": mime or "image/jpeg",
        "name": str(name or image.get("name") or "").strip(),
        "nbytes": len(raw),
    }


def format_eyes_record(
    ref: dict[str, Any],
    m3_text: str,
    *,
    model: str,
    route_id: str,
    hop: dict[str, Any] | None = None,
) -> str:
    body = str(m3_text or "").strip()
    eyes_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12] if body else ""
    lines = [
        EYES_PREFIX,
        f"image_ref={ref.get('sha256')}",
        f"sha12={ref.get('sha12')}",
        f"mime={ref.get('mime')}",
        f"name={ref.get('name') or ''}",
        f"nbytes={ref.get('nbytes')}",
        f"eyes_model={model}",
        f"eyes_sha12={eyes_sha}",
        f"route_id={route_id}",
        "role=vision_only",
        "execution_authority=NONE",
        "audit_layer=glm",
    ]
    if hop:
        if hop.get("vl_ok") is not None:
            lines.append(f"vl_ok={int(bool(hop.get('vl_ok')))}")
        if hop.get("vl_latency_ms") is not None:
            lines.append(f"vl_latency_ms={hop.get('vl_latency_ms')}")
    lines.extend(["---", M3_SECTION, body or "(empty)"])
    return "\n".join(lines)


def format_glm_audit_record(
    refs: list[dict[str, Any]],
    glm_text: str,
    *,
    substrate: str,
    route_id: str,
    glm_model: str = "",
) -> str:
    body = str(glm_text or "").strip()
    glm_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12] if body else ""
    sha_list = ",".join(str(r.get("sha256") or "") for r in refs if r.get("sha256"))
    lines = [
        AUDIT_PREFIX,
        f"image_ref={sha_list}",
        f"glm_substrate={substrate}",
        f"glm_model={glm_model}",
        f"glm_sha12={glm_sha}",
        f"route_id={route_id}",
        "execution_authority=NONE",
        "---",
        body[:12000] or "(empty)",
    ]
    return "\n".join(lines)


def glm_inject_block(records: list[str]) -> str:
    chunks = [GLM_INJECT_HEADER]
    chunks.extend(records)
    return "\n\n".join(chunks).strip()


def persist_allowed(body: dict[str, Any] | None) -> tuple[bool, str]:
    """Write eyes only to GLM cloud nodes / smoke. Never diary / b11 / field."""
    b = body or {}
    if b.get("persist") is False:
        return False, ""
    node = str(b.get("memory_node") or "").strip()
    if b.get("memory_sealed") and node in ("", "sealed", "none"):
        return False, ""
    if not node or node in ("sealed", "none"):
        return False, ""
    low = node.lower()
    if any(low.startswith(p) for p in FORBIDDEN_STORE_PREFIXES):
        return False, ""
    if node in EYES_STORE_NODES or low.startswith("cloud-glm") or low.startswith("smoke"):
        return True, node
    return False, ""


def persist_eyes_messages(
    msgs: list[dict[str, Any]],
    *,
    node_id: str,
    db_path: str | None = None,
) -> int:
    if not msgs or not node_id:
        return 0
    explicit = bool((db_path or os.environ.get("GRID_STORE_DB") or "").strip())
    path = (db_path or os.environ.get("GRID_STORE_DB") or "").strip()
    if not path:
        try:
            from grid_mem import DEFAULT_STORE_DB
            path = str(DEFAULT_STORE_DB)
        except Exception:
            path = str(_DEMO_ROOT / "grid-sovereign-runtime" / "data" / "grid_store.db")
    if not path:
        return 0
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        return 0
    if not explicit and not os.path.isfile(path):
        return 0
    if str(_GATEWAY_DIR) not in sys.path:
        sys.path.insert(0, str(_GATEWAY_DIR))
    from grid_store import GridStore  # noqa: E402

    store = GridStore(path)
    try:
        try:
            return int(store.append_messages(node_id, msgs) or 0)
        except RuntimeError:
            last = 0
            for m in msgs:
                store.db.execute(
                    "INSERT INTO messages(node_id, role, content, ts) VALUES(?,?,?,?)",
                    (node_id, m["role"], m["content"], m.get("ts", time.time())),
                )
                last = int(store.db.execute("SELECT MAX(id) FROM messages").fetchone()[0] or 0)
            store.db.commit()
            return last
    finally:
        try:
            store.db.close()
        except Exception:
            pass


async def describe_image_m3(
    image: dict[str, str],
    *,
    config: dict[str, Any] | None = None,
    route_id: str,
    index: int = 0,
    name: str = "",
) -> tuple[str | None, dict[str, Any], dict[str, Any]]:
    """Single-hop M3 VL. Returns (prefixed_text, hop_meta, image_ref)."""
    ref = image_ref(image, name=name)
    model = _m3_model(config)
    endpoint = _m3_endpoint(config)
    timeout = float((config or {}).get("vl_bypass_timeout") or 180.0)
    b64 = str(image.get("base64") or image.get("data") or "").strip()
    question = (
        f"图 {index + 1}"
        + (f"（{name}）" if name else "")
        + "：只做视觉转述。图上有什么、关键可见数字、异常点。不报判断。"
    )
    started = time.time()
    hop: dict[str, Any] = {
        "vl_index": index,
        "vl_ok": False,
        "vl_latency_ms": 0,
        "vl_desc_len": 0,
        "vl_model": model,
        "vl_backend": "minimax_m3",
        "image_ref": ref,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                endpoint,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": M3_SYSTEM},
                        {"role": "user", "content": question, "images": [b64]},
                    ],
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.1, "num_predict": 1024},
                },
            )
            r.raise_for_status()
            body = r.json()
    except Exception as exc:
        hop["vl_latency_ms"] = int((time.time() - started) * 1000)
        hop["vl_error"] = type(exc).__name__
        hop["vl_error_detail"] = str(exc)[:240]
        return None, hop, ref

    message = body.get("message") if isinstance(body.get("message"), dict) else {}
    content = str(message.get("content") or "").strip()
    hop["vl_latency_ms"] = int((time.time() - started) * 1000)
    hop["vl_desc_len"] = len(content)
    hop["vl_ok"] = bool(content)
    echoed = str(body.get("model") or "").strip()
    if echoed:
        hop["vl_model"] = echoed
    if not content:
        hop["vl_error"] = "empty_content"
        return None, hop, ref
    return f"{VL_PREFIX} {content}", hop, ref


async def describe_images_m3(
    images: list[dict[str, str]],
    *,
    config: dict[str, Any] | None = None,
    route_id: str,
    names: list[str] | None = None,
) -> dict[str, Any]:
    """Run M3 on each image. Never includes pixels in the return payload."""
    blocks: list[str] = []
    records: list[str] = []
    warnings: list[str] = []
    hops: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    ok_n = 0
    for i, image in enumerate(images or []):
        nm = ""
        if names and i < len(names):
            nm = str(names[i] or "")
        text, hop, ref = await describe_image_m3(
            image, config=config, route_id=route_id, index=i, name=nm
        )
        hops.append({k: v for k, v in hop.items() if k != "image_ref"})
        refs.append(ref)
        if text:
            ok_n += 1
            raw = text[len(VL_PREFIX):].strip() if text.startswith(VL_PREFIX) else text
            blocks.append(text)
            records.append(format_eyes_record(
                ref, raw, model=str(hop.get("vl_model") or _m3_model(config)),
                route_id=route_id, hop=hop,
            ))
        elif VL_UNAVAILABLE not in warnings:
            warnings.append(VL_UNAVAILABLE)
    inject = glm_inject_block(records) if records else ""
    return {
        "blocks": blocks,
        "records": records,
        "inject": inject,
        "warnings": warnings,
        "refs": refs,
        "hops": hops,
        "vl_calls": len(images or []),
        "vl_ok": ok_n,
        "vl_images": len(images or []),
        "vl_backend": "minimax_m3",
        "vl_model": _m3_model(config),
    }
