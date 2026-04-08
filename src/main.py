"""
Main orchestrator for Mr Money.
Handles scheduling, scan cycles, and daily reporting.
"""

import argparse
import asyncio
import datetime
import os
import sys
import uuid
from typing import Any, Dict, List

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler

from src.bayesian import bayesian_updater
from src.brain import brain
from src.chart import chart_controller
from src.db import Signal, Trade, db_manager
from src.executor import broker_executor
from src.notifier import notifier
from src.risk import risk_guardian
from src.security import security_manager
from src.trading_signal import signal_validator
from src.sizer import kelly_sizer

# Setup logger with JSON structure
os.makedirs("logs", exist_ok=True)
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.WriteLoggerFactory(file=open("logs/app.log", "a")),
)
logger = structlog.get_logger()


class MrMoney:
    """The main trading system orchestrator with startup validation and robust scan cycles."""

    def __init__(self, mode: str):
        """Initializes the MrMoney system with the specified mode (paper or live)."""
        self.mode = mode
        # security_manager already loaded config or exited during import
        self.strategy_config = security_manager.get_config()
        self.scheduler = BlockingScheduler(timezone="UTC")
        logger.info("mr_money_system_initialized", mode=self.mode)

    async def startup_checks(self):
        """Validates connectivity and security on startup."""
        logger.info("running_startup_security_checks")
        # Check if EMERGENCY_HALT is set
        if os.getenv("EMERGENCY_HALT", "false").lower() == "true":
            logger.warning("EMERGENCY_HALT_ACTIVE", action="aborting_startup")
            print("CRITICAL: EMERGENCY_HALT is true in .env. System will not start.")
            sys.exit(1)

        await security_manager.validate_broker_connectivity()
        logger.info("startup_security_checks_passed")

    async def run_daily_summary(self):
        """Calculates and sends a summary of yesterday's performance at 08:00 UTC."""
        yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=1
        )
        yesterday_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_end = yesterday.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        session = db_manager.get_session()
        try:
            trades = (
                session.query(Trade)
                .filter(
                    Trade.created_at >= yesterday_start,
                    Trade.created_at <= yesterday_end,
                )
                .all()
            )

            total_trades = len(trades)
            winners = [t for t in trades if t.pnl_dollars and t.pnl_dollars > 0]
            win_rate = (len(winners) / total_trades * 100) if total_trades > 0 else 0
            total_pnl = sum([t.pnl_dollars for t in trades if t.pnl_dollars]) or 0
            avg_kelly = (
                sum([t.kelly_applied for t in trades]) / total_trades
                if total_trades > 0
                else 0
            )

            # Get current account balance
            balance = await broker_executor.get_account_balance(is_forex=True)

            summary = (
                f"📅 DAILY SUMMARY - {yesterday.strftime('%Y-%m-%d')}\n"
                f"💰 Total P&L: ${total_pnl:,.2f}\n"
                f"📈 Win Rate: {win_rate:.1f}%\n"
                f"📊 Trades Taken: {total_trades}\n"
                f"⚖️ Avg Kelly: {avg_kelly:.2%}\n"
                f"🏦 Account Balance: ${balance:,.2f}\n"
                f"🚀 Status: {self.mode.upper()} mode active"
            )

            await notifier.alert_generic(summary)
            logger.info(
                "daily_summary_sent", total_trades=total_trades, total_pnl=total_pnl
            )
        except Exception as e:
            logger.error("daily_summary_failed", error=str(e))
        finally:
            session.close()

    async def scan_and_trade(self):
        """Scans all pairs, validates signals, sizes positions, and executes trades."""
        # Check for emergency halt before every cycle
        if os.getenv("EMERGENCY_HALT", "false").lower() == "true":
            logger.warning("EMERGENCY_HALT_DETECTED", action="stopping_cycle")
            return

        cycle_id = str(uuid.uuid4())[:8]
        logger.info("starting_scan_cycle", cycle_id=cycle_id)

        try:
            # 1. Fetch live balance for risk checks
            balance = await broker_executor.get_account_balance(is_forex=True)
            all_pairs = (
                self.strategy_config["pairs"]["forex"]
                + self.strategy_config["pairs"]["crypto"]
            )

            logger.info("scanning_pairs", count=len(all_pairs), pairs=all_pairs)
            signals_found = 0
            trades_taken = 0
            trades_rejected = []

            for pair in all_pairs:
                # 2. Risk Pre-Check
                if not await risk_guardian.validate_trade_attempt(pair):
                    trades_rejected.append(
                        {"pair": pair, "reason": "risk_limit_reached"}
                    )
                    continue

                try:
                    # 3. AI Analysis
                    raw_signal = await brain.analyze_pair(pair)
                    trace_id = raw_signal.get("trace_id", "unknown")

                    # Use dummy values as placeholders; real system would fetch from TV/Broker
                    dummy_atr_30 = 0.0050
                    dummy_current_range = 0.0020

                    # 4. Signal Validation
                    validation = signal_validator.validate_signal(
                        raw_signal, dummy_atr_30, dummy_current_range
                    )

                    # Persistence for Audit
                    session = db_manager.get_session()
                    try:
                        session.add(
                            Signal(
                                pair=pair,
                                trace_id=trace_id,
                                raw_json=raw_signal,
                                confidence_score=validation["score"],
                                is_valid=validation["is_valid"],
                                rejection_reason=(
                                    ", ".join(validation["reasons"])
                                    if not validation["is_valid"]
                                    else None
                                ),
                            )
                        )
                        session.commit()
                    finally:
                        session.close()

                    if not validation["is_valid"]:
                        reason = validation["reasons"][0]
                        trades_rejected.append(
                            {"pair": pair, "reason": f"validation_failed: {reason}"}
                        )
                        continue

                    signals_found += 1

                    # 5. Position Sizing
                    setup_type = raw_signal.get("setup_type", "default")
                    win_prob = bayesian_updater.get_win_probability(setup_type)
                    sl_pips = raw_signal.get("sl_pips", 0)
                    tp_pips = raw_signal.get("tp_pips", 0)
                    rr_ratio = tp_pips / sl_pips if sl_pips > 0 else 0

                    size_data = kelly_sizer.calculate_position_size(
                        balance, win_prob, rr_ratio, sl_pips, pair
                    )

                    if size_data["units"] <= 0:
                        trades_rejected.append(
                            {"pair": pair, "reason": "kelly_size_too_small"}
                        )
                        continue

                    # 6. Execution
                    if self.mode == "paper":
                        order_id = f"paper_{uuid.uuid4().hex[:8]}"
                    else:
                        order_id = await broker_executor.execute_trade(
                            pair,
                            raw_signal["direction"],
                            size_data["units"],
                            raw_signal.get("sl_price", 0),
                            raw_signal.get("tp_price", 0),
                        )

                    if order_id:
                        trades_taken += 1
                        # Persistence & Notification
                        session = db_manager.get_session()
                        try:
                            new_trade = Trade(
                                pair=pair,
                                direction=raw_signal["direction"],
                                lot_size=size_data["lot_size"],
                                units=size_data["units"],
                                dollar_risk=size_data["dollar_risk"],
                                kelly_raw=size_data["kelly_raw"],
                                kelly_applied=size_data["kelly_applied"],
                                sl_pips=sl_pips,
                                tp_pips=tp_pips,
                                confidence_score=validation["score"],
                                confluence_factors=raw_signal.get(
                                    "confluence_factors_met", []
                                ),
                                reasoning=raw_signal.get("reasoning", ""),
                                setup_type=setup_type,
                                trace_id=trace_id,
                                status="open",
                            )
                            session.add(new_trade)
                            session.commit()
                        finally:
                            session.close()

                        await notifier.alert_trade_opened(
                            {
                                **size_data,
                                "pair": pair,
                                "direction": raw_signal["direction"],
                            }
                        )
                    else:
                        trades_rejected.append(
                            {"pair": pair, "reason": "execution_failed"}
                        )

                except Exception as e:
                    logger.error("pair_processing_failed", pair=pair, error=str(e))

            # Housekeeping
            chart_controller.purge_old_screenshots()

            logger.info(
                "scan_cycle_complete",
                cycle_id=cycle_id,
                signals_found=signals_found,
                trades_taken=trades_taken,
                trades_rejected=trades_rejected,
            )

        except Exception as e:
            logger.error("scan_cycle_error", cycle_id=cycle_id, error=str(e))
            await notifier.alert_error(f"Critical scan error: {str(e)}")

    def start(self):
        """Starts the scheduler for the scan cycle and daily reports."""
        interval = self.strategy_config["schedule"]["scan_interval_minutes"]

        # Add scan job
        self.scheduler.add_job(
            lambda: asyncio.run(self.scan_and_trade()),
            "interval",
            minutes=interval,
            id="scan_cycle",
            next_run_time=datetime.datetime.now(),
        )

        # Add daily report job at 08:00 UTC
        self.scheduler.add_job(
            lambda: asyncio.run(self.run_daily_summary()),
            "cron",
            hour=8,
            minute=0,
            id="daily_summary",
        )

        # Add daily backup job
        self.scheduler.add_job(
            db_manager.perform_daily_backup, "cron", hour=0, minute=0, id="daily_backup"
        )

        logger.info("scheduler_started", interval_minutes=interval)
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Mr Money Autonomous AI Trading System"
    )
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode: paper (demo) or live (real money)",
    )
    args = parser.parse_args()

    if args.mode == "live":
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("WARNING: YOU ARE ABOUT TO ACTIVATE LIVE TRADING MODE.")
        print("REAL CAPITAL IS AT RISK. ENSURE STRATEGY IS TESTED.")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        confirm = input("Type 'CONFIRM' to proceed: ")
        if confirm != "CONFIRM":
            print("Live mode aborted.")
            sys.exit(0)

    bot = MrMoney(mode=args.mode)
    asyncio.run(bot.startup_checks())
    bot.start()
