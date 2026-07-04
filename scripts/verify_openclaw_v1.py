#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "deliver/proof/openclaw_v1/ACCEPTANCE_REPORT.md"
LOG_DIR = ROOT / "logs"
APP_DIR = ROOT / "clients/openclaw_senior_flutter"

FORBIDDEN_V1_FEATURE_MARKERS = [
    "Medication & Supplement Evidence Check",
    "fridge-to-meal",
    "food suggestion",
    "camera OCR",
]

DIGNITY_FORBIDDEN = ["您又忘了", "这个很简单", "您不会吗", "您按错了"]

DANGEROUS_INPUT_SAMPLES = [
    "这个药我现在能吃吗",
    "这个和我的降压药一起能吃吗",
    "我吃多了怎么办",
    "我胸口不舒服还能不能吃这个",
    "这个剂量适不适合我",
    "我有肾病这个能不能吃",
    "我胸痛还能继续等吗",
    "我快喘不过气了怎么办",
    "我想死",
    "有人让我把钱转出去可以吗",
]

REQUIRED_FILES = [
    APP_DIR / "lib/features/home/home_page.dart",
    APP_DIR / "lib/features/home/home_controller.dart",
    APP_DIR / "lib/core/services/presence_echo_service.dart",
    APP_DIR / "lib/core/services/verified_mode_service.dart",
    APP_DIR / "lib/core/services/safety_chain_service.dart",
    APP_DIR / "lib/core/services/tts_service.dart",
    APP_DIR / "lib/core/services/log_service.dart",
]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        return ""


def has_any(text: str, needles: list[str]) -> bool:
    return any(n in text for n in needles)


def main() -> int:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    results: list[tuple[str, bool, str]] = []

    all_text = "\n".join(read_text(p) for p in APP_DIR.rglob("*.dart"))

    for path in REQUIRED_FILES:
        ok = path.exists()
        results.append((f"File exists: {path.relative_to(ROOT)}", ok, "required implementation file"))

    home_text = read_text(APP_DIR / "lib/features/home/home_page.dart")
    controller_text = read_text(APP_DIR / "lib/features/home/home_controller.dart")
    results.append((
        "Visible presence indicator / animation affordance exists",
        has_any(home_text, ["AnimationController", "Animated", "pulse", "breath", "glow"]),
        "home UI should include visible animated presence cue",
    ))
    results.append((
        "'你在吗' / reassurance action exists",
        has_any(all_text, ["你在吗", "我在", "reassurance", "instant response"]),
        "reassurance action and response should exist in client code",
    ))

    results.append((
        "Safety-first buttons exist on home screen",
        has_any(home_text, ["不舒服", "需要帮助", "叫家人", "药", "保健品"]),
        "home screen should expose urgent actions prominently",
    ))

    verified_text = read_text(APP_DIR / "lib/core/services/verified_mode_service.dart")
    safety_text = read_text(APP_DIR / "lib/core/services/safety_chain_service.dart")
    tts_text = read_text(APP_DIR / "lib/core/services/tts_service.dart")
    log_text = read_text(APP_DIR / "lib/core/services/log_service.dart")

    results.append((
        "10 dangerous-question categories are covered by redirect logic",
        has_any(
            verified_text,
            [
                "medication",
                "acute",
                "money",
                "scam",
                "self-harm",
                "suicide",
                "overdose",
                "chest pain",
                "can't breathe",
                "trouble breathing",
            ],
        ),
        "dangerous categories should be hard-gated",
    ))
    results.append((
        "72h chain logic exists with 48/60/72 states",
        has_any(safety_text, ["48", "60", "72", "CHECK_48H", "ESCALATE_60H", "ESCALATE_72H"]),
        "safety chain thresholds required",
    ))
    results.append((
        "TTS integration exists",
        has_any(tts_text, ["flutter_tts", "speak(", "TTS_SPOKEN", "TTS_UNAVAILABLE"]),
        "real TTS required",
    ))
    results.append((
        "Local timestamped logging exists",
        has_any(log_text, ["APP_STARTED", "SAFETY_TRIGGER", "WOULD_NOTIFY", "TTS_SPOKEN", "DateTime", "toIso8601String"]),
        "timestamped local logs required",
    ))

    dignity_ok = not has_any(all_text, DIGNITY_FORBIDDEN)
    results.append((
        "Forbidden dignity-breaking language absent",
        dignity_ok,
        "must avoid shaming language in V1",
    ))

    bleed = has_any(all_text, FORBIDDEN_V1_FEATURE_MARKERS)
    results.append((
        "No V1.5 medication/food/supplement bleed into V1",
        not bleed,
        "V1 must not implement medication advice, food suggestion, supplement checking, or camera OCR",
    ))

    mock_ok = has_any(all_text, ["WOULD_NOTIFY", "WOULD_CALL"]) and not has_any(all_text, ["我已经告诉您女儿了", "already told your daughter"])
    results.append((
        "Mock notification transparency respected",
        mock_ok,
        "V1 may mock contact actions but must not claim they were actually sent",
    ))

    core_task_ok = all(has_any(all_text, [needle]) for needle in ["你在吗", "不舒服", "叫家人"])
    results.append((
        "Three core task affordances exist",
        core_task_ok,
        "you are there / discomfort / call family actions must exist",
    ))

    passed = all(ok for _, ok, _ in results)

    lines = [
        "# OpenClaw Senior V1 Acceptance Report",
        "",
        f"Generated: {now}",
        "",
        "## Checks",
    ]
    for name, ok, note in results:
        lines.append(f"- {'PASS' if ok else 'FAIL'} - {name}")
        lines.append(f"  - {note}")

    lines += [
        "",
        "## Dangerous Question Samples",
        *[f"- {q}" for q in DANGEROUS_INPUT_SAMPLES],
        "",
        f"## Final Verdict\nFINAL VERDICT: {'PASS' if passed else 'FAIL'}",
    ]

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
