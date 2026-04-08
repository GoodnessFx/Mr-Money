import os
import v20
import ccxt
import structlog
import asyncio
from typing import Dict, Any, Optional
from src.security import security_manager

# Setup logger
logger = structlog.get_logger()


class BrokerExecutor:
    """Executes trades via OANDA and CCXT with atomic SL/TP, retries, and key masking."""

    def __init__(self):
        # OANDA Setup
        self.oanda_api_key = os.getenv("OANDA_API_KEY")
        self.oanda_account_id = os.getenv("OANDA_ACCOUNT_ID")
        self.oanda_env = os.getenv("OANDA_ENVIRONMENT", "practice")

        domain = (
            "api-fxpractice.oanda.com"
            if self.oanda_env == "practice"
            else "api-fxtrade.oanda.com"
        )
        self.oanda_ctx = v20.Context(
            domain, 443, True, application="MrMoney", token=self.oanda_api_key
        )

        # CCXT Setup (Binance as default)
        self.binance_api_key = os.getenv("BINANCE_API_KEY")
        self.binance_secret = os.getenv("BINANCE_SECRET")

        self.ccxt_exchange = ccxt.binance(
            {
                "apiKey": self.binance_api_key,
                "secret": self.binance_secret,
                "enableRateLimit": True,
            }
        )

        self._log_startup_status()

    def _mask_key(self, key: str) -> str:
        """Masks API keys for logging."""
        if not key:
            return "N/A"
        return "*" * (len(key) - 4) + key[-4:]

    def _log_startup_status(self):
        """Logs masked API keys on startup."""
        logger.info(
            "broker_executor_initialized",
            oanda_key=self._mask_key(self.oanda_api_key),
            binance_key=self._mask_key(self.binance_api_key),
        )

    async def get_account_balance(self, is_forex: bool = True) -> float:
        """Returns account balance from broker with input validation."""
        try:
            if is_forex:
                response = self.oanda_ctx.account.summary(self.oanda_account_id)
                if response.status != 200:
                    raise Exception(f"OANDA balance failed: {response.body}")

                account_data = response.get("account")
                if not account_data or "balance" not in account_data:
                    raise ValueError("Invalid OANDA response: missing balance")

                return float(account_data.balance)
            else:
                balance = await asyncio.to_thread(self.ccxt_exchange.fetch_balance)
                if "total" not in balance or "USDT" not in balance["total"]:
                    raise ValueError("Invalid CCXT response: missing USDT balance")

                return float(balance["total"]["USDT"])
        except Exception as e:
            logger.error("balance_fetch_failed", error=str(e))
            raise

    async def execute_trade(
        self, pair: str, direction: str, units: int, sl_price: float, tp_price: float
    ) -> Optional[str]:
        """Executes a trade with atomic SL/TP and retry logic."""
        is_forex = "_" in pair or any(
            cur in pair
            for cur in ["EUR", "USD", "GBP", "JPY", "AUD", "CAD", "NZD", "XAU"]
        )

        for attempt in range(1, 3):
            try:
                if is_forex:
                    order_id = await self._execute_oanda_trade(
                        pair, direction, units, sl_price, tp_price
                    )
                else:
                    order_id = await self._execute_ccxt_trade(
                        pair, direction, units, sl_price, tp_price
                    )

                if order_id:
                    return order_id
            except Exception as e:
                logger.warning("trade_execution_failed", attempt=attempt, error=str(e))
                if attempt == 1:
                    await asyncio.sleep(2)
                else:
                    logger.error("trade_execution_aborted", pair=pair)
                    return None
        return None

    async def _execute_oanda_trade(
        self, pair: str, direction: str, units: int, sl_price: float, tp_price: float
    ) -> Optional[str]:
        """Atomic OANDA market order with SL/TP and response validation."""
        oanda_pair = pair.replace("/", "_")
        if "_" not in oanda_pair:
            oanda_pair = oanda_pair[:3] + "_" + oanda_pair[3:]

        signed_units = units if direction.lower() == "buy" else -units

        order_request = {
            "order": {
                "units": str(signed_units),
                "instrument": oanda_pair,
                "type": "MARKET",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": f"{sl_price:.5f}"},
                "takeProfitOnFill": {"price": f"{tp_price:.5f}"},
            }
        }

        response = self.oanda_ctx.order.market(self.oanda_account_id, **order_request)
        if response.status != 201:
            raise Exception(f"OANDA order failed: {response.body}")

        fill_data = response.get("orderFillTransaction")
        if not fill_data or "id" not in fill_data:
            raise ValueError("Invalid OANDA response: missing order fill ID")

        order_id = fill_data.id
        logger.info(
            "oanda_trade_executed",
            order_id=order_id,
            pair=oanda_pair,
            units=signed_units,
        )
        return str(order_id)

    async def _execute_ccxt_trade(
        self, pair: str, direction: str, units: int, sl_price: float, tp_price: float
    ) -> Optional[str]:
        """CCXT market order with response validation."""
        try:
            order = await asyncio.to_thread(
                self.ccxt_exchange.create_order,
                symbol=pair,
                type="market",
                side=direction.lower(),
                amount=units,
                params={"stopLossPrice": sl_price, "takeProfitPrice": tp_price},
            )

            if not order or "id" not in order:
                raise ValueError("Invalid CCXT response: missing order ID")

            logger.info("ccxt_trade_executed", order_id=order["id"], pair=pair)
            return str(order["id"])
        except Exception as e:
            raise Exception(f"CCXT order failed: {str(e)}")


# Singleton instance
broker_executor = BrokerExecutor()
