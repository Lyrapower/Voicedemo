"""日记阅读密码 — 6 位数字,本地存储 hash,0600。写入 POST /diary 不受限。"""
from __future__ import annotations
import hashlib, json, os, secrets, time

PIN_FILE = os.environ.get(
    "DIARY_PIN_FILE",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "diary_pin.json"),
)
_TOKENS: dict[str, float] = {}
_TOKEN_TTL = 86400


def _load() -> dict:
    if not os.path.exists(PIN_FILE):
        return {}
    with open(PIN_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(PIN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    try:
        os.chmod(PIN_FILE, 0o600)
    except OSError:
        pass


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000).hex()


def _valid_pin(pin: str) -> bool:
    return pin.isdigit() and len(pin) == 6


def pin_is_set() -> bool:
    return bool(_load().get("hash"))


def set_pin(pin: str, old_pin: str | None = None) -> dict:
    if not _valid_pin(pin):
        return {"ok": False, "error": "需要 6 位数字"}
    data = _load()
    if data.get("hash"):
        if not old_pin or not _verify(old_pin, data):
            return {"ok": False, "error": "原密码不对"}
    salt = secrets.token_hex(16)
    _save({"salt": salt, "hash": _hash(pin, salt)})
    _TOKENS.clear()
    return {"ok": True}


def _verify(pin: str, data: dict) -> bool:
    return _hash(pin, data["salt"]) == data["hash"]


def unlock(pin: str) -> dict:
    data = _load()
    if not data.get("hash"):
        return _issue_token()
    if not _valid_pin(pin):
        return {"ok": False, "error": "需要 6 位数字"}
    if not _verify(pin, data):
        return {"ok": False, "error": "密码不对"}
    return _issue_token()


def _issue_token() -> dict:
    token = secrets.token_urlsafe(32)
    _TOKENS[token] = time.time() + _TOKEN_TTL
    return {"ok": True, "token": token}


def check_token(token: str | None) -> bool:
    if not pin_is_set():
        return True
    if not token:
        return False
    exp = _TOKENS.get(token)
    if not exp or time.time() > exp:
        _TOKENS.pop(token or "", None)
        return False
    return True
