# RadarBrief — 30–120 Second Demo Script

**Audience:** Reviewer / stakeholder. **Goal:** Show runnable app and voice brief.

---

## 30-second version

1. **"I'll start the backend and open the app."**  
   Run: `MPLCONFIGDIR="./.mplconfig" ./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000`  
   Open: http://127.0.0.1:8000/dashboard

2. **"This is the landing screen."**  
   Point: Welcome / 欢迎, two buttons.  
   Click **Start**.

3. **"Radar: today's mood, top three items, and one tap to play the brief."**  
   Point: Today, Top 3 cards, **Play Brief**.  
   Click **Play voice brief** (or go to Brief tab → Generate → Play).  
   Let 10–20 seconds of audio play.

4. **"Settings: watchlist, crypto toggle, language — all persisted."**  
   Open Settings tab, show fields, optionally change language and Save.

5. **"No JSON or debug on the main UI; that's in Details."**  
   Expand one **Details** on Radar to show Trust/Sources, then collapse.

---

## 60–120 second version (add these)

- **Language:** Switch to 中文 on Landing or in Settings; show Radar/Brief in Chinese.
- **Brief tab:** Click **Generate** → show script → **Play voice brief** (CN or EN).
- **Tier:** Switch Mode chip to Tier1 or Tier2; show Top 3 / Today Snapshot (and Tier2 strip if visible).
- **iOS (if available):** Open Xcode project, Run on iPhone; show same flow in WKWebView and in-app Settings for Base URL.

**Outro:** "Everything you see is from real public sources; if a feed is down we show 'Source not connected' — no mock data."

---

# Voice MVP — 30–120 Second Demo Script

**Audience:** Reviewer / stakeholder. **Goal:** Show record → analyze → outcome → neighbors → predict (behavior tracking; no strong conclusions without enough data).

## 30-second version

1. **"I'll start the backend and open the Voice app."**  
   Run: `MPLCONFIGDIR="./.mplconfig" ./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000`  
   Open: http://127.0.0.1:8000/

2. **"Landing: record a short clip."**  
   Click **Start** → speak a few seconds → **Stop**.  
   Point: "Upload ok", recording_id, **Analyze** enabled.

3. **"Analyze: spectrogram and readable feature cards."**  
   Click **Analyze**. Point: image, Feature Schema, Analyze Features (no raw JSON on main view).

4. **"Label outcome, then similar sessions and predict."**  
   Click **Happened** or **Not Happened**.  
   Click **Find Similar Sessions** (table or "Need more labeled data").  
   Click **Predict** ("Need more data" or experimental P(success) + confidence).

5. **"Dashboard has the same in one view."**  
   Open http://127.0.0.1:8000/dashboard — latest recording, spectrogram, hit rate, neighbors, predict, history, schema.

## 60–120 second version (add these)

- **Intent tag:** Type an optional intent before recording; show it in history.
- **Health:** Open http://127.0.0.1:8000/healthz.html — "Service Healthy".
- **API:** Open http://127.0.0.1:8000/docs — show /predict/latest, /features/schema; explain debug/advanced stays in API, not main UI.

**Outro:** "We only show a prediction when there's enough labeled data; otherwise we clearly say 'Need more data'."
