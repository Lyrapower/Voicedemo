# TripPack — acceptance (SQLite, no Docker)

Generated: 2026-04-25T05:50:02Z

**Result: PASS** — all checks below executed successfully.

## Environment

- `DATABASE_URL` (this run): `sqlite:///data/acceptance.db` (from `trippack_api/` with relative `data/acceptance.db`)
- Modes: `accept_sub.py 0` (DEMO off) then `accept_sub.py 1` (DEMO on), separate processes, fresh `data/acceptance.db` per run of this script.

## Endpoints exercised

- `GET /health` — 200, epoch `ts_ms`
- `GET /ui/dev` — 200, sections: trip goals, quotes, snapshots, alerts
- `GET /provider-status` — `demo_mode`, `providers`, worker timestamps
- `POST /trip-goals`, `POST /trip-goals/{id}/check-now`, `GET /trip-goals/{id}/quotes`, `GET /trip-goals/{id}/package-snapshots`, `GET /alerts`

## Run API locally (demo)

```bash
bash scripts/run_dev_demo.sh
```

Then open: **http://127.0.0.1:8810/ui/dev**

## iOS Simulator

- Open `TripPackAI/TripPackAI.xcodeproj`, run on Simulator.
- **Settings** (DEBUG): set base URL to `http://127.0.0.1:8810`
- **Seed Demo + Check** to pull demo quotes, snapshot, and alerts into SQLite-backed API.

## Sample output (Mode 0)

```json
{
  "mode": 0,
  "lines": [
    "start mode=0",
    "GET /health 200",
    "GET /ui/dev 200",
    "{'demo_mode': False, 'providers': {'flight': 'NOT_CONNECTED', 'stay': 'NOT_CONNECTED', 'car': 'NOT_CONNECTED'}, 'last_worker_run_at_ms': 0, 'next_scheduled_run_at_ms': 0}",
    "check-now 409"
  ],
  "goal_id_a": "f0c89ebb-01f0-41df-8fd4-5ad6bb9a8f1d"
}
```

## Sample output (Mode 1)

```json
{
  "mode": 1,
  "lines": [
    "start mode=1",
    "GET /health 200",
    "GET /ui/dev 200",
    "{'demo_mode': True, 'providers': {'flight': 'DEMO_ONLY', 'stay': 'DEMO_ONLY', 'car': 'DEMO_ONLY'}, 'last_worker_run_at_ms': 0, 'next_scheduled_run_at_ms': 0}",
    "quotes {'items': [{'id': '753c4d4b-fe9a-4977-981d-e0500558b465', 'trip_goal_id': 'b4a49ab3-0b11-40fa-9c00-4346b1489fda', 'component_type': 'flight', 'provider': 'DEMO', 'title': 'Demo round-trip (per person estimate)', 'price': 1158.0, 'currency': 'USD', 'source_url': 'https://example.com/demo-booking?goal=b4a49ab3-0b11-40fa-9c00-4346b1489fda&c=flight', 'fetched_at_ms': 1777096202602, 'status': 'DEMO', 'terms_notes': 'Demo data \u2014 provider not connected'}, {'id': '8de99e65-289b-4ad4-bfb7-4d0a6c81fa46', 'trip_goal_id': 'b4a49ab3-0b11-40fa-9c00-4346b1489fda', 'component_type': 'stay', 'provider': 'DEMO', 'title': 'Demo hotel (5 nights)', 'price': 975.0, 'currency': 'USD', 'source_url': 'https://example.com/demo-booking?goal=b4a49ab3-0b11-40fa-9c00-4346b1489fda&c=stay', 'fetched_at_ms': 1777096202602, 'status': 'DEMO', 'terms_notes': 'Demo data \u2014 provider not connected'}, {'id': '1ffa6aea-92b9-47e6-9f78-9d9219e73ff1', 'trip_goal_id': 'b4a49ab3-0b11-40fa-9c00-4346b1489fda', 'component_type': 'car', 'provider': 'DEMO', 'title': 'Demo rental (5 days)', 'price': 275.0, 'currency': 'USD', 'source_url': 'https://example.com/demo-booking?goal=b4a49ab3-0b11-40fa-9c00-4346b1489fda&c=car', 'fetched_at_ms': 1777096202602, 'status': 'DEMO', 'terms_notes': 'Demo data \u2014 provider not connected'}], 'status': 'DEMO'}"
  ],
  "goal_id_b": "b4a49ab3-0b11-40fa-9c00-4346b1489fda",
  "snapshots": [
    {
      "id": "0a8623ed-e629-4803-ba57-c3463c41dd25",
      "trip_goal_id": "b4a49ab3-0b11-40fa-9c00-4346b1489fda",
      "flight_quote_id": "753c4d4b-fe9a-4977-981d-e0500558b465",
      "stay_quote_id": "8de99e65-289b-4ad4-bfb7-4d0a6c81fa46",
      "car_quote_id": "1ffa6aea-92b9-47e6-9f78-9d9219e73ff1",
      "total_estimate": 2408.0,
      "budget_gap": 5592.0,
      "recommendation": "watch",
      "confidence": 0.75,
      "constraints": [],
      "created_at_ms": 1777096202602
    }
  ],
  "alerts_count": 1
}
```

## Command

```bash
bash scripts/accept.sh --trippack
# or: ACCEPT_TRIPPACK_ONLY=1 bash scripts/accept.sh
```

FINAL_VERDICT: PASS
