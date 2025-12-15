"""
Stealth Configuration Module for Google Maps Scraper

This module provides anti-detection utilities including:
- User agent rotation
- Proxy management
- Human-like delay generation
- Browser fingerprint configuration
- CAPTCHA detection and handling
"""

import os
import random
import logging
import time
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass
from enum import Enum

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv

    # Load .env file from the same directory as this script
    try:
        script_dir = Path(__file__).parent.absolute()
        env_path = script_dir / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        else:
            load_dotenv()
    except Exception:
        load_dotenv()
except ImportError:
    # python-dotenv not installed, skip loading .env
    pass

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration from Environment Variables
# ============================================================================


class StealthConfig:
    """Configuration class for stealth settings loaded from environment variables."""

    # Stealth settings
    STEALTH_ENABLED: bool = os.getenv("STEALTH_ENABLED", "true").lower() == "true"
    HUMAN_SIMULATION_ENABLED: bool = (
        os.getenv("HUMAN_SIMULATION_ENABLED", "true").lower() == "true"
    )

    # Proxy settings
    PROXY_ENABLED: bool = (
        os.getenv("PROXY_ENABLED", "false").lower() == "true"
    )  # Master switch for proxy usage
    PROXY_URL: Optional[str] = os.getenv("PROXY_URL")
    PROXY_USERNAME: Optional[str] = os.getenv("PROXY_USERNAME")
    PROXY_PASSWORD: Optional[str] = os.getenv("PROXY_PASSWORD")
    PROXY_ROTATION_ENABLED: bool = (
        os.getenv("PROXY_ROTATION_ENABLED", "false").lower() == "true"
    )
    PROXY_LIST: Optional[str] = os.getenv(
        "PROXY_LIST"
    )  # Comma-separated list of proxies

    # Browserless settings (fallback)
    BROWSERLESS_TOKEN: Optional[str] = os.getenv("BROWSERLESS_TOKEN")
    BROWSERLESS_BASE_URL: str = os.getenv(
        "BROWSERLESS_BASE_URL", "https://chrome.browserless.io"
    )

    # CAPTCHA settings
    CAPTCHA_SERVICE: Optional[str] = os.getenv(
        "CAPTCHA_SERVICE"
    )  # "2captcha" or "anticaptcha"
    CAPTCHA_API_KEY: Optional[str] = os.getenv("CAPTCHA_API_KEY")

    @classmethod
    def has_proxy(cls) -> bool:
        """Check if proxy is configured and enabled."""
        return cls.PROXY_ENABLED and bool(cls.PROXY_URL)

    @classmethod
    def has_browserless(cls) -> bool:
        """Check if browserless is configured."""
        return bool(cls.BROWSERLESS_TOKEN)

    @classmethod
    def has_captcha_service(cls) -> bool:
        """Check if CAPTCHA service is configured."""
        return bool(cls.CAPTCHA_SERVICE and cls.CAPTCHA_API_KEY)


# ============================================================================
# User Agent Rotation
# ============================================================================


class UserAgentRotator:
    """Rotating user agent generator with realistic browser fingerprints."""

    # Modern Chrome user agents (updated regularly)
    CHROME_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    ]

    # Firefox user agents
    FIREFOX_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]

    # Edge user agents
    EDGE_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    ]

    def __init__(self, browser_type: str = "chrome"):
        """
        Initialize user agent rotator.

        Args:
            browser_type: "chrome", "firefox", "edge", or "random"
        """
        self.browser_type = browser_type
        self._last_ua = None

    def get_user_agent(self) -> str:
        """Get a random user agent."""
        if self.browser_type == "chrome":
            agents = self.CHROME_USER_AGENTS
        elif self.browser_type == "firefox":
            agents = self.FIREFOX_USER_AGENTS
        elif self.browser_type == "edge":
            agents = self.EDGE_USER_AGENTS
        else:  # random
            agents = (
                self.CHROME_USER_AGENTS
                + self.FIREFOX_USER_AGENTS
                + self.EDGE_USER_AGENTS
            )

        # Avoid using the same user agent twice in a row
        available = (
            [ua for ua in agents if ua != self._last_ua] if self._last_ua else agents
        )
        self._last_ua = random.choice(available)
        return self._last_ua

    @staticmethod
    def get_accept_language(location: Optional[str] = None) -> str:
        """Get Accept-Language header based on location."""
        language_map = {
            "us": "en-US,en;q=0.9",
            "uk": "en-GB,en;q=0.9",
            "ca": "en-CA,en;q=0.9,fr-CA;q=0.8",
            "au": "en-AU,en;q=0.9",
            "de": "de-DE,de;q=0.9,en;q=0.8",
            "fr": "fr-FR,fr;q=0.9,en;q=0.8",
            "es": "es-ES,es;q=0.9,en;q=0.8",
        }

        if location:
            location_lower = location.lower()
            for key, value in language_map.items():
                if key in location_lower:
                    return value

        return "en-US,en;q=0.9"


