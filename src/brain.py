"""
Claude AI analysis engine for Mr Money.
Uses Anthropic Computer Use API to analyze TradingView charts.
"""

import asyncio
import base64
import json
import os
import uuid
from typing import Any, Dict

import structlog
from anthropic import AsyncAnthropic

from src.chart import chart_controller
from src.security import security_manager

# Setup logger
logger = structlog.get_logger()


class ClaudeBrain:
    """Claude AI analysis engine using Anthropic Computer Use API with trace_id and concurrency limits."""

    MODEL = "claude-3-5-sonnet-20241022"
    MAX_CONCURRENT_SESSIONS = 4

    def __init__(self):
        """Initializes the ClaudeBrain with API client and concurrency semaphore."""
        self.client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.strategy_config = security_manager.get_config()
        self.semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_SESSIONS)
        logger.info(
            "claude_brain_initialized",
            model=self.MODEL,
            max_concurrent=self.MAX_CONCURRENT_SESSIONS,
        )

    def _get_system_prompt(self, pair: str) -> str:
        """Generates the institutional-grade system prompt for Claude."""
        confluence = self.strategy_config["confluence"]
        factors_str = "\n".join(
            [
                f"- {f['name']} (Weight: {f['weight']}): {f['description']}"
                for f in confluence["factors"]
            ]
        )

        return f"""
You are an elite institutional forex and commodities trader with 10+ years experience. You are analyzing live TradingView charts to identify high-probability trade setups.

Your analysis framework (apply in this exact order):

STEP 1 — HIGHER TIMEFRAME BIAS (Daily and 4H)
- Determine trend: distinguish between EXTERNAL (swing) structure and INTERNAL (sub) structure.
- Identify major S/R and Supply/Demand zones visible on this timeframe.
- Note any premium/discount zones (above/below 50% of last major swing).
- Go from DAILY to 4H to 1H then 15M.

STEP 2 — ADVANCED MARKET STRUCTURE (1H)
- Identify the SWING points (HH/HL or LH/LL).
- Look for INDUCEMENT (IDM): the first internal pullback after a break of structure (BOS).
- Confirm Change of Character (CHOCH) for trend reversals or BOS for trend continuation.
- Identify the TRADING RANGE: work only within the most recent valid high and low.
- Identify Order Blocks (OB) and Fair Value Gaps (FVG) within the range.

STEP 3 — LIQUIDITY DETECTION & ENTRY TRIGGER (15M)
- Spot LIQUIDITY: Equal Highs (EQH), Equal Lows (EQL), or Trendline Liquidity.
- Wait for a LIQUIDITY SWEEP: price must take out liquidity (stop hunt) before reversing.
- Identify the ENTRY TRIGGER: SMT (Smart Money Tool) divergence, or a 15M CHOCH after the sweep.
- Confirm volume spike on the sweep and reversal candle.
- Fibonacci: ensure entry is in the DISCOUNT zone for buys and PREMIUM zone for sells.

STEP 4 — TRADE PARAMETERS
- Entry: current close price of signal candle.
- SL: 5-10 pips below demand zone (buy) or above supply zone (sell), never more than 20 pips for majors.
- TP: next significant structure level with minimum 2:1 R:R.
- Invalidation: if price closes beyond SL level on 15M before entry fills.

CONFLUENCE CHECKLIST:
{factors_str}

REQUIRED SCORE: {confluence['required_score']}/10

If you are not at least 70% confident: direction must be NO_TRADE.
Never force a trade. Capital preservation is the primary objective.

Return ONLY this JSON (no other text):
{{
  "direction": "BUY" | "SELL" | "NO_TRADE",
  "confidence_score": integer (0-10),
  "confluence_factors_met": [list of factor names],
  "reasoning": "concise explanation under 200 chars",
  "entry_price": float,
  "sl_price": float,
  "tp_price": float,
  "sl_pips": float,
  "tp_pips": float,
  "rr_ratio": float,
  "invalidation": "brief description",
  "setup_type": "descriptive_slug_for_bayesian_tracking"
}}
"""

    async def analyze_pair(self, pair: str) -> Dict[str, Any]:
        """Orchestrates analysis with trace_id, rate limiting, and session isolation."""
        trace_id = str(uuid.uuid4())

        async with self.semaphore:
            logger.info("starting_analysis", pair=pair, trace_id=trace_id)

            # Start browser if not running
            await chart_controller.start()

            # Create isolated context
            context = await chart_controller.get_session_context()
            page = await context.new_page()

            try:
                # Login and Navigate
                await chart_controller.login_to_tradingview(page)
                await chart_controller.navigate_to_pair(page, pair)

                messages = [{"role": "user", "content": []}]

                # Analysis Steps with Screenshots
                analysis_steps = ["1D", "4H", "1H", "15M"]
                for tf in analysis_steps:
                    await chart_controller.set_timeframe(page, tf)

                    # Take screenshot
                    filename = f"{pair}_{tf}_{trace_id}"
                    encrypted_path = await chart_controller.take_encrypted_screenshot(
                        page, filename
                    )

                    # Decrypt for Claude (in memory)
                    with open(encrypted_path, "rb") as f:
                        decrypted_data = security_manager.fernet.decrypt(f.read())
                        image_base64 = base64.b64encode(decrypted_data).decode()

                    messages[0]["content"].append(
                        {
                            "type": "text",
                            "text": f"Chart screenshot for {tf} timeframe:",
                        }
                    )
                    messages[0]["content"].append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_base64,
                            },
                        }
                    )

                # Final Analysis Call
                response = await self.client.messages.create(
                    model=self.MODEL,
                    max_tokens=2000,
                    system=self._get_system_prompt(pair),
                    messages=messages,
                )

                text_response = response.content[0].text
                result = self._parse_strict_json(text_response, trace_id)
                result["trace_id"] = trace_id

                logger.info(
                    "analysis_completed",
                    pair=pair,
                    trace_id=trace_id,
                    direction=result.get("direction"),
                )
                return result

            except Exception as e:
                logger.error(
                    "analysis_failed", pair=pair, trace_id=trace_id, error=str(e)
                )
                return {
                    "direction": "NO_TRADE",
                    "confidence_score": 0,
                    "reasoning": f"Error: {str(e)}",
                    "trace_id": trace_id,
                }
            finally:
                await page.close()
                await context.close()

    def _parse_strict_json(self, text: str, trace_id: str) -> Dict[str, Any]:
        """Parses response strictly and logs errors."""
        try:
            start_idx = text.find("{")
            end_idx = text.rfind("}") + 1
            if start_idx == -1 or end_idx == 0:
                raise ValueError("No JSON object found in response")

            json_str = text[start_idx:end_idx]
            return json.loads(json_str)
        except Exception as e:
            logger.error(
                "malformed_json_response",
                trace_id=trace_id,
                error=str(e),
                raw_text=text[:200],
            )
            return {
                "direction": "NO_TRADE",
                "confidence_score": 0,
                "reasoning": "Malformed JSON response",
            }


# Singleton instance
brain = ClaudeBrain()
