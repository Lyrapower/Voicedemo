"""Reset daily_used for all tokens (e.g. cron at midnight UTC)."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DB_PATH
from app.rate_limit import get_local_date_utc


def main():
    today = get_local_date_utc()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "UPDATE tokens SET daily_used = 0, daily_reset_at = ? WHERE daily_reset_at IS NULL OR date(daily_reset_at) < date(?)",
            (today, today),
        )
        conn.commit()
        print(f"Reset daily_used for new date {today}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
