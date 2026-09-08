#!/usr/bin/env python3
"""Isolated GRID_STORE_TOKEN helper tests. Never print secret values."""
from __future__ import annotations
import os, stat, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import provision_grid_store_token as P  # noqa: E402

SCRIPT = ROOT / "scripts" / "provision_grid_store_token.py"


def _vals(*xs):
    return {x for x in xs}


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        cfg = self.root / "grid-sovereign-runtime" / "config"
        cfg.mkdir(parents=True)

    def tearDown(self):
        self.td.cleanup()

    def test_cli_no_args_is_help_nonzero(self):
        r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=8)
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stdout or r.stderr)

    def test_first_create_then_reuse(self):
        a = P.provision(root=self.root)
        self.assertTrue(a["ok"] and a["created"])
        path = P.token_path(root=self.root)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        first = path.read_bytes()
        b = P.provision(root=self.root)
        self.assertTrue(b["ok"] and not b["created"])
        self.assertEqual(b["reason"], "reused")
        self.assertEqual(path.read_bytes(), first)
        self.assertGreaterEqual(len(first.strip()), 32)

    def test_concurrent_processes_same_value(self):
        env = dict(os.environ)
        procs = []
        for _ in range(8):
            procs.append(subprocess.Popen(
                [sys.executable, str(SCRIPT), "--provision", "--root", str(self.root)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
            ))
        codes = []
        outs = []
        for p in procs:
            try:
                so, se = p.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
                self.fail("provision subprocess timeout")
            codes.append(p.returncode)
            outs.append(so or "")
        self.assertTrue(all(c == 0 for c in codes), codes)
        path = P.token_path(root=self.root)
        self.assertTrue(path.is_file())
        got = []
        for _ in procs:
            info = P.inspect_token_file(path)
            self.assertTrue(info["ok"])
            got.append(info["value"])
        self.assertEqual(len(set(got)), 1)
        created_lines = sum(1 for out in outs if "created True" in out)
        self.assertEqual(created_lines, 1)

    def test_concurrent_threads_compare_reader_set(self):
        barrier = threading.Barrier(8, timeout=10)
        results = []
        errors = []

        def run():
            try:
                barrier.wait()
                r = P.provision(root=self.root)
                info = P.inspect_token_file(P.token_path(root=self.root))
                results.append((r, info.get("value")))
            except Exception as e:
                errors.append(repr(e))

        ts = [threading.Thread(target=run) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=15)
            self.assertFalse(t.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 8)
        created = sum(1 for r, _ in results if r.get("created"))
        ok = sum(1 for r, _ in results if r.get("ok"))
        self.assertEqual(created, 1)
        self.assertEqual(ok, 8)
        self.assertEqual(len({v for _, v in results}), 1)

    def test_symlink_rejected(self):
        path = P.token_path(root=self.root)
        os.symlink("/tmp/nope", path)
        r = P.provision(root=self.root)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "symlink")

    def test_fifo_rejected(self):
        path = P.token_path(root=self.root)
        os.mkfifo(path)
        r = P.provision(root=self.root)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "not_regular")
        self.assertTrue(stat.S_ISFIFO(path.lstat().st_mode))

    def test_empty_rejected_unchanged(self):
        path = P.token_path(root=self.root)
        original = b"\n"
        path.write_bytes(original)
        os.chmod(path, 0o600)
        r = P.provision(root=self.root)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "empty_or_short")
        self.assertEqual(path.read_bytes(), original)

    def test_embedded_newline_rejected(self):
        path = P.token_path(root=self.root)
        original = b"x" * 16 + b"\n" + b"y" * 16
        path.write_bytes(original)
        os.chmod(path, 0o600)
        info = P.inspect_token_file(path)
        self.assertFalse(info["ok"])
        self.assertEqual(info["reason"], "embedded_newline")
        r = P.provision(root=self.root)
        self.assertFalse(r["ok"])
        self.assertEqual(path.read_bytes(), original)

    def test_invalid_utf8_rejected(self):
        path = P.token_path(root=self.root)
        original = b"\xff" * 20
        path.write_bytes(original)
        os.chmod(path, 0o600)
        info = P.inspect_token_file(path)
        self.assertFalse(info["ok"])
        self.assertIn(info["reason"], {"non_ascii", "control_char"})
        self.assertEqual(path.read_bytes(), original)

    def test_inspect_does_not_chmod(self):
        path = P.token_path(root=self.root)
        path.write_bytes(b"A" * 32 + b"\n")
        os.chmod(path, 0o644)
        before = path.read_bytes()
        info = P.inspect_token_file(path)
        self.assertFalse(info["ok"])
        self.assertEqual(info["reason"], "mode")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        self.assertEqual(path.read_bytes(), before)

    def test_cwd_independent(self):
        old = os.getcwd()
        try:
            os.chdir("/")
            r = P.provision(root=self.root)
            self.assertTrue(r["ok"])
            self.assertTrue(P.token_path(root=self.root).is_file())
        finally:
            os.chdir(old)

    def test_wrong_root_does_not_create_second_identity(self):
        inner = self.root / "grid-sovereign-runtime"
        r = P.provision(root=inner)
        self.assertFalse(r["ok"])
        self.assertFalse((inner / "grid-sovereign-runtime" / "config" / "grid_store.token").exists())
        self.assertFalse(P.token_path(root=self.root).exists())

    def test_runtime_symlink_rejected(self):
        real = Path(self.td.name) / "real-rt"
        real.mkdir()
        (real / "config").mkdir()
        target = self.root / "grid-sovereign-runtime"
        # replace dir with symlink
        import shutil
        shutil.rmtree(target)
        os.symlink(real, target)
        r = P.provision(root=self.root)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "runtime_symlink")

    def test_lock_symlink_rejected(self):
        canary = Path(self.td.name) / "canary"
        canary.write_bytes(b"KEEP")
        lock = self.root / "grid-sovereign-runtime" / "config" / ".grid_store.token.lock"
        os.symlink(canary, lock)
        r = P.provision(root=self.root)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "lock_symlink")
        self.assertEqual(canary.read_bytes(), b"KEEP")

    def test_hardlink_rejected(self):
        path = P.token_path(root=self.root)
        P.provision(root=self.root)
        other = path.parent / "other"
        os.link(path, other)
        info = P.inspect_token_file(path)
        self.assertFalse(info["ok"])
        self.assertEqual(info["reason"], "nlink")

    def test_env_matches_unset_ok_strict_fails(self):
        P.provision(root=self.root)
        env = dict(os.environ)
        env.pop("GRID_STORE_TOKEN", None)
        a = subprocess.run(
            [sys.executable, str(SCRIPT), "--env-matches-file", "--root", str(self.root)],
            capture_output=True, text=True, env=env, timeout=8,
        )
        self.assertEqual(a.returncode, 0)
        b = subprocess.run(
            [sys.executable, str(SCRIPT), "--env-loaded", "--root", str(self.root)],
            capture_output=True, text=True, env=env, timeout=8,
        )
        self.assertEqual(b.returncode, 78)

    def test_env_mismatch(self):
        P.provision(root=self.root)
        env = dict(os.environ)
        env["GRID_STORE_TOKEN"] = "not-the-file-value-at-all-0000"
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--env-loaded", "--root", str(self.root)],
            capture_output=True, text=True, env=env, timeout=8,
        )
        self.assertEqual(r.returncode, 79)
        self.assertNotIn(env["GRID_STORE_TOKEN"], r.stdout)
        self.assertNotIn(env["GRID_STORE_TOKEN"], r.stderr)

    def test_inspect_cli_readonly(self):
        path = P.token_path(root=self.root)
        path.write_bytes(b"B" * 32 + b"\n")
        os.chmod(path, 0o600)
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--inspect", "--root", str(self.root)],
            capture_output=True, text=True, timeout=8,
        )
        self.assertEqual(r.returncode, 0)
        self.assertEqual(path.read_bytes(), b"B" * 32 + b"\n")
        self.assertNotIn("B" * 32, r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
