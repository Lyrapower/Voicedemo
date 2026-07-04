"""
Deterministic demo quotes: seed = trip_goal_id + check_count.
DEBUG_DEMO only.
"""

import hashlib
from datetime import datetime, timezone

from app.providers.base import TripQuotesProvider, QuotePayload

DEMO_NOTE = "Demo data — provider not connected."


def _drift(goal_id: str, run_count: int, salt: str) -> float:
    h = hashlib.sha256(f"{goal_id}:{run_count}:{salt}".encode()).hexdigest()
    return int(h[:6], 16) % 400


class DemoProvider(TripQuotesProvider):
    def fetch_quotes(self, ctx: dict) -> list[QuotePayload]:
        gid = ctx["id"]
        rc = int(ctx.get("check_count", 0))
        now = datetime.now(timezone.utc)
        travelers = max(1, int(ctx.get("travelers", 2)))
        nights = max(3, int(ctx.get("nights_hint", 5)))
        base_f = 400 + _drift(gid, rc, "flight")
        flight_total = float(base_f * travelers)
        nightly = 120 + (_drift(gid, rc, "stay") % 80)
        stay_total = float(nightly * nights)
        days = nights
        daily = 35 + (_drift(gid, rc, "car") % 25)
        car_total = float(daily * days)
        out = [
            QuotePayload(
                category="flight",
                provider="DEMO",
                title="Demo round-trip (estimate)",
                price_usd=flight_total,
                currency="USD",
                source_url=f"https://example.com/demo-source?goal={gid}&c=flight",
                terms_notes=DEMO_NOTE,
                is_demo=True,
                is_live=False,
            ),
            QuotePayload(
                category="stay",
                provider="DEMO",
                title=f"Demo stay ({nights} nights)",
                price_usd=stay_total,
                currency="USD",
                source_url=f"https://example.com/demo-source?goal={gid}&c=stay",
                terms_notes=DEMO_NOTE,
                is_demo=True,
                is_live=False,
            ),
        ]
        if ctx.get("needs_car"):
            out.append(
                QuotePayload(
                    category="car",
                    provider="DEMO",
                    title=f"Demo rental ({days} days)",
                    price_usd=car_total,
                    currency="USD",
                    source_url=f"https://example.com/demo-source?goal={gid}&c=car",
                    terms_notes=DEMO_NOTE,
                    is_demo=True,
                    is_live=False,
                )
            )
        return out
