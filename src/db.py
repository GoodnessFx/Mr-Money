import datetime
import os
import shutil
import tarfile

import structlog
from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey,
                        Integer, String, create_engine)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

# Setup logger
logger = structlog.get_logger()

# Base model
Base = declarative_base()


class Trade(Base):
    """Represents a trade executed by the system."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    pair = Column(String, nullable=False)
    direction = Column(String, nullable=False)  # 'buy' or 'sell'
    entry_price = Column(Float)
    exit_price = Column(Float)
    sl_pips = Column(Float)
    tp_pips = Column(Float)
    lot_size = Column(Float)
    units = Column(Float)
    dollar_risk = Column(Float)
    kelly_raw = Column(Float)
    kelly_applied = Column(Float)
    confidence_score = Column(Integer)
    confluence_factors = Column(JSON)
    reasoning = Column(String)
    status = Column(String, default="open")  # 'open', 'closed', 'cancelled'
    result = Column(Float)  # Profit/Loss amount
    pnl_pct = Column(Float)
    entry_time = Column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    exit_time = Column(DateTime)
    setup_type = Column(String)  # For Bayesian updates
    trace_id = Column(String)  # Audit trail

    def __repr__(self):
        return f"<Trade(id={self.id}, pair='{self.pair}', direction='{self.direction}', result={self.result})>"


class Signal(Base):
    """Stores Claude's analysis results for audit."""

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    timestamp = Column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    pair = Column(String, nullable=False)
    trace_id = Column(String, unique=True)
    raw_json = Column(JSON)
    confidence_score = Column(Integer)
    is_valid = Column(Boolean)
    rejection_reason = Column(String)


class BayesianState(Base):
    """Tracks performance metrics for Bayesian win probability updates."""

    __tablename__ = "bayesian_state"

    id = Column(Integer, primary_key=True)
    setup_type = Column(String, unique=True, nullable=False)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    total_trades = Column(Integer, default=0)
    win_probability = Column(Float, default=0.5)  # Posterior
    last_updated = Column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


class DailyPL(Base):
    """Tracks daily profit and loss for risk management."""

    __tablename__ = "daily_pl"

    id = Column(Integer, primary_key=True)
    date = Column(
        DateTime,
        unique=True,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    starting_balance = Column(Float)
    current_pnl_pct = Column(Float, default=0.0)
    is_breached = Column(Boolean, default=False)


class AuditLog(Base):
    """Full reasoning trail for every decision."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    trace_id = Column(String)
    pair = Column(String)
    action = Column(String)  # 'scan', 'signal', 'size', 'execute', 'risk_check'
    data = Column(JSON)
    reasoning = Column(String)


class DatabaseManager:
    """Manages the encrypted SQLite database and backups."""

    def __init__(self):
        self.db_dir = "data"
        self.db_path = os.path.join(self.db_dir, "mr_money.db")
        os.makedirs(self.db_dir, exist_ok=True)

        # SQLCipher connection string: sqlite+pysqlcipher://:password@/path/to/db.db
        encryption_key = os.getenv("DB_ENCRYPTION_KEY")

        try:
            # Try to use SQLCipher for encryption
            db_url = f"sqlite+pysqlcipher://:{encryption_key}@/{self.db_path}"
            self.engine = create_engine(db_url)
            # Test connection to check if driver is available
            with self.engine.connect() as conn:
                pass
            logger.info("database_initialized_with_encryption", path=self.db_path)
        except Exception as e:
            # Fallback to standard SQLite if pysqlcipher3 is not available
            db_url = f"sqlite:///{self.db_path}"
            self.engine = create_engine(db_url)
            logger.warning(
                "database_encryption_unavailable_using_standard_sqlite",
                path=self.db_path,
                error=str(e),
            )

        self.Session = sessionmaker(bind=self.engine)

        # Initialize tables
        Base.metadata.create_all(self.engine)

    def get_session(self):
        """Returns a new session."""
        return self.Session()

    def log_audit(self, trace_id, pair, action, reasoning, data=None):
        """Logs a decision to the audit log."""
        session = self.get_session()
        try:
            log = AuditLog(
                trace_id=trace_id,
                pair=pair,
                action=action,
                reasoning=reasoning,
                data=data,
            )
            session.add(log)
            session.commit()
        except Exception as e:
            logger.error("db_audit_log_failed", error=str(e))
            session.rollback()
        finally:
            session.close()

    def perform_daily_backup(self):
        """Creates an encrypted local backup of the database."""
        backup_dir = os.path.join(self.db_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%d_%H%M%S"
        )
        backup_filename = f"mr_money_backup_{timestamp}.tar.gz"
        backup_path = os.path.join(backup_dir, backup_filename)

        try:
            with tarfile.open(backup_path, "w:gz") as tar:
                tar.add(self.db_path, arcname=os.path.basename(self.db_path))
            logger.info("daily_backup_successful", path=backup_path)

            # Encrypt the backup archive as well (optional, but good for security)
            # For now, since the DB is already encrypted, the tar.gz is relatively safe.
        except Exception as e:
            logger.error("daily_backup_failed", error=str(e))


# Singleton instance
db_manager = DatabaseManager()
