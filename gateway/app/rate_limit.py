"""Daily budget: reset by date (UTC), then check and consume per token."""
import sqlite3
from datetime import datetime, timezone

from app.config import DB_PATH


def get_local_date_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_and_consume(token_id: str, daily_limit: int, daily_used: int) -> tuple[bool, int]:
    """
    If new day, reset daily_used. Then check limit and optionally increment.
    Returns (allowed, new_daily_used).
    """
    today = get_local_date_utc()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "UPDATE tokens SET daily_used = 0, daily_reset_at = ? WHERE token_id = ? AND (daily_reset_at IS NULL OR date(daily_reset_at) < date(?))",
            (today, token_id, today),
        )
        conn.commit()
        row = conn.execute(
            "SELECT daily_used, daily_limit FROM tokens WHERE token_id = ?", (token_id,)
        ).fetchone()
        if not row:
            return False, daily_used
        used, limit = row[0], row[1]
        if used >= limit:
            return False, used
        conn.execute("UPDATE tokens SET daily_used = daily_used + 1 WHERE token_id = ?", (token_id,))
        conn.commit()
        return True, used + 1
    finally:
        conn.close()
