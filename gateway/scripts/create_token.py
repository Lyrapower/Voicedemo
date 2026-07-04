"""Create a new token (scopes + daily_limit). Token shown only once."""
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
    p = argparse.ArgumentParser(description="Create gateway token")
    p.add_argument("--scopes", default="chat,tts,vision", help="Comma-separated scopes")
    p.add_argument("--daily-limit", type=int, default=100, help="Daily request limit")
    p.add_argument("--note", default="", help="Optional note")
    args = p.parse_args()
    scopes = ",".join(s.strip() for s in args.scopes.split(",") if s.strip())
    if not scopes:
        print("Error: at least one scope required", file=sys.stderr)
        sys.exit(1)

    plain = secrets.token_urlsafe(48)
    token_id = secrets.token_hex(8)
    token_hash = hash_token(plain)
    created_at = __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime())

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT INTO tokens (token_id, token_hash, scopes, daily_limit, daily_used, enabled, created_at, note)
               VALUES (?, ?, ?, ?, 0, 1, ?, ?)""",
            (token_id, token_hash, scopes, args.daily_limit, created_at, args.note or None),
        )
        conn.commit()
    finally:
        conn.close()

    print("Token created. Save the token below; it will not be shown again.")
    print("token_id:", token_id)
    print("token:", plain)


if __name__ == "__main__":
    main()
