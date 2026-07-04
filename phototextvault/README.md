# PhotoTextVault

Turn exported Photos screenshots into clean, monthly Markdown at the vault root (plus `raw_text/` and `logs/` for support only).

## Quick start

```bash
bash phototextvault/accept.sh
```

```bash
python3 -m phototextvault.export \
  --source-folder "$HOME/Desktop/PhotosExport" \
  --start 2025-08-01 \
  --end 2026-04-23 \
  --monthly \
  --out-dir "$HOME/Obsidian/PhotoTextVault"
```

Single month file (`--end` is **exclusive**):

```bash
python3 -m phototextvault.export \
  --source-folder "$HOME/Desktop/PhotosExport" \
  --start 2025-08-01 \
  --end 2025-09-01 \
  --out "$HOME/Obsidian/PhotoTextVault/2025-08_to_2025-09.md"
```

## Direct Photos / iCloud

UNKNOWN: direct Photos access not verified. Export screenshots from Photos to `~/Desktop/PhotosExport`, then use `--source-folder` as above.

## Flags

- `--include-jpg` — include JPEG files
- `--include-all-images` — all PNG/JPEG under the tree (skip screenshot filename heuristic)

## OCR

Install: `pip install -r phototextvault/requirements.txt` (macOS: `ocrmac` + Vision). Optional fallback: `pytesseract` and system Tesseract (`brew install tesseract`).
