# Weekly OCR sync (Mac Photos → OCR_Text_Inbox)

Standalone automation. **Does not modify** `inbox_export.py`, `build_monthly.py`, or existing month folders.

## Folder layout

```
~/Desktop/OCR_Text_Inbox/
  2026-06/                          ← month of screenshot date
    {uuid}.md                        ← one per screenshot
    _weekly_2026-05-20_2026-05-26.md
    _weekly_2026-05-20_2026-05-26.json
    _weekly_2026-05-27_2026-05-31.md
    _monthly_review.md               ← rebuilt after each week
  2026-07/
  ocr_index.json                     ← all months (via build_monthly_auto.py)
```

Week windows are **non-overlapping 7-day chunks** (e.g. 5/20–5/26, then 5/27–5/31).

## Manual runs (Terminal.app — grant Photos to Terminal)

```bash
cd ~/Desktop/demo
bash scripts/ocr_text_inbox/run_weekly_sync.sh
```

```bash
# Specific week
.venv_ocr_inbox/bin/python scripts/ocr_text_inbox/weekly_sync.py --week 2026-05-20 2026-05-26

# Whole calendar month, split into ~7-day weeks
.venv_ocr_inbox/bin/python scripts/ocr_text_inbox/weekly_sync.py --month 2026-06

# From 2026-06-01 through today, week by week
.venv_ocr_inbox/bin/python scripts/ocr_text_inbox/weekly_sync.py --catch-up-from 2026-06-01

# Rebuild monthly reviews + ocr_index only
.venv_ocr_inbox/bin/python scripts/ocr_text_inbox/weekly_sync.py --rebuild-monthly
```

## Automatic schedule (every Sunday 10:00)

Processes **previous Monday–Sunday** screenshots.

```bash
cd ~/Desktop/demo
bash scripts/ocr_text_inbox/install_weekly_launchd.sh
```

Uninstall:

```bash
launchctl bootout "gui/$(id -u)/com.ocr_text_inbox.weekly"
rm ~/Library/LaunchAgents/com.ocr_text_inbox.weekly.plist
```

## Logs

- `~/Desktop/OCR_Text_Inbox/weekly_sync.log`
- `~/Desktop/OCR_Text_Inbox/weekly_launchd.out.log` (if using launchd)

## Notes

- Skips `.md` that already exist (same screenshot UUID).
- Uses Chinese-capable OCR (`zh-Hans`, `zh-Hant`, `en-US`) via existing `inbox_export` helpers.
- **Image-heavy screenshots** (photos / almost no text) are **not scanned** by default. Vision fast-pass decides before OCR. Disable with `OCR_SKIP_IMAGE_SCREENSHOTS=0`.
- Legacy months (2025-08 … 2026-05) are unchanged unless you run weekly sync for dates in those months.
