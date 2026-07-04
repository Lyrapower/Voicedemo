from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


REPO_ROOT = Path(__file__).resolve().parents[2]
DELIVER_DIR = REPO_ROOT / "deliver"
ROUNDS_DIR = DELIVER_DIR / "rounds"
PATCH_PACK_DIR = DELIVER_DIR / "patch_packs"

router = APIRouter(prefix="/api/rounds", tags=["rounds"])


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dirs() -> None:
    ROUNDS_DIR.mkdir(parents=True, exist_ok=True)
    PATCH_PACK_DIR.mkdir(parents=True, exist_ok=True)


def _round_dir(round_id: str) -> Path:
    return ROUNDS_DIR / round_id


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(text, encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8") as f:
            f.write(text)


class CreateRoundReq(BaseModel):
    round_id: Optional[str] = None
    title: str = "Jarvis Round"
    owner: str = "Lyra"


class CreateRoundResp(BaseModel):
    round_id: str
    round_dir: str
    dialogue_path: str
    tasks_path: str


class AddMessageReq(BaseModel):
    round_id: str
    speaker: str = Field(
        description="Lyra|Aster|Che|ReviewDecide|Cursor (Cursor allowed as speaker, NOT as OWNER in patch pack)"
    )
    message: str


class AddTaskReq(BaseModel):
    round_id: str
    assignee: str = Field(description="Lyra|Aster|Che|ReviewDecide|Cursor")
    task: str
    priority: str = "P2"  # P0/P1/P2
    status: str = "todo"  # todo/doing/done


class GeneratePackReq(BaseModel):
    round_id: str
    owner: str = "Lyra"  # MUST NOT be Cursor
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
    patch: str = Field(default="", description="unified diff content (diff --git ...).")


class GeneratePackResp(BaseModel):
    round_id: str
    patch_pack_path: str
    patch_pack_archive_path: str
    patch_pack_md: str


PATCH_PACK_TEMPLATE = """# PATCH PACK
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


@router.post("/create", response_model=CreateRoundResp)
def create_round(req: CreateRoundReq) -> CreateRoundResp:
    _ensure_dirs()
    rid = req.round_id or f"round-{_utc_stamp()}"
    rdir = _round_dir(rid)
    rdir.mkdir(parents=True, exist_ok=True)

    dialogue = rdir / "DIALOGUE.md"
    tasks = rdir / "TASKS.md"

    if not dialogue.exists():
        dialogue.write_text(
            "\n".join(
                [
                    "# ROUND DIALOGUE",
                    f"- round_id: {rid}",
                    f"- title: {req.title}",
                    f"- created_utc: {_utc_iso()}",
                    "",
                    "## messages",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    if not tasks.exists():
        tasks.write_text(
            "\n".join(
                [
                    "# ROUND TASKS",
                    f"- round_id: {rid}",
                    f"- created_utc: {_utc_iso()}",
                    "",
                    "## tasks",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    return CreateRoundResp(
        round_id=rid,
        round_dir=str(rdir.relative_to(REPO_ROOT)),
        dialogue_path=str(dialogue.relative_to(REPO_ROOT)),
        tasks_path=str(tasks.relative_to(REPO_ROOT)),
    )


@router.post("/message")
def add_message(req: AddMessageReq) -> dict:
    _ensure_dirs()
    rdir = _round_dir(req.round_id)
    rdir.mkdir(parents=True, exist_ok=True)
    dialogue = rdir / "DIALOGUE.md"
    _append(
        dialogue,
        "\n".join(
            [
                f"- [{_utc_iso()}] **{req.speaker}**:",
                f"  {req.message.strip()}",
                "",
            ]
        ),
    )
    return {"status": "OK", "path": str(dialogue.relative_to(REPO_ROOT))}


@router.post("/task")
def add_task(req: AddTaskReq) -> dict:
    _ensure_dirs()
    rdir = _round_dir(req.round_id)
    rdir.mkdir(parents=True, exist_ok=True)
    tasks = rdir / "TASKS.md"
    _append(
        tasks,
        "\n".join(
            [
                f"- [{_utc_iso()}] **{req.priority}** **{req.status}** — **{req.assignee}**: {req.task.strip()}",
            ]
        )
        + "\n",
    )
    return {"status": "OK", "path": str(tasks.relative_to(REPO_ROOT))}


@router.post("/generate_patch_pack", response_model=GeneratePackResp)
def generate_patch_pack(req: GeneratePackReq) -> GeneratePackResp:
    _ensure_dirs()
    rid = req.round_id

    if req.owner.strip().lower() == "cursor":
        raise HTTPException(status_code=400, detail="OWNER cannot be Cursor.")

    scopes_block = _bullets(req.scopes) or "- ui"
    paths_block = _bullets(req.path_allowlist) or "- templates/**"
    commands_block = _bullets(req.commands)
    rollback_block = _bullets(req.rollback)

    md = PATCH_PACK_TEMPLATE.format(
        round_id=rid,
        owner=req.owner,
        scopes_block=scopes_block,
        paths_block=paths_block,
        patch=req.patch.strip(),
        commands_block=commands_block,
        rollback_block=rollback_block,
    )

    rdir = _round_dir(rid)
    rdir.mkdir(parents=True, exist_ok=True)
    pack_path = rdir / "PATCH_PACK.md"
    pack_path.write_text(md, encoding="utf-8")

    archive = PATCH_PACK_DIR / f"{rid}.md"
    archive.write_text(md, encoding="utf-8")

    return GeneratePackResp(
        round_id=rid,
        patch_pack_path=str(pack_path.relative_to(REPO_ROOT)),
        patch_pack_archive_path=str(archive.relative_to(REPO_ROOT)),
        patch_pack_md=md,
    )
