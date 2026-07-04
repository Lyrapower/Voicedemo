# ChatGPT → Obsidian exporter

Personal-account bulk and one-click export for ChatGPT conversations into a fixed monthly vault layout. Uses **browser automation / DOM extraction** for bulk export and a **localhost HTTP receiver** for the bookmarklet. This is **not** a private reverse-engineered ChatGPT API client.

## Vault layout

Target (expand `~`):

- `~/Obsidian/ChatGPTVault/markdown/` — monthly `.md` files only  
- `~/Obsidian/ChatGPTVault/raw_json/YYYY-MM/` — one JSON file per conversation (archival)  
- `~/Obsidian/ChatGPTVault/unresolved_dates.log` — conversations whose `conversation_date` could not be resolved (not placed in monthly markdown)

Configured in `config.yaml`.

## Environment setup

- **Python** 3.10+ recommended  
- **Playwright Chromium** — installed via `playwright install chromium` after pip  
- **macOS / Linux / Windows** — paths use `~` expansion via `config.yaml`

## Dependency installation

```bash
cd chatgpt_exporter
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

Run all CLI scripts from the `chatgpt_exporter/` directory so imports resolve.

## How to run bulk export (Phase 1)

1. Ensure `config.yaml` `date_range` matches the window you want (default `2025-08-01` … `2026-03-31`).  
2. Start Chromium via Playwright, sign in when prompted:

```bash
cd chatgpt_exporter
python3 bulk_export_chatgpt.py
```

3. In the opened window, **log in** to your personal ChatGPT account (Projects enabled).  
4. Return to the terminal and **press Enter** to start enumeration.

The script will:

- Scroll the sidebar / history to reduce missed lazy-loaded items  
- Visit Library / Projects-style URLs (`/library`, `/projects`, `/g/…`) to include **personal Project chats** where links appear in the DOM  
- Open each `/c/…` conversation, scrape `[data-message-author-role]` turns and optional `time[datetime]`  
- Resolve `conversation_date` from embedded `__NEXT_DATA__` JSON when present, else visible `datetime` attributes — **never fabricates** a date; unresolved items go to `raw_json/_unresolved/` and `unresolved_dates.log`  
- Filter by `date_range` for raw JSON + markdown (out-of-range conversations are skipped)

## How to start the receiver (Phase 2)

```bash
cd chatgpt_exporter
python3 capture_receiver.py
```

Listens on `http://127.0.0.1:8765/capture` per `config.yaml`. Keep this running while using the bookmarklet.

## How to install the bookmarklet

1. Open `browser/chatgpt_export_bookmarklet.js` in this repo.  
2. Copy the entire IIFE.  
3. Create a new bookmark; set the URL to:

   `javascript:` + paste the minified or single-line version of the same code.

   For a quick test without minifying, you can prefix the file contents with `javascript:` and wrap in `void(function(){ ... })();` — avoid newlines in the bookmark URL if your browser rejects them (use a minifier).

4. On a **chatgpt.com** conversation page, click the bookmark. You should see a success alert when the receiver accepts the payload.

## How to test regular chat export

1. Open any non-project chat whose URL contains `/c/<id>`.  
2. Run `capture_receiver.py`.  
3. Click the bookmarklet.  
4. Confirm `raw_json/YYYY-MM/<id>.json` exists and the correct `markdown/YYYY-MM.md` gained a new `## Conversation:` block (or `duplicate_skipped` on repeat).

## How to test Project chat export

1. Open a chat that lives under a Project (URL typically contains `/g/`).  
2. Click the bookmarklet with the receiver running.  
3. Confirm `is_project_chat: true` in the saved JSON when the UI exposes project context, and `project_id` / `project_name` when detectable from the DOM.

## Known limitations

- **ChatGPT’s DOM changes frequently** — selectors live in `bulk_export_chatgpt.py` (`SELECTORS`) and in the bookmarklet; you may need to adjust them after UI updates.  
- **Conversation dates** come from embedded page JSON (`__NEXT_DATA__`) or visible `datetime` nodes only; if neither yields a day, `conversation_date` is `null` and the conversation is **not** merged into monthly markdown (see `unresolved_dates.log`).  
- **Lazy loading** may still miss some history items if the sidebar does not load them into the DOM; scroll heuristics are best-effort.  
- **Playwright** is used for bulk export; use non-headless mode for login (`--headless` is optional and awkward for sign-in).  
- **CORS** is open (`*`) on the local receiver for bookmarklet `fetch`; use only on a trusted machine.

## How to repair selectors if ChatGPT DOM changes

1. **Bulk export:** edit the `SELECTORS` dict near the top of `bulk_export_chatgpt.py`:  
   - `history_links` — anchors pointing at `/c/…` conversations  
   - `sidebar_scroll_candidates` — element that scrolls to load older history  
   - `message_turn` — should match each message row (`[data-message-author-role]` is the current primary)  
   - `markdown_content` — inner prose container for each turn  

2. **Bookmarklet:** mirror the same logic in `browser/chatgpt_export_bookmarklet.js` (`querySelector` / `querySelectorAll` strings).  

3. Re-run a single conversation in the browser DevTools console by pasting the bookmarklet body to verify nodes match.

## Schema

- Export JSON shape is validated by `browser_payload_schema.py` (required keys only; no extra keys added by the exporter).  
- Future memory-graph contracts are documented in `memory_schema_contract.json` (not generated by this tool).

## Files

| File | Role |
|------|------|
| `config.yaml` | Vault paths, date range, receiver port |
| `bulk_export_chatgpt.py` | Playwright bulk export |
| `monthly_writer.py` | Monthly markdown merge, sorting, dedupe |
| `capture_receiver.py` | Flask `POST /capture` |
| `browser_payload_schema.py` | Payload validation / normalization |
| `utils.py` | Dates, paths, dedupe keys, markdown helpers |
| `memory_schema_contract.json` | Future architecture placeholders |
