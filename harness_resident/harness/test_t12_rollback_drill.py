"""T12: rollback drill — exact EGRESS still rejects after rollback.

Tests the real egress decision path (`load_egress` + `_resolve_row`)
directly, no DNS/network. Apply a permissive row → decision flips to
allow; roll back to the exact snapshot → same request denied again.
Confirms rollback restores the exact rejection, not a relaxed state.
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import web_fetch_v3 as w


BASE_EGRESS = """| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |
| source.test | fixture | yes | none | 1000 | attested | TEST | research |
[deny]
blocked.test
"""


def _decision(egress_path: str, host: str, lane: str = "research"):
    reg = w.load_egress(egress_path)
    row, why, meta = w._resolve_row(reg, host, lane)
    return row, why, meta


class T12RollbackDrillTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.eg = Path(self.td.name) / "egress.md"
        self.eg.write_text(BASE_EGRESS, encoding="utf-8")
        self.snapshot = self.eg.read_text(encoding="utf-8")

    def tearDown(self):
        self.td.cleanup()

    def test_baseline_denies_unapproved_domain(self):
        row, why, meta = _decision(str(self.eg), "blocked.test")
        self.assertIsNone(row, why)
        self.assertEqual(meta["match_kind"], "deny")

    def test_permissive_row_allows_then_rollback_denies(self):
        # 1. apply a permissive change: drop the deny + add exact approved row
        relaxed = """| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |
| source.test | fixture | yes | none | 1000 | attested | TEST | research |
| blocked.test | drill | yes | none | 1000 | attested | TEST | research |
"""
        self.eg.write_text(relaxed, encoding="utf-8")
        row1, why1, meta1 = _decision(str(self.eg), "blocked.test")
        self.assertIsNotNone(row1, why1)
        self.assertEqual(meta1["match_kind"], "exact")

        # 2. rollback to exact snapshot (deny restored)
        self.eg.write_text(self.snapshot, encoding="utf-8")
        row2, why2, meta2 = _decision(str(self.eg), "blocked.test")
        self.assertIsNone(row2, why2)
        self.assertEqual(meta2["match_kind"], "deny")

    def test_rollback_file_matches_snapshot_byte_for_byte(self):
        self.eg.write_text("CORRUPT", encoding="utf-8")
        self.eg.write_text(self.snapshot, encoding="utf-8")
        self.assertEqual(self.eg.read_text(encoding="utf-8"), self.snapshot)

    def test_star_cannot_override_exact_deny_after_rollback(self):
        # deny takes precedence over any star/exact approval for the same host
        row, why, meta = _decision(str(self.eg), "blocked.test")
        self.assertIsNone(row)
        self.assertEqual(meta["match_kind"], "deny")
        # approved source.test still allowed
        row_s, _, meta_s = _decision(str(self.eg), "source.test")
        self.assertIsNotNone(row_s)
        self.assertEqual(meta_s["match_kind"], "exact")


if __name__ == "__main__":
    unittest.main(verbosity=2)
