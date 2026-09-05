"""Caliber lock — runtime proof that E4-B / verdict protocol is wired before 07-15."""
from __future__ import annotations

from pathlib import Path
from typing import Any

_BASE = Path(__file__).resolve().parent


def caliber_proof_status() -> dict[str, Any]:
    """Three checks required before ledger layer is locked."""
    pairing = (_BASE / "premarket_ab_pairing.py").read_text(encoding="utf-8")
    protocol_path = _BASE / "docs" / "VERDICT_PROTOCOL.md"
    protocol = protocol_path.read_text(encoding="utf-8") if protocol_path.is_file() else ""
    checks: list[dict[str, Any]] = [
        {
            "id": "adj_info_bucket",
            "label": "adj Δ 剔除 world-knowledge×information 桶",
            "ok": all(
                s in pairing
                for s in (
                    "is_information_bucket_row",
                    "world-knowledge",
                    "attribution",
                    "information",
                )
            ),
            "proof": "premarket_ab_pairing.is_information_bucket_row + daily_returns_for_date(adjusted=True)",
        },
        {
            "id": "void_symmetry_assert",
            "label": "void 对称 + grid_n==sonnet_n assert",
            "ok": "is_either_side_void" in pairing and "assert_paired_symmetry" in pairing,
            "proof": "premarket_ab_pairing.paired_scorable_dates → assert_paired_symmetry",
        },
        {
            "id": "win_rate_denominator",
            "label": "胜率分母仅方向性信号",
            "ok": "directional only" in protocol.lower() and "dir" in protocol,
            "proof": "docs/VERDICT_PROTOCOL.md §1 + is_directional_row()",
        },
    ]
    locked = all(c["ok"] for c in checks)
    return {
        "caliber_locked": locked,
        "checks": checks,
        "protocol_doc": "docs/VERDICT_PROTOCOL.md",
        "banner": None if locked else "记分层 未锁定 · 三口径验收未全过 · 07-15 前须闭环",
    }
