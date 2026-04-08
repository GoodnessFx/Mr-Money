import structlog
import os
import datetime
from typing import Dict, Any, List
from src.security import security_manager
from src.db import db_manager, Trade, DailyPL
from src.executor import broker_executor

# Setup logger
logger = structlog.get_logger()


class RiskGuardian:
    """The 'Risk Guardian' enforcing circuit breakers, daily loss limits, and position caps."""

    def __init__(self):
        self.strategy_config = security_manager.get_config()
        self.risk_config = self.strategy_config["risk"]
        self.consecutive_losses_limit = 3
        logger.info("risk_guardian_initialized")

    async def validate_trade_attempt(self, pair: str) -> bool:
        """Runs all risk checks before allowing a trade to proceed."""

        # 0. Emergency Halt Check
        if os.getenv("EMERGENCY_HALT") == "true":
            logger.error("risk_check_failed", reason="emergency_halt_active")
            return False

        # 1. Account Balance Sanity Check
        try:
            live_balance = await broker_executor.get_account_balance(is_forex=True)
            if live_balance <= 0:
                logger.error(
                    "risk_check_failed", reason="account_balance_zero_or_negative"
                )
                return False
        except Exception as e:
            logger.error(
                "risk_check_failed", reason="broker_balance_fetch_failed", error=str(e)
            )
            return False

        session = db_manager.get_session()
        try:
            # 2. Daily P&L vs Max Daily Loss Pct
            now = datetime.datetime.now(datetime.timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            closed_trades_today = (
                session.query(Trade)
                .filter(Trade.exit_time >= today_start, Trade.status == "closed")
                .all()
            )

            daily_pnl_pct = (
                sum([t.pnl_pct for t in closed_trades_today])
                if closed_trades_today
                else 0
            )
            max_daily_loss = self.risk_config.get("max_daily_loss_pct", 3.0)

            if daily_pnl_pct <= -max_daily_loss:
                if os.getenv("OVERRIDE_DAILY_LOSS_LIMIT") != "true":
                    logger.error(
                        "risk_check_failed",
                        reason="daily_loss_limit_exceeded",
                        pnl=daily_pnl_pct,
                    )
                    return False
                else:
                    logger.warning(
                        "risk_limit_overridden",
                        reason="daily_loss_limit_exceeded",
                        pnl=daily_pnl_pct,
                    )

            # 3. Max Open Trades Count
            open_trades_count = (
                session.query(Trade).filter(Trade.status == "open").count()
            )
            if open_trades_count >= self.risk_config.get("max_open_trades", 3):
                logger.info("risk_check_failed", reason="max_open_trades_reached")
                return False

            # 4. No Double-Up Check (Existing position in same pair)
            existing_pair_trade = (
                session.query(Trade)
                .filter(Trade.pair == pair, Trade.status == "open")
                .first()
            )
            if existing_pair_trade:
                logger.info(
                    "risk_check_failed", reason="existing_position_in_pair", pair=pair
                )
                return False

            # 5. Circuit Breaker: 3 consecutive losses
            last_trades = (
                session.query(Trade)
                .filter(Trade.status == "closed")
                .order_by(Trade.exit_time.desc())
                .limit(3)
                .all()
            )
            if len(last_trades) == self.consecutive_losses_limit and all(
                t.result < 0 for t in last_trades
            ):
                # Check if the last loss was within the last 4 hours
                last_exit = last_trades[0].exit_time
                if (
                    datetime.datetime.now(datetime.timezone.utc) - last_exit
                ).total_seconds() < (4 * 3600):
                    logger.error(
                        "risk_check_failed",
                        reason="circuit_breaker_active",
                        consecutive_losses=3,
                    )
                    return False

            logger.info(
                "risk_check_passed", pair=pair, daily_pnl=f"{daily_pnl_pct:.2f}%"
            )
            return True

        except Exception as e:
            logger.error("risk_check_failed", reason="internal_db_error", error=str(e))
            return False
        finally:
            session.close()


# Singleton instance
risk_guardian = RiskGuardian()
