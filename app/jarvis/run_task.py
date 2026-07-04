"""CLI entry for launchd / shell — uses the same registry as platform_main."""

from __future__ import annotations

import argparse
import json
import sys

from app.jarvis.task_registry import list_tasks, run_task


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a registered Jarvis automation task.")
    parser.add_argument("task_id", nargs="?", help="Task id from config/jarvis_automation.yaml")
    parser.add_argument("--list", action="store_true", help="List registered tasks")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Force dry-run mode")
    parser.add_argument("--live", action="store_true", help="Disable dry-run (blocked if task disabled)")
    parser.add_argument("--force", action="store_true", help="Run even if task disabled in yaml")
    args = parser.parse_args(argv)

    if args.list or not args.task_id:
        for row in list_tasks():
            print(f"{row['task_id']}\tenabled={row['enabled']}\t{row['title']}")
        return 0

    dry_run = not args.live
    if args.dry_run:
        dry_run = True
    result = run_task(args.task_id, dry_run=dry_run, force=args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
