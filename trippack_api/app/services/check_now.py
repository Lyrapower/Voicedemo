from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db_models import TripGoal, ProviderQuote, PackageSnapshot, DealAlert, utcnow
from app.providers.demo import DemoProvider
from app.providers.not_connected import NotConnectedProvider
from app.providers.connected_stub import ConnectedStubProvider

NOT_CONNECTED_MSG = "Provider not connected. No live quotes shown."


def _pick_provider():
    mode = settings.provider_mode_public()
    if mode == "DEBUG_DEMO":
        return DemoProvider(), "DEBUG_DEMO"
    if mode == "CONNECTED":
        return ConnectedStubProvider(), "CONNECTED"
    return NotConnectedProvider(), "NOT_CONNECTED"


def _goal_ctx(goal: TripGoal) -> dict:
    nights = 5
    try:
        if goal.start_date and goal.end_date:
            from datetime import date as date_cls

            a = date_cls.fromisoformat(goal.start_date[:10])
            b = date_cls.fromisoformat(goal.end_date[:10])
            d = (b - a).days
            if d > 0:
                nights = max(1, d)
    except Exception:
        pass
    return {
        "id": goal.id,
        "check_count": goal.check_count or 0,
        "travelers": 2,
        "nights_hint": nights,
        "budget_usd": float(goal.budget_usd or 0),
        "needs_car": bool(goal.needs_car),
    }


def _constraints_for(
    goal: TripGoal,
    fp: float,
    sp: float,
    cp: float,
    total: float | None,
    *,
    passed_budget: bool | None,
    is_demo: bool,
) -> list[str]:
    out: list[str] = []
    budget = float(goal.budget_usd or 0)
    if total is not None and budget > 0 and total > budget:
        out.append(f"Over budget by ${(total - budget):,.0f}")
    if goal.needs_car and cp <= 0:
        out.append("Rental car requested but no car option in this snapshot.")
    if total is None or total <= 0:
        out.append("No package estimate yet for this check.")
    if passed_budget is True and len(out) < 5:
        out.append("Why not selected: other dates or sources may still be a better fit.")
    if is_demo and len(out) < 5:
        out.append("Demo data — provider not connected.")
    return out[:5]


def run_check_for_goal(db: Session, goal_id: str) -> dict:
    goal = db.get(TripGoal, goal_id)
    if not goal:
        return {"ok": False, "error": "not_found", "message": "Trip goal not found."}
    if goal.status != "active":
        return {
            "ok": True,
            "provider_status": settings.provider_mode_public(),
            "message": "Watch is paused; no check performed.",
        }

    provider, pstatus = _pick_provider()
    now = utcnow()

    if pstatus == "NOT_CONNECTED":
        goal.last_checked_at = now
        goal.next_check_at = None
        goal.check_count = (goal.check_count or 0) + 1
        goal.updated_at = now
        db.commit()
        return {
            "ok": True,
            "provider_status": "NOT_CONNECTED",
            "message": NOT_CONNECTED_MSG,
        }

    if pstatus == "CONNECTED":
        quotes = provider.fetch_quotes(_goal_ctx(goal))
        goal.last_checked_at = now
        goal.next_check_at = None
        goal.check_count = (goal.check_count or 0) + 1
        goal.updated_at = now
        for p in quotes:
            db.add(
                ProviderQuote(
                    id=str(uuid.uuid4()),
                    trip_goal_id=goal.id,
                    category=p.category,
                    provider=p.provider,
                    title=p.title,
                    price_usd=Decimal(str(p.price_usd)) if p.price_usd is not None else None,
                    currency=p.currency,
                    source_url=p.source_url,
                    fetched_at=now,
                    terms_notes=p.terms_notes,
                    is_demo=p.is_demo,
                    is_live=p.is_live,
                )
            )
        db.commit()
        return {
            "ok": True,
            "provider_status": "CONNECTED",
            "message": "Provider connected; no live quotes returned yet.",
        }

    # DEBUG_DEMO
    ctx = _goal_ctx(goal)
    payloads = provider.fetch_quotes(ctx)
    goal.check_count = (goal.check_count or 0) + 1
    for p in payloads:
        db.add(
            ProviderQuote(
                id=str(uuid.uuid4()),
                trip_goal_id=goal.id,
                category=p.category,
                provider=p.provider,
                title=p.title,
                price_usd=Decimal(str(p.price_usd)) if p.price_usd is not None else None,
                currency=p.currency,
                source_url=p.source_url,
                fetched_at=now,
                terms_notes=p.terms_notes,
                is_demo=True,
                is_live=False,
            )
        )
    db.flush()

    rows = list(
        db.execute(
            select(ProviderQuote)
            .where(ProviderQuote.trip_goal_id == goal.id)
            .order_by(ProviderQuote.fetched_at.desc())
        ).scalars()
    )
    f_best = next((q for q in rows if q.category == "flight"), None)
    s_best = next((q for q in rows if q.category == "stay"), None)
    c_best = next((q for q in rows if q.category == "car"), None) if goal.needs_car else None

    fp = float(f_best.price_usd) if f_best and f_best.price_usd is not None else 0.0
    sp = float(s_best.price_usd) if s_best and s_best.price_usd is not None else 0.0
    cp = float(c_best.price_usd) if c_best and c_best.price_usd is not None else 0.0
    if not goal.needs_car:
        cp = 0.0
    total = fp + sp + (cp if goal.needs_car else 0.0)
    budget = float(goal.budget_usd or 0)
    passed = budget > 0 and total <= budget
    const = _constraints_for(
        goal, fp, sp, cp, total, passed_budget=passed, is_demo=True
    )

    snap = PackageSnapshot(
        id=str(uuid.uuid4()),
        trip_goal_id=goal.id,
        total_price_usd=Decimal(str(round(total, 2))) if total > 0 else None,
        flight_quote_id=f_best.id if f_best else None,
        stay_quote_id=s_best.id if s_best else None,
        car_quote_id=c_best.id if c_best else None,
        passed_budget=passed if budget > 0 else None,
        constraints_json=const,
        created_at=now,
        is_demo=True,
    )
    db.add(snap)

    if budget > 0 and total <= budget and total > 0:
        exists = (
            db.execute(
                select(DealAlert.id).where(DealAlert.trip_goal_id == goal.id).limit(1)
            ).first()
        )
        if not exists:
            db.add(
                DealAlert(
                    id=str(uuid.uuid4()),
                    trip_goal_id=goal.id,
                    snapshot_id=snap.id,
                    title="Package within budget (demo)",
                    why_triggered="Demo estimate total is at or below your Trip Watch budget.",
                    source_url=f_best.source_url if f_best else None,
                    is_read=False,
                    created_at=now,
                    is_demo=True,
                )
            )

    goal.last_checked_at = now
    goal.next_check_at = now + timedelta(minutes=20)
    goal.updated_at = now
    db.commit()

    return {
        "ok": True,
        "provider_status": "DEBUG_DEMO",
        "message": "Demo data — provider not connected.",
    }