# ============================================================================
# Proxy Management
# ============================================================================


@dataclass
class ProxyInfo:
    """Proxy configuration dataclass."""

    url: str
    username: Optional[str] = None
    password: Optional[str] = None
    failed_count: int = 0
    last_used: float = 0

    @property
    def auth_url(self) -> str:
        """Get proxy URL with authentication if available."""
        if self.username and self.password:
            # Parse and reconstruct URL with auth
            from urllib.parse import urlparse, urlunparse

            parsed = urlparse(self.url)
            netloc = f"{self.username}:{self.password}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
        return self.url


class ProxyManager:
    """Proxy rotation and management."""

    def __init__(self):
        self.proxies: List[ProxyInfo] = []
        self.current_index: int = 0
        self._load_proxies()

    def _load_proxies(self) -> None:
        """Load proxies from environment configuration."""
        # Only load proxies if proxy is enabled
        if not StealthConfig.PROXY_ENABLED:
            logger.info("Proxy is disabled via PROXY_ENABLED=false")
            return

        # Load single proxy
        if StealthConfig.PROXY_URL:
            self.proxies.append(
                ProxyInfo(
                    url=StealthConfig.PROXY_URL,
                    username=StealthConfig.PROXY_USERNAME,
                    password=StealthConfig.PROXY_PASSWORD,
                )
            )

        # Load proxy list if provided
        if StealthConfig.PROXY_LIST:
            for proxy_url in StealthConfig.PROXY_LIST.split(","):
                proxy_url = proxy_url.strip()
                if proxy_url and proxy_url not in [p.url for p in self.proxies]:
                    self.proxies.append(ProxyInfo(url=proxy_url))

        if self.proxies:
            logger.info(f"Loaded {len(self.proxies)} proxies for rotation")
        else:
            logger.info("No proxies configured, running without proxy")

    def get_proxy(self) -> Optional[ProxyInfo]:
        """Get the next available proxy."""
        # Don't use proxy if disabled
        if not StealthConfig.PROXY_ENABLED:
            return None

        if not self.proxies:
            return None

        if not StealthConfig.PROXY_ROTATION_ENABLED:
            return self.proxies[0]

        # Find a proxy that hasn't failed too many times
        for _ in range(len(self.proxies)):
            proxy = self.proxies[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.proxies)

            if proxy.failed_count < 3:
                proxy.last_used = time.time()
                return proxy

        # Reset failed counts if all proxies have failed
        for proxy in self.proxies:
            proxy.failed_count = 0

        return self.proxies[0] if self.proxies else None

    def mark_proxy_failed(self, proxy: ProxyInfo) -> None:
        """Mark a proxy as failed."""
        proxy.failed_count += 1
        logger.warning(f"Proxy {proxy.url} failed ({proxy.failed_count} failures)")

    def mark_proxy_success(self, proxy: ProxyInfo) -> None:
        """Mark a proxy as successful."""
        proxy.failed_count = max(0, proxy.failed_count - 1)

    def get_playwright_proxy_config(self) -> Optional[Dict[str, Any]]:
        """Get proxy configuration for Playwright."""
        proxy = self.get_proxy()
        if not proxy:
            return None

        config = {"server": proxy.url}
        if proxy.username:
            config["username"] = proxy.username
        if proxy.password:
            config["password"] = proxy.password

        return config


# ============================================================================
# Human Behavior Simulation
# ============================================================================


