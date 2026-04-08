import pytest

from src.trading_signal import SignalValidator


@pytest.fixture
def signal_validator():
    return SignalValidator()


def test_valid_confluence_score_accepts_trade(signal_validator):
    """Test that a valid confluence score accepts a trade setup."""
    signal = {
        "direction": "BUY",
        "confidence_score": 8,
        "confluence_factors_met": [
            "higher_timeframe_trend_aligned",
            "liquidity_sweep_confirmed",
            "inducement_tapped",
        ],
        "sl_pips": 10,
        "tp_pips": 30,
    }
    # Weights: 2 + 3 + 2 = 7 (Required is 7)
    result = signal_validator.validate_signal(signal, 0.0100, 0.0050)
    assert result["is_valid"] is True


def test_score_below_threshold_rejects_trade(signal_validator):
    """Test that a score below the threshold rejects the trade."""
    signal = {
        "direction": "BUY",
        "confidence_score": 5,
        "confluence_factors_met": ["higher_timeframe_trend_aligned"],
        "sl_pips": 10,
        "tp_pips": 30,
    }
    # Weight: 2 (Required is 7)
    result = signal_validator.validate_signal(signal, 0.0100, 0.0050)
    assert result["is_valid"] is False
    assert any("low_confluence_score" in r for r in result["reasons"])


def test_volatility_filter_rejects_in_high_vol(signal_validator):
    """Test that high volatility (above 1.4x ATR) rejects the trade."""
    signal = {
        "direction": "BUY",
        "confidence_score": 8,
        "confluence_factors_met": [
            "higher_timeframe_trend_aligned",
            "liquidity_sweep_confirmed",
            "inducement_tapped",
        ],
        "sl_pips": 10,
        "tp_pips": 30,
    }
    # current_range = 0.0150, atr_30 = 0.0100. Range is 1.5x ATR (Limit is 1.4x)
    result = signal_validator.validate_signal(signal, 0.0100, 0.0150)
    assert result["is_valid"] is False
    assert any("high_volatility" in r for r in result["reasons"])


def test_minimum_rr_rejects_bad_setups(signal_validator):
    """Test that an R:R below 3:1 rejects the trade setup."""
    signal = {
        "direction": "BUY",
        "confidence_score": 8,
        "confluence_factors_met": [
            "higher_timeframe_trend_aligned",
            "liquidity_sweep_confirmed",
            "inducement_tapped",
        ],
        "sl_pips": 10,
        "tp_pips": 20,  # 2:1 RR (Required is 3:1)
    }
    result = signal_validator.validate_signal(signal, 0.0100, 0.0050)
    assert result["is_valid"] is False
    assert any("low_rr_ratio" in r for r in result["reasons"])
