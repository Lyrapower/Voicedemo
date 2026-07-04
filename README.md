# RadarBrief V1

FastAPI + lightweight frontend for Radar / Brief / Settings with bilingual UI, voice brief, Tier gating, and rule-based impact mapping.

## Run (fixed local endpoint)

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
MPLCONFIGDIR="./.mplconfig" ./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open:
- `http://127.0.0.1:8000/dashboard`

## Storage and schema

- SQLite: `data/radarbrief_v1.sqlite3`
- schema_version: `1` (table `app_meta`)
- persisted settings: `data/radar_settings.json`
- quick recap daily limiter: `data/quick_recap_log.json`

## Data pipeline

1. Pull public sources (macro official, SEC EDGAR, mainstream RSS, options proxy links)
2. Normalize + dedupe into rule-based event cards
3. Store structured cards in SQLite
4. Render plain-language cards in UI
5. Generate and play brief via TTS endpoint

If a source is unavailable, UI shows plain text: `Source not connected` / `数据源未连接`.

## Source connectors (current)

- Macro official: Fed / BLS / BEA feeds
- SEC: EDGAR current filings feeds (8-K, 13D/13G, Form 4)
- Mainstream RSS: Reuters / CNBC / MarketWatch / Yahoo Finance / Investing
- Options verified proxy: Tradier docs + Cboe historical volume link

## TTS

- Endpoint: `POST /radarbrief/tts`
- Uses neural voices with language switch (zh/en)
- Falls back with plain text status when voice source is unavailable

## Future integration hooks

- Real options chain scoring connector: `_collect_public_sources()` options block
- SEC filings enrichment mapping: `_collect_public_sources()` sec block
- IAP/Paywall state machine hooks:
  - frontend: `static/dashboard.html` buttons `restoreBtn`, `manageBtn`
  - backend: add entitlement checks in `/radarbrief/state` and `/radarbrief/brief`

## Compliance note

The product is informational only and does not provide buy/sell calls, target prices, or return guarantees.

## iOS Wrapper (SwiftUI + WKWebView)

Wrapper project path:
- `ios-wrapper/RadarBriefIOS`

Open in Xcode:
- `ios-wrapper/RadarBriefIOS/RadarBriefIOS.xcodeproj`

Run flow:
1. Start backend:
   ```bash
   MPLCONFIGDIR="./.mplconfig" ./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```
2. In Xcode target `RadarBriefIOS`, configure Signing & Capabilities:
   - Automatically manage signing ON
   - Team = your Apple developer team
   - Bundle ID = `com.lyra.airadar` (or unique if conflict)
3. Select iPhone and press Run.

Base URL config:
- `Resources/Info.plist` keys:
  - `DEV_URL`
  - `PROD_URL`
  - `BASE_URL`
- In-app Settings allows overriding base URL.

Release/TestFlight:
- See `RELEASE.md`.

## Jarvis workbench (sole entry — `platform_main`)

The command above starts **Radar** (`main:app` on port 8000). The **Jarvis** UI, automation registry, and `/health` live on **`app.platform_main:app`** only:

```bash
./scripts/start_jarvis.sh
# or:
python3 -m uvicorn app.platform_main:app --host 127.0.0.1 --port 8686
```

- Workbench: `http://127.0.0.1:8686/ui/overview`
- Automation tasks: `http://127.0.0.1:8686/api/jarvis/tasks`
- Health JSON: `http://127.0.0.1:8686/health` or `/healthz`
- Merge map: `deliver/jarvis/JARVIS_MERGE_MAP.md`

**Do not** use `app.main:app` for Jarvis — that is the Pack 4 Grid Router (default :8792) without trading/crypto UI.