class HumanBehavior:
    """Simulate human-like behavior to avoid detection."""

    @staticmethod
    def random_delay(min_sec: float = 1.0, max_sec: float = 3.0) -> float:
        """
        Generate human-like random delay using normal distribution.

        Args:
            min_sec: Minimum delay in seconds
            max_sec: Maximum delay in seconds

        Returns:
            Delay duration in seconds
        """
        mean = (min_sec + max_sec) / 2
        std = (max_sec - min_sec) / 4
        delay = random.gauss(mean, std)
        return max(min_sec, min(max_sec, delay))

    @staticmethod
    def typing_delay() -> float:
        """Get delay for simulating typing speed."""
        return HumanBehavior.random_delay(0.05, 0.15)

    @staticmethod
    def click_delay() -> float:
        """Get delay before clicking."""
        return HumanBehavior.random_delay(0.3, 0.8)

    @staticmethod
    def page_load_delay() -> float:
        """Get delay after page load."""
        return HumanBehavior.random_delay(2.0, 4.0)

    @staticmethod
    def scroll_delay() -> float:
        """Get delay between scroll actions."""
        return HumanBehavior.random_delay(0.5, 1.5)

    @staticmethod
    def between_actions_delay() -> float:
        """Get delay between major actions."""
        return HumanBehavior.random_delay(1.0, 2.5)

    @staticmethod
    def get_random_viewport() -> Dict[str, int]:
        """Get a random but realistic viewport size."""
        viewports = [
            {"width": 1920, "height": 1080},
            {"width": 1366, "height": 768},
            {"width": 1536, "height": 864},
            {"width": 1440, "height": 900},
            {"width": 1280, "height": 720},
            {"width": 1600, "height": 900},
            {"width": 2560, "height": 1440},
            {"width": 1680, "height": 1050},
        ]
        return random.choice(viewports)

    @staticmethod
    async def simulate_mouse_movement(
        page, target_x: int, target_y: int, steps: int = 10
    ) -> None:
        """
        Simulate human-like mouse movement to a target position.

        Args:
            page: Playwright page object
            target_x: Target X coordinate
            target_y: Target Y coordinate
            steps: Number of intermediate steps
        """
        try:
            # Get current mouse position (start from random position if unknown)
            current_x = random.randint(100, 500)
            current_y = random.randint(100, 500)

            for i in range(steps):
                # Calculate intermediate position with some randomness
                progress = (i + 1) / steps
                # Add slight curve to movement
                curve = random.uniform(-20, 20) * (1 - progress)

                next_x = int(current_x + (target_x - current_x) * progress + curve)
                next_y = int(current_y + (target_y - current_y) * progress + curve)

                await page.mouse.move(next_x, next_y)
                await asyncio.sleep(random.uniform(0.01, 0.03))

            # Final move to exact position
            await page.mouse.move(target_x, target_y)

        except Exception as e:
            logger.debug(f"Mouse movement simulation error: {e}")

    @staticmethod
    async def human_scroll(page, direction: str = "down", amount: int = 300) -> None:
        """
        Simulate human-like scrolling.

        Args:
            page: Playwright page object
            direction: "up" or "down"
            amount: Scroll amount in pixels
        """
        try:
            multiplier = 1 if direction == "down" else -1

            # Scroll in smaller increments with slight pauses
            scroll_steps = random.randint(3, 6)
            step_amount = amount // scroll_steps

            for _ in range(scroll_steps):
                # Add randomness to each scroll step
                actual_amount = step_amount + random.randint(-20, 20)
                await page.mouse.wheel(0, actual_amount * multiplier)
                await asyncio.sleep(random.uniform(0.05, 0.15))

        except Exception as e:
            logger.debug(f"Scroll simulation error: {e}")


# ============================================================================
# Browser Fingerprint Configuration
# ============================================================================


