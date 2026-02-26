# Demo — How to Run + What You Should See

This repo includes **RadarBrief** (dashboard, brief, settings) and **Voice MVP** (record, analyze, predict). Same backend; different entry points.

---

## Prerequisites

- Python 3.10+
- Xcode (for iOS wrapper; optional for web-only)

## 1. Backend (required for web and iOS)

```bash
cd /path/to/demo
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
MPLCONFIGDIR="./.mplconfig" ./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

- Server: `http://127.0.0.1:8000`
- Health: http://127.0.0.1:8000/healthz.html

---

## 2a. Voice MVP — What to run and see

| Step | URL / Action | What you see |
|------|----------------|---------------|
| 1 | Open **http://127.0.0.1:8000/** | Voice UI: Start / Stop, optional intent tag, recording_id after upload |
| 2 | Click **Start** → speak → **Stop** | Status: "Upload ok"; Analyze button enabled |
| 3 | Click **Analyze** | Spectrogram image; Feature Schema + Analyze Features cards (readable, no raw JSON on main view) |
| 4 | Click **Happened** or **Not Happened** | Outcome saved; Baseline and History update |
| 5 | Click **Find Similar Sessions** | Neighbors table or "Need more labeled data" |
| 6 | Click **Predict** | Either "Need more data" (if labeled < N) or experimental P(success) + LOO/Bootstrap + confidence |
| 7 | Open **http://127.0.0.1:8000/dashboard** | Dashboard: latest recording, spectrogram, hit rate, neighbors, predict, history, feature schema |
| 8 | Open **http://127.0.0.1:8000/predict/latest** | JSON for latest recording prediction (API; debug) |
| 9 | Open **http://127.0.0.1:8000/features/schema** | Feature schema version and fields (API) |

- No JSON or tech terms on main UI; debug/advanced only in collapsible or API.
- Config: `config/scoring_config.yml` (e.g. MIN_LABELED_FOR_HINT, TOPK). If missing, defaults apply.

---

## 2b. RadarBrief — What to run and see

- Open: **http://127.0.0.1:8000/dashboard** (RadarBrief landing if that is the default route; otherwise use the RadarBrief-specific path documented in README).
- Landing → Start → Radar (Today, Top 3, Play Brief), tabs Radar | Brief | Settings.
- Brief: Generate → Play voice brief. Settings: Watchlist, Crypto toggle, Language; Save.
- Debug only in collapsible Details.

---

## 3. iOS Wrapper (optional)

- Xcode: **ios-wrapper/RadarBriefIOS/RadarBriefIOS.xcodeproj**
- Signing: Automatically manage signing ON, Team = your Apple ID, Bundle ID = `com.lyra.airadar` (or unique)
- Select iPhone → Run. App loads backend URL (set in app Settings). Backend must be running.

---

## Links (validated)

- Voice home: http://127.0.0.1:8000/
- Voice dashboard: http://127.0.0.1:8000/dashboard
- Voice predict (latest): http://127.0.0.1:8000/predict/latest
- Feature schema: http://127.0.0.1:8000/features/schema
- Health (HTML): http://127.0.0.1:8000/healthz.html
- API docs: http://127.0.0.1:8000/docs
