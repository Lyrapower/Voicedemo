#!/usr/bin/env python3
"""
vl_normalize.py — Gateway V4.11 多模态归一化层
===============================================
清偿第4问的架构债: 让 Qwen-VL 的 content 数组安全通过 gateway,
不动现有校验逻辑, 只在它前面加一层归一化。

三个问题, 三个函数:
  1. 校验层假设 content 是字符串, VL 请求是数组
     → extract_text_blocks(): 只把 text 块交给 forbidden-pattern 扫描,
       image_url 块永不进扫描 (base64 会撑爆正则也毫无意义)
  2. token 预算按字节估算, 一张图就触发熔断
     → budget_chars(): 计数时图像载荷记为常量 IMAGE_BUDGET_CHARS,
       而不是 base64 长度
  3. 图像块本身的最小卫生检查
     → validate_image_blocks(): 只收 data:image/* 或 http(s),
       尺寸上限, 数量上限 — 确定性规则, 不用模型判断

接入 (gateway 请求管线, 校验中间件之前):
    from vl_normalize import gate_multimodal
    ok, reason, scan_text, budget = gate_multimodal(body["messages"])
    if not ok: return 422, reason
    # 把 scan_text 交给现有 forbidden-pattern 扫描 (替代原来扫全 body)
    # 把 budget 交给现有预算中间件 (替代原来的字节计数)

零依赖, 纯 stdlib。与 cloud_boundary.py 互补不重叠:
cloud_boundary 管出云载荷的秘密形状, 本层管入站 VL 请求的结构卫生。
"""

from __future__ import annotations

import re
from typing import Any

VERSION = "1.0.0"

MAX_IMAGES_PER_REQUEST = 12          # Seedance i2v 上限9张参考图 + 余量
MAX_IMAGE_B64_BYTES = 12_000_000     # ~9MB 原图的 base64 体积
IMAGE_BUDGET_CHARS = 1200            # 预算层中一张图折算的"字符成本"(≈视觉token的量级占位)
ALLOWED_URL_RE = re.compile(r"^(data:image/(png|jpeg|jpg|webp|gif);base64,|https?://)", re.I)


def _iter_blocks(messages: list[dict]) -> list[tuple[int, dict | str]]:
    """展平所有消息的 content, 保留消息序号。字符串 content 原样返回。"""
    out: list[tuple[int, dict | str]] = []
    for i, m in enumerate(messages or []):
        c = m.get("content")
        if isinstance(c, str):
            out.append((i, c))
        elif isinstance(c, list):
            for blk in c:
                out.append((i, blk))
    return out


def extract_text_blocks(messages: list[dict]) -> str:
    """所有应受 forbidden-pattern 扫描的文本, 合并为一个 blob。
    image_url 块被完整跳过 — 这是本模块存在的核心原因。"""
    parts: list[str] = []
    for _, blk in _iter_blocks(messages):
        if isinstance(blk, str):
            parts.append(blk)
        elif isinstance(blk, dict) and blk.get("type") == "text":
            parts.append(str(blk.get("text", "")))
    return "\n".join(parts)


def image_blocks(messages: list[dict]) -> list[dict]:
    return [blk for _, blk in _iter_blocks(messages)
            if isinstance(blk, dict) and blk.get("type") == "image_url"]


def validate_image_blocks(messages: list[dict]) -> tuple[bool, str]:
    imgs = image_blocks(messages)
    if len(imgs) > MAX_IMAGES_PER_REQUEST:
        return False, f"too_many_images: {len(imgs)} > {MAX_IMAGES_PER_REQUEST}"
    for i, blk in enumerate(imgs):
        url = (blk.get("image_url") or {}).get("url", "")
        if not isinstance(url, str) or not ALLOWED_URL_RE.match(url):
            return False, f"image[{i}]: url scheme not allowed"
        if url.startswith("data:") and len(url) > MAX_IMAGE_B64_BYTES:
            return False, f"image[{i}]: base64 payload {len(url)}B exceeds cap"
    return True, "ok"


def budget_chars(messages: list[dict]) -> int:
    """预算层用的字符数: 文本按实长, 图像按常量折算。
    这样一张 6MB 的图对预算的贡献是 1200 字符, 不是六百万。"""
    total = len(extract_text_blocks(messages))
    total += IMAGE_BUDGET_CHARS * len(image_blocks(messages))
    return total


def gate_multimodal(messages: list[dict]) -> tuple[bool, str, str, int]:
    """一次调用给出全部四个值: (通过?, 原因, 待扫描文本, 预算字符数)"""
    ok, reason = validate_image_blocks(messages)
    return ok, reason, extract_text_blocks(messages), budget_chars(messages)


# ── selftest ────────────────────────────────────────────────────────────
def selftest() -> None:
    b64 = "data:image/png;base64," + "A" * 40_000
    msgs = [
        {"role": "system", "content": "你是质检员"},
        {"role": "user", "content": [
            {"type": "text", "text": "评估这帧, 分镜要求: 粒子场域"},
            {"type": "image_url", "image_url": {"url": b64}},
            {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
        ]},
    ]
    ok, reason, scan_text, budget = gate_multimodal(msgs)
    assert ok, reason
    assert "粒子场域" in scan_text and "AAAA" not in scan_text          # base64 不进扫描
    assert budget == len(scan_text) + 2 * IMAGE_BUDGET_CHARS            # 图按常量折算
    # 纯文本请求零影响
    ok2, _, t2, b2 = gate_multimodal([{"role": "user", "content": "普通请求"}])
    assert ok2 and t2 == "普通请求" and b2 == 4
    # 违规 scheme 被拒
    bad = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "file:///etc/passwd"}}]}]
    ok3, r3 = validate_image_blocks(bad)
    assert not ok3 and "scheme" in r3
    # 超量图片被拒
    many = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "https://x/i.png"}}] * 13}]
    ok4, r4 = validate_image_blocks(many)
    assert not ok4 and "too_many" in r4
    print("PASS: vl_normalize selftest")


if __name__ == "__main__":
    selftest()
