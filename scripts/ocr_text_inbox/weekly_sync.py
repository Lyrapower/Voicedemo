#!/usr/bin/env python3
"""
Weekly Mac Photos screenshot → OCR_Text_Inbox sync (standalone; does not modify legacy scripts).

- Pulls screenshots from Photos for a date window (e.g. 2026-05-20 .. 2026-05-26).
- Writes per-note .md into ~/Desktop/OCR_Text_Inbox/YYYY-MM/ (month = screenshot date).
- Builds _weekly_YYYY-MM-DD_YYYY-MM-DD.md + .json for that week.
- Rebuilds monthly _monthly_review.md + root ocr_index.json via build_monthly_auto.py.

Scheduling: use run_weekly_sync.sh + install_weekly_launchd.sh (Sunday morning).

Examples:
  python weekly_sync.py --last-week
  python weekly_sync.py --week 2026-05-20 2026-05-26
  python weekly_sync.py --month 2026-06
  python weekly_sync.py --catch-up-from 2026-06-01
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.ocr_text_inbox import inbox_export as ie  # noqa: E402

OUT_DIR = ie.OUT_DIR
LOG_PATH = OUT_DIR / "weekly_sync.log"
_export_asset_to_temp_timed = ie._export_asset_to_temp_timed
_ensure_photos_authorized = ie._ensure_photos_authorized
_iso = ie._iso
_md_filename = ie._md_filename
_vision_ocr = ie._vision_ocr
_ocr_screenshot_image = ie._ocr_screenshot_image
SkipImageScreenshot = ie.SkipImageScreenshot

WEEKLY_PREFIX = "_weekly_"


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)
    print(msg, flush=True)


def _month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def iter_week_ranges(
    start: date, end: date, *, chunk_days: int = 7
) -> Iterator[Tuple[date, date]]:
    """
    Non-overlapping windows, e.g. May 20–26 then May 27–31.
    chunk_days=7 → 5/20-5/26, 5/27-5/31, …
    """
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


def previous_calendar_week(today: Optional[date] = None) -> Tuple[date, date]:
    """Monday .. Sunday of the week before the week containing `today`."""
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    prev_sunday = this_monday - timedelta(days=1)
    prev_monday = prev_sunday - timedelta(days=6)
    return prev_monday, prev_sunday


def week_label(start: date, end: date) -> str:
    return f"{start.isoformat()}_{end.isoformat()}"


def _render_md(
    *, created: str, asset_id: str, text: str, week_start: date, week_end: date
) -> str:
    return (
        "---\n"
        "type: ocr_note\n"
        f"created: {created}\n"
        "source: screenshot\n"
        "ocr_engine: macos_vision_zh_en\n"
        f"asset_id: {asset_id}\n"
        f"week_start: {week_start.isoformat()}\n"
        f"week_end: {week_end.isoformat()}\n"
        "tags:\n"
        "  - ocr\n"
        "  - screenshot\n"
        "  - weekly_sync\n"
        "---\n"
        "\n"
        "# OCR Note\n"
        "\n"
        f"{text}\n"
    )


def parse_frontmatter(text: str) -> Dict[str, str]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    meta: Dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta


def ocr_body(text: str) -> str:
    if "# OCR Note" in text:
        return text.split("# OCR Note", 1)[-1].strip()
    return text.strip()


def resolve_datetime(path: Path, text: str) -> datetime:
    meta = parse_frontmatter(text)
    for key in ("created", "date"):
        if key in meta:
            s = meta[key].strip().replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _fetch_assets_between(start: date, end: date):
    import Photos
    from Foundation import NSDate, NSPredicate

    t0 = datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()
    t1 = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc).timestamp()
    d0 = NSDate.dateWithTimeIntervalSince1970_(t0)
    d1 = NSDate.dateWithTimeIntervalSince1970_(t1)
    sub = Photos.PHAssetMediaSubtypePhotoScreenshot
    pred = NSPredicate.predicateWithFormat_(
        "(mediaSubtype & %d) != 0 AND creationDate >= %@ AND creationDate <= %@",
        sub,
        d0,
        d1,
    )
    opts = Photos.PHFetchOptions.alloc().init()
    opts.setPredicate_(pred)
    return Photos.PHAsset.fetchAssetsWithOptions_(opts)


def _asset_created(asset) -> datetime:
    dt = asset.creationDate()
    if hasattr(dt, "timeIntervalSince1970"):
        return datetime.fromtimestamp(float(dt.timeIntervalSince1970()), tz=timezone.utc)
    return datetime.now(timezone.utc)


def sync_week(
    week_start: date,
    week_end: date,
    *,
    skip_existing: bool = True,
) -> Dict[str, Any]:
    """OCR screenshots in [week_start, week_end] inclusive."""
    if sys.platform != "darwin":
        raise RuntimeError("weekly_sync requires macOS + Photos")

    _ensure_photos_authorized()
    stats: Dict[str, Any] = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "ok": 0,
        "skip": 0,
        "fail": 0,
        "keep": 0,
        "months_touched": set(),
    }
    label = week_label(week_start, week_end)
    _log(f"Week sync {label}")

    assets = _fetch_assets_between(week_start, week_end)
    total = int(assets.count())

    for i in range(total):
        asset = assets.objectAtIndex_(i)
        asset_id = str(asset.localIdentifier())
        created_dt = _asset_created(asset)
        shot = created_dt.date()
        if shot < week_start or shot > week_end:
            continue

        month = _month_key(shot)
        folder = OUT_DIR / month
        folder.mkdir(parents=True, exist_ok=True)
        md_path = folder / _md_filename(asset_id)

        if skip_existing and md_path.is_file():
            stats["skip"] += 1
            continue

        tmp: Optional[Path] = None
        try:
            tmp = _export_asset_to_temp_timed(asset)
            text = _ocr_screenshot_image(tmp)
        except SkipImageScreenshot as e:
            stats["skip"] += 1
            if stats["skip"] <= 5:
                _log(f"SKIP image {asset_id}: {e}")
            continue
        except Exception as e:
            stats["fail"] += 1
            if md_path.is_file():
                stats["keep"] += 1
            elif stats["fail"] <= 10:
                _log(f"FAIL {asset_id}: {e}")
            continue
        finally:
            if tmp and tmp.is_file():
                tmp.unlink(missing_ok=True)

        md_path.write_text(
            _render_md(
                created=_iso(created_dt),
                asset_id=asset_id,
                text=text,
                week_start=week_start,
                week_end=week_end,
            ),
            encoding="utf-8",
        )
        stats["ok"] += 1
        stats["months_touched"].add(month)

    build_weekly_review(week_start, week_end)
    months = sorted(stats["months_touched"])
    if months:
        rebuild_months(months)
    stats["months_touched"] = months
    _log(f"Week {label} done: ok={stats['ok']} skip={stats['skip']} fail={stats['fail']}")
    return stats


def _source_notes_in_week(month_folder: Path, week_start: date, week_end: date) -> List[Tuple[datetime, Path]]:
    rows: List[Tuple[datetime, Path]] = []
    for path in month_folder.glob("*.md"):
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        meta = parse_frontmatter(text)
        shot: Optional[date] = None
        if "created" in meta:
            try:
                shot = datetime.fromisoformat(
                    meta["created"].replace("Z", "+00:00")
                ).date()
            except ValueError:
                pass
        if shot is None:
            shot = resolve_datetime(path, text).date()
        if week_start <= shot <= week_end:
            rows.append((resolve_datetime(path, text), path))
    rows.sort(key=lambda x: (x[0], x[1].name))
    return rows


def build_weekly_review(week_start: date, week_end: date) -> None:
    """Write _weekly_START_END.md + .json under each month folder that has notes."""
    label = week_label(week_start, week_end)
    months_seen: Set[str] = set()

    for month_dir in sorted(OUT_DIR.iterdir()):
        if not month_dir.is_dir() or not re.match(r"^\d{4}-\d{2}$", month_dir.name):
            continue
        rows = _source_notes_in_week(month_dir, week_start, week_end)
        if not rows:
            continue
        months_seen.add(month_dir.name)
        lines = [
            f"# OCR Weekly Review — {label}",
            "",
            f"Window: **{week_start.isoformat()}** .. **{week_end.isoformat()}**",
            "",
            "## Index",
            "",
        ]
        files_meta: List[Dict[str, Any]] = []
        for dt, path in rows:
            name = path.name
            body = ocr_body(path.read_text(encoding="utf-8", errors="replace"))
            lines.append(f"- [[{name}]]")
            files_meta.append(
                {
                    "file": f"{month_dir.name}/{name}",
                    "created": dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "text_preview": body[:120].replace("\n", " "),
                    "text_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                }
            )
        lines.extend(["", "---", ""])
        for dt, path in rows:
            body = ocr_body(path.read_text(encoding="utf-8", errors="replace"))
            lines.extend(
                [
                    f"## {dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
                    "",
                    f"Source file: {path.name}",
                    "",
                    body,
                    "",
                    "---",
                    "",
                ]
            )
        base = f"{WEEKLY_PREFIX}{label}"
        (month_dir / f"{base}.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        (month_dir / f"{base}.json").write_text(
            json.dumps(
                {
                    "week_start": week_start.isoformat(),
                    "week_end": week_end.isoformat(),
                    "month": month_dir.name,
                    "file_count": len(files_meta),
                    "files": files_meta,
                    "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        _log(f"Weekly review {month_dir.name}/{base}.md ({len(rows)} notes)")


def rebuild_months(months: List[str]) -> None:
    script = Path(__file__).resolve().parent / "build_monthly_auto.py"
    subprocess.run([sys.executable, str(script), *months], check=True)
    _log(f"Monthly rebuild: {', '.join(months)}")


def sync_month(year: int, month: int, *, chunk_days: int = 7) -> None:
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    for w0, w1 in iter_week_ranges(start, end, chunk_days=chunk_days):
        sync_week(w0, w1)


def catch_up_from(start: date, *, chunk_days: int = 7) -> None:
    end = date.today()
    for w0, w1 in iter_week_ranges(start, end, chunk_days=chunk_days):
        sync_week(w0, w1)


def main() -> int:
    if sys.platform != "darwin":
        print("macOS only", file=sys.stderr)
        return 1

    argv = sys.argv[1:]
    if not argv or "--last-week" in argv:
        w0, w1 = previous_calendar_week()
        sync_week(w0, w1)
        return 0

    if "--week" in argv:
        i = argv.index("--week")
        w0 = date.fromisoformat(argv[i + 1])
        w1 = date.fromisoformat(argv[i + 2])
        sync_week(w0, w1)
        return 0

    if "--month" in argv:
        i = argv.index("--month")
        ym = argv[i + 1]
        y, m = map(int, ym.split("-"))
        sync_month(y, m)
        return 0

    if "--catch-up-from" in argv:
        i = argv.index("--catch-up-from")
        start = date.fromisoformat(argv[i + 1])
        catch_up_from(start)
        return 0

    if "--rebuild-monthly" in argv:
        script = Path(__file__).resolve().parent / "build_monthly_auto.py"
        subprocess.run([sys.executable, str(script)], check=True)
        return 0

    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
