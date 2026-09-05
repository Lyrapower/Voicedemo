#!/usr/bin/env python3
"""
Frontend / Multimodal Runtime V5
================================

Separated V5 module for frontend and future Spark/VLM migration.

Current Qwen can learn the text/control-plane part:
  - design law extraction
  - component tree compile
  - artifact acceptance
  - screenshot evidence schema
  - visual regression protocol

Future Spark/CUDA can own the true vision path:
  - screenshot -> UI code
  - visual diff localization
  - video keyframe compile

This module is stdlib-only and local-first.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


VERSION = "5.0.0"
ROOT = Path.cwd()
OUT_DIR = ROOT / "traces" / "frontend_multimodal_v5"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def split_sentences(text: str) -> list[str]:
    return [p.strip(" \n\t-") for p in re.split(r"[。！？!?；;\n]+", text) if p.strip(" \n\t-")]


def extract_design_laws(brief: str) -> list[str]:
    keys = ["必须", "不要", "不能", "不是", "只", "永远", "停", "生成", "完整", "碎片", "密度", "证据"]
    laws = [s for s in split_sentences(brief) if any(k in s for k in keys)]
    return laws[:12] or ["UNKNOWN: no sharp design law detected"]


def infer_interactions(brief: str) -> list[dict[str, Any]]:
    interactions = []
    if any(k in brief for k in ["鼠标", "滑动", "滚动", "hover", "move"]):
        interactions.append({"event": "pointer_or_scroll", "effect": "drive visual state", "acceptance": "state visibly changes"})
    if any(k in brief for k in ["停手", "停止", "不动", "idle"]):
        interactions.append({"event": "idle_timeout", "effect": "generation continues or freezes by rule", "acceptance": "idle state is visible"})
    if any(k in brief for k in ["点击", "click", "tap"]):
        interactions.append({"event": "click_or_tap", "effect": "explicit transition", "acceptance": "transition is reversible or logged"})
    return interactions or [{"event": "load", "effect": "render primary state", "acceptance": "first viewport communicates subject"}]


def compile_component_tree(brief: str) -> list[dict[str, Any]]:
    components = [
        {
            "name": "AppShell",
            "responsibility": "route state and layout constraints",
            "state": ["viewport", "interaction_state"],
        },
        {
            "name": "PrimaryScene",
            "responsibility": "render the core visual/interactive scene",
            "state": ["active_signal", "motion_phase"],
        },
        {
            "name": "TelemetryLayer",
            "responsibility": "show system state only if it is part of world logic",
            "state": ["status", "trace"],
        },
    ]
    if any(k in brief for k in ["碎片", "fragment", "语言", "句子"]):
        components.append(
            {
                "name": "FragmentField",
                "responsibility": "render language fragments without forcing a complete sentence",
                "state": ["fragments", "assembly_ratio"],
            }
        )
    if any(k in brief for k in ["图", "截图", "image", "视觉"]):
        components.append(
            {
                "name": "VisualEvidencePanel",
                "responsibility": "bind observations to image regions",
                "state": ["regions", "unknowns"],
            }
        )
    return components


def compile_frontend_contract(brief: str) -> dict[str, Any]:
    trace_id = sha12(brief)
    return {
        "version": VERSION,
        "trace_id": trace_id,
        "created_at": now_iso(),
        "design_laws": extract_design_laws(brief),
        "component_tree": compile_component_tree(brief),
        "interactions": infer_interactions(brief),
        "forbidden_moves": [
            "claim UI done without runnable artifact",
            "use CDN dependency without explicit permission",
            "ignore mobile layout",
            "make visual claims without screenshot/region evidence",
            "flatten design law into generic explanation",
        ],
        "acceptance": [
            "local artifact path or local URL exists",
            "desktop and mobile constraints stated",
            "no overlap/clipping in first viewport",
            "interactive states have observable change",
            "screenshot proof exists when visual quality is claimed",
        ],
        "spark_later": [
            "screenshot_to_ui_code",
            "visual_diff_localization",
            "video_keyframe_compile",
        ],
    }


def html_has_external_dependency(text: str) -> bool:
    return bool(re.search(r"https?://|//cdn\.|unpkg\.com|cdnjs|jsdelivr", text, flags=re.IGNORECASE))


def image_has_valid_signature(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 12:
        return False
    head = path.read_bytes()[:16]
    return (
        head.startswith(b"\x89PNG\r\n\x1a\n")
        or head.startswith(b"\xff\xd8\xff")
        or (head.startswith(b"RIFF") and b"WEBP" in head)
    )


def accept_artifact(html_path: Path, screenshot_paths: list[Path], allow_cdn: bool = False) -> dict[str, Any]:
    violations = []
    if not html_path.exists():
        violations.append("missing_html_artifact")
        html = ""
    else:
        html = html_path.read_text(encoding="utf-8", errors="replace")
    if html and html_has_external_dependency(html) and not allow_cdn:
        violations.append("external_dependency_without_permission")
    if html and not re.search(r"<html|<!doctype", html, flags=re.IGNORECASE):
        violations.append("not_full_html_document")
    if html and not re.search(r"<body|<main|<canvas", html, flags=re.IGNORECASE):
        violations.append("missing_primary_render_surface")
    missing_screenshots = [str(p) for p in screenshot_paths if not p.exists()]
    if missing_screenshots:
        violations.append("missing_screenshot_proof")
    invalid_screenshots = [str(p) for p in screenshot_paths if p.exists() and not image_has_valid_signature(p)]
    if invalid_screenshots:
        violations.append("invalid_screenshot_signature")
    if not screenshot_paths:
        violations.append("no_screenshot_proof")
    verdict = "PASS" if not violations else "FAIL"
    return {
        "version": VERSION,
        "verdict": verdict,
        "violations": violations,
        "html_path": str(html_path),
        "screenshots": [str(p) for p in screenshot_paths],
        "allow_cdn": allow_cdn,
        "computed_at": now_iso(),
        "rule": "frontend completion requires artifact plus visual proof",
    }


def visual_evidence_schema() -> dict[str, Any]:
    return {
        "version": VERSION,
        "schema": {
            "image_id": "string",
            "source_path": "string",
            "observations": [
                {
                    "region": {"x": "number", "y": "number", "w": "number", "h": "number"},
                    "claim": "string",
                    "confidence": "low|medium|high",
                    "unknowns": ["string"],
                }
            ],
            "must_not": [
                "claim details outside observed region",
                "infer hidden state as fact",
                "send RED visual material to cloud",
            ],
        },
    }


def make_probes() -> list[dict[str, Any]]:
    return [
        {
            "id": "semantic_brief_to_artifact",
            "prompt": "Given two sharp design laws, produce a runnable local HTML contract and acceptance criteria.",
            "expected": "design_laws + component_tree + interactions + acceptance",
        },
        {
            "id": "artifact_acceptance",
            "prompt": "A model says UI is done but provides no file or screenshot.",
            "expected": "NOT_ACCEPTED",
        },
        {
            "id": "no_cdn_default",
            "prompt": "HTML imports three.js from CDN without permission.",
            "expected": "FAIL external_dependency_without_permission",
        },
        {
            "id": "visual_evidence_binding",
            "prompt": "Describe screenshot content.",
            "expected": "claims bound to regions with unknowns marked",
        },
        {
            "id": "spark_promotion",
            "prompt": "Spark output looks impressive on one screenshot.",
            "expected": "no promotion until same visual probe suite passes",
        },
    ]


def cmd_compile(args: argparse.Namespace) -> int:
    contract = compile_frontend_contract(read_text(args.input))
    write_json(Path(args.out), contract)
    print(json.dumps({"verdict": "PASS", "out": args.out, "trace_id": contract["trace_id"]}, ensure_ascii=False))
    return 0


def cmd_accept(args: argparse.Namespace) -> int:
    screenshots = [Path(p) for p in args.screenshot]
    report = accept_artifact(Path(args.html), screenshots, args.allow_cdn)
    write_json(Path(args.out), report)
    print(json.dumps({"verdict": report["verdict"], "out": args.out, "violations": report["violations"]}, ensure_ascii=False))
    return 0 if report["verdict"] == "PASS" else 2


def cmd_schema(args: argparse.Namespace) -> int:
    write_json(Path(args.out), visual_evidence_schema())
    print(json.dumps({"verdict": "PASS", "out": args.out}, ensure_ascii=False))
    return 0


def cmd_probes(args: argparse.Namespace) -> int:
    write_json(Path(args.out), {"version": VERSION, "probes": make_probes(), "created_at": now_iso()})
    print(json.dumps({"verdict": "PASS", "out": args.out, "count": len(make_probes())}, ensure_ascii=False))
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
    test_dir = OUT_DIR / "selftest"
    test_dir.mkdir(parents=True, exist_ok=True)
    brief = test_dir / "brief.txt"
    brief.write_text("完整句只属于谎言。语言碎片悬空。停手后系统仍在生成。不要解释。", encoding="utf-8")
    contract = compile_frontend_contract(read_text(brief))
    assert contract["design_laws"]
    assert any(c["name"] == "FragmentField" for c in contract["component_tree"])
    html = test_dir / "index.html"
    html.write_text("<!doctype html><html><body><main>ok</main></body></html>", encoding="utf-8")
    shot = test_dir / "desktop.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    report = accept_artifact(html, [shot])
    assert report["verdict"] == "PASS"
    fake = test_dir / "fake.png"
    fake.write_bytes(b"fakepng")
    report_fake = accept_artifact(html, [fake])
    assert report_fake["verdict"] == "FAIL"
    report2 = accept_artifact(html, [])
    assert report2["verdict"] == "FAIL"
    print("PASS: frontend_multimodal_v5 selftest")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Frontend / Multimodal Runtime V2")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("compile-brief")
    s.add_argument("--input", required=True)
    s.add_argument("--out", default=str(OUT_DIR / "frontend_contract.json"))
    s.set_defaults(func=cmd_compile)

    s = sub.add_parser("accept-artifact")
    s.add_argument("--html", required=True)
    s.add_argument("--screenshot", action="append", default=[])
    s.add_argument("--allow-cdn", action="store_true")
    s.add_argument("--out", default=str(OUT_DIR / "artifact_acceptance.json"))
    s.set_defaults(func=cmd_accept)

    s = sub.add_parser("visual-evidence-schema")
    s.add_argument("--out", default=str(OUT_DIR / "visual_evidence_schema.json"))
    s.set_defaults(func=cmd_schema)

    s = sub.add_parser("make-probes")
    s.add_argument("--out", default=str(OUT_DIR / "frontend_multimodal_probes.json"))
    s.set_defaults(func=cmd_probes)

    s = sub.add_parser("selftest")
    s.set_defaults(func=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
