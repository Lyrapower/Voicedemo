"""
Deterministic mock data for TripPack AI V0.

Default scenario: $5,000 budget · San Diego origin · May 8–22 2026 · 1 traveler · rental car required.
  PASS:  Maui, Seattle, Denver
  FAIL:  Cancun (over budget), New York (hotel rating 3.8 < 4.0), Vancouver (dep before window)
"""

from datetime import date
from app.models import FlightOption, HotelOption, CarOption

DESTINATION_TYPES: dict[str, str] = {
    "Maui": "Beach",
    "Seattle": "City",
    "Denver": "Nature",
    "Cancun": "Beach",
    "New York": "City",
    "Vancouver": "City",
}

DESTINATION_SUBTITLES: dict[str, str] = {
    "Maui": "Hawaii, USA",
    "Seattle": "Washington, USA",
    "Denver": "Colorado, USA",
    "Cancun": "Mexico",
    "New York": "New York, USA",
    "Vancouver": "BC, Canada",
}

FLIGHTS: list[FlightOption] = [
    FlightOption(
        destination="Maui",
        airline="Hawaiian Airlines",
        departure_date=date(2026, 5, 9),
        return_date=date(2026, 5, 22),
        price_per_person=650.0,
        flight_quality_score=4.2,
        booking_url="https://flights.example.com/maui-mock",
    ),
    FlightOption(
        destination="Seattle",
        airline="Alaska Airlines",
        departure_date=date(2026, 5, 10),
        return_date=date(2026, 5, 21),
        price_per_person=285.0,
        flight_quality_score=4.0,
        booking_url="https://flights.example.com/seattle-mock",
    ),
    FlightOption(
        destination="Denver",
        airline="Southwest Airlines",
        departure_date=date(2026, 5, 8),
        return_date=date(2026, 5, 20),
        price_per_person=218.0,
        flight_quality_score=3.9,
        booking_url="https://flights.example.com/denver-mock",
    ),
    # FAIL — over budget
    FlightOption(
        destination="Cancun",
        airline="United Airlines",
        departure_date=date(2026, 5, 10),
        return_date=date(2026, 5, 22),
        price_per_person=520.0,
        flight_quality_score=4.5,
        booking_url="https://flights.example.com/cancun-mock",
    ),
    # FAIL — hotel rating below 4.0
    FlightOption(
        destination="New York",
        airline="JetBlue",
        departure_date=date(2026, 5, 12),
        return_date=date(2026, 5, 20),
        price_per_person=310.0,
        flight_quality_score=3.7,
        booking_url="https://flights.example.com/nyc-mock",
    ),
    # FAIL — departure before earliest window (May 5 < May 8)
    FlightOption(
        destination="Vancouver",
        airline="Air Canada",
        departure_date=date(2026, 5, 5),
        return_date=date(2026, 5, 19),
        price_per_person=340.0,
        flight_quality_score=3.8,
        booking_url="https://flights.example.com/yvr-mock",
    ),
]

HOTELS: list[HotelOption] = [
    HotelOption(
        destination="Maui",
        hotel_name="Wailea Beach Resort",
        nightly_rate=185.0,
        rating=4.6,
        location_score=4.8,
        booking_url="https://hotels.example.com/wailea-mock",
    ),
    HotelOption(
        destination="Seattle",
        hotel_name="Hotel Theodore",
        nightly_rate=158.0,
        rating=4.3,
        location_score=4.5,
        booking_url="https://hotels.example.com/theodore-mock",
    ),
    HotelOption(
        destination="Denver",
        hotel_name="The Maven Hotel",
        nightly_rate=165.0,
        rating=4.2,
        location_score=4.4,
        booking_url="https://hotels.example.com/maven-mock",
    ),
    HotelOption(
        destination="Cancun",
        hotel_name="Hotel Riu Cancun",
        nightly_rate=280.0,
        rating=4.7,
        location_score=4.9,
        booking_url="https://hotels.example.com/riu-mock",
    ),
    # FAIL — rating 3.8 below 4.0 minimum
    HotelOption(
        destination="New York",
        hotel_name="The Moxy NYC Times Square",
        nightly_rate=210.0,
        rating=3.8,
        location_score=4.6,
        booking_url="https://hotels.example.com/moxy-mock",
    ),
    HotelOption(
        destination="Vancouver",
        hotel_name="Fairmont Pacific Rim",
        nightly_rate=170.0,
        rating=4.5,
        location_score=4.7,
        booking_url="https://hotels.example.com/fairmont-mock",
    ),
]

CARS: list[CarOption] = [
    CarOption(destination="Maui", provider="Alamo", daily_rate=48.0,
              booking_url="https://cars.example.com/maui-mock"),
    CarOption(destination="Seattle", provider="Enterprise", daily_rate=40.0,
              booking_url="https://cars.example.com/seattle-mock"),
    CarOption(destination="Denver", provider="Budget", daily_rate=44.0,
              booking_url="https://cars.example.com/denver-mock"),
    CarOption(destination="Cancun", provider="Hertz", daily_rate=52.0,
              booking_url="https://cars.example.com/cancun-mock"),
    CarOption(destination="New York", provider="Avis", daily_rate=62.0,
              booking_url="https://cars.example.com/nyc-mock"),
    CarOption(destination="Vancouver", provider="National", daily_rate=42.0,
              booking_url="https://cars.example.com/yvr-mock"),
]


def get_flights_by_dest() -> dict[str, FlightOption]:
    return {f.destination: f for f in FLIGHTS}


def get_hotels_by_dest() -> dict[str, HotelOption]:
    return {h.destination: h for h in HOTELS}


def get_cars_by_dest() -> dict[str, CarOption]:
    return {c.destination: c for c in CARS}
