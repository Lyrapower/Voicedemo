# Voice MVP — Evidence Screenshots

Capture these **≥3** screenshots for handoff/demo evidence. Name files exactly as below.

## Required (name clearly)

1. **voice-landing.png**  
   - **How:** Open http://127.0.0.1:8000/ with backend running.  
   - **Shows:** Voice UI with Start / Stop, optional intent tag, recording_id area, Baseline / Analyze Features / Neighbors / Predict / History cards (or "No data yet").

2. **voice-dashboard.png**  
   - **How:** Open http://127.0.0.1:8000/dashboard  
   - **Shows:** Latest Recording, Spectrogram image, Hit Rate, Neighbors, Predict, Feature Schema, History (readable cards/tables; no raw JSON on main view).

3. **voice-predict.png**  
   - **How:** After at least one Analyze (and optionally Outcome), click **Predict** on http://127.0.0.1:8000/ or view Predict card on dashboard.  
   - **Shows:** Either "Need more data" (with available/required counts) or Experimental P(success) + LOO/Bootstrap + confidence (no JSON dump on main UI).

## How to capture

- **macOS:** Cmd+Shift+4 (region) or Cmd+Shift+5 (screenshot tool). Save into `assets/screenshots/` with the names above.
- **Browser:** Ensure backend is running; use http://127.0.0.1:8000 (not https, not localhost if you had issues).

## Checklist

- [ ] voice-landing.png
- [ ] voice-dashboard.png
- [ ] voice-predict.png
