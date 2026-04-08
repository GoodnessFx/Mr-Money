import asyncio
import os
import time
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext
import structlog
from src.security import security_manager

# Setup logger
logger = structlog.get_logger()


class ChartController:
    """Manages Playwright browser with TradingView login, retry logic, and session isolation."""

    TRADINGVIEW_URL = "https://www.tradingview.com/"
    CHART_URL = "https://www.tradingview.com/chart/"

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.screenshot_dir = Path("logs/screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        logger.info("chart_controller_initialized")

    async def start(self):
        """Initializes the browser."""
        if not self.browser:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
            logger.info("browser_started", headless=True)

    async def stop(self):
        """Closes the browser."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("browser_stopped")

    async def get_session_context(self) -> BrowserContext:
        """Creates an isolated browser context for a pair session."""
        context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        return context

    async def login_to_tradingview(self, page: Page):
        """Handles login to TradingView using credentials from env."""
        username = os.getenv("TV_USERNAME")
        password = os.getenv("TV_PASSWORD")

        await page.goto(self.TRADINGVIEW_URL)
        try:
            # Note: Selectors might need updates as TV changes their UI
            await page.click("button:has-text('Sign in')", timeout=10000)
            await page.click("button:has-text('Email')")
            await page.fill("input[name='username']", username)
            await page.fill("input[name='password']", password)
            await page.click("button[type='submit']")
            await page.wait_for_selector(".tv-header-user-menu-button", timeout=30000)
            logger.info("tradingview_login_success")
        except Exception as e:
            logger.error("tradingview_login_failed", error=str(e))
            raise

    async def navigate_to_pair(self, page: Page, pair: str):
        """Navigates to the chart for a specific pair with retry logic."""
        if "/" in pair:
            pair = pair.replace("/", "")

        url = f"{self.CHART_URL}?symbol={pair}"

        for attempt in range(1, 4):
            try:
                await page.goto(url, wait_until="networkidle", timeout=60000)
                logger.info("navigated_to_pair", pair=pair, attempt=attempt)
                return
            except Exception as e:
                logger.warning(
                    "navigation_failed", pair=pair, attempt=attempt, error=str(e)
                )
                if attempt == 3:
                    raise
                await asyncio.sleep(5)

    async def set_timeframe(self, page: Page, timeframe: str):
        """Changes the timeframe on the chart."""
        tf_map = {"4H": "240", "1H": "60", "15M": "15", "1D": "1D"}
        tf_code = tf_map.get(timeframe, timeframe)

        await page.keyboard.press("Escape")
        await page.keyboard.type(tf_code)
        await page.keyboard.press("Enter")
        await asyncio.sleep(3)
        logger.info("timeframe_set", timeframe=timeframe)

    async def take_encrypted_screenshot(self, page: Page, filename: str) -> str:
        """Takes a screenshot, encrypts it, and saves it."""
        raw_path = self.screenshot_dir / f"raw_{filename}.png"
        encrypted_path = self.screenshot_dir / f"{filename}.enc"

        await page.screenshot(path=str(raw_path))

        # Encrypt the file
        with open(raw_path, "rb") as f:
            encrypted_data = security_manager.encrypt_data(
                f.read().decode("latin1") if isinstance(f.read(), bytes) else f.read()
            )
            # Correction: security_manager.encrypt_data expects str, returns bytes.
            # Actually let's just store the bytes directly.

        # Re-implement encryption for binary data in security_manager or here
        data = raw_path.read_bytes()
        encrypted_data = security_manager.fernet.encrypt(data)
        encrypted_path.write_bytes(encrypted_data)

        # Remove raw screenshot
        raw_path.unlink()

        logger.info("encrypted_screenshot_saved", path=str(encrypted_path))
        return str(encrypted_path)

    def purge_old_screenshots(self, days: int = 7):
        """Purges screenshots older than the specified number of days."""
        cutoff = time.time() - (days * 86400)
        for f in self.screenshot_dir.glob("*.enc"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                logger.info("purged_old_screenshot", file=f.name)


# Singleton instance
chart_controller = ChartController()
