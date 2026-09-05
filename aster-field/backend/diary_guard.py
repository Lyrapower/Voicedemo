"""日记防污染 — 拒绝 agent 验收/探测写入生产库。"""
from __future__ import annotations
import re

# 仅 22:30 aster-diary/diary.py 可带此头发 POST /diary
SCHEDULER_WRITER = "aster-scheduler"

# agent 验收/探测常见垃圾（命中即拒）— 不含「YYYY-MM-DD 日记：」：Grid 22:30 正文会用该格式
_PROBE_PATTERNS = re.compile(
    r"(?i)"
    r"(acceptance[-_]|browser-accept|grid-write-(probe|check)|"
    r"signal\s+locked|signal\s+received|channel\s+stable)"
)


def reject_probe_text(text: str, *, what: str = "content") -> None:
    clean = (text or "").strip()
    if not clean:
        return
    if _PROBE_PATTERNS.search(clean):
        raise ValueError(f"refused: {what} matches agent probe/acceptance pattern")


def require_scheduler_writer(header: str | None) -> None:
    if (header or "").strip() != SCHEDULER_WRITER:
        raise PermissionError("refused: POST /diary only from aster-scheduler (22:30 diary.py)")
