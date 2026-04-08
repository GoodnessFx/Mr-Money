import os
import asyncio
from telegram import Bot
import structlog

# Setup logger
logger = structlog.get_logger()


class TelegramNotifier:
    """Async Telegram notifier for trade events, risk alerts, and system status."""

    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.bot = Bot(token=self.bot_token)
        logger.info("telegram_notifier_initialized")

    async def send_message(self, message: str):
        """Sends an async Telegram message with a 3s timeout."""
        try:
            await asyncio.wait_for(
                self.bot.send_message(
                    chat_id=self.chat_id, text=message, parse_mode="Markdown"
                ),
                timeout=3.0,
            )
            logger.info("telegram_message_sent")
        except asyncio.TimeoutError:
            logger.error("telegram_send_timeout")
        except Exception as e:
            logger.error("telegram_send_failed", error=str(e))

    async def alert_trade_opened(self, trade_data: dict):
        """🚀 Trade Opened alert."""
        msg = (
            f"🚀 *TRADE OPENED*\n"
            f"-------------------\n"
            f"Pair: `{trade_data['pair']}`\n"
            f"Direction: `{trade_data['direction'].upper()}`\n"
            f"Size: `{trade_data['lot_size']} lots` (`{trade_data['units']} units`)\n"
            f"Risk: `${trade_data['dollar_risk']}`\n"
            f"SL: `{trade_data['sl_pips']} pips`\n"
            f"TP: `{trade_data['tp_pips']} pips`\n"
            f"Balance: `${trade_data['balance']}`\n"
            f"Trace: `{trade_data['trace_id']}`\n"
        )
        await self.send_message(msg)

    async def alert_trade_closed(self, trade_data: dict):
        """🏁 Trade Closed alert with P&L."""
        status = "✅ WIN" if trade_data["result"] > 0 else "❌ LOSS"
        msg = (
            f"🏁 *TRADE CLOSED: {status}*\n"
            f"-------------------\n"
            f"Pair: `{trade_data['pair']}`\n"
            f"PnL: `${trade_data['result']:.2f}` (`{trade_data['pnl_pct']:.2f}%`)\n"
            f"Exit Price: `{trade_data['exit_price']}`\n"
            f"New Balance: `${trade_data['balance']}`\n"
        )
        await self.send_message(msg)

    async def alert_trade_skipped(self, pair: str, reason: str, trace_id: str):
        """⚠️ Trade Skipped alert."""
        msg = (
            f"⚠️ *TRADE SKIPPED*\n"
            f"-------------------\n"
            f"Pair: `{pair}`\n"
            f"Reason: `{reason}`\n"
            f"Trace: `{trace_id}`\n"
        )
        await self.send_message(msg)

    async def alert_circuit_breaker(self, reason: str):
        """🛑 CIRCUIT BREAKER TRIGGERED alert."""
        msg = (
            f"🛑 *CIRCUIT BREAKER TRIGGERED*\n"
            f"-------------------\n"
            f"Reason: `{reason}`\n"
            f"Action: `HALTING ALL TRADING`\n"
        )
        await self.send_message(msg)

    async def alert_daily_summary(self, stats: dict):
        """📊 DAILY SUMMARY alert."""
        msg = (
            f"📊 *DAILY SUMMARY*\n"
            f"-------------------\n"
            f"Date: `{stats['date']}`\n"
            f"Trades: `{stats['total_trades']}`\n"
            f"Win Rate: `{stats['win_rate']:.1%}`\n"
            f"Net PnL: `${stats['net_pnl']:.2f}` (`{stats['pnl_pct']:.2f}%`)\n"
            f"Final Balance: `${stats['balance']}`\n"
        )
        await self.send_message(msg)

    async def alert_error(self, error: str):
        """🚨 SYSTEM ERROR alert."""
        msg = f"🚨 *SYSTEM ERROR*\n-------------------\n`{error}`"
        await self.send_message(msg)


# Singleton instance
notifier = TelegramNotifier()
