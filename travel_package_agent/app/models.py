from pydantic import BaseModel
from typing import Optional, List
from datetime import date


class TripRequest(BaseModel):
    origin: str = "San Diego"
    budget: float = 5000.0
    earliest_departure: date = date(2026, 5, 8)
    latest_return: date = date(2026, 5, 22)
    travelers: int = 1
    style: str = "Best Value"
    rental_car_required: bool = True
    destination_preference: str = "Any"


class FlightOption(BaseModel):
    destination: str
    airline: str
    departure_date: date
    return_date: date
    price_per_person: float
    flight_quality_score: float
    booking_url: str


class HotelOption(BaseModel):
    destination: str
    hotel_name: str
    nightly_rate: float
    rating: float
    location_score: float
    booking_url: str


class CarOption(BaseModel):
    destination: str
    provider: str
    daily_rate: float
    booking_url: str


class TravelPackage(BaseModel):
    destination: str
    destination_type: str = "Any"
    departure_date: date
    return_date: date
    nights: int
    flight: FlightOption
    hotel: HotelOption
    car: Optional[CarOption] = None
    flight_total: float
    hotel_total: float
    car_total: float
    taxes_fees: float
    buffer: float
    total_cost: float
    budget_remaining: float
    pass_fail: str
    score: float = 0.0
    explanation: str = ""
    rank_label: str = ""
    fail_reason: Optional[str] = None


class SearchResult(BaseModel):
    request: TripRequest
    top_packages: List[TravelPackage]
    rejected_packages: List[TravelPackage]
