"""Push notification infrastructure for scheduled tasks (Phase 2+)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import Bot

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, bot: "Bot", authorized_user_ids: list[int]) -> None:
        self.bot = bot
        self.recipients = authorized_user_ids

    async def send_signal_generated(self, run_id: str, summary: dict) -> None:
        """
        Sends notification when scheduled signal generation completes.
        Includes top 5 long + bottom 5 short summary.
        """
        top = summary.get("top_long", [])
        bottom = summary.get("bottom_short", [])
        lines = [f"Signal run complete: {run_id}", "", "Top 5 long:"]
        for row in top[:5]:
            lines.append(f"  {row.get('ticker')} | {row.get('combined_score', 0):.3f} | #{row.get('rank')}")
        lines.append("")
        lines.append("Bottom 5 short:")
        for row in bottom[:5]:
            lines.append(f"  {row.get('ticker')} | {row.get('combined_score', 0):.3f} | #{row.get('rank')}")
        text = "\n".join(lines)
        for uid in self.recipients:
            try:
                await self.bot.send_message(chat_id=uid, text=text)
            except Exception as e:
                logger.warning("Notification failed for %s: %s", uid, e)

    async def send_error(self, error: str) -> None:
        """Sends error notification to admin users."""
        text = f"Quant framework error:\n{error[:500]}"
        for uid in self.recipients:
            try:
                await self.bot.send_message(chat_id=uid, text=text)
            except Exception as e:
                logger.warning("Error notification failed for %s: %s", uid, e)
