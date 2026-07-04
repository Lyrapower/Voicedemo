"""Disable old token and create new one with same scopes/limit."""
import argparse
import secrets
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DB_PATH
from app.auth import hash_token


def main():
    p = argparse.ArgumentParser(description="Rotate gateway token")
    p.add_argument("token_id", help="token_id to rotate")
    args = p.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT token_id, scopes, daily_limit FROM tokens WHERE token_id = ?",
            (args.token_id,),
        ).fetchone()
        if not row:
            print("Error: token_id not found", file=sys.stderr)
            sys.exit(1)
        scopes = row["scopes"]
        daily_limit = row["daily_limit"]
        conn.execute("UPDATE tokens SET enabled = 0 WHERE token_id = ?", (args.token_id,))
        conn.commit()
    finally:
        conn.close()

    plain = secrets.token_urlsafe(48)
    new_id = secrets.token_hex(8)
    token_hash = hash_token(plain)
    created_at = __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime())

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT INTO tokens (token_id, token_hash, scopes, daily_limit, daily_used, enabled, created_at, note)
               VALUES (?, ?, ?, ?, 0, 1, ?, ?)""",
            (new_id, token_hash, scopes, daily_limit, created_at, f"rotated from {args.token_id}"),
        )
        conn.commit()
    finally:
        conn.close()

    print("Old token disabled. New token (save it; not shown again):")
    print("token_id:", new_id)
    print("token:", plain)


if __name__ == "__main__":
    main()
