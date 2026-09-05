#!/usr/bin/env python3
"""
Telegram Aster/Fable Bot V5 — EMERGENCY-ONLY (off daily patrol).
Coach role migrated to 场域 app 陪跑 node; start manually when Lyra authorizes.
Telegram Aster/Fable Bot V5
===========================

Telegram wrapper for aster_fable_bridge_v5.py.

One Telegram bot front door:
  Telegram message
    -> aster_fable_bridge_v5.run_bridge()
    -> local verifier + Fable coach + Qwen revision
    -> final answer back to Telegram
    -> local distill/method/proof artifacts written by bridge

This file intentionally keeps Telegram separate from the bridge.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib import error, request

import aster_fable_bridge_v5 as bridge


VERSION = "5.0.0"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_USER_IDS = {
    x.strip() for x in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if x.strip()
}
REPLY_MAX_CHARS = int(os.environ.get("TELEGRAM_REPLY_MAX_CHARS", "3500"))


def http_json(method: str, url: str, payload: dict, timeout: int = 60) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, method=method, headers={"content-type": "application/json"})
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def telegram_api(method: str, payload: dict) -> dict:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    return http_json("POST", f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}", payload, timeout=65)


def require_allowed_users_configured() -> None:
    if not TELEGRAM_ALLOWED_USER_IDS:
        raise RuntimeError("TELEGRAM_ALLOWED_USER_IDS is required; refusing fail-open Telegram bot")


def send_message(chat_id: int | str, text: str, reply_to: int | None = None) -> None:
    if len(text) > REPLY_MAX_CHARS:
        text = text[: REPLY_MAX_CHARS - 80] + "\n\n[truncated by telegram bot]"
    payload = {"chat_id": chat_id, "text": text}
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to
    telegram_api("sendMessage", payload)


def handle_command(text: str) -> str | None:
    cmd = text.strip()
    if cmd == "/status":
        return json.dumps({"telegram_bot": VERSION, **bridge.status()}, ensure_ascii=False, indent=2)
    if cmd == "/privacy":
        return (
            "Privacy / authority:\n"
            "- RED/sealed/no-cloud input is not sent to Fable/Claude API.\n"
            "- Qwen/Aster drafts and revises.\n"
            "- Fable/Claude coaches only.\n"
            "- Local verifier computes PASS/FAIL.\n"
            "- Bridge writes proof logs and review queue.\n"
            "- Training export requires PASS + non-RED + non-blocklisted source + manual review."
        )
    if cmd == "/export_distill":
        status = bridge.status()
        return (
            "Local export status only. Paths are intentionally not sent over Telegram.\n"
            f"runs: {status.get('runs')}\n"
            f"export_reviewed_only: {status.get('export_reviewed_only')}\n"
            f"verifier_impl: {status.get('verifier_impl')}\n"
            "Check local filesystem on the Mac for exact artifact paths."
        )
    return None


def process_message(text: str) -> str:
    record = bridge.run_bridge(text)
    prefix = ""
    if bridge.sentinel is None and bridge.ALLOW_FALLBACK_VERIFIER:
        prefix = "[DEGRADED VERIFIER]\n"
    footer = (
        f"\n\n[bridge:{record['id']} verdict:{record['verdict']} "
        f"task:{record['task_kind']} access:{record['access_level']}]"
    )
    return prefix + record["final_answer"] + footer


def poll_loop() -> None:
    require_allowed_users_configured()
    bridge.init_db()
    offset = 0
    print("Telegram Aster/Fable Bot V5 started", flush=True)
    while True:
        try:
            data = telegram_api("getUpdates", {"offset": offset, "timeout": 45})
        except (error.URLError, TimeoutError, RuntimeError) as exc:
            print(f"[telegram] {exc}", file=sys.stderr, flush=True)
            time.sleep(5)
            continue

        for update in data.get("result", []):
            offset = max(offset, int(update["update_id"]) + 1)
            msg = update.get("message") or update.get("edited_message") or {}
            text = msg.get("text") or ""
            chat = msg.get("chat") or {}
            user = msg.get("from") or {}
            chat_id = chat.get("id")
            chat_type = chat.get("type")
            user_id = str(user.get("id", ""))
            message_id = msg.get("message_id")

            if chat_type != "private":
                print(f"[telegram] ignored non-private chat {chat_id} type={chat_type}", file=sys.stderr, flush=True)
                continue
            if TELEGRAM_ALLOWED_USER_IDS and user_id not in TELEGRAM_ALLOWED_USER_IDS:
                continue
            if not text.strip() or chat_id is None:
                continue

            try:
                command_reply = handle_command(text)
                reply = command_reply if command_reply is not None else process_message(text)
            except Exception as exc:
                reply = f"NULL\nTelegram bridge error captured locally: {type(exc).__name__}: {exc}"
                print(reply, file=sys.stderr, flush=True)

            send_message(chat_id, reply, message_id)


def cmd_poll(_: argparse.Namespace) -> int:
    poll_loop()
    return 0


def cmd_once(args: argparse.Namespace) -> int:
    if not args.unsafe_local_once:
        raise SystemExit("once requires --unsafe-local-once to avoid accidental Telegram bypass")
    bridge.init_db()
    print(process_message(args.text))
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    bridge.init_db()
    print(handle_command("/status"))
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
    bridge.init_db()
    assert handle_command("/privacy")
    assert handle_command("/export_distill")
    try:
        require_allowed_users_configured()
    except RuntimeError:
        pass
    else:
        assert TELEGRAM_ALLOWED_USER_IDS
    red = bridge.run_bridge("RED sealed core no cloud")
    assert red["access_level"] == "RED"
    assert red["fable_coach"] == ""
    print("PASS: telegram_aster_fable_bot_v5 selftest")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Telegram Aster/Fable Bot V5")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("poll")
    s.set_defaults(func=cmd_poll)

    s = sub.add_parser("once")
    s.add_argument("text")
    s.add_argument("--unsafe-local-once", action="store_true")
    s.set_defaults(func=cmd_once)

    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("selftest")
    s.set_defaults(func=cmd_selftest)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
