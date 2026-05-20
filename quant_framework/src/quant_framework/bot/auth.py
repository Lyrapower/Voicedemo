"""Whitelist-based Telegram bot authorization."""

from __future__ import annotations

import functools
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable, TypeVar

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable)


class BotAuth:
    def __init__(self, authorized_user_ids: list[int], max_commands_per_hour: int = 60) -> None:
        self.authorized = set(authorized_user_ids)
        self.max_commands_per_hour = max_commands_per_hour
        self._command_counts: dict[int, list[datetime]] = defaultdict(list)

    def is_authorized(self, user_id: int) -> bool:
        return user_id in self.authorized

    def reject_response(self) -> str:
        return "Unauthorized. Contact admin."

    def check_rate_limit(self, user_id: int) -> bool:
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=1)
        hits = [t for t in self._command_counts[user_id] if t > cutoff]
        self._command_counts[user_id] = hits
        if len(hits) >= self.max_commands_per_hour:
            return False
        self._command_counts[user_id].append(now)
        return True

    def rate_limit_response(self) -> str:
        return "Rate limit exceeded. Max 60 commands per hour."


def authorized_command(auth: BotAuth) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            user = update.effective_user
            if user is None:
                return
            uid = user.id
            logger.info("Command %s from user %s", func.__name__, uid)
            if not auth.is_authorized(uid):
                await update.message.reply_text(auth.reject_response())
                return
            if not auth.check_rate_limit(uid):
                await update.message.reply_text(auth.rate_limit_response())
                return
            try:
                await func(update, context)
            except Exception as e:
                logger.exception("Command error: %s", e)
                await update.message.reply_text(
                    "An error occurred processing your request. Please try again later."
                )

        return wrapper  # type: ignore[return-value]

    return decorator
