from typing import Any, Dict, List

import structlog

from src.security import security_manager

# Setup logger
logger = structlog.get_logger()


class SignalValidator:
    """Validates trade signals with weighted scoring, ATR volatility check, and R:R validation."""

    def __init__(self):
        self.strategy_config = security_manager.get_config()
        self.confluence_config = self.strategy_config["confluence"]
        self.risk_config = self.strategy_config["risk"]
        logger.info("signal_validator_initialized")

    def validate_signal(
        self, signal: Dict[str, Any], current_atr_30: float, current_price_range: float
    ) -> Dict[str, Any]:
        """Comprehensive validation of Claude's signal."""
        trace_id = signal.get("trace_id", "unknown")
        reasons = []

        # 1. Basic Check
        if signal.get("direction") == "none":
            return {"is_valid": False, "score": 0, "reasons": ["no_setup_found"]}

        # 2. Weighted Confluence Scoring
        factors_met = signal.get("confluence_factors_met", [])
        score = self._calculate_confluence_score(factors_met)
        required_score = self.confluence_config["required_score"]

        if score < required_score:
            reasons.append(f"low_confluence_score: {score} < {required_score}")

        # 3. Volatility Check (30-day ATR)
        vol_multiplier = self.risk_config.get("volatility_filter_multiplier", 1.4)
        if current_price_range > (current_atr_30 * vol_multiplier):
            reasons.append(
                f"high_volatility: {current_price_range:.5f} > {current_atr_30 * vol_multiplier:.5f}"
            )

        # 4. Minimum R:R Check
        sl_pips = signal.get("sl_pips", 0)
        tp_pips = signal.get("tp_pips", 0)
        min_rr = self.risk_config.get("min_rr_ratio", 3.0)

        if sl_pips <= 0:
            reasons.append("invalid_sl_pips")
        else:
            rr_ratio = tp_pips / sl_pips
            if rr_ratio < min_rr:
                reasons.append(f"low_rr_ratio: {rr_ratio:.2f} < {min_rr}")

        is_valid = len(reasons) == 0

        result = {
            "is_valid": is_valid,
            "score": score,
            "direction": signal.get("direction"),
            "reasons": reasons,
            "trace_id": trace_id,
        }

        if not is_valid:
            logger.info("signal_rejected", trace_id=trace_id, reasons=reasons)
        else:
            logger.info("signal_validated", trace_id=trace_id, score=score)

        return result

    def _calculate_confluence_score(self, factors_met: List[str]) -> float:
        """Calculates total score based on weights in strategy config."""
        total_score = 0
        available_factors = {
            f["name"]: f["weight"] for f in self.confluence_config["factors"]
        }

        for factor in factors_met:
            weight = available_factors.get(factor, 0)
            total_score += weight

        return total_score


# Singleton instance
signal_validator = SignalValidator()
