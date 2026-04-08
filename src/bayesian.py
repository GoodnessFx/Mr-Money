import structlog
from typing import Dict, Any, List
from src.db import db_manager, BayesianState
import datetime

# Setup logger
logger = structlog.get_logger()


class BayesianUpdater:
    """Updates win probabilities per setup type using Bayesian update (Beta distribution)."""

    def __init__(self):
        self.prior_alpha = 1  # Initial wins + 1
        self.prior_beta = 1  # Initial losses + 1
        self.min_samples = 10
        logger.info("bayesian_updater_initialized")

    def get_win_probability(self, setup_type: str) -> float:
        """Returns the current win probability (posterior) for a setup type."""
        session = db_manager.get_session()
        try:
            state = (
                session.query(BayesianState).filter_by(setup_type=setup_type).first()
            )

            # Prior: 0.5 (Beta(1,1))
            if not state or state.total_trades < self.min_samples:
                logger.info(
                    "using_prior_probability",
                    setup_type=setup_type,
                    samples=state.total_trades if state else 0,
                )
                return 0.5

            # Bayesian Update: (wins + alpha) / (total + alpha + beta)
            # This is the mean of the Beta distribution posterior
            posterior_mean = (state.wins + self.prior_alpha) / (
                state.total_trades + self.prior_alpha + self.prior_beta
            )

            logger.info(
                "posterior_probability_calculated",
                setup_type=setup_type,
                prob=round(posterior_mean, 4),
                total=state.total_trades,
            )
            return posterior_mean

        except Exception as e:
            logger.error("bayesian_update_failed", error=str(e))
            return 0.5
        finally:
            session.close()

    def update_performance(self, setup_type: str, is_win: bool):
        """Updates Bayesian state for a specific setup type after trade closes."""
        session = db_manager.get_session()
        try:
            state = (
                session.query(BayesianState).filter_by(setup_type=setup_type).first()
            )
            if not state:
                state = BayesianState(setup_type=setup_type)
                session.add(state)

            state.total_trades += 1
            if is_win:
                state.wins += 1
            else:
                state.losses += 1

            # Update win probability for cache/reference
            state.win_probability = (state.wins + self.prior_alpha) / (
                state.total_trades + self.prior_alpha + self.prior_beta
            )
            state.last_updated = datetime.datetime.now(datetime.timezone.utc)

            session.commit()
            logger.info("bayesian_state_updated", setup_type=setup_type, is_win=is_win)
        except Exception as e:
            logger.error("performance_update_failed", error=str(e))
            session.rollback()
        finally:
            session.close()


# Singleton instance
bayesian_updater = BayesianUpdater()
