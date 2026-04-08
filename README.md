# Mr Money — Professional AI Trading System 

Mr Money is a fully autonomous, institutional-grade trading system that connects Claude AI (via Anthropic Computer Use API) to TradingView to visually analyze charts and execute high-probability confluence trades.

## What it does
- **Autonomous Chart Analysis**: Claude AI "looks" at live TradingView charts across multiple timeframes (Daily, 4H, 1H, 15M).
- **Institutional Strategy**: Applies a rigorous 4-step analysis framework: Trend Bias -> Advanced Market Structure -> Liquidity Detection -> Entry Triggers.
- **Mathematical Sizing**: Uses the fractional Kelly Criterion and Bayesian win probability updates to optimize risk.
- **Security-First**: Encrypted database, masked API keys, and non-root Docker containerization.
- **Multi-Broker**: Native support for OANDA (Forex) and CCXT (Crypto fallback).

## Architecture diagram (ASCII)
```text
+----------------+       +-------------------+       +-------------------+
|  TradingView   | <---> |  Chart Controller | <---> |   Claude Brain    |
|   (Browser)    |       |   (Playwright)    |       | (Computer Use API)|
+----------------+       +-------------------+       +-------------------+
                                  ^                            |
                                  |                            v
+----------------+       +-------------------+       +-------------------+
|  Telegram Bot  | <---  |  Main Orchestrator| <---  |  Signal Validator |
| (Notifications)|       |    (Scheduler)    |       | (Confluence Score)|
+----------------+       +-------------------+       +-------------------+
                                  |                            |
                                  v                            v
+----------------+       +-------------------+       +-------------------+
|  Broker API    | <---  |   Order Executor  | <---  |   Kelly Sizer     |
| (OANDA/CCXT)   |       |  (Atomic SL/TP)   |       | (Risk Management) |
+----------------+       +-------------------+       +-------------------+
                                  |                            ^
                                  v                            |
                         +-------------------+       +-------------------+
                         | Encrypted SQLite  | <---> | Bayesian Updater  |
                         |   (SQLCipher)     |       | (Self-Learning)   |
                         +-------------------+       +-------------------+
```

## Prerequisites
- Docker & Docker Compose
- Anthropic API Key (Claude 3.5 Sonnet)
- OANDA API Key (Practice or Live)
- Telegram Bot Token & Chat ID
- TradingView Credentials

## Quick start (5 commands to running)
1. **Clone the repo**: `git clone https://github.com/your-repo/mr_money.git && cd mr_money`
2. **Setup Env**: `cp .env.example .env` (fill in your keys)
3. **Gen Encryption Key**: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` (add to .env)
4. **Init Strategy**: `python -m src.main --mode=paper` (generates `config/strategy.yaml`, then edit it)
5. **Launch**: `docker compose up -d --build` (Note: use `docker compose` instead of `docker-compose`)

## Configuration guide (strategy.yaml explained)
- **pairs**: Define the Forex and Crypto pairs to scan.
- **confluence**: Weighted factors (e.g., HTF Trend = 3, BOS = 2). Requires a total score of 7/10 to trade.
- **risk**: `max_risk_per_trade_pct` (cap), `max_daily_loss_pct` (halt bot), `min_rr_ratio` (minimum 3:1).
- **schedule**: `scan_interval_minutes` (frequency of analysis).

## Adding your pairs and strategy
Simply edit `config/strategy.yaml`. The bot will automatically reload the configuration at the start of the next scan cycle.

## Security model
- **Secrets**: Never hardcoded. Loaded from `.env` and masked in logs.
- **Database**: Encrypted with SQLCipher using a key derived from your `DB_ENCRYPTION_KEY`.
- **Docker**: Runs as a non-root user (uid 1001) with no-new-privileges escalation.
- **Network**: Strict whitelist of external API calls (Anthropic, OANDA, Telegram, TradingView).

## Risk management explained
- **Daily Loss Limit**: Bot halts all trading if daily drawdown hits 3%.
- **Circuit Breaker**: 3 consecutive losses trigger a mandatory 4-hour pause.
- **Max Positions**: Caps simultaneous open trades (default 3) and prevents doubling up on the same pair.
- **Emergency Halt**: Set `EMERGENCY_HALT=true` in `.env` to stop the bot immediately.

## How Kelly Criterion sizing works
The bot uses the formula `f* = (p * b - q) / b`.
- `p` = Win Probability (from Bayesian engine).
- `b` = Reward:Risk Ratio (from signal).
- We apply a `kelly_fraction` (0.25) to dampen volatility and ensure capital preservation.

## How Bayesian updating works
Every trade outcome is logged per `setup_type`. The bot calculates the posterior win probability using a Beta distribution `(wins + 1) / (total + 2)`. It requires at least 10 samples before moving away from the conservative 50/50 prior.

## Telegram notifications setup
1. Create a bot via `@BotFather` on Telegram.
2. Get your `TELEGRAM_BOT_TOKEN`.
3. Get your `TELEGRAM_CHAT_ID` via `@userinfobot`.
4. Add both to your `.env`.

## Running in paper trading mode (OANDA practice)
Start the system with:
```bash
python -m src.main --mode=paper
```
In paper mode, the bot performs full analysis and sizing but generates mock `order_id`s instead of hitting the broker API.

## Going live (checklist)
- [ ] Passed 100% of test suite: `pytest tests/`
- [ ] Strategy backtested manually via Claude's logic
- [ ] `OANDA_ENVIRONMENT` set to `live`
- [ ] Sufficient margin in account
- [ ] Start with: `python -m src.main --mode=live` (requires manual confirmation)

## Monitoring and logs
- **Audit Log**: Every decision is stored in the `audit_logs` table in the DB.
- **Application Logs**: Found in `logs/app.log` (JSON format).
- **Screenshots**: Encrypted analysis screenshots stored in `logs/screenshots/`.

## Troubleshooting
- **Playwright Errors**: Check if your TradingView credentials are correct and if TV has changed its UI selectors.
- **Database Locked**: Ensure only one instance of the bot is running.
- **API Errors**: Check your `.env` keys and connectivity.

## Performance tuning
- Increase `MAX_CONCURRENT_SESSIONS` in `brain.py` if your machine has more than 4 CPU cores.
- Adjust `scan_interval_minutes` based on your strategy's timeframe.

## Disclaimer
**Capital at Risk**. Trading Forex and Crypto involves significant risk. Mr Money is provided for educational and research purposes. The developers are not responsible for any financial losses. Use at your own risk.

---
*Built with precision for the modern quantitative trader.*