class BrowserFingerprint:
    """Browser fingerprint configuration for stealth mode."""

    @staticmethod
    def get_stealth_args() -> List[str]:
        """Get Chrome launch arguments for stealth mode."""
        return [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-site-isolation-trials",
            "--disable-web-security",
            "--disable-features=CrossSiteDocumentBlockingIfIsolating",
            "--disable-features=CrossSiteDocumentBlockingAlways",
            "--disable-infobars",
            "--window-position=0,0",
            "--ignore-certificate-errors",
            "--ignore-certificate-errors-spki-list",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-default-apps",
            "--disable-translate",
            "--disable-sync",
            "--hide-scrollbars",
            "--metrics-recording-only",
            "--mute-audio",
            "--no-first-run",
            "--safebrowsing-disable-auto-update",
        ]

    @staticmethod
    def get_timezone_for_location(location: Optional[str]) -> str:
        """Get timezone ID based on location."""
        timezone_map = {
            "new york": "America/New_York",
            "los angeles": "America/Los_Angeles",
            "chicago": "America/Chicago",
            "houston": "America/Chicago",
            "phoenix": "America/Phoenix",
            "san francisco": "America/Los_Angeles",
            "seattle": "America/Los_Angeles",
            "denver": "America/Denver",
            "boston": "America/New_York",
            "atlanta": "America/New_York",
            "miami": "America/New_York",
            "dallas": "America/Chicago",
            "austin": "America/Chicago",
            "london": "Europe/London",
            "paris": "Europe/Paris",
            "berlin": "Europe/Berlin",
            "tokyo": "Asia/Tokyo",
            "sydney": "Australia/Sydney",
            "toronto": "America/Toronto",
            "vancouver": "America/Vancouver",
        }

        if location:
            location_lower = location.lower()
            for key, tz in timezone_map.items():
                if key in location_lower:
                    return tz

        return "America/New_York"  # Default

    @staticmethod
    def get_geolocation_for_location(
        location: Optional[str],
    ) -> Optional[Dict[str, float]]:
        """Get approximate geolocation for location."""
        geo_map = {
            "new york": {"latitude": 40.7128, "longitude": -74.0060},
            "los angeles": {"latitude": 34.0522, "longitude": -118.2437},
            "chicago": {"latitude": 41.8781, "longitude": -87.6298},
            "houston": {"latitude": 29.7604, "longitude": -95.3698},
            "phoenix": {"latitude": 33.4484, "longitude": -112.0740},
            "san francisco": {"latitude": 37.7749, "longitude": -122.4194},
            "seattle": {"latitude": 47.6062, "longitude": -122.3321},
            "denver": {"latitude": 39.7392, "longitude": -104.9903},
            "boston": {"latitude": 42.3601, "longitude": -71.0589},
            "atlanta": {"latitude": 33.7490, "longitude": -84.3880},
            "miami": {"latitude": 25.7617, "longitude": -80.1918},
            "dallas": {"latitude": 32.7767, "longitude": -96.7970},
            "austin": {"latitude": 30.2672, "longitude": -97.7431},
            "london": {"latitude": 51.5074, "longitude": -0.1278},
            "paris": {"latitude": 48.8566, "longitude": 2.3522},
            "berlin": {"latitude": 52.5200, "longitude": 13.4050},
            "tokyo": {"latitude": 35.6762, "longitude": 139.6503},
            "sydney": {"latitude": -33.8688, "longitude": 151.2093},
            "toronto": {"latitude": 43.6532, "longitude": -79.3832},
            "vancouver": {"latitude": 49.2827, "longitude": -123.1207},
        }

        if location:
            location_lower = location.lower()
            for key, geo in geo_map.items():
                if key in location_lower:
                    # Add slight randomness to avoid exact coordinates
                    return {
                        "latitude": geo["latitude"] + random.uniform(-0.01, 0.01),
                        "longitude": geo["longitude"] + random.uniform(-0.01, 0.01),
                        "accuracy": random.randint(10, 100),
                    }

        return None


# ============================================================================
# CAPTCHA Detection and Handling
# ============================================================================


class CaptchaType(Enum):
    """Types of CAPTCHA that can be detected."""

    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V3 = "recaptcha_v3"
    HCAPTCHA = "hcaptcha"
    FUNCAPTCHA = "funcaptcha"
    UNKNOWN = "unknown"


