import pytest
import datetime
from unittest.mock import MagicMock, patch
from src.risk import RiskGuardian


@pytest.fixture
def risk_guardian():
    return RiskGuardian()


@pytest.mark.asyncio
@patch("src.executor.broker_executor.get_account_balance")
@patch("src.db.db_manager.get_session")
async def test_daily_loss_limit_halts_trading(
    mock_get_session, mock_balance, risk_guardian
):
    """Test that breaching the daily loss limit (3%) halts all trading."""
    mock_balance.return_value = 10000
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    # Breached daily P&L (-3.5%)
    mock_trade = MagicMock()
    mock_trade.pnl_pct = -3.5
    mock_session.query().filter().all.return_value = [mock_trade]

    # Other checks would pass
    mock_session.query().filter().count.return_value = 0
    mock_session.query().filter().order_by().limit().all.return_value = []

    assert await risk_guardian.validate_trade_attempt("EURUSD") is False


@pytest.mark.asyncio
@patch("src.executor.broker_executor.get_account_balance")
@patch("src.db.db_manager.get_session")
async def test_circuit_breaker_fires_after_3_losses(
    mock_get_session, mock_balance, risk_guardian
):
    """Test that 3 consecutive losses within 4 hours triggers the circuit breaker."""
    mock_balance.return_value = 10000
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    # 3 consecutive losses in the last hour
    now = datetime.datetime.now(datetime.timezone.utc)
    mock_trades = [MagicMock(result=-100, exit_time=now) for _ in range(3)]
    mock_session.query().filter().order_by().limit().all.return_value = mock_trades

    # Other checks would pass
    mock_session.query().filter().all.return_value = []
    mock_session.query().filter().count.return_value = 0

    assert await risk_guardian.validate_trade_attempt("EURUSD") is False


@pytest.mark.asyncio
@patch("src.executor.broker_executor.get_account_balance")
@patch("src.db.db_manager.get_session")
async def test_max_open_trades_respected(mock_get_session, mock_balance, risk_guardian):
    """Test that exceeding max_open_trades (3) halts trading."""
    mock_balance.return_value = 10000
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    # 3 open trades
    mock_session.query().filter().count.return_value = 3

    # Other checks would pass
    mock_session.query().filter().all.return_value = []
    mock_session.query().filter().order_by().limit().all.return_value = []

    assert await risk_guardian.validate_trade_attempt("EURUSD") is False
