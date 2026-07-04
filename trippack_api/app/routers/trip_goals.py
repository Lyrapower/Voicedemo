import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.database import get_db
from app.config import settings
from app.db_models import TripGoal, ProviderQuote, PackageSnapshot
from app.schemas import (
    TripGoalCreate,
    TripGoalOut,
    ProviderQuoteOut,
    QuotesEnvelope,
    PackageSnapshotOut,
)
from app.services.check_now import run_check_for_goal, NOT_CONNECTED_MSG


router = APIRouter(prefix="/trip-goals", tags=["trip-goals"])


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _goal_out(g: TripGoal) -> TripGoalOut:
    return TripGoalOut(
        id=g.id,
        origin=g.origin,
        destination_preference=g.destination_preference,
        budget_usd=float(g.budget_usd or 0),
        start_date=g.start_date,
        end_date=g.end_date,
        needs_car=bool(g.needs_car),
        status=g.status,
        created_at=_iso(g.created_at) or "",
        updated_at=_iso(g.updated_at) or "",
        last_checked_at=_iso(g.last_checked_at),
        next_check_at=_iso(g.next_check_at),
    )


def _quote_out(q: ProviderQuote) -> ProviderQuoteOut:
    return ProviderQuoteOut(
        id=q.id,
        trip_goal_id=q.trip_goal_id,
        category=q.category,
        provider=q.provider,
        title=q.title,
        price_usd=float(q.price_usd) if q.price_usd is not None else None,
        currency=q.currency,
        source_url=q.source_url,
        fetched_at=_iso(q.fetched_at) or "",
        terms_notes=q.terms_notes,
        is_demo=bool(q.is_demo),
        is_live=bool(q.is_live),
    )


@router.post("", response_model=TripGoalOut)
def create_goal(body: TripGoalCreate, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    g = TripGoal(
        id=str(uuid.uuid4()),
        origin=body.origin,
        destination_preference=body.destination_preference,
        budget_usd=Decimal(str(body.budget_usd)),
        start_date=body.start_date,
        end_date=body.end_date,
        needs_car=body.needs_car,
        status=body.status if body.status in ("active", "paused") else "active",
        created_at=now,
        updated_at=now,
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return _goal_out(g)


@router.get("", response_model=list[TripGoalOut])
def list_goals(db: Session = Depends(get_db)):
    rows = db.execute(select(TripGoal).order_by(TripGoal.created_at.desc())).scalars()
    return [_goal_out(x) for x in rows]


@router.get("/{goal_id}", response_model=TripGoalOut)
def get_goal(goal_id: str, db: Session = Depends(get_db)):
    g = db.get(TripGoal, goal_id)
    if not g:
        raise HTTPException(404, detail="Trip goal not found.")
    return _goal_out(g)


@router.patch("/{goal_id}", response_model=TripGoalOut)
def patch_goal(goal_id: str, data: dict = Body(...), db: Session = Depends(get_db)):
    g = db.get(TripGoal, goal_id)
    if not g:
        raise HTTPException(404, detail="Trip goal not found.")
    allowed = {
        "origin",
        "destination_preference",
        "budget_usd",
        "start_date",
        "end_date",
        "needs_car",
        "status",
    }
    for k, v in data.items():
        if k not in allowed or v is None:
            continue
        if k == "budget_usd":
            setattr(g, k, Decimal(str(v)))
        elif k == "status" and v not in ("active", "paused"):
            continue
        else:
            setattr(g, k, v)
    g.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(g)
    return _goal_out(g)


@router.post("/{goal_id}/pause", response_model=TripGoalOut)
def pause_goal(goal_id: str, db: Session = Depends(get_db)):
    g = db.get(TripGoal, goal_id)
    if not g:
        raise HTTPException(404, detail="Trip goal not found.")
    g.status = "paused"
    g.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _goal_out(g)


@router.post("/{goal_id}/resume", response_model=TripGoalOut)
def resume_goal(goal_id: str, db: Session = Depends(get_db)):
    g = db.get(TripGoal, goal_id)
    if not g:
        raise HTTPException(404, detail="Trip goal not found.")
    g.status = "active"
    g.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _goal_out(g)


@router.post("/{goal_id}/check-now")
def check_now(goal_id: str, db: Session = Depends(get_db)):
    out = run_check_for_goal(db, goal_id)
    if out.get("error") == "not_found":
        raise HTTPException(404, detail=out.get("message", "not found"))
    return out


@router.get("/{goal_id}/quotes", response_model=QuotesEnvelope)
def get_quotes(goal_id: str, db: Session = Depends(get_db)):
    if not db.get(TripGoal, goal_id):
        raise HTTPException(404, detail="Trip goal not found.")
    mode = settings.provider_mode_public()
    if mode == "NOT_CONNECTED":
        return QuotesEnvelope(
            items=[],
            provider_status="NOT_CONNECTED",
            message=NOT_CONNECTED_MSG,
        )
    rows = list(
        db.execute(
            select(ProviderQuote)
            .where(ProviderQuote.trip_goal_id == goal_id)
            .order_by(desc(ProviderQuote.fetched_at))
        ).scalars()
    )
    return QuotesEnvelope(
        items=[_quote_out(r) for r in rows],
        provider_status=mode,
        message="Demo data — provider not connected." if mode == "DEBUG_DEMO" else None,
    )


@router.get("/{goal_id}/snapshots", response_model=list[PackageSnapshotOut])
def get_snapshots(goal_id: str, db: Session = Depends(get_db)):
    if not db.get(TripGoal, goal_id):
        raise HTTPException(404, detail="Trip goal not found.")
    mode = settings.provider_mode_public()
    if mode == "NOT_CONNECTED":
        return []
    rows = list(
        db.execute(
            select(PackageSnapshot)
            .where(PackageSnapshot.trip_goal_id == goal_id)
            .order_by(desc(PackageSnapshot.created_at))
        ).scalars()
    )
    return [
        PackageSnapshotOut(
            id=s.id,
            trip_goal_id=s.trip_goal_id,
            total_price_usd=float(s.total_price_usd) if s.total_price_usd is not None else None,
            flight_quote_id=s.flight_quote_id,
            stay_quote_id=s.stay_quote_id,
            car_quote_id=s.car_quote_id,
            passed_budget=s.passed_budget,
            constraints=(s.constraints_json or [])[:5],
            created_at=_iso(s.created_at) or "",
            is_demo=bool(s.is_demo),
        )
        for s in rows
    ]