class CaptchaDetector:
    """Detect CAPTCHA challenges on pages."""

    CAPTCHA_INDICATORS = [
        # reCAPTCHA indicators
        "g-recaptcha",
        "recaptcha",
        "grecaptcha",
        "rc-anchor",
        "rc-imageselect",
        # hCaptcha indicators
        "h-captcha",
        "hcaptcha",
        # General CAPTCHA indicators
        "captcha",
        "challenge",
        "verify you are human",
        "are you a robot",
        "prove you're not a robot",
        "unusual traffic",
        "automated queries",
    ]

    @classmethod
    async def detect_captcha(cls, page) -> Tuple[bool, Optional[CaptchaType]]:
        """
        Detect if a CAPTCHA is present on the page.

        Args:
            page: Playwright page object

        Returns:
            Tuple of (is_captcha_present, captcha_type)
        """
        try:
            page_content = await page.content()
            page_content_lower = page_content.lower()

            # Check for reCAPTCHA
            if (
                "g-recaptcha" in page_content_lower
                or "grecaptcha" in page_content_lower
            ):
                if "recaptcha/api2/anchor" in page_content_lower:
                    return True, CaptchaType.RECAPTCHA_V2
                return True, CaptchaType.RECAPTCHA_V3

            # Check for hCaptcha
            if "h-captcha" in page_content_lower or "hcaptcha" in page_content_lower:
                return True, CaptchaType.HCAPTCHA

            # Check for FunCaptcha
            if "funcaptcha" in page_content_lower or "arkoselabs" in page_content_lower:
                return True, CaptchaType.FUNCAPTCHA

            # Check for generic CAPTCHA indicators
            for indicator in cls.CAPTCHA_INDICATORS:
                if indicator in page_content_lower:
                    return True, CaptchaType.UNKNOWN

            # Check for Google's "unusual traffic" page
            if (
                "unusual traffic" in page_content_lower
                or "automated queries" in page_content_lower
            ):
                return True, CaptchaType.RECAPTCHA_V2

            return False, None

        except Exception as e:
            logger.error(f"Error detecting CAPTCHA: {e}")
            return False, None


