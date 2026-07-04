from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.database import get_db
from app.config import settings
from app.db_models import DealAlert
from app.schemas import DealAlertOut

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _alert_out(a: DealAlert) -> DealAlertOut:
    return DealAlertOut(
        id=a.id,
        trip_goal_id=a.trip_goal_id,
        snapshot_id=a.snapshot_id,
        title=a.title,
        why_triggered=a.why_triggered or "",
        source_url=a.source_url,
        is_read=bool(a.is_read),
        created_at=_iso(a.created_at),
        is_demo=bool(a.is_demo),
    )


@router.get("", response_model=list[DealAlertOut])
def list_alerts(db: Session = Depends(get_db)):
    if settings.provider_mode_public() == "NOT_CONNECTED":
        return []
    rows = list(
        db.execute(select(DealAlert).order_by(desc(DealAlert.created_at))).scalars()
    )
    return [_alert_out(x) for x in rows]


@router.patch("/{aid}/read", response_model=DealAlertOut)
def mark_read(aid: str, db: Session = Depends(get_db)):
    a = db.get(DealAlert, aid)
    if not a:
        raise HTTPException(404, detail="Alert not found.")
    a.is_read = True
    db.commit()
    db.refresh(a)
    return _alert_out(a)
