from typing import Any, Dict

import structlog

from src.security import security_manager

# Setup logger
logger = structlog.get_logger()


class KellySizer:
    """Calculates position sizing using fractional Kelly Criterion and enforces risk caps."""

    def __init__(self):
        self.strategy_config = security_manager.get_config()
        self.risk_config = self.strategy_config["risk"]
        logger.info("kelly_sizer_initialized")

    def _get_pip_value(self, pair: str) -> float:
        """Calculates approximate pip value for a standard lot ($10 for most majors)."""
        # For majors against USD (EURUSD, GBPUSD, AUDUSD, NZDUSD), pip value is $10.00
        # For JPY pairs (USDJPY, EURJPY, GBPJPY), pip value is roughly $9-10 (1000 JPY)
        # This is a simplified institutional approximation.
        if "JPY" in pair.upper():
            return 9.0  # Approx $9.00 per lot for JPY pairs at current rates
        elif "XAU" in pair.upper() or "GOLD" in pair.upper():
            return 10.0  # $10.00 per lot (0.10 per pip)
        else:
            return 10.0  # Default to $10.00 for most majors

    def calculate_position_size(
        self,
        account_balance: float,
        win_probability: float,
        rr_ratio: float,
        sl_pips: float,
        pair: str,
    ) -> Dict[str, Any]:
        """
        Calculates optimal position size using Kelly formula and risk limits.

        Formula: f* = (p * b - q) / b
        Where:
        p = win_probability
        q = 1 - p (loss probability)
        b = rr_ratio (avg_win / avg_loss)
        """
        if rr_ratio <= 0 or sl_pips <= 0:
            return {
                "units": 0,
                "lot_size": 0,
                "dollar_risk": 0,
                "kelly_raw": 0,
                "kelly_applied": 0,
                "error": "invalid_inputs",
            }

        # 1. Calculate Raw Kelly (f*)
        # f* = (p * (b + 1) - 1) / b
        p = win_probability
        b = rr_ratio
        kelly_raw = (p * (b + 1) - 1) / b

        # 2. Apply Fractional Kelly
        kelly_fraction = self.risk_config.get("kelly_fraction", 0.25)
        kelly_applied = max(0, kelly_raw * kelly_fraction)

        # 3. Hard Cap: Max Risk Per Trade %
        max_risk_pct = self.risk_config.get("max_risk_per_trade_pct", 1.0) / 100.0
        final_risk_pct = min(kelly_applied, max_risk_pct)

        # 4. Calculate Dollar Risk and Lot Size
        dollar_risk = account_balance * final_risk_pct

        # Calculate lot size based on pip value
        pip_value_per_lot = self._get_pip_value(pair)
        lot_size = round(dollar_risk / (sl_pips * pip_value_per_lot), 2)
        units = int(lot_size * 100000)

        result = {
            "units": units,
            "lot_size": lot_size,
            "dollar_risk": round(dollar_risk, 2),
            "kelly_raw": round(kelly_raw, 4),
            "kelly_applied": round(final_risk_pct, 4),
        }

        logger.info("position_sizing_completed", pair=pair, **result)
        return result


# Singleton instance
kelly_sizer = KellySizer()