class CaptchaSolver:
    """CAPTCHA solving integration (2Captcha/Anti-Captcha)."""

    def __init__(self):
        self.service = StealthConfig.CAPTCHA_SERVICE
        self.api_key = StealthConfig.CAPTCHA_API_KEY

    def is_configured(self) -> bool:
        """Check if CAPTCHA solving is configured."""
        return bool(self.service and self.api_key)

    async def solve_recaptcha_v2(self, site_key: str, page_url: str) -> Optional[str]:
        """
        Solve reCAPTCHA v2 using external service.

        Args:
            site_key: reCAPTCHA site key
            page_url: URL of the page with CAPTCHA

        Returns:
            Solution token or None if failed
        """
        if not self.is_configured():
            logger.warning("CAPTCHA service not configured")
            return None

        try:
            if self.service == "2captcha":
                return await self._solve_with_2captcha(site_key, page_url)
            elif self.service == "anticaptcha":
                return await self._solve_with_anticaptcha(site_key, page_url)
            else:
                logger.error(f"Unknown CAPTCHA service: {self.service}")
                return None

        except Exception as e:
            logger.error(f"Error solving CAPTCHA: {e}")
            return None

    async def _solve_with_2captcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve CAPTCHA using 2Captcha service."""
        try:
            import aiohttp

            # Submit CAPTCHA
            submit_url = "http://2captcha.com/in.php"
            params = {
                "key": self.api_key,
                "method": "userrecaptcha",
                "googlekey": site_key,
                "pageurl": page_url,
                "json": 1,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(submit_url, data=params) as response:
                    result = await response.json()

                if result.get("status") != 1:
                    logger.error(f"2Captcha submit error: {result}")
                    return None

                captcha_id = result.get("request")

                # Poll for result
                result_url = f"http://2captcha.com/res.php?key={self.api_key}&action=get&id={captcha_id}&json=1"

                for _ in range(30):  # Max 30 attempts (5 minutes)
                    await asyncio.sleep(10)  # Wait 10 seconds between polls

                    async with session.get(result_url) as response:
                        result = await response.json()

                    if result.get("status") == 1:
                        return result.get("request")
                    elif result.get("request") != "CAPCHA_NOT_READY":
                        logger.error(f"2Captcha error: {result}")
                        return None

                logger.error("2Captcha timeout")
                return None

        except Exception as e:
            logger.error(f"2Captcha error: {e}")
            return None

    async def _solve_with_anticaptcha(
        self, site_key: str, page_url: str
    ) -> Optional[str]:
        """Solve CAPTCHA using Anti-Captcha service."""
        try:
            import aiohttp

            # Create task
            create_url = "https://api.anti-captcha.com/createTask"
            payload = {
                "clientKey": self.api_key,
                "task": {
                    "type": "RecaptchaV2TaskProxyless",
                    "websiteURL": page_url,
                    "websiteKey": site_key,
                },
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(create_url, json=payload) as response:
                    result = await response.json()

                if result.get("errorId") != 0:
                    logger.error(f"Anti-Captcha create error: {result}")
                    return None

                task_id = result.get("taskId")

                # Poll for result
                result_url = "https://api.anti-captcha.com/getTaskResult"
                result_payload = {"clientKey": self.api_key, "taskId": task_id}

                for _ in range(30):  # Max 30 attempts (5 minutes)
                    await asyncio.sleep(10)

                    async with session.post(
                        result_url, json=result_payload
                    ) as response:
                        result = await response.json()

                    if result.get("status") == "ready":
                        return result.get("solution", {}).get("gRecaptchaResponse")
                    elif result.get("errorId") != 0:
                        logger.error(f"Anti-Captcha error: {result}")
                        return None

                logger.error("Anti-Captcha timeout")
                return None

        except Exception as e:
            logger.error(f"Anti-Captcha error: {e}")
            return None


# ============================================================================
# Detection Exception
# ============================================================================


class DetectionException(Exception):
    """Exception raised when bot detection is encountered."""

    pass


class CaptchaException(Exception):
    """Exception raised when CAPTCHA is encountered."""

    def __init__(self, captcha_type: CaptchaType, message: str = "CAPTCHA detected"):
        self.captcha_type = captcha_type
        super().__init__(message)


class AllMethodsFailedException(Exception):
    """Exception raised when all scraping methods have failed."""

    pass


# Import asyncio at the end to avoid circular imports
import asyncio


# ============================================================================
# Stealth Page Setup
# ============================================================================


async def apply_stealth_scripts(page) -> None:
    """
    Apply stealth JavaScript to evade detection.

    Args:
        page: Playwright page object
    """
    # Override navigator.webdriver
    await page.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """
    )

    # Override navigator.plugins
    await page.add_init_script(
        """
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                { name: 'Native Client', filename: 'internal-nacl-plugin' }
            ]
        });
    """
    )

    # Override navigator.languages
    await page.add_init_script(
        """
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
    """
    )

    # Override chrome runtime
    await page.add_init_script(
        """
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };
    """
    )

    # Override permissions
    await page.add_init_script(
        """
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
    """
    )

    # Add WebGL vendor and renderer
    await page.add_init_script(
        """
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) {
                return 'Intel Inc.';
            }
            if (parameter === 37446) {
                return 'Intel Iris OpenGL Engine';
            }
            return getParameter(parameter);
        };
    """
    )

    logger.debug("Applied stealth scripts to page")


async def handle_cookie_consent(page) -> None:
    """
    Handle cookie consent popups.

    Args:
        page: Playwright page object
    """
    consent_selectors = [
        # Google consent
        'button[aria-label*="Accept"]',
        'button[aria-label*="Agree"]',
        '[aria-label*="Accept all"]',
        '[aria-label*="Accept cookies"]',
        # Generic consent buttons
        'button:has-text("Accept")',
        'button:has-text("Accept all")',
        'button:has-text("Agree")',
        'button:has-text("I agree")',
        'button:has-text("OK")',
        'button:has-text("Got it")',
        ".consent-accept",
        "#accept-cookies",
        '[data-testid="cookie-accept"]',
    ]

    for selector in consent_selectors:
        try:
            button = await page.query_selector(selector)
            if button:
                await button.click()
                logger.info(f"Clicked cookie consent button: {selector}")
                await asyncio.sleep(0.5)
                return
        except Exception:
            continue

    logger.debug("No cookie consent popup found")
