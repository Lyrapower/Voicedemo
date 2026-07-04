# Obsidian vault deliverables

This project writes ChatGPT exports into a personal Obsidian vault with a fixed structure.

## Directory layout

```
~/Obsidian/ChatGPTVault/
  markdown/
    2025-08.md
    2025-09.md
    …
    2026-03.md
  raw_json/
    2025-08/
    …
    2026-03/
  unresolved_dates.log   (optional; created when dates cannot be resolved)
```

## Rules

- Markdown lives **only** under `markdown/`.  
- Raw JSON lives **only** under `raw_json/YYYY-MM/` (plus `raw_json/_unresolved/` when `conversation_date` is null).  
- No JSON inside `.md` files.  
- Monthly files are named `YYYY-MM.md` and contain sorted conversations for that calendar month only.

## Tooling

Implemented under repository paths:

- `chatgpt_exporter/` — Python package (bulk export, receiver, writers, schema)  
- `browser/chatgpt_export_bookmarklet.js` — Phase 2 one-click capture  

See `chatgpt_exporter/README.md` for operation.
