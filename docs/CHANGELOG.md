# Changelog

## 2026-02-26 — Voice deliverables + demo pack

- Updated `docs/HANDOFF.md`: added Voice MVP run steps and links (/, /dashboard, /predict/latest, /features/schema, healthz.html)
- Updated `docs/VERIFY.md`: Voice MVP Yes/No checklist (10 items) + repo hygiene; no main-UI JSON
- Updated `docs/CHANGELOG.md`: this entry
- Updated `docs/DEMO/DEMO_SCRIPT.md`: added Voice 30–120s demo script (record → analyze → outcome → neighbors → predict)
- Added `assets/screenshots/VOICE_README.md`: required Voice screenshots (voice-landing, voice-dashboard, voice-predict) and how to capture
- Updated `assets/demo/README.md`: added Voice MVP section for screen recording and optional audio capture
- Confirmed `.env` in `.gitignore` and `.env.example` present; no secrets committed

## 2026-02-25 — Deliverables + demo pack

- Added required deliverable structure: `docs/HANDOFF.md`, `docs/VERIFY.md`, `docs/CHANGELOG.md`, `docs/DEMO/DEMO_SCRIPT.md`
- Added `assets/screenshots/` with evidence screenshots (Radar, Brief, Settings, iOS wrapper)
- Added `assets/demo/` and `assets/demo/README.md` (how to generate screen recording and audio samples)
- Added `.gitignore` (`.env`, `.venv`, `__pycache__`, data/upload/generated artifacts, Xcode user data)
- Added `.env.example` for `TRADIER_TOKEN` (optional for Tier2 options)
- Repo initialized; commit format: "RadarBrief Phase - deliverables + demo pack"

## Previous (summary)

- RadarBrief V1: FastAPI backend, static dashboard (Radar/Brief/Settings), bilingual, TTS brief, Tier1/Tier2, SQLite, SEC/options proxy
- iOS wrapper: SwiftUI + WKWebView, Config via Info.plist + in-app Settings, RELEASE.md for Archive/TestFlight
