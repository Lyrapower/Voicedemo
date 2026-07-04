#!/usr/bin/env python3
from __future__ import annotations

import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[1]
DELIVER_DIR = REPO_ROOT / "deliver"
PROOF_DIR = DELIVER_DIR / "proof" / "bridge"


def _run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, capture_output=True, check=check)


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return _run(["git", *args])


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short(s: str) -> str:
    return s[:12] if s else s


def _extract_round_id(md: str) -> str:
    lines = md.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "## ROUND_ID":
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    return lines[j].strip()
    return f"round-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')}"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "Usage: python3 scripts/bridge_round_runner.py <deliver/rounds/<round>/PATCH_PACK.md>",
            file=sys.stderr,
        )
        return 2

    pack_path = Path(argv[1]).resolve()
    if not pack_path.exists():
        print(f"FAIL: patch pack not found: {pack_path}", file=sys.stderr)
        return 2

    md = pack_path.read_text(encoding="utf-8")
    rid = _extract_round_id(md)

    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    proof_path = PROOF_DIR / f"{rid}_BRIDGE_RUN.md"

    pre_sha = _git(["rev-parse", "HEAD"]).stdout.strip()

    bridge = REPO_ROOT / "scripts" / "bridge_apply_patch_pack.py"
    cp = _run([sys.executable, str(bridge), str(pack_path)])

    post_sha = _git(["rev-parse", "HEAD"]).stdout.strip()
    changed = _git(["diff", "--name-only", pre_sha, post_sha]).stdout.strip().splitlines()
    changed = [c for c in changed if c.strip()]

    status = "PASS" if cp.returncode == 0 else "FAIL"

    proof_path.write_text(
        "\n".join(
            [
                "# BRIDGE RUN (Jarvis closed-loop)",
                f"- timestamp_utc: {_utc()}",
                f"- round_id: {rid}",
                f"- status: {status}",
                f"- pre_sha: {pre_sha}",
                f"- post_sha: {post_sha}",
                "",
                "## changed_files",
                *([f"- {p}" for p in changed] if changed else ["- (none)"]),
                "",
                "## stdout",
                cp.stdout.rstrip(),
                "",
                "## stderr",
                cp.stderr.rstrip(),
                "",
            ]
        ),
        encoding="utf-8",
    )

    round_dir = pack_path.parent
    (round_dir / "BRIDGE_RESULT.md").write_text(
        "\n".join(
            [
                "# BRIDGE RESULT",
                f"- round_id: {rid}",
                f"- status: {status}",
                f"- proof: deliver/proof/bridge/{rid}_BRIDGE_RUN.md",
                f"- post_sha: {post_sha}",
                f"- sha_short: {_short(post_sha)}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    if cp.returncode != 0:
        return cp.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
