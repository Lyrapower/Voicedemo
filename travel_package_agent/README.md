# TripPack AI

**Flight + hotel + car, under budget.**

TripPack AI turns a broad travel need into three complete, bookable-style packages — ranked by score, validated by deterministic Python code, and ready to compare. It does not chat about travel. It helps you decide.

---

## Why this is different from asking ChatGPT or Claude

| ChatGPT / Claude | TripPack AI |
|---|---|
| Suggests destinations | Builds full packages with flight + hotel + car |
| Budget is a suggestion | Budget is enforced by deterministic code |
| Output is text | Output is ranked, decision-ready package cards |
| Numbers may be hallucinated | All math is calculated, not generated |
| No rejection logic | Over-budget and low-rating options are filtered out |

---

## V0 Limitations

- Uses deterministic mock data (no real flight/hotel/car APIs)
- No user accounts or saved searches
- No real booking — all links are placeholders
- Taxes/fees are estimated at 12% flat
- Destination pool is limited to 6 cities

---

## Future Hard Parts

- **Real-time flight API** — live pricing, seat availability, fare classes
- **Hotel inventory** — availability by date, room types, cancellation policies
- **Rental car data** — provider APIs, pick-up locations, insurance options
- **Taxes/fees accuracy** — varies by destination, airline, hotel, and car type
- **Cancellation policy parsing** — unstructured text from multiple sources
- **Affiliate links** — partner integrations and revenue tracking
- **Price monitoring** — detect and alert on fare drops
- **Booking liability** — legal and compliance for real transactions

---

## Install

```bash
cd travel_package_agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

Open: http://127.0.0.1:8000

## Test

```bash
pytest tests/ -v
```

## Acceptance

```bash
bash accept.sh
```

Expected output:
```
ACCEPTANCE PASS
Top packages: 3
Budget respected: YES
Rejected packages visible: YES
```
