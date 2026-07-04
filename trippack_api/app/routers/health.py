from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter(tags=["health"])


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/health")
def health():
    return {"ok": True, "ts": _iso()}
