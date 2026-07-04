"""Token verification: hash comparison, scope check. No raw token in DB."""
import hashlib
import os
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Optional

from app.config import DB_PATH


@dataclass
class TokenInfo:
    token_id: str
    scopes: list[str]
    daily_limit: int
    daily_used: int
    enabled: bool


def hash_token(plain: str, salt: Optional[str] = None) -> str:
    s = salt or secrets.token_hex(16)
    h = hashlib.sha256((s + plain).encode()).hexdigest()
    return f"{s}${h}"


def verify_token(plain: str) -> Optional[TokenInfo]:
    """Verify Bearer token and return token info or None."""
    if not plain or not plain.strip():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT token_id, token_hash, scopes, daily_limit, daily_used, enabled FROM tokens WHERE enabled = 1"
        ).fetchall()
        for row in rows:
            stored = row["token_hash"]
            if "$" in stored:
                salt, _ = stored.split("$", 1)
                candidate = hash_token(plain, salt)
                if candidate == stored:
                    scopes = [s.strip() for s in row["scopes"].split(",") if s.strip()]
                    return TokenInfo(
                        token_id=row["token_id"],
                        scopes=scopes,
                        daily_limit=row["daily_limit"],
                        daily_used=row["daily_used"],
                        enabled=bool(row["enabled"]),
                    )
        return None
    finally:
        conn.close()


def require_scope(token_info: TokenInfo, scope: str) -> bool:
    return scope in token_info.scopes or "admin" in token_info.scopes
