"""
Package solver — all budget validation done by deterministic Python code.
The LLM never decides whether a package passes or fails budget.
"""

from app.models import TripRequest, TravelPackage, SearchResult
from app.mock_data import (
    get_flights_by_dest,
    get_hotels_by_dest,
    get_cars_by_dest,
    DESTINATION_TYPES,
)

DESTINATIONS = ["Maui", "Seattle", "Denver", "Cancun", "New York", "Vancouver"]

RANK_LABELS = ["Best Match", "Comfort Pick", "Cheapest Valid"]


def _calculate_score(pkg: TravelPackage, request: TripRequest) -> float:
    """Score a PASS package. Higher is better. LLM-free."""
    if pkg.pass_fail != "PASS":
        return 0.0

    savings_pct = (request.budget - pkg.total_cost) / request.budget
    hotel_rating = pkg.hotel.rating
    flight_q = pkg.flight.flight_quality_score

    if request.style == "Cheapest Valid":
        score = savings_pct * 60 + hotel_rating * 5 + flight_q * 3
    elif request.style == "Comfort":
        score = hotel_rating * 20 + flight_q * 10 + savings_pct * 20
    else:  # Best Value (default)
        score = savings_pct * 35 + hotel_rating * 12 + flight_q * 6

    # Destination preference bonus
    if request.destination_preference != "Any":
        if pkg.destination_type == request.destination_preference:
            score += 15

    return round(score, 2)


def _generate_explanation(pkg: TravelPackage, request: TripRequest) -> str:
    remaining = pkg.budget_remaining
    rating = pkg.hotel.rating
    dest_type = pkg.destination_type

    if remaining > 1500:
        budget_text = f"leaves a strong ${remaining:,.0f} budget cushion"
    elif remaining > 800:
        budget_text = f"stays ${remaining:,.0f} comfortably under budget"
    else:
        budget_text = f"comes in ${remaining:,.0f} under budget"

    pref_text = ""
    if request.destination_preference != "Any" and dest_type == request.destination_preference:
        pref_text = f"matches your {request.destination_preference.lower()} preference, "

    vibe = ""
    if dest_type == "Beach":
        vibe = " with beach access"
    elif dest_type == "Nature":
        vibe = " with mountain and nature access"
    elif dest_type == "City":
        vibe = " with urban exploration"

    return (
        f"This package {pref_text}{budget_text}{vibe}, "
        f"a {rating}-star hotel, and a {pkg.flight.flight_quality_score:.1f}/5 flight score."
    )


def solve(request: TripRequest) -> SearchResult:
    """
    Build and validate all candidate packages. Return top 3 PASS + rejected list.
    Budget PASS/FAIL is determined entirely by deterministic arithmetic — never by an LLM.
    """
    flights = get_flights_by_dest()
    hotels = get_hotels_by_dest()
    cars = get_cars_by_dest()

    passed: list[TravelPackage] = []
    rejected: list[TravelPackage] = []

    for dest in DESTINATIONS:
        flight = flights.get(dest)
        hotel = hotels.get(dest)
        if not flight or not hotel:
            continue

        car = cars.get(dest) if request.rental_car_required else None

        nights = (flight.return_date - flight.departure_date).days
        rental_days = nights

        # --- Deterministic cost calculation ---
        flight_total = round(flight.price_per_person * request.travelers, 2)
        hotel_total = round(hotel.nightly_rate * nights, 2)
        car_total = round(car.daily_rate * rental_days, 2) if car else 0.0
        taxes_fees = round((flight_total + hotel_total + car_total) * 0.12, 2)
        buffer = max(150.0, round(request.budget * 0.05, 2))
        total_cost = round(flight_total + hotel_total + car_total + taxes_fees + buffer, 2)
        budget_remaining = round(request.budget - total_cost, 2)

        # --- Deterministic PASS/FAIL rules ---
        fail_reasons: list[str] = []
        if total_cost > request.budget:
            fail_reasons.append(f"Over budget by ${total_cost - request.budget:,.0f}")
        if flight.departure_date < request.earliest_departure:
            fail_reasons.append("Departure before your earliest date")
        if flight.return_date > request.latest_return:
            fail_reasons.append("Return after your latest date")
        if nights < 4:
            fail_reasons.append("Trip too short (minimum 4 nights)")
        if hotel.rating < 4.0:
            fail_reasons.append(f"Hotel rating {hotel.rating} is below 4.0 minimum")

        pass_fail = "PASS" if not fail_reasons else "FAIL"
        fail_reason = "; ".join(fail_reasons) if fail_reasons else None

        pkg = TravelPackage(
            destination=dest,
            destination_type=DESTINATION_TYPES.get(dest, "Any"),
            departure_date=flight.departure_date,
            return_date=flight.return_date,
            nights=nights,
            flight=flight,
            hotel=hotel,
            car=car,
            flight_total=flight_total,
            hotel_total=hotel_total,
            car_total=car_total,
            taxes_fees=taxes_fees,
            buffer=buffer,
            total_cost=total_cost,
            budget_remaining=budget_remaining,
            pass_fail=pass_fail,
            fail_reason=fail_reason,
        )

        pkg.score = _calculate_score(pkg, request)
        pkg.explanation = _generate_explanation(pkg, request)

        if pass_fail == "PASS":
            passed.append(pkg)
        else:
            rejected.append(pkg)

    # Sort PASS packages by score descending
    passed.sort(key=lambda p: p.score, reverse=True)

    top_3 = passed[:3]
    for i, pkg in enumerate(top_3):
        pkg.rank_label = RANK_LABELS[i] if i < len(RANK_LABELS) else f"#{i + 1}"

    return SearchResult(
        request=request,
        top_packages=top_3,
        rejected_packages=rejected,
    )
