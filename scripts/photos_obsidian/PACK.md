# PhotoTextVault pipeline — consolidated pack

## What this is

- **EXPORT_MODE**: OCR images from a folder you exported from Photos (or any tree of PNG/JPEG/HEIC/etc.).
- **PHOTOS_MODE**: Discover indexed **screen captures** via Spotlight (`mdfind`), then optionally try a **Photos AppleScript** export from a **Screenshots** album. It does **not** assume direct reads inside `*.photoslibrary` work.

Output vault: `~/Obsidian/PhotoTextVault/`  
Per image: **one** `markdown/<slug>_<id>.md` and **one** `text/<slug>_<id>.txt`.

## Files in this pack

| Path | Role |
|------|------|
| `scripts/photos_obsidian/pipeline.py` | Main pipeline (EXPORT / PHOTOS / DRY_RUN / CLEAN) |
| `scripts/photos_obsidian/accept.sh` | Acceptance checks + single-image guard |
| `scripts/photos_obsidian/PACK.md` | This document |
| `photos_screenshots_to_obsidian.py` (repo root) | Thin wrapper → runs `pipeline.py` |

## Commands

### Dry-run (no OCR writes; writes `_logs/dry_run_report.json`)

```bash
cd /Users/ciciwang/Desktop/demo
DRY_RUN=1 PHOTOS_MODE=1 python3 scripts/photos_obsidian/pipeline.py
```

Or export folder:

```bash
cd /Users/ciciwang/Desktop/demo
DRY_RUN=1 EXPORT_MODE=1 EXPORT_ROOT="$HOME/Desktop/PhotosExport" python3 scripts/photos_obsidian/pipeline.py
```

### Real run — **recommended** (exported originals from Photos)

1. In **Photos**: select items → **File → Export → Export Unmodified Originals** → e.g. `~/Desktop/PhotosExport` (use **2+** images for default acceptance).
2. Clean + run:

```bash
cd /Users/ciciwang/Desktop/demo
CLEAN=1 EXPORT_MODE=1 EXPORT_ROOT="$HOME/Desktop/PhotosExport" python3 scripts/photos_obsidian/pipeline.py
```

### Real run — Photos / iCloud discovery (Spotlight + optional album export)

```bash
cd /Users/ciciwang/Desktop/demo
CLEAN=1 PHOTOS_MODE=1 python3 scripts/photos_obsidian/pipeline.py
```

If nothing is found, the script exits with code **3** and writes `~/Obsidian/PhotoTextVault/_logs/unknown.txt` with **UNKNOWN** and exact actions.

### Acceptance

```bash
chmod +x /Users/ciciwang/Desktop/demo/scripts/photos_obsidian/accept.sh
/Users/ciciwang/Desktop/demo/scripts/photos_obsidian/accept.sh
```

To allow a **single-image** smoke test:

```bash
ALLOW_SINGLE_TEST=1 /Users/ciciwang/Desktop/demo/scripts/photos_obsidian/accept.sh
```

### Optional: Shortcuts CLI

If you build a Shortcut named e.g. `ExportPhotosToFolder` that writes originals into `~/Desktop/PhotosExport`, run it **before** `EXPORT_MODE`:

```bash
shortcuts run "ExportPhotosToFolder"
```

(Then use `EXPORT_MODE` as above.)

## Expected **PASS** output (accept.sh)

When `processed_count >= 2` and outputs match:

```
---- VAULT COUNTS ----
markdown_count=2
text_count=2
manifest_processed_count=2
first_md_bytes=1234
PASS
```

(Exact numbers depend on your export.)

## Expected **FAIL** examples

- Only one file processed and `ALLOW_SINGLE_TEST` unset → `FAIL: only one image processed...`
- `markdown_count != processed_count` → count mismatch **FAIL**
- Missing manifest → **FAIL**
- PHOTOS_MODE with no Spotlight hits and no album export → pipeline exits **3** and `unknown.txt` describes **UNKNOWN** + actions

## Date range

Pipeline filters by image date (EXIF when available, else mtime) to **2025-08-01 … 2026-04-23** (edit constants at top of `pipeline.py` if needed).
