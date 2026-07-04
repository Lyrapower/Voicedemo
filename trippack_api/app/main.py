import html
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
import uuid

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, SessionLocal, Base, engine
from app.db_models import TripGoal, ProviderQuote, PackageSnapshot, DealAlert
from app.routers import health, provider_status, trip_goals, alerts
from app.services.check_now import run_check_for_goal, NOT_CONNECTED_MSG


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _make_seed_goal() -> TripGoal:
    now = datetime.now(timezone.utc)
    return TripGoal(
        id=str(uuid.uuid4()),
        origin="San Diego",
        destination_preference="Maui",
        budget_usd=Decimal("5000"),
        start_date="2026-06-01",
        end_date="2026-06-10",
        needs_car=True,
        status="active",
        created_at=now,
        updated_at=now,
    )


def _ensure_demo_seed() -> None:
    if settings.resolved_backend_mode() != "DEBUG_DEMO":
        return
    db = SessionLocal()
    try:
        if db.execute(select(TripGoal.id).limit(1)).first():
            return
        g = _make_seed_goal()
        db.add(g)
        db.commit()
        run_check_for_goal(db, g.id)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.database_url.lower().startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    _ensure_demo_seed()
    yield


app = FastAPI(title="TripPackAI Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(provider_status.router)
app.include_router(trip_goals.router)
app.include_router(alerts.router)


@app.get("/", response_class=HTMLResponse)
def backend_home(db: Session = Depends(get_db)):
    mode = settings.provider_mode_public()
    mode_note = {
        "DEBUG_DEMO": "Backend is in DEBUG_DEMO — demo quotes may appear with disclosure.",
        "NOT_CONNECTED": NOT_CONNECTED_MSG,
        "CONNECTED": "Provider connection asserted; no fake live prices are returned from this build.",
    }.get(mode, "")

    goal = (
        db.execute(
            select(TripGoal)
            .where(TripGoal.status == "active")
            .order_by(desc(TripGoal.updated_at))
            .limit(1)
        )
        .scalars()
        .first()
    )
    latest_goal = goal
    if not latest_goal:
        latest_goal = (
            db.execute(select(TripGoal).order_by(desc(TripGoal.updated_at)).limit(1))
            .scalars()
            .first()
        )

    quotes_html = "<p>No quotes stored for the latest goal.</p>"
    snap_html = "<p>No package snapshot yet.</p>"
    alert_html = "<p>No alerts yet.</p>"
    gid = ""
    if latest_goal:
        gid = latest_goal.id
        quotes = list(
            db.execute(
                select(ProviderQuote)
                .where(ProviderQuote.trip_goal_id == latest_goal.id)
                .order_by(desc(ProviderQuote.fetched_at))
                .limit(6)
            ).scalars()
        )
        if quotes:
            rows = []
            for q in quotes:
                p = (
                    f"${float(q.price_usd):,.0f}"
                    if q.price_usd is not None
                    else "— (no price)"
                )
                rows.append(
                    f"<li>{html.escape(q.category)} · {html.escape(q.provider)} · "
                    f"{html.escape(q.title)} · {p} · "
                    f"<a href=\"{html.escape(q.source_url, quote=True)}\">source</a></li>"
                )
            quotes_html = "<ul>" + "".join(rows) + "</ul>"
        elif mode == "NOT_CONNECTED":
            quotes_html = f"<p>{html.escape(NOT_CONNECTED_MSG)}</p>"

        snap = (
            db.execute(
                select(PackageSnapshot)
                .where(PackageSnapshot.trip_goal_id == latest_goal.id)
                .order_by(desc(PackageSnapshot.created_at))
                .limit(1)
            )
            .scalars()
            .first()
        )
        if snap:
            tot = (
                f"${float(snap.total_price_usd):,.0f}"
                if snap.total_price_usd is not None
                else "—"
            )
            snap_html = (
                f"<p><strong>Current package estimate:</strong> {tot} (created {_iso(snap.created_at)})</p>"
                f"<p>Constraints: {html.escape(str((snap.constraints_json or [])[:5]))}</p>"
            )

        alert = (
            db.execute(
                select(DealAlert)
                .where(DealAlert.trip_goal_id == latest_goal.id)
                .order_by(desc(DealAlert.created_at))
                .limit(1)
            )
            .scalars()
            .first()
        )
        if alert:
            alert_html = (
                f"<p><strong>{html.escape(alert.title)}</strong><br/>"
                f"{html.escape(alert.why_triggered)}<br/>{_iso(alert.created_at)}</p>"
            )

    goal_block = "<p>No trip goals yet. Create one via the TripPackAI app or API.</p>"
    if latest_goal:
        goal_block = (
            f"<p><strong>Latest goal</strong> ({latest_goal.status})<br/>"
            f"{html.escape(latest_goal.origin)} → {html.escape(latest_goal.destination_preference)} · "
            f"budget ${float(latest_goal.budget_usd):,.0f} · "
            f"{html.escape(latest_goal.start_date)}–{html.escape(latest_goal.end_date)}</p>"
            f"<p>Last check: {_iso(latest_goal.last_checked_at)} · Next check: {_iso(latest_goal.next_check_at)}</p>"
        )

    check_section = ""
    if gid and latest_goal and latest_goal.status == "active":
        check_section = f"""
        <button type="button" id="chk">Check Now</button>
        <script>
        document.getElementById('chk').onclick = async function() {{
          this.disabled = true;
          try {{
            await fetch('/trip-goals/{gid}/check-now', {{ method: 'POST' }});
          }} catch (e) {{}}
          location.reload();
        }};
        </script>
        """

    body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>TripPackAI Backend</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  max-width: 720px; margin: 40px auto; padding: 0 20px; color: #101828; background: #f6f3ee; }}
.card {{ background: #fff; border-radius: 20px; padding: 24px; box-shadow: 0 10px 30px rgba(0,0,0,.08); }}
h1 {{ font-size: 1.5rem; }}
.status {{ color: #067647; font-weight: 600; }}
.note {{ color: #667085; font-size: 0.9rem; margin-top: 12px; }}
button {{ margin-top: 12px; padding: 12px 20px; border-radius: 14px; border: none;
  background: #0e7490; color: white; font-weight: 600; cursor: pointer; }}
button:disabled {{ opacity: 0.5; }}
</style></head><body>
<div class="card">
<h1>TripPackAI Backend</h1>
<p class="status">status: OK</p>
<p><strong>Provider mode:</strong> {html.escape(mode)}</p>
<p class="note">{html.escape(mode_note)}</p>
<p class="note">Prices can change. Final booking price is confirmed by the provider.</p>
<hr/>
{goal_block}
<h2>Latest quotes</h2>
{quotes_html}
<h2>Latest package estimate</h2>
{snap_html}
<h2>Latest alert</h2>
{alert_html}
<hr/>
{check_section}
<p class="note">API: <code>/health</code>, <code>/provider-status</code>, <code>/trip-goals</code>, <code>/alerts</code></p>
</div>
</body></html>"""
    return HTMLResponse(content=body)
