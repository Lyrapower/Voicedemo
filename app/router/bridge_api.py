from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

import subprocess
import sys
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[2]
DELIVER_DIR = REPO_ROOT / "deliver"
ROUNDS_DIR = DELIVER_DIR / "rounds"
PROOF_DIR = DELIVER_DIR / "proof" / "bridge"
PATCH_PACK_DIR = DELIVER_DIR / "patch_packs"

router = APIRouter(prefix="/api/bridge", tags=["bridge"])


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def _ensure_dirs() -> None:
    PATCH_PACK_DIR.mkdir(parents=True, exist_ok=True)
    ROUNDS_DIR.mkdir(parents=True, exist_ok=True)
    PROOF_DIR.mkdir(parents=True, exist_ok=True)


def _run(cmd: List[str], *, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)


def _git(cmd: List[str]) -> subprocess.CompletedProcess:
    return _run(["git", *cmd])


class GenerateReq(BaseModel):
    owner: str = Field(default="Lyra")
    round_id: Optional[str] = None
    scopes: List[str] = Field(default_factory=lambda: ["ui"])
    path_allowlist: List[str] = Field(
        default_factory=lambda: [
            "templates/**",
            "static/**",
            "app/**",
            "scripts/**",
            "specs/**",
            "deliver/**",
            "config/**",
        ]
    )
    commands: List[str] = Field(default_factory=list)
    rollback: List[str] = Field(default_factory=list)
    patch: str = Field(default="", description="unified diff")


class GenerateResp(BaseModel):
    round_id: str
    patch_pack_path: str
    patch_pack_md: str


class ApplyReq(BaseModel):
    patch_pack_md: str


class ApplyResp(BaseModel):
    status: str
    round_id: str
    note: str
    pre_sha: str
    post_sha: str
    changed_files: List[str]
    stdout: str
    stderr: str
    proof_path: str
    round_path: str


PATCH_PACK_TEMPLATE_V2 = """# PATCH PACK
## ROUND_ID
{round_id}

## OWNER
{owner}

## SCOPE_ALLOWLIST
{scopes_block}

## PATH_ALLOWLIST
{paths_block}

## PATCH_TYPE
unified_diff

## PATCH
BEGIN_PATCH
{patch}
END_PATCH

## COMMANDS
{commands_block}

## ROLLBACK
{rollback_block}
"""


def _bullets(items: List[str]) -> str:
    if not items:
        return ""
    return "\n".join([f"- {x}" for x in items])


def _extract_round_id(md: str) -> str:
    lines = md.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "## ROUND_ID":
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    return lines[j].strip()
    return f"round-{_utc_stamp()}"


@router.post("/generate", response_model=GenerateResp)
def generate(req: GenerateReq) -> GenerateResp:
    _ensure_dirs()
    rid = req.round_id or f"round-{_utc_stamp()}"
    scopes_block = _bullets(req.scopes) or "- ui"
    paths_block = _bullets(req.path_allowlist) or "- templates/**"
    commands_block = _bullets(req.commands)
    rollback_block = _bullets(req.rollback)

    md = PATCH_PACK_TEMPLATE_V2.format(
        round_id=rid,
        owner=req.owner,
        scopes_block=scopes_block,
        paths_block=paths_block,
        patch=req.patch.strip(),
        commands_block=commands_block,
        rollback_block=rollback_block,
    )
    path = PATCH_PACK_DIR / f"{rid}.md"
    path.write_text(md, encoding="utf-8")
    return GenerateResp(round_id=rid, patch_pack_path=str(path.relative_to(REPO_ROOT)), patch_pack_md=md)


@router.post("/apply", response_model=ApplyResp)
def apply(req: ApplyReq) -> ApplyResp:
    _ensure_dirs()

    md = req.patch_pack_md
    rid = _extract_round_id(md)

    round_dir = ROUNDS_DIR / rid
    round_dir.mkdir(parents=True, exist_ok=True)
    round_pack_path = round_dir / "PATCH_PACK.md"
    round_pack_path.write_text(md, encoding="utf-8")

    archive_path = PATCH_PACK_DIR / f"{rid}.md"
    archive_path.write_text(md, encoding="utf-8")

    pre_sha = _git(["rev-parse", "HEAD"]).stdout.strip()

    runner = REPO_ROOT / "scripts" / "bridge_round_runner.py"
    cp = _run([sys.executable, str(runner), str(round_pack_path)])

    post_sha = _git(["rev-parse", "HEAD"]).stdout.strip()
    changed = _git(["diff", "--name-only", pre_sha, post_sha]).stdout.strip().splitlines()
    changed = [c for c in changed if c.strip()]

    proof_path = PROOF_DIR / f"{rid}_BRIDGE_RUN.md"
    if not proof_path.exists():
        proof_path.write_text(
            f"# BRIDGE RUN\n\nROUND_ID: {rid}\n\n(pre_sha={pre_sha}, post_sha={post_sha})\n\n## STDOUT\n\n{cp.stdout}\n\n## STDERR\n\n{cp.stderr}\n",
            encoding="utf-8",
        )

    status = "PASS" if cp.returncode == 0 else "FAIL"
    return ApplyResp(
        status=status,
        round_id=rid,
        note="Bridge apply runs verify+accept via scripts/bridge_apply_patch_pack.py; failures auto rollback.",
        pre_sha=pre_sha,
        post_sha=post_sha,
        changed_files=changed,
        stdout=cp.stdout,
        stderr=cp.stderr,
        proof_path=str(proof_path.relative_to(REPO_ROOT)),
        round_path=str(round_pack_path.relative_to(REPO_ROOT)),
    )
