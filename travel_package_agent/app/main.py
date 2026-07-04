import re
import json
from datetime import date
from typing import Optional
from markupsafe import Markup

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.models import TripRequest
from app.solver import solve

app = FastAPI(title="TripPack AI")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


# ── Jinja2 filters ────────────────────────────────────────────────────────────

def _dateformat(value, fmt: str = "%b %d") -> str:
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return value.strftime(fmt)


def _dest_slug(destination: str) -> str:
    return "dest-" + destination.lower().replace(" ", "-")


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _tojson(value) -> Markup:
    return Markup(json.dumps(value, ensure_ascii=False))

templates.env.filters["dateformat"] = _dateformat
templates.env.filters["dest_slug"] = _dest_slug
templates.env.filters["money"] = _money
templates.env.filters["tojson"] = _tojson


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    origin: str = Form("San Diego"),
    budget: float = Form(5000.0),
    earliest_departure: str = Form("2026-05-08"),
    latest_return: str = Form("2026-05-22"),
    travelers: int = Form(1),
    style: str = Form("Best Value"),
    rental_car_required: Optional[str] = Form(None),
    destination_preference: str = Form("Any"),
):
    trip_req = TripRequest(
        origin=origin,
        budget=budget,
        earliest_departure=date.fromisoformat(earliest_departure),
        latest_return=date.fromisoformat(latest_return),
        travelers=travelers,
        style=style,
        rental_car_required=rental_car_required is not None,
        destination_preference=destination_preference,
    )
    result = solve(trip_req)
    return templates.TemplateResponse(
        "results.html",
        {"request": request, "result": result},
    )


@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})


@app.get("/review-notes", response_class=HTMLResponse)
async def review_notes(request: Request):
    return templates.TemplateResponse("review_notes.html", {"request": request})


@app.post("/parse-request")
async def parse_request(text: str = Form(...)):
    """
    Lightweight regex/keyword parser for voice or typed natural language.
    Returns structured fields to pre-fill the form — no LLM involved.
    """
    text_lower = text.lower()

    # Budget
    budget = 5000.0
    budget_match = re.search(r"\$?([\d,]+)", text)
    if budget_match:
        candidate = float(budget_match.group(1).replace(",", ""))
        if candidate >= 500:
            budget = candidate

    # Origin
    origin = "San Diego"
    origin_match = re.search(
        r"from\s+([A-Za-z\s]+?)(?:\s+in\s|\s+to\s|\s+during\s|,|\.)", text, re.IGNORECASE
    )
    if origin_match:
        origin = origin_match.group(1).strip()

    # Dates — May window heuristics
    earliest = date(2026, 5, 8)
    latest = date(2026, 5, 22)
    if "second" in text_lower and "third" in text_lower:
        earliest, latest = date(2026, 5, 8), date(2026, 5, 22)
    elif "second week" in text_lower:
        earliest, latest = date(2026, 5, 8), date(2026, 5, 15)
    elif "third week" in text_lower:
        earliest, latest = date(2026, 5, 15), date(2026, 5, 22)

    # Destination preference
    preference = "Any"
    if "beach" in text_lower:
        preference = "Beach"
    elif "city" in text_lower or "urban" in text_lower:
        preference = "City"
    elif "nature" in text_lower or "mountain" in text_lower or "hiking" in text_lower:
        preference = "Nature"

    # Rental car
    rental_car = any(
        kw in text_lower for kw in ["rental car", "rent a car", "need a car", "with a car"]
    )

    return JSONResponse({
        "budget": budget,
        "origin": origin,
        "earliest_departure": earliest.isoformat(),
        "latest_return": latest.isoformat(),
        "travelers": 1,
        "style": "Best Value",
        "rental_car_required": rental_car,
        "destination_preference": preference,
    })
