"""
Security module for Mr Money.
Handles environment validation, secret management, and system health checks.
"""

import os
import ssl
from pathlib import Path

import structlog
import yaml
import httpx
import requests
from cryptography.fernet import Fernet
from dotenv import load_dotenv

# Setup logger
logger = structlog.get_logger()


# Enforce TLS 1.2+ globally for security
def enforce_tls12():
    """Configures requests and httpx to use at least TLS 1.2."""
    # For requests/urllib3
    from urllib3.util import ssl_

    ssl_.DEFAULT_CIPHERS = "DEFAULT:!OTLSv1:!OTLSv1.1"

    # For httpx
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT:!OTLSv1:!OTLSv1.1")
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    # Store for global use
    global httpx_client
    httpx_client = httpx.AsyncClient(verify=ctx, timeout=30.0)
    logger.info("tls_1_2_enforced")


# Run enforcement on module load
enforce_tls12()

# Load environment variables
load_dotenv()


class SecurityManager:
    """Handles environment validation, secret management, and configuration loading."""

    REQUIRED_ENV_VARS = [
        "ANTHROPIC_API_KEY",
        "OANDA_API_KEY",
        "OANDA_ACCOUNT_ID",
        "DB_ENCRYPTION_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TV_USERNAME",
        "TV_PASSWORD",
    ]

    def __init__(self):
        """Initializes the SecurityManager and runs startup checks."""
        self.validate_env()
        self.validate_anthropic_key()
        self.fernet = Fernet(os.getenv("DB_ENCRYPTION_KEY").encode())
        self.strategy_config = self._load_strategy_config()
        logger.info("security_startup_checks_passed")

    def validate_env(self):
        """Ensures all required environment variables are present. Hard exits if any missing."""
        missing_vars = [var for var in self.REQUIRED_ENV_VARS if not os.getenv(var)]
        if missing_vars:
            error_msg = (
                f"CRITICAL: Missing required environment variables: "
                f"{', '.join(missing_vars)}"
            )
            logger.error("env_validation_failed", missing_vars=missing_vars)
            print(error_msg)
            exit(1)
        logger.info("env_validation_success")

    def validate_anthropic_key(self):
        """Validates Anthropic API key format. Hard exits if invalid."""
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key or not key.startswith("sk-ant-"):
            logger.error("invalid_anthropic_key_format")
            print(
                "CRITICAL: Invalid Anthropic API key format (must start with sk-ant-)"
            )
            exit(1)
        logger.info("anthropic_key_format_validated")

    async def validate_broker_connectivity(self):
        """Validates broker API connectivity on startup. Hard exits if fails."""
        from src.executor import broker_executor

        try:
            balance = await broker_executor.get_account_balance(is_forex=True)
            logger.info("broker_connectivity_validated", balance=balance)
            return True
        except Exception as e:
            logger.error("broker_connectivity_failed", error=str(e))
            print(f"CRITICAL: Broker connectivity failed: {str(e)}")
            exit(1)

    def _load_strategy_config(self):
        """Loads the strategy.yaml configuration file."""
        config_path = Path("config/strategy.yaml")
        if not config_path.exists():
            # If strategy.yaml is not present, we will generate a template and exit as per instructions
            self.generate_strategy_template(config_path)
            print(
                f"Setup guide: Generated {config_path}. Please configure it and restart."
            )
            exit(0)

        with open(config_path, "r") as f:
            try:
                config = yaml.safe_load(f)
                logger.info("strategy_config_loaded")
                return config
            except yaml.YAMLError as e:
                logger.error("strategy_config_parse_error", error=str(e))
                raise

    def generate_strategy_template(self, path: Path):
        """Generates a default strategy.yaml template."""
        template = {
            "pairs": {"forex": ["EURUSD", "GBPUSD", "USDJPY"], "crypto": ["BTC/USDT"]},
            "timeframes": {"primary": "4H", "intermediate": "1H", "entry": "15M"},
            "confluence": {
                "required_score": 7,
                "factors": [
                    {
                        "name": "higher_timeframe_trend_aligned",
                        "weight": 3,
                        "description": "4H trend matches trade direction",
                    },
                    {
                        "name": "key_level_interaction",
                        "weight": 2,
                        "description": "Price at S/R or Supply/Demand zone",
                    },
                    {
                        "name": "market_structure_break",
                        "weight": 2,
                        "description": "BOS/CHOCH on 1H/15M",
                    },
                    {
                        "name": "candle_confirmation",
                        "weight": 1,
                        "description": "Engulfing/Pin bar at level",
                    },
                    {
                        "name": "volume_confirmation",
                        "weight": 1,
                        "description": "Volume spike on signal",
                    },
                    {
                        "name": "fibonacci_confluence",
                        "weight": 1,
                        "description": "Price at 0.618/0.786",
                    },
                ],
            },
            "risk": {
                "max_risk_per_trade_pct": 1.0,
                "max_daily_loss_pct": 3.0,
                "max_open_trades": 3,
                "min_rr_ratio": 3.0,
                "kelly_fraction": 0.25,
                "volatility_filter_multiplier": 1.4,
            },
            "schedule": {"scan_interval_minutes": 15, "market_open_only": False},
        }
        os.makedirs(path.parent, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(template, f, default_flow_style=False)

    def encrypt_data(self, data: str) -> bytes:
        """Encrypts data using Fernet."""
        return self.fernet.encrypt(data.encode())

    def decrypt_data(self, encrypted_data: bytes) -> str:
        """Decrypts data using Fernet."""
        return self.fernet.decrypt(encrypted_data).decode()

    def get_config(self) -> dict:
        """Returns the loaded strategy configuration."""
        return self.strategy_config

    @staticmethod
    def health_check():
        """System health check for Docker healthcheck."""
        try:
            # Check if logs directory exists
            log_dir = Path("logs")
            if not log_dir.exists():
                print("Healthcheck failed: logs directory missing")
                exit(1)
            # Check if DB is accessible
            db_path = Path("data/mr_money.db")
            if not db_path.exists():
                print("Healthcheck failed: database file missing")
                exit(1)
            # Check if strategy.yaml exists
            config_path = Path("config/strategy.yaml")
            if not config_path.exists():
                print("Healthcheck failed: strategy.yaml missing")
                exit(1)
            print("Healthcheck passed")
            exit(0)
        except Exception as e:
            print(f"Healthcheck failed with exception: {str(e)}")
            exit(1)


def health_check():
    """Top-level health check function for Docker."""
    SecurityManager.health_check()


def mask_key(key: str) -> str:
    """Masks API keys for logging, showing only last 4 characters."""
    if not key or len(key) <= 4:
        return "****"
    return "*" * (len(key) - 4) + key[-4:]


# Singleton instance
security_manager = SecurityManager()
