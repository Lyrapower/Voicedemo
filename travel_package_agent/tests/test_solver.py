"""
Tests for the deterministic package solver.
Budget validation is done by Python code, never by an LLM.
"""

import pytest
from datetime import date
from app.models import TripRequest
from app.solver import solve


DEFAULT_REQUEST = TripRequest(
    origin="San Diego",
    budget=5000.0,
    earliest_departure=date(2026, 5, 8),
    latest_return=date(2026, 5, 22),
    travelers=1,
    style="Best Value",
    rental_car_required=True,
    destination_preference="Any",
)


def test_default_scenario_returns_three_pass_packages():
    result = solve(DEFAULT_REQUEST)
    assert len(result.top_packages) >= 3, (
        f"Expected at least 3 PASS packages, got {len(result.top_packages)}"
    )


def test_no_top_package_exceeds_budget():
    result = solve(DEFAULT_REQUEST)
    for pkg in result.top_packages:
        assert pkg.total_cost <= DEFAULT_REQUEST.budget, (
            f"{pkg.destination}: total_cost {pkg.total_cost} exceeds budget {DEFAULT_REQUEST.budget}"
        )


def test_all_top_packages_have_flight_hotel_car():
    result = solve(DEFAULT_REQUEST)
    for pkg in result.top_packages:
        assert pkg.flight is not None, f"{pkg.destination} missing flight"
        assert pkg.hotel is not None, f"{pkg.destination} missing hotel"
        assert pkg.car is not None, f"{pkg.destination} missing car"


def test_all_top_packages_have_taxes_fees_and_buffer():
    result = solve(DEFAULT_REQUEST)
    for pkg in result.top_packages:
        assert pkg.taxes_fees > 0, f"{pkg.destination} taxes_fees is 0"
        assert pkg.buffer > 0, f"{pkg.destination} buffer is 0"


def test_rejected_list_has_at_least_two():
    result = solve(DEFAULT_REQUEST)
    assert len(result.rejected_packages) >= 2, (
        f"Expected >= 2 rejected packages, got {len(result.rejected_packages)}"
    )


def test_total_cost_math():
    """Verify that cost formula is applied correctly (using Maui mock data)."""
    result = solve(DEFAULT_REQUEST)
    for pkg in result.top_packages:
        expected_taxes = round(
            (pkg.flight_total + pkg.hotel_total + pkg.car_total) * 0.12, 2
        )
        expected_total = round(
            pkg.flight_total + pkg.hotel_total + pkg.car_total
            + expected_taxes + pkg.buffer,
            2,
        )
        assert abs(pkg.taxes_fees - expected_taxes) < 0.02, (
            f"{pkg.destination}: taxes_fees mismatch. "
            f"Got {pkg.taxes_fees}, expected {expected_taxes}"
        )
        assert abs(pkg.total_cost - expected_total) < 0.02, (
            f"{pkg.destination}: total_cost mismatch. "
            f"Got {pkg.total_cost}, expected {expected_total}"
        )


def test_budget_fail_detected():
    """A very tight budget should produce failures."""
    tight_request = TripRequest(
        origin="San Diego",
        budget=100.0,
        earliest_departure=date(2026, 5, 8),
        latest_return=date(2026, 5, 22),
        travelers=1,
        style="Cheapest Valid",
        rental_car_required=False,
        destination_preference="Any",
    )
    result = solve(tight_request)
    assert len(result.top_packages) == 0, "Expected 0 PASS packages with $100 budget"
    assert len(result.rejected_packages) > 0


def test_hotel_rating_fail():
    """New York should fail because hotel rating is 3.8 (below 4.0 minimum)."""
    result = solve(DEFAULT_REQUEST)
    nyc_rejected = [p for p in result.rejected_packages if p.destination == "New York"]
    assert len(nyc_rejected) == 1, "New York should be in rejected list"
    assert "rating" in nyc_rejected[0].fail_reason.lower() or "4.0" in nyc_rejected[0].fail_reason


def test_rental_car_optional_mode():
    """Without rental car, car_total should be 0 and car field None."""
    no_car_request = TripRequest(
        origin="San Diego",
        budget=5000.0,
        earliest_departure=date(2026, 5, 8),
        latest_return=date(2026, 5, 22),
        travelers=1,
        style="Best Value",
        rental_car_required=False,
        destination_preference="Any",
    )
    result = solve(no_car_request)
    assert len(result.top_packages) >= 3, "Should still have 3 packages without car"
    for pkg in result.top_packages:
        assert pkg.car is None, f"{pkg.destination}: car should be None when not required"
        assert pkg.car_total == 0.0, f"{pkg.destination}: car_total should be 0"


def test_top_packages_ordered_by_score():
    result = solve(DEFAULT_REQUEST)
    scores = [p.score for p in result.top_packages]
    assert scores == sorted(scores, reverse=True), (
        f"Top packages not sorted by score: {scores}"
    )


def test_buffer_is_minimum_150():
    result = solve(DEFAULT_REQUEST)
    for pkg in result.top_packages:
        assert pkg.buffer >= 150.0, f"{pkg.destination}: buffer {pkg.buffer} is below 150"


def test_comfort_style_respects_budget():
    comfort_request = TripRequest(
        origin="San Diego",
        budget=5000.0,
        earliest_departure=date(2026, 5, 8),
        latest_return=date(2026, 5, 22),
        travelers=1,
        style="Comfort",
        rental_car_required=True,
        destination_preference="Any",
    )
    result = solve(comfort_request)
    for pkg in result.top_packages:
        assert pkg.total_cost <= 5000.0, (
            f"Comfort style: {pkg.destination} exceeds budget: {pkg.total_cost}"
        )
