#!/usr/bin/env python3
"""Dual-entry health monitor — Entry A (8500) and Entry B (8787) checked separately."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime

import requests

ENTRY_A_URL = "http://127.0.0.1:8500"
ENTRY_B_URL = "http://127.0.0.1:8787"


class HealthMonitor:
    def __init__(
        self,
        entry_a_url: str = ENTRY_A_URL,
        entry_b_url: str = ENTRY_B_URL,
        *,
        entry: str = "both",
    ) -> None:
        self.entry_a_url = entry_a_url.rstrip("/")
        self.entry_b_url = entry_b_url.rstrip("/")
        self.entry = entry.lower()
        self.checks: list[dict] = []

    def check_entry_a(self) -> dict:
        timestamp = datetime.now().isoformat()
        try:
            r = requests.get(f"{self.entry_a_url}/health", timeout=5)
            status = r.json()
            return {
                "entry": "A",
                "port": 8500,
                "timestamp": timestamp,
                "reachable": True,
                "status": status.get("status"),
                "service": status.get("service"),
            }
        except Exception as e:
            return {
                "entry": "A",
                "port": 8500,
                "timestamp": timestamp,
                "reachable": False,
                "error": str(e),
            }

    def check_entry_b(self) -> dict:
        timestamp = datetime.now().isoformat()
        try:
            r = requests.get(f"{self.entry_b_url}/health", timeout=5)
            status = r.json()
            return {
                "entry": "B",
                "port": 8787,
                "timestamp": timestamp,
                "reachable": True,
                "status": status.get("status"),
                "substrates_available": status.get("substrates_available"),
                "substrates_total": status.get("substrates_total"),
                "routes": status.get("routes"),
            }
        except Exception as e:
            return {
                "entry": "B",
                "port": 8787,
                "timestamp": timestamp,
                "reachable": False,
                "error": str(e),
            }

    def check_health(self) -> list[dict]:
        out: list[dict] = []
        if self.entry in ("both", "a"):
            out.append(self.check_entry_a())
        if self.entry in ("both", "b"):
            out.append(self.check_entry_b())
        self.checks.extend(out)
        return out

    def monitor(self, interval: int = 30, duration: int | None = None) -> None:
        start = time.time()
        label = self.entry.upper() if self.entry != "both" else "A+B"
        print(f"Monitoring Entry {label} every {interval}s...")
        try:
            while True:
                for check in self.check_health():
                    ok = check.get("reachable")
                    print(
                        f"[{check['timestamp']}] Entry {check['entry']} "
                        f"({check.get('port')}): {'OK' if ok else 'DOWN'} {check}"
                    )
                if duration and (time.time() - start) > duration:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nMonitoring stopped")
        finally:
            path = "health_history.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.checks, f, indent=2, ensure_ascii=False)
            print(f"History saved: {len(self.checks)} checks → {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor Entry A and/or B separately")
    parser.add_argument("interval", nargs="?", type=int, default=30)
    parser.add_argument("--entry", choices=["both", "a", "b"], default="both")
    parser.add_argument("--duration", type=int, default=None)
    parser.add_argument("--entry-a-url", default=ENTRY_A_URL)
    parser.add_argument("--entry-b-url", default=ENTRY_B_URL)
    args = parser.parse_args()
    monitor = HealthMonitor(args.entry_a_url, args.entry_b_url, entry=args.entry)
    monitor.monitor(interval=args.interval, duration=args.duration)


if __name__ == "__main__":
    main()
