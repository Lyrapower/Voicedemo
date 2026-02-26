# 10-Minute Acceptance Checklist

Use this for a quick review. Answer Yes/No; if No, note the issue.

## Voice MVP

| # | Check | Yes/No | Notes |
|---|--------|--------|--------|
| 1 | Backend starts: `uvicorn main:app --host 127.0.0.1 --port 8000` | | |
| 2 | http://127.0.0.1:8000/ loads (Voice UI: Start/Stop, Analyze, etc.) | | |
| 3 | http://127.0.0.1:8000/dashboard loads (cards, no raw JSON on main view) | | |
| 4 | Record → Upload → Analyze shows spectrogram and feature cards (readable) | | |
| 5 | Predict shows "Need more data" when labeled < N; or P(success) + confidence when sufficient | | |
| 6 | Neighbors shows table or "Need more labeled data"; no JSON dump on main UI | | |
| 7 | Feature schema and version visible (e.g. Feature Schema card or /features/schema) | | |
| 8 | Debug/technical info only in collapsible or API (e.g. /docs, /predict/latest) | | |
| 9 | config/scoring_config.yml exists or app runs with defaults | | |
| 10 | docs/HANDOFF.md, VERIFY.md, CHANGELOG.md, DEMO/DEMO_SCRIPT.md exist | | |

## Repo hygiene

| # | Check | Yes/No | Notes |
|---|--------|--------|--------|
| 11 | No secrets in repo; .env in .gitignore, .env.example present | | |
| 12 | assets/screenshots/ has evidence (≥3 for UI); assets/demo/ or README for demo artifacts | | |

**Sign-off:** All Yes = ready for handoff. Any No = list in Notes and fix before sign-off.
