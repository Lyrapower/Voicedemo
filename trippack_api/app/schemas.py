from pydantic import BaseModel, Field
from typing import Any, Literal

ProviderMode = Literal["DEBUG_DEMO", "NOT_CONNECTED", "CONNECTED"]


class TripGoalCreate(BaseModel):
    origin: str = ""
    destination_preference: str = ""
    budget_usd: float = 0
    start_date: str = ""
    end_date: str = ""
    needs_car: bool = False
    status: str = "active"


class TripGoalPatch(BaseModel):
    origin: str | None = None
    destination_preference: str | None = None
    budget_usd: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    needs_car: bool | None = None
    status: str | None = None


class TripGoalOut(BaseModel):
    id: str
    origin: str
    destination_preference: str
    budget_usd: float
    start_date: str
    end_date: str
    needs_car: bool
    status: str
    created_at: str
    updated_at: str
    last_checked_at: str | None = None
    next_check_at: str | None = None


class ProviderQuoteOut(BaseModel):
    id: str
    trip_goal_id: str
    category: str
    provider: str
    title: str
    price_usd: float | None
    currency: str
    source_url: str
    fetched_at: str
    terms_notes: str | None = None
    is_demo: bool = False
    is_live: bool = False


class QuotesEnvelope(BaseModel):
    items: list[ProviderQuoteOut]
    provider_status: ProviderMode | str
    message: str | None = None


class PackageSnapshotOut(BaseModel):
    id: str
    trip_goal_id: str
    total_price_usd: float | None
    flight_quote_id: str | None
    stay_quote_id: str | None
    car_quote_id: str | None
    passed_budget: bool | None
    constraints: list[str] = Field(default_factory=list)
    created_at: str
    is_demo: bool = False


class DealAlertOut(BaseModel):
    id: str
    trip_goal_id: str
    snapshot_id: str | None
    title: str
    why_triggered: str
    source_url: str | None
    is_read: bool
    created_at: str
    is_demo: bool = False


class ProviderStatusOut(BaseModel):
    provider_mode: str
    backend_mode: str
    message: str | None = None
