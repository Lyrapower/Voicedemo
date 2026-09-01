#!/usr/bin/env python3
"""Grid immutable infrastructure guard — pre-commit, CI, runtime boot.

Modes:
  check-staged     Block commit if frozen files changed without unlock
  check-diff       Block CI if PR diff touches frozen files (no unlock in CI)
  verify-runtime   SHA256 manifest vs disk; exit 1 on drift (gateway boot gate)
  update-lock      Rewrite manifest hashes (requires GRID_INFRASTRUCTURE_UNLOCK=1)
  snapshot         JSON status for health / ops
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "config" / "grid_infrastructure_lock.json"
UNLOCK_ENV = "GRID_INFRASTRUCTURE_UNLOCK"


def _load_lock() -> dict:
    if not LOCK_PATH.is_file():
        raise SystemExit(f"MISSING lock manifest: {LOCK_PATH}")
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unlocked() -> bool:
    v = os.environ.get(UNLOCK_ENV, "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()


def _changed_paths(mode: str, base_ref: str) -> list[str]:
    if mode == "staged":
        out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMRT")
    else:
        out = _git("diff", "--name-only", "--diff-filter=ACMRT", f"{base_ref}...HEAD")
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _frozen_set(lock: dict) -> set[str]:
    return set((lock.get("frozen_files") or {}).keys())


def check_tree_changes(mode: str, *, base_ref: str = "origin/main") -> list[str]:
    lock = _load_lock()
    frozen = _frozen_set(lock)
    touched = [p for p in _changed_paths(mode, base_ref) if p in frozen]
    if touched and not _unlocked():
        print("P0 BLOCK: immutable Grid infrastructure modified without authorization.", file=sys.stderr)
        print(f"  unlock: export {UNLOCK_ENV}=1  (explicit user authorization only)", file=sys.stderr)
        print("  touched:", file=sys.stderr)
        for p in touched:
            print(f"    - {p}", file=sys.stderr)
        print(f"  manifest: {LOCK_PATH}", file=sys.stderr)
        return touched
    if touched and _unlocked():
        want_map = lock.get("frozen_files") or {}
        for p in touched:
            staged = _staged_sha256(p)
            want = want_map.get(p)
            if staged is None or want is None or staged != want:
                print(f"WARN: {p} staged sha256 ≠ manifest — run update-lock before commit (got={staged and staged[:12]} want={want and want[:12]})")
    return []


def _git_silent(*args: str) -> int:
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode


def _staged_sha256(rel: str) -> str | None:
    """sha256 of staged blob content (git show :<rel>); None if not staged."""
    try:
        content = subprocess.check_output(
            ["git", "show", f":{rel}"], cwd=ROOT, stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return None
    return hashlib.sha256(content).hexdigest()


def _frozen_dirty_reasons(rel: str, *, precommit: bool) -> list[str]:
    """Reasons a frozen file is not boot-clean.

    runtime 严(默认):对 HEAD 比 — staged 文件也算 dirty(防 add 后不 commit 就启动)。
    precommit 松(--precommit):对 index 比 — staged 且 worktree==index 即 clean
    (让冻结文件能 commit 通过,不撞鸡生蛋)。
    """
    reasons: list[str] = []
    if _git_silent("ls-files", "--error-unmatch", rel) != 0:
        reasons.append("untracked")
        return reasons
    diff_args = ["diff", "--quiet", "--", rel] if precommit else ["diff", "--quiet", "HEAD", "--", rel]
    if _git_silent(*diff_args) != 0:
        reasons.append("dirty")
    return reasons


def verify_runtime(*, strict: bool = True, precommit: bool = False) -> dict:
    lock = _load_lock()
    expected: dict[str, str] = lock.get("frozen_files") or {}
    drift: list[dict[str, str]] = []
    ok_count = 0
    for rel, want in expected.items():
        path = ROOT / rel
        if not path.is_file():
            drift.append({"path": rel, "reason": "missing", "expected": want[:12]})
            print(f"FROZEN_DIRTY {rel} (missing)", file=sys.stderr)
            continue
        reasons = _frozen_dirty_reasons(rel, precommit=precommit)
        if reasons:
            drift.append({"path": rel, "reason": "/".join(reasons), "expected": want[:12]})
            print(f"FROZEN_DIRTY {rel} ({'/'.join(reasons)})", file=sys.stderr)
            continue
        if precommit:
            # precommit 模式只验 tracked+clean(vs index);hash 交给 redline hook + runtime boot
            ok_count += 1
            continue
        got = _sha256(path)
        if got != want:
            drift.append({
                "path": rel,
                "reason": "hash_mismatch",
                "expected": want[:12],
                "actual": got[:12],
            })
        else:
            ok_count += 1
    man_rel = str(LOCK_PATH.relative_to(ROOT))
    man_reasons = _frozen_dirty_reasons(man_rel, precommit=precommit)
    if man_reasons:
        drift.append({"path": man_rel, "reason": "/".join(man_reasons)})
        print(f"FROZEN_DIRTY {man_rel} ({'/'.join(man_reasons)})", file=sys.stderr)
    snap = {
        "ok": len(drift) == 0,
        "version": lock.get("version"),
        "checked": len(expected),
        "matched": ok_count,
        "drift": drift,
        "decoupled_injection_note": lock.get("decoupled_injection_note"),
    }
    if drift and strict:
        print("P0 RUNTIME BLOCK: Grid infrastructure hash drift detected.", file=sys.stderr)
        for row in drift:
            print(f"  {row['path']}: {row['reason']}", file=sys.stderr)
        print(f"  manifest: {LOCK_PATH}", file=sys.stderr)
        print(f"  re-seal: {UNLOCK_ENV}=1 python3 scripts/grid_infrastructure_guard.py update-lock", file=sys.stderr)
        raise SystemExit(1)
    return snap


def update_lock() -> None:
    if not _unlocked():
        raise SystemExit(f"REFUSED: set {UNLOCK_ENV}=1 to update lock hashes after authorized edit")
    lock = _load_lock()
    files = list((lock.get("frozen_files") or {}).keys())
    new_hashes: dict[str, str] = {}
    for rel in files:
        path = ROOT / rel
        if not path.is_file():
            raise SystemExit(f"MISSING frozen file: {rel}")
        new_hashes[rel] = _sha256(path)
    lock["frozen_files"] = new_hashes
    LOCK_PATH.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: updated {len(new_hashes)} hashes in {LOCK_PATH}")


def snapshot() -> dict:
    try:
        return verify_runtime(strict=False)
    except SystemExit:
        return {"ok": False, "error": "verify_failed"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Grid immutable infrastructure guard")
    ap.add_argument(
        "mode",
        choices=("check-staged", "check-diff", "verify-runtime", "update-lock", "snapshot"),
    )
    ap.add_argument("--base-ref", default="origin/main")
    ap.add_argument("--precommit", action="store_true",
                    help="pre-commit mode: compare frozen files to index (staged clean), not HEAD")
    args = ap.parse_args()

    if args.mode == "check-staged":
        bad = check_tree_changes("staged")
        raise SystemExit(1 if bad else 0)
    if args.mode == "check-diff":
        bad = check_tree_changes("diff", base_ref=args.base_ref)
        raise SystemExit(1 if bad else 0)
    if args.mode == "verify-runtime":
        verify_runtime(strict=True, precommit=args.precommit)
        print("OK: runtime infrastructure lock verified")
    if args.mode == "update-lock":
        update_lock()
    if args.mode == "snapshot":
        print(json.dumps(snapshot(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
