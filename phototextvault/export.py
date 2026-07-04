"""CLI: export screenshots to monthly Obsidian Markdown."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Set

from phototextvault import dates, filters, ocr, writer


def _parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def _collect_images(root: Path) -> List[Path]:
    out: List[Path] = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p)
    return sorted(out, key=lambda x: str(x))


def run_monthly(
    *,
    source_folder: Path,
    clip_start: date,
    clip_end_inclusive: date,
    out_dir: Path,
    include_jpg: bool,
    include_all_images: bool,
) -> int:
    log_lines: List[str] = []
    if not source_folder.is_dir():
        print(f"ERROR: source folder not found: {source_folder}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw_text"
    log_dir = out_dir / "logs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    for legacy in ("markdown", "text"):
        lp = out_dir / legacy
        if lp.is_dir():
            shutil.rmtree(lp, ignore_errors=True)
            log_lines.append(f"removed_legacy_dir:{lp}")

    seen: Set[str] = set()
    entries: List[Dict[str, Any]] = []
    ocr_attempts = 0

    for path in _collect_images(source_folder):
        ok, reason = filters.should_process(
            path,
            include_jpg=include_jpg,
            include_all_png=include_all_images,
        )
        if not ok:
            log_lines.append(f"skip_filter:{path}:{reason}")
            continue
        try:
            if path.stat().st_size <= 0:
                log_lines.append(f"skip_zero_byte:{path}")
                continue
        except OSError as e:
            log_lines.append(f"skip_stat:{path}:{e}")
            continue

        shot = dates.resolve_screenshot_date(path)
        if shot is None:
            log_lines.append(f"skip_no_date:{path}")
            continue
        if not (clip_start <= shot <= clip_end_inclusive):
            log_lines.append(f"skip_out_of_range:{path}:{shot}")
            continue

        ocr_attempts += 1
        try:
            text, engine = ocr.ocr_image(path)
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

        if not text.strip():
            log_lines.append(f"skip_empty_ocr:{path}")
            continue

        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        dedupe_key = f"{shot.isoformat()}|{h}"
        if dedupe_key in seen:
            log_lines.append(f"duplicate_skipped:{path}")
            continue
        seen.add(dedupe_key)

        entries.append(
            {
                "path": str(path.resolve()),
                "filename": path.name,
                "shot_date": shot,
                "ocr": text,
                "engine": engine,
            }
        )

    if ocr_attempts > 0 and not entries:
        print(
            "ERROR: Screenshots matched filters and date range but OCR produced no usable text. "
            "Check image clarity, OCR permissions, and engine install.",
            file=sys.stderr,
        )
        return 3

    source_label = "exported Photos folder"
    writer.write_monthly_bundle(
        out_dir,
        raw_dir,
        log_dir,
        entries=entries,
        source_label=source_label,
        log_lines=log_lines,
    )

    print(f"OK: processed {len(entries)} screenshot(s) into monthly files.", flush=True)
    return 0


def run_single(
    *,
    source_folder: Path,
    range_start: date,
    range_end_exclusive: date,
    out_file: Path,
    include_jpg: bool,
    include_all_images: bool,
) -> int:
    log_lines: List[str] = []
    if not source_folder.is_dir():
        print(f"ERROR: source folder not found: {source_folder}", file=sys.stderr)
        return 1

    out_file.parent.mkdir(parents=True, exist_ok=True)
    base = out_file.parent
    raw_dir = base / "raw_text"
    log_dir = base / "logs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    seen: Set[str] = set()
    entries: List[Dict[str, Any]] = []
    ocr_attempts = 0

    for path in _collect_images(source_folder):
        ok, reason = filters.should_process(
            path,
            include_jpg=include_jpg,
            include_all_png=include_all_images,
        )
        if not ok:
            log_lines.append(f"skip_filter:{path}:{reason}")
            continue
        try:
            if path.stat().st_size <= 0:
                log_lines.append(f"skip_zero_byte:{path}")
                continue
        except OSError as e:
            log_lines.append(f"skip_stat:{path}:{e}")
            continue

        shot = dates.resolve_screenshot_date(path)
        if shot is None:
            log_lines.append(f"skip_no_date:{path}")
            continue
        if not (range_start <= shot < range_end_exclusive):
            log_lines.append(f"skip_out_of_range:{path}:{shot}")
            continue

        ocr_attempts += 1
        try:
            text, engine = ocr.ocr_image(path)
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

        if not text.strip():
            log_lines.append(f"skip_empty_ocr:{path}")
            continue

        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        dedupe_key = f"{shot.isoformat()}|{h}"
        if dedupe_key in seen:
            log_lines.append(f"duplicate_skipped:{path}")
            continue
        seen.add(dedupe_key)

        entries.append(
            {
                "path": str(path.resolve()),
                "filename": path.name,
                "shot_date": shot,
                "ocr": text,
                "engine": engine,
            }
        )

    if ocr_attempts > 0 and not entries:
        print(
            "ERROR: Screenshots matched filters and date range but OCR produced no usable text. "
            "Check image clarity, OCR permissions, and engine install.",
            file=sys.stderr,
        )
        return 3

    source_label = "exported Photos folder"
    writer.write_single_range(
        out_file,
        raw_dir,
        log_dir,
        range_start=range_start,
        range_end_exclusive=range_end_exclusive,
        entries=entries,
        source_label=source_label,
        log_lines=log_lines,
    )

    print(f"OK: processed {len(entries)} screenshot(s) into {out_file}.", flush=True)
    return 0


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PhotoTextVault: screenshots → monthly Markdown")
    ap.add_argument("--source-folder", type=str, required=True)
    ap.add_argument("--start", type=str, required=True, help="Inclusive YYYY-MM-DD")
    ap.add_argument(
        "--end",
        type=str,
        required=True,
        help="With --monthly: inclusive last day. Without --monthly: exclusive upper bound (same month file as next month start).",
    )
    ap.add_argument("--monthly", action="store_true")
    ap.add_argument("--out-dir", type=str, default=None)
    ap.add_argument("--out", type=str, default=None, help="Single output .md (non-monthly mode)")
    ap.add_argument("--include-jpg", action="store_true")
    ap.add_argument(
        "--include-all-images",
        action="store_true",
        help="Include all PNG/JPEG (when extension matches), skip screenshot filename heuristic",
    )
    args = ap.parse_args(argv)

    source = Path(args.source_folder).expanduser().resolve()

    if args.monthly:
        if not args.out_dir:
            ap.error("--monthly requires --out-dir")
        return run_monthly(
            source_folder=source,
            clip_start=_parse_date(args.start),
            clip_end_inclusive=_parse_date(args.end),
            out_dir=Path(args.out_dir).expanduser().resolve(),
            include_jpg=args.include_jpg,
            include_all_images=args.include_all_images,
        )

    if not args.out:
        ap.error("without --monthly, --out is required")
    return run_single(
        source_folder=source,
        range_start=_parse_date(args.start),
        range_end_exclusive=_parse_date(args.end),
        out_file=Path(args.out).expanduser().resolve(),
        include_jpg=args.include_jpg,
        include_all_images=args.include_all_images,
    )


if __name__ == "__main__":
    raise SystemExit(main())
