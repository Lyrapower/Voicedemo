"""Telegram command handlers (python-telegram-bot v20+)."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from quant_framework.bot.auth import BotAuth, authorized_command
from quant_framework.config import get_settings
from quant_framework.service import build_adapter, build_cache, build_combiner, most_recent_month_end
from quant_framework.universe.sp500 import get_sp500_constituents

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _parse_date_arg(text: str | None) -> date:
    if not text or not text.strip():
        return most_recent_month_end()
    s = text.strip()
    if not _DATE_RE.match(s):
        raise ValueError("Invalid date format. Use YYYY-MM-DD.")
    return datetime.strptime(s, "%Y-%m-%d").date()


def _sanitize_ticker(ticker: str) -> str:
    t = ticker.strip().upper().replace(".", "-")
    if not _TICKER_RE.match(t.replace("-", "")):
        raise ValueError("Invalid ticker.")
    return t


def build_application() -> Application:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    auth = BotAuth(settings.authorized_user_ids)
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    app = Application.builder().token(settings.telegram_bot_token).build()

    handlers = [
        ("start", cmd_start),
        ("help", cmd_help),
        ("signals", cmd_signals),
        ("status", cmd_status),
        ("positions", cmd_positions),
        ("factor", cmd_factor),
        ("runs", cmd_runs),
    ]
    for name, func in handlers:
        wrapped = _wrap(auth, func)
        app.add_handler(CommandHandler(name, wrapped))

    return app


def _wrap(auth: BotAuth, func):
    decorated = authorized_command(auth)(func)
    return decorated


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Welcome to Quant Framework Bot (Phase 1).\n\n"
        "Commands:\n"
        "/help - List commands\n"
        "/signals [date] - Top/bottom ranked signals\n"
        "/status - System status\n"
        "/factor <ticker> [date] - Factor breakdown\n"
        "/runs [run_id] - Signal run history\n"
        "/positions - Position tracking (Phase 4)"
    )
    await update.message.reply_text(text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "/start - Welcome\n"
        "/help - This message\n"
        "/signals [YYYY-MM-DD] - Generate & show top 10 / bottom 10\n"
        "/status - Cache size, last run, fetch log\n"
        "/factor <TICKER> [date] - Per-ticker factors\n"
        "/runs - Last 10 runs; /runs <uuid> for details\n"
        "/positions - Placeholder for Phase 4"
    )


async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        as_of = _parse_date_arg(context.args[0] if context.args else None)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.reply_text("Generating signals... this may take a minute.")

    universe = get_sp500_constituents(as_of)
    combiner = build_combiner()
    adapter = build_adapter()
    df = combiner.compute_combined(universe, as_of, adapter)
    ranked = df[df["rank"].notna()].sort_values("rank")
    top = ranked.head(10)
    bottom = ranked.tail(10).sort_values("rank", ascending=False)

    lines = [f"Signals as of {as_of}", "", "Top 10 long:"]
    for ticker, row in top.iterrows():
        lines.append(f"{ticker} | {row['combined_score']:.3f} | #{int(row['rank'])}")
    lines.append("")
    lines.append("Bottom 10 short:")
    for ticker, row in bottom.iterrows():
        lines.append(f"{ticker} | {row['combined_score']:.3f} | #{int(row['rank'])}")
    await update.message.reply_text("\n".join(lines))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cache = build_cache()
    size_mb = cache.db_size_bytes() / (1024 * 1024)
    last_fetch = cache.last_fetch_time() or "N/A"
    last_run = cache.get_last_signal_run()
    summary = cache.fetch_log_summary_24h()
    lines = [
        "System Status",
        f"Cache DB size: {size_mb:.2f} MB",
        f"Last data fetch: {last_fetch}",
        f"Fetch log (24h): {summary.get('success', 0)} ok, {summary.get('failure', 0)} failed",
        "Active processes: bot (polling)",
    ]
    if last_run:
        lines.append(
            f"Last signal run: {last_run.get('as_of_date')} at {last_run.get('completed_at')}"
        )
    else:
        lines.append("Last signal run: none")
    await update.message.reply_text("\n".join(lines))


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Position tracking — Phase 4")


async def cmd_factor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /factor <TICKER> [YYYY-MM-DD]")
        return
    try:
        ticker = _sanitize_ticker(context.args[0])
        as_of = _parse_date_arg(context.args[1] if len(context.args) > 1 else None)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    combiner = build_combiner()
    adapter = build_adapter()
    df = combiner.compute_combined([ticker], as_of, adapter)
    if ticker not in df.index:
        await update.message.reply_text(f"No data for {ticker} on {as_of}")
        return
    row = df.loc[ticker]
    lines = [f"Factor breakdown: {ticker} @ {as_of}"]
    for raw_col in [c for c in df.columns if c.endswith("_raw")]:
        z_col = raw_col.replace("_raw", "_zscore")
        rank = row.get("rank", "N/A")
        lines.append(
            f"{raw_col}: {row.get(raw_col, float('nan')):.4f} | "
            f"z={row.get(z_col, float('nan')):.2f}"
        )
    lines.append(f"combined_score: {row.get('combined_score', float('nan')):.3f}")
    lines.append(f"rank: {row.get('rank', 'N/A')}")
    await update.message.reply_text("\n".join(lines))


async def cmd_runs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cache = build_cache()
    if context.args:
        run_id = context.args[0].strip()
        if not re.match(r"^[a-f0-9\-]{36}$", run_id, re.I):
            await update.message.reply_text("Invalid run_id format.")
            return
        df = cache.get_signal_results(run_id)
        if df.empty:
            await update.message.reply_text("Run not found.")
            return
        ranked = df[df["rank"].notna()].sort_values("rank").head(10)
        lines = [f"Run {run_id} (top 10):"]
        for ticker, row in ranked.iterrows():
            lines.append(f"#{int(row['rank'])} {ticker} | {row['combined_score']:.3f}")
        await update.message.reply_text("\n".join(lines))
        return

    runs = cache.list_signal_runs(limit=10)
    if runs.empty:
        await update.message.reply_text("No signal runs yet.")
        return
    lines = ["Last 10 signal runs:", ""]
    for _, r in runs.iterrows():
        lines.append(f"{r['run_id'][:8]}... | {r['as_of_date']} | {r['completed_at']}")
    lines.append("")
    lines.append("Use /runs <run_id> for details.")
    await update.message.reply_text("\n".join(lines))
