from unittest.mock import MagicMock, patch

import pytest

from src.bayesian import BayesianUpdater


@pytest.fixture
def bayesian_updater():
    return BayesianUpdater()


@patch("src.db.db_manager.get_session")
def test_prior_returns_0_5_with_no_data(mock_get_session, bayesian_updater):
    """Test that the prior (0.5) is returned when no data exists for a setup type."""
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_session.query().filter_by().first.return_value = None

    assert bayesian_updater.get_win_probability("trend_breakout") == 0.5


@patch("src.db.db_manager.get_session")
def test_probability_updates_correctly_after_wins(mock_get_session, bayesian_updater):
    """Test that the win probability is updated correctly (Beta distribution posterior mean)."""
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    # Existing metrics: 10 wins, 20 total trades
    # Posterior Mean = (10 + 1) / (20 + 1 + 1) = 11 / 22 = 0.5
    # Wait, let's use different numbers: 15 wins, 20 total
    # Posterior Mean = (15 + 1) / (20 + 1 + 1) = 16 / 22 = 0.7272
    mock_state = MagicMock()
    mock_state.wins = 15
    mock_state.total_trades = 20
    mock_session.query().filter_by().first.return_value = mock_state

    prob = bayesian_updater.get_win_probability("trend_breakout")
    assert round(prob, 4) == 0.7273


@patch("src.db.db_manager.get_session")
def test_handles_insufficient_sample_size(mock_get_session, bayesian_updater):
    """Test that the prior (0.5) is returned if samples are below min_samples (10)."""
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session

    # 5 total trades (Less than 10)
    mock_state = MagicMock()
    mock_state.wins = 4
    mock_state.total_trades = 5
    mock_session.query().filter_by().first.return_value = mock_state

    assert bayesian_updater.get_win_probability("trend_breakout") == 0.5
