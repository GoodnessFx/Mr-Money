import pytest

from src.sizer import KellySizer


@pytest.fixture
def kelly_sizer():
    return KellySizer()


def test_kelly_never_exceeds_max_risk_pct(kelly_sizer):
    """Test that the position size is capped by the max_risk_per_trade_pct."""
    # High win rate and R:R would yield a large Kelly size
    # W=0.8, R=5. Raw Kelly = (0.8 * 6 - 1) / 5 = 0.76 (76% risk)
    # Applied Kelly (0.25) = 19%
    # Cap (1.0%) should bring it down to 1.0%
    result = kelly_sizer.calculate_position_size(10000, 0.8, 5.0, 10, "EURUSD")
    assert result["kelly_applied"] == 0.01


def test_fractional_kelly_applied_correctly(kelly_sizer):
    """Test that fractional Kelly (0.25) is applied correctly."""
    # W=0.6, R=3. Raw Kelly = (0.6 * 4 - 1) / 3 = (2.4 - 1) / 3 = 0.4666
    # Fractional Kelly (0.25) = 0.1166 (11.66%)
    # Cap is 1.0%
    result = kelly_sizer.calculate_position_size(10000, 0.6, 3.0, 10, "EURUSD")
    assert result["kelly_applied"] == 0.01


def test_handles_zero_negative_expected_value(kelly_sizer):
    """Test that zero or negative expected value returns zero size."""
    # W=0.2, R=2. Raw Kelly = (0.2 * 3 - 1) / 2 = -0.2 (Negative)
    result = kelly_sizer.calculate_position_size(10000, 0.2, 2.0, 10, "EURUSD")
    assert result["units"] == 0
    assert result["lot_size"] == 0
    assert result["dollar_risk"] == 0
