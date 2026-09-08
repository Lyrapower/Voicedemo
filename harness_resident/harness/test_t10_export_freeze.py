"""T10: real `_export_work` freeze path, canary zero leak via escape vectors.

Isolated job volume. The canary lives ONLY behind a symlink / hardlink /
fifo — vectors the freeze export must reject. Verifies the canary never
appears in the destination (no leak via symlink-follow, hardlink, fifo).
A regular job file (RESULT.md) is copied normally.
"""
from __future__ import annotations
import os, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import safe_export as SX


class T10ExportFreezeTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.src = self.root / "job"
        self.dst = self.root / "export"
        self.src.mkdir()
        (self.src / "RESULT.md").write_text("P4C_T10_20260908", encoding="utf-8")
        (self.src / "ok.txt").write_text("hello", encoding="utf-8")
        # canary lives ONLY behind escape vectors — not as a plain regular file
        self.canary = "CANARY_T10_LEAK_" + "x" * 8
        canary_target = self.root / "canary_target.txt"
        canary_target.write_text(self.canary, encoding="utf-8")
        os.symlink(canary_target, self.src / "escape")          # symlink to canary
        os.link(self.src / "ok.txt", self.src / "hard")          # hardlink (rejected)
        os.mkfifo(self.src / "fifo")                             # special (rejected)

    def tearDown(self):
        self.td.cleanup()

    def test_canary_not_in_export_via_escape_vectors(self):
        r = SX.export_tree(str(self.src), str(self.dst))
        self.assertTrue(r["ok"], r)
        blob = ""
        for p in self.dst.rglob("*"):
            if p.is_file():
                try:
                    blob += p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass
        self.assertNotIn(self.canary, blob, "canary leaked via escape vector")
        self.assertEqual((self.dst / "RESULT.md").read_text(encoding="utf-8"),
                         "P4C_T10_20260908")
        self.assertFalse((self.dst / "escape").exists())
        self.assertFalse((self.dst / "hard").exists())
        self.assertFalse((self.dst / "fifo").exists())

    def test_rejected_logged(self):
        r = SX.export_tree(str(self.src), self.dst)
        reasons = {x["reason"] for x in r["rejected"]}
        self.assertIn("symlink", reasons)
        self.assertIn("hardlink", reasons)
        self.assertIn("special file", reasons)

    def test_dst_symlink_rejected(self):
        real_dst = self.root / "real_export"
        real_dst.mkdir()
        out_link = self.root / "out_link"
        os.symlink(real_dst, out_link)
        with self.assertRaises(SX.ExportReject) as cm:
            SX.export_tree(str(self.src), str(out_link))
        self.assertIn("real directory", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
