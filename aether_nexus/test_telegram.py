#!/usr/bin/env python3
"""Send a test notification via configured channel (Telegram / Pushover)."""
from aether_shared import NOTIFY_CHANNEL, send_notification, _telegram_configured, _pushover_configured

if __name__ == "__main__":
    print(f"Channel: {NOTIFY_CHANNEL}")
    print(f"Telegram configured: {_telegram_configured()}")
    print(f"Pushover configured: {_pushover_configured()}")
    send_notification("Aether Nexus test — Telegram/notification OK")
    print("Test message sent (check your phone).")
