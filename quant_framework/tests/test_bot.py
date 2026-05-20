import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from quant_framework.bot.auth import BotAuth, authorized_command
from quant_framework.bot.handlers import cmd_positions, cmd_start


def _make_update(user_id: int = 12345):
    user = MagicMock()
    user.id = user_id
    message = MagicMock()
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_user = user
    update.message = message
    return update


@pytest.mark.asyncio
async def test_auth_rejects_unauthorized():
    auth = BotAuth([99999])
    update = _make_update(user_id=12345)

    @authorized_command(auth)
    async def dummy(u, c):
        pass

    await dummy(update, None)
    update.message.reply_text.assert_called_once_with("Unauthorized. Contact admin.")


@pytest.mark.asyncio
async def test_auth_allows_authorized():
    auth = BotAuth([12345])
    update = _make_update(user_id=12345)

    @authorized_command(auth)
    async def dummy(u, c):
        await u.message.reply_text("ok")

    await dummy(update, None)
    update.message.reply_text.assert_called_with("ok")


@pytest.mark.asyncio
async def test_cmd_start_authorized():
    auth = BotAuth([12345])

    @authorized_command(auth)
    async def wrapped(u, c):
        await cmd_start(u, c)

    update = _make_update(12345)
    await wrapped(update, None)
    assert update.message.reply_text.called


@pytest.mark.asyncio
async def test_cmd_positions():
    auth = BotAuth([1])
    update = _make_update(1)

    @authorized_command(auth)
    async def wrapped(u, c):
        await cmd_positions(u, c)

    await wrapped(update, None)
    text = update.message.reply_text.call_args[0][0]
    assert "Phase 4" in text


def test_rate_limit():
    auth = BotAuth([1], max_commands_per_hour=2)
    assert auth.check_rate_limit(1)
    assert auth.check_rate_limit(1)
    assert not auth.check_rate_limit(1)


def test_build_application_missing_token():
    with patch("quant_framework.bot.handlers.get_settings") as mock_settings:
        mock_settings.return_value.telegram_bot_token = ""
        mock_settings.return_value.authorized_user_ids = []
        mock_settings.return_value.log_level = "INFO"
        from quant_framework.bot.handlers import build_application

        with pytest.raises(RuntimeError):
            build_application()
