#!/usr/bin/env python3
from __future__ import annotations
import os, stat, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sandbox"))
import safe_export as SX


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.src = Path(self.td.name) / "src"
        self.dst = Path(self.td.name) / "dst"
        self.sentinel = Path(self.td.name) / "SENTINEL"
        self.src.mkdir()
        self.dst.mkdir()
        self.sentinel.write_bytes(b"keep-me")
        (self.src / "ok.txt").write_text("hello", encoding="utf-8")
        (self.src / "sub").mkdir()
        (self.src / "sub" / "a.txt").write_text("aa", encoding="utf-8")

    def tearDown(self):
        self.td.cleanup()

    def test_happy(self):
        r = SX.export_tree(str(self.src), str(self.dst))
        self.assertTrue(r["ok"])
        self.assertEqual((self.dst / "ok.txt").read_text(encoding="utf-8"), "hello")
        self.assertEqual(self.sentinel.read_bytes(), b"keep-me")

    def test_dotdot_name_rejected_as_walk(self):
        # exporter uses relative_to; plant a symlink escape
        os.symlink(self.td.name, self.src / "escape")
        with self.assertRaises(SX.ExportReject):
            SX.export_tree(str(self.src), str(self.dst))
        self.assertEqual(self.sentinel.read_bytes(), b"keep-me")

    def test_symlink_file(self):
        os.symlink("/etc/passwd", self.src / "p")
        with self.assertRaises(SX.ExportReject):
            SX.export_tree(str(self.src), str(self.dst))
        self.assertFalse((self.dst / "p").exists())
        self.assertEqual(self.sentinel.read_bytes(), b"keep-me")

    def test_hardlink(self):
        os.link(self.src / "ok.txt", self.src / "hard")
        with self.assertRaises(SX.ExportReject):
            SX.export_tree(str(self.src), str(self.dst))
        self.assertEqual(self.sentinel.read_bytes(), b"keep-me")

    def test_fifo(self):
        os.mkfifo(self.src / "f")
        with self.assertRaises(SX.ExportReject):
            SX.export_tree(str(self.src), str(self.dst))
        self.assertEqual(self.sentinel.read_bytes(), b"keep-me")

    def test_absolute_rel_impossible_via_name(self):
        # dest symlink
        os.symlink(self.td.name, self.dst / "out")
        # exporter copies into dest; a file named normally is fine; dest symlink file not used as root
        r = SX.export_tree(str(self.src), str(self.dst))
        self.assertTrue(r["ok"])
        self.assertEqual(self.sentinel.read_bytes(), b"keep-me")


if __name__ == "__main__":
    unittest.main(verbosity=2)
