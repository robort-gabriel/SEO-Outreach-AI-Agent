"""
Email Finder Agent for FastAPI

This is a production-ready backend agent that uses LangGraph
to orchestrate email finding from website URLs using Playwright
with advanced anti-detection features.

This module is designed to be used with the FastAPI application (main.py).
Use the FastAPI endpoints to interact with the email finder.

FEATURES:
    - Stealth browser configuration to avoid bot detection
    - Proxy rotation support
    - Human-like behavior simulation
    - CAPTCHA detection and handling
    - Scrapes homepage, contact page, and about page for emails

REQUIRED ENVIRONMENT VARIABLES:
    None (optional stealth features can be configured)

OPTIONAL ENVIRONMENT VARIABLES:
    - STEALTH_ENABLED: Enable stealth mode (default: true)
    - HUMAN_SIMULATION_ENABLED: Enable human behavior simulation (default: true)
    - PROXY_URL: Proxy server URL
    - PROXY_USERNAME: Proxy authentication username
    - PROXY_PASSWORD: Proxy authentication password
    - PROXY_ROTATION_ENABLED: Enable proxy rotation (default: false)
    - CAPTCHA_SERVICE: CAPTCHA solving service (2captcha or anticaptcha)
    - CAPTCHA_API_KEY: API key for CAPTCHA solving service

USAGE:
    This module is imported and used by main.py. To use the email finder:
    1. Start the FastAPI server: python main.py
    2. Make API requests to /api/v1/find-emails endpoint
"""

import logging
import os
import random
import re
from pathlib import Path
from typing import TypedDict, Annotated, List, Optional, Dict, Any, Literal
from urllib.parse import urlparse, urljoin
import asyncio

from playwright.async_api import (
    async_playwright,
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver

# Import stealth configuration
from stealth_config import (
    StealthConfig,
    UserAgentRotator,
    ProxyManager,
    HumanBehavior,
    BrowserFingerprint,
    CaptchaDetector,
    CaptchaSolver,
    CaptchaType,
    DetectionException,
    CaptchaException,
    AllMethodsFailedException,
    apply_stealth_scripts,
    handle_cookie_consent,
)

# Try to load .env file if python-dotenv is available
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
    except NameError:
        load_dotenv()
except ImportError:
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Try to import playwright-stealth (optional but recommended)
try:
    from playwright_stealth import stealth_async

    PLAYWRIGHT_STEALTH_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_STEALTH_AVAILABLE = False
    logger.warning(
        "playwright-stealth not installed. Some anti-detection features may be limited."
    )

# Try to import httpx for static HTML parsing
try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logger.warning("httpx not installed. Static HTML parsing will not be available.")

# Try to import BeautifulSoup for HTML parsing
try:
    from bs4 import BeautifulSoup

    BEAUTIFULSOUP_AVAILABLE = True
except ImportError:
    BEAUTIFULSOUP_AVAILABLE = False
    logger.warning(
        "BeautifulSoup not installed. Static HTML parsing will not be available."
    )

# Try to import Selenium for fallback browser automation
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException

    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    logger.warning("Selenium not installed. Selenium fallback will not be available.")

# Try to import python-whois for WHOIS lookup
try:
    import whois

    WHOIS_AVAILABLE = True
except ImportError:
    WHOIS_AVAILABLE = False
    logger.warning("python-whois not installed. WHOIS lookup will not be available.")

# Try to import dnspython for MX record checking
try:
    import dns.resolver

    DNS_AVAILABLE = True
except ImportError:
    DNS_AVAILABLE = False
    logger.warning("dnspython not installed. MX record checking will be limited.")

# Try to import aiohttp for async HTTP requests
try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logger.warning("aiohttp not installed. Some features may be limited.")


# ============================================================================
# Custom Exceptions
# ============================================================================


class PlaywrightTimeoutSkipException(Exception):
    """
    Exception raised when Playwright times out.
    This indicates the URL should be skipped entirely without trying other methods.
    """

    pass


# ============================================================================
# State Definition
# ============================================================================


class EmailFinderState(TypedDict):
    """State for the email finder agent."""

    messages: Annotated[List, lambda x, y: x + y]
    websites: List[Dict[str, Any]]  # List of websites with URL field
    location: Optional[str]  # Optional location for context
    scrape_website_info: (
        bool  # Whether to scrape website title, description, and summary
    )
    enriched_results: Optional[List[Dict[str, Any]]]
    status: str
    error: Optional[str]


# ============================================================================
# Website Scraper (Same as Google Maps Scraper)
# ============================================================================


class WebsiteScraper:
    """
    Advanced scraper for extracting email addresses from websites.
    Uses the same advanced scraping functionality as Google Maps scraper.

    Features:
    - Stealth browser configuration
    - Proxy rotation support
    - Human-like behavior simulation
    - CAPTCHA detection and handling
    - Scrapes homepage, contact page, and about page
    """

    def __init__(self):
        # Initialize stealth components
        self.user_agent_rotator = UserAgentRotator(browser_type="chrome")
        self.proxy_manager = ProxyManager()
        self.captcha_solver = CaptchaSolver()

        # Configuration flags
        self.stealth_enabled = StealthConfig.STEALTH_ENABLED
        self.human_simulation_enabled = StealthConfig.HUMAN_SIMULATION_ENABLED

        # Current session info
        self._current_location: Optional[str] = None

        logger.info(
            f"WebsiteScraper initialized (stealth={self.stealth_enabled}, human_sim={self.human_simulation_enabled})"
        )

    def _get_browser_args(self, proxy_url: Optional[str] = None) -> List[str]:
        """Get browser launch arguments with optional proxy."""
        args = BrowserFingerprint.get_stealth_args()

        if proxy_url:
            args.append(f"--proxy-server={proxy_url}")

        return args

    async def _create_stealth_page(
        self, browser: Browser, location: Optional[str] = None
    ) -> Page:
        """
        Create a new page with stealth configuration.

        Args:
            browser: Playwright browser instance
            location: Optional location for timezone/geolocation matching

        Returns:
            Configured Playwright page
        """
        # Get random viewport
        viewport = HumanBehavior.get_random_viewport()

        # Get user agent
        user_agent = self.user_agent_rotator.get_user_agent()

        # Get timezone for location
        timezone_id = BrowserFingerprint.get_timezone_for_location(location)

        # Get geolocation for location
        geolocation = BrowserFingerprint.get_geolocation_for_location(location)

        # Get accept language
        accept_language = UserAgentRotator.get_accept_language(location)

        # Create context with configuration
        context_options = {
            "viewport": viewport,
            "user_agent": user_agent,
            "locale": "en-US",
            "timezone_id": timezone_id,
            "extra_http_headers": {
                "Accept-Language": accept_language,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
            },
        }

        if geolocation:
            context_options["geolocation"] = geolocation
            context_options["permissions"] = ["geolocation"]

        # Add proxy if configured
        proxy_config = self.proxy_manager.get_playwright_proxy_config()
        if proxy_config:
            context_options["proxy"] = proxy_config

        context = await browser.new_context(**context_options)
        page = await context.new_page()

        # Apply stealth scripts
        if self.stealth_enabled:
            # Use playwright-stealth if available
            if PLAYWRIGHT_STEALTH_AVAILABLE:
                await stealth_async(page)

            # Apply additional stealth scripts
            await apply_stealth_scripts(page)

        logger.debug(
            f"Created stealth page with viewport {viewport['width']}x{viewport['height']}"
        )
        return page

    async def _handle_detection(self, page: Page) -> bool:
        """
        Check for and handle bot detection.

        Args:
            page: Playwright page object

        Returns:
            True if detection was handled, False if unrecoverable
        """
        # Check for CAPTCHA
        has_captcha, captcha_type = await CaptchaDetector.detect_captcha(page)

        if has_captcha:
            logger.warning(f"CAPTCHA detected: {captcha_type}")

            # Check if CAPTCHA is actually blocking the page content
            is_blocking = await page.evaluate(
                """
                () => {
                    // Check if page is showing a blocking CAPTCHA page
                    const bodyText = document.body.innerText.toLowerCase();
                    const blockingIndicators = [
                        'unusual traffic',
                        'automated queries',
                        'sorry we cannot verify',
                        'please verify you are not a robot'
                    ];
                    
                    for (const indicator of blockingIndicators) {
                        if (bodyText.includes(indicator)) {
                            return true;
                        }
                    }
                    
                    // Check if main content is hidden by CAPTCHA
                    const mainContent = document.querySelector('main, article, [role="main"], .content, #content');
                    if (mainContent) {
                        const rect = mainContent.getBoundingClientRect();
                        const style = window.getComputedStyle(mainContent);
                        // If main content is visible, CAPTCHA is not blocking
                        if (rect.width > 100 && rect.height > 100 && 
                            style.display !== 'none' && style.visibility !== 'hidden') {
                            return false;
                        }
                    }
                    
                    return false;
                }
                """
            )

            if is_blocking:
                # Only raise exception if CAPTCHA is actually blocking
                if self.captcha_solver.is_configured():
                    # Try to solve CAPTCHA
                    try:
                        # Extract site key (for reCAPTCHA)
                        site_key = await page.evaluate(
                            """
                            () => {
                                const recaptcha = document.querySelector('.g-recaptcha');
                                return recaptcha ? recaptcha.getAttribute('data-sitekey') : null;
                            }
                        """
                        )

                        if site_key:
                            solution = await self.captcha_solver.solve_recaptcha_v2(
                                site_key, page.url
                            )

                            if solution:
                                # Inject solution
                                await page.evaluate(
                                    f"""
                                    (token) => {{
                                        document.getElementById('g-recaptcha-response').innerHTML = token;
                                        if (typeof ___grecaptcha_cfg !== 'undefined') {{
                                            Object.entries(___grecaptcha_cfg.clients).forEach(([key, client]) => {{
                                                if (client.callback) client.callback(token);
                                            }});
                                        }}
                                    }}
                                """,
                                    solution,
                                )

                                logger.info("CAPTCHA solved successfully")
                                return True

                    except Exception as e:
                        logger.error(f"Failed to solve CAPTCHA: {e}")

                raise CaptchaException(
                    captcha_type, "CAPTCHA detected and blocking page access"
                )
            else:
                # CAPTCHA detected but not blocking - log and continue
                logger.info(
                    f"CAPTCHA detected ({captcha_type}) but not blocking page content, continuing..."
                )
                return False

        # Check for other detection indicators
        page_content = await page.content()
        detection_indicators = [
            "unusual traffic",
            "automated queries",
            "please verify",
            "sorry, we can't verify",
            "something went wrong",
        ]

        page_content_lower = page_content.lower()
        for indicator in detection_indicators:
            if indicator in page_content_lower:
                logger.warning(f"Bot detection indicator found: {indicator}")
                raise DetectionException(f"Bot detected: {indicator}")

        return False

    async def _human_like_navigation(
        self, page: Page, url: str, timeout: int = 60000
    ) -> None:
        """
        Navigate to URL with human-like behavior.

        Args:
            page: Playwright page object
            url: URL to navigate to
            timeout: Navigation timeout in milliseconds
        """
        # Check if page is already closed
        if page.is_closed():
            raise Exception("Page is already closed before navigation")

        if self.human_simulation_enabled:
            # Add slight delay before navigation
            await asyncio.sleep(HumanBehavior.random_delay(0.5, 1.5))

        # Navigate with error handling
        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout)
        except Exception as nav_error:
            # Check if page was closed during navigation
            if page.is_closed() or "closed" in str(nav_error).lower():
                raise Exception(
                    f"Page/browser closed during navigation: {str(nav_error)}"
                )
            raise

        # Check if page is still valid after navigation
        if page.is_closed():
            raise Exception("Page was closed after navigation")

        if self.human_simulation_enabled:
            # Wait for page to fully render
            await asyncio.sleep(HumanBehavior.page_load_delay())

            # Check if page is still valid
            if page.is_closed():
                raise Exception("Page was closed during page load delay")

            # Handle cookie consent if present
            try:
                await handle_cookie_consent(page)
            except Exception as cookie_error:
                if page.is_closed() or "closed" in str(cookie_error).lower():
                    raise Exception(
                        f"Page closed during cookie consent handling: {str(cookie_error)}"
                    )
                logger.warning(f"Error handling cookie consent: {str(cookie_error)}")

            # Check for detection
            if not page.is_closed():
                try:
                    await self._handle_detection(page)
                except (DetectionException, CaptchaException):
                    raise
                except Exception as det_error:
                    if page.is_closed() or "closed" in str(det_error).lower():
                        raise Exception(
                            f"Page closed during detection check: {str(det_error)}"
                        )
                    raise

    async def _find_page_url(
        self, page: Page, base_url: str, keywords: List[str]
    ) -> Optional[str]:
        """
        Find a page URL by examining links on the website.

        Args:
            page: Playwright page object
            base_url: Base website URL
            keywords: List of keywords to search for in links

        Returns:
            URL of the found page, or None if not found
        """
        try:
            # Extract all links from the page
            links = await page.evaluate(
                """
                () => {
                    const links = [];
                    const allLinks = document.querySelectorAll('a[href]');
                    for (const link of allLinks) {
                        const href = link.getAttribute('href') || '';
                        const text = (link.textContent || link.getAttribute('aria-label') || '').toLowerCase();
                        if (href) {
                            links.push({ href: href, text: text });
                        }
                    }
                    return links;
                }
                """
            )

            # Parse base URL for relative URL resolution
            parsed_url = urlparse(base_url)
            base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"

            potential_links = []

            for link in links:
                href = link.get("href", "").lower()
                text = link.get("text", "").lower()

                # Skip empty links or external links (unless they're on the same domain)
                if not href:
                    continue

                # Resolve relative URLs
                if href.startswith("/"):
                    full_url = urljoin(base_domain, href)
                elif href.startswith("http"):
                    # Only include if same domain
                    if base_domain in href:
                        full_url = href
                    else:
                        continue
                else:
                    full_url = urljoin(base_url, href)

                # Check if link text or URL contains keywords
                text_matches = sum(1 for keyword in keywords if keyword in text)
                href_matches = sum(0.5 for keyword in keywords if keyword in href)

                if text_matches > 0 or href_matches > 0:
                    score = text_matches + href_matches
                    potential_links.append({"url": full_url, "score": score})

            # Sort by score and return the best match
            if potential_links:
                potential_links.sort(key=lambda x: x["score"], reverse=True)
                return potential_links[0]["url"]

            return None

        except Exception as e:
            logger.warning(f"Error finding page URL: {str(e)}")
            return None

    def _find_page_url_static(
        self, soup: Any, base_url: str, keywords: List[str]
    ) -> Optional[str]:
        """
        Find a page URL by examining links in static HTML (BeautifulSoup).

        Args:
            soup: BeautifulSoup object
            base_url: Base website URL
            keywords: List of keywords to search for in links

        Returns:
            URL of the found page, or None if not found
        """
        try:
            # Parse base URL for relative URL resolution
            parsed_url = urlparse(base_url)
            base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"

            # Find all links
            links = soup.find_all("a", href=True)
            potential_links = []

            for link in links:
                href = link.get("href", "").lower()
                text = (link.get_text(strip=True) or link.get("aria-label", "")).lower()

                if not href:
                    continue

                # Resolve relative URLs
                if href.startswith("/"):
                    full_url = urljoin(base_domain, href)
                elif href.startswith("http"):
                    # Only include if same domain
                    if base_domain in href:
                        full_url = href
                    else:
                        continue
                else:
                    full_url = urljoin(base_url, href)

                # Check if link text or URL contains keywords
                text_matches = sum(1 for keyword in keywords if keyword in text)
                href_matches = sum(0.5 for keyword in keywords if keyword in href)

                if text_matches > 0 or href_matches > 0:
                    score = text_matches + href_matches
                    potential_links.append({"url": full_url, "score": score})

            # Sort by score and return the best match
            if potential_links:
                potential_links.sort(key=lambda x: x["score"], reverse=True)
                return potential_links[0]["url"]

            return None

        except Exception as e:
            logger.warning(f"Error finding page URL in static HTML: {str(e)}")
            return None

    async def _scrape_page_static_html(
        self, client: httpx.AsyncClient, url: str
    ) -> Dict[str, Any]:
        """
        Scrape a single page using static HTML parsing.

        Args:
            client: httpx AsyncClient
            url: URL to scrape

        Returns:
            Dictionary containing page content, emails, and phone numbers
        """
        try:
            response = await client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Extract body text
            body = soup.find("body")
            body_text = body.get_text(separator="\n", strip=True) if body else ""
            body_text = body_text[:5000]  # Limit to 5000 chars

            # Extract emails using regex
            email_pattern = re.compile(
                r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
            )
            all_text = response.text
            email_matches = email_pattern.findall(all_text)

            # Filter emails
            filtered_emails = []
            exclude_patterns = [
                "example.com",
                "test.com",
                "sample.com",
                "domain.com",
                "email.com",
                "@google",
                "@facebook",
                "@twitter",
                "@instagram",
                "noreply",
                "no-reply",
                "donotreply",
            ]
            for email in email_matches:
                email_lower = email.lower()
                if not any(pattern in email_lower for pattern in exclude_patterns):
                    if email_lower not in filtered_emails:
                        filtered_emails.append(email_lower)

            # Extract mailto links
            mailto_links = soup.find_all("a", href=re.compile(r"^mailto:", re.I))
            for link in mailto_links:
                href = link.get("href", "")
                email_match = re.search(r"mailto:([^?\s]+)", href)
                if email_match:
                    email = email_match.group(1).lower()
                    if email not in filtered_emails:
                        filtered_emails.append(email)

            # Extract phone numbers
            phone_pattern = re.compile(
                r"\+?1?[\s\-]?\(?[0-9]{3}\)?[\s\-]?[0-9]{3}[\s\-]?[0-9]{4}"
            )
            phone_matches = phone_pattern.findall(all_text)
            phone_numbers = list(dict.fromkeys(phone_matches))[:5]

            # Extract tel: links
            tel_links = soup.find_all("a", href=re.compile(r"^tel:", re.I))
            for link in tel_links:
                href = link.get("href", "")
                phone_match = re.search(r"tel:([\d\+\-\(\)\s]+)", href)
                if phone_match:
                    phone = phone_match.group(1).strip()
                    if phone not in phone_numbers:
                        phone_numbers.append(phone)

            return {
                "bodyText": body_text,
                "emails": filtered_emails,
                "phoneNumbers": phone_numbers,
            }

        except Exception as e:
            logger.warning(f"Error scraping page {url} with static HTML: {str(e)}")
            return {"bodyText": "", "emails": [], "phoneNumbers": []}

    async def _scrape_with_static_html(
        self, website_url: str, timeout: int = 30000, scrape_website_info: bool = False
    ) -> Dict[str, Any]:
        """
        Fast static HTML parsing method using httpx + BeautifulSoup.
        Checks homepage, contact page, and about page for emails.

        Args:
            website_url: Website URL to scrape
            timeout: Timeout in milliseconds (for consistency with other methods)

        Returns:
            Dictionary containing website information and email addresses
        """
        if not HTTPX_AVAILABLE or not BEAUTIFULSOUP_AVAILABLE:
            raise Exception("httpx or BeautifulSoup not available")

        try:
            logger.info(f"Attempting static HTML parsing for: {website_url}")

            # Convert milliseconds to seconds for httpx (default 15 seconds)
            timeout_seconds = timeout / 1000.0 if timeout > 0 else 15.0

            async with httpx.AsyncClient(
                timeout=timeout_seconds,
                follow_redirects=True,
                headers={
                    "User-Agent": self.user_agent_rotator.get_user_agent(),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                },
            ) as client:
                # Step 1: Scrape homepage
                response = await client.get(website_url)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, "html.parser")

                # Initialize combined info with homepage data
                homepage_content = await self._scrape_page_static_html(
                    client, website_url
                )
                website_info = {
                    "emails": homepage_content.get("emails", []),
                    "phoneNumbers": homepage_content.get("phoneNumbers", []),
                }

                # Only scrape title, description, and summary if requested
                if scrape_website_info:
                    # Extract title and meta description from homepage
                    title = soup.find("title")
                    title_text = title.get_text(strip=True) if title else ""

                    meta_desc = soup.find(
                        "meta", attrs={"name": "description"}
                    ) or soup.find("meta", attrs={"property": "og:description"})
                    meta_description = meta_desc.get("content", "") if meta_desc else ""

                    website_info["title"] = title_text
                    website_info["metaDescription"] = meta_description
                    website_info["bodyText"] = homepage_content.get("bodyText", "")

                # Step 2: Find and scrape Contact page for emails
                contact_keywords = [
                    "contact",
                    "contact us",
                    "contact-us",
                    "get in touch",
                    "reach us",
                    "email us",
                ]
                contact_url = self._find_page_url_static(
                    soup, website_url, contact_keywords
                )

                if contact_url:
                    logger.info(f"Found contact page: {contact_url}")
                    contact_content = await self._scrape_page_static_html(
                        client, contact_url
                    )
                    website_info["emails"].extend(contact_content.get("emails", []))
                    website_info["phoneNumbers"].extend(
                        contact_content.get("phoneNumbers", [])
                    )
                else:
                    logger.info("No contact page found, using homepage emails only")

                # Step 3: Find and scrape About page for better summary
                about_keywords = [
                    "about",
                    "about us",
                    "about-us",
                    "our story",
                    "who we are",
                    "company",
                ]
                about_url = self._find_page_url_static(
                    soup, website_url, about_keywords
                )

                if about_url and scrape_website_info:
                    logger.info(f"Found about page: {about_url}")
                    about_content = await self._scrape_page_static_html(
                        client, about_url
                    )
                    about_text = about_content.get("bodyText", "")
                    if about_text and len(about_text) > 100:
                        website_info["bodyText"] = about_text

                # Remove duplicates from emails and phone numbers
                website_info["emails"] = list(dict.fromkeys(website_info["emails"]))[
                    :10
                ]
                website_info["phoneNumbers"] = list(
                    dict.fromkeys(website_info["phoneNumbers"])
                )[:5]

                return website_info

        except Exception as e:
            logger.warning(f"Static HTML parsing failed for {website_url}: {str(e)}")
            raise

    def _find_page_url_selenium(
        self, driver: Any, base_url: str, keywords: List[str]
    ) -> Optional[str]:
        """
        Find a page URL by examining links in Selenium.

        Args:
            driver: Selenium WebDriver
            base_url: Base website URL
            keywords: List of keywords to search for in links

        Returns:
            URL of the found page, or None if not found
        """
        try:
            # Parse base URL for relative URL resolution
            parsed_url = urlparse(base_url)
            base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"

            # Find all links
            links = driver.find_elements(By.TAG_NAME, "a")
            potential_links = []

            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    text = (link.text or link.get_attribute("aria-label") or "").lower()
                    href_lower = href.lower()

                    if not href:
                        continue

                    # Resolve relative URLs
                    if href.startswith("/"):
                        full_url = urljoin(base_domain, href)
                    elif href.startswith("http"):
                        # Only include if same domain
                        if base_domain in href:
                            full_url = href
                        else:
                            continue
                    else:
                        full_url = urljoin(base_url, href)

                    # Check if link text or URL contains keywords
                    text_matches = sum(1 for keyword in keywords if keyword in text)
                    href_matches = sum(
                        0.5 for keyword in keywords if keyword in href_lower
                    )

                    if text_matches > 0 or href_matches > 0:
                        score = text_matches + href_matches
                        potential_links.append({"url": full_url, "score": score})
                except Exception:
                    continue

            # Sort by score and return the best match
            if potential_links:
                potential_links.sort(key=lambda x: x["score"], reverse=True)
                return potential_links[0]["url"]

            return None

        except Exception as e:
            logger.warning(f"Error finding page URL in Selenium: {str(e)}")
            return None

    def _scrape_page_selenium(self, driver: Any, url: str) -> Dict[str, Any]:
        """
        Scrape a single page using Selenium.

        Args:
            driver: Selenium WebDriver
            url: URL to scrape

        Returns:
            Dictionary containing page content, emails, and phone numbers
        """
        try:
            driver.get(url)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Extract body text
            body = driver.find_element(By.TAG_NAME, "body")
            body_text = body.text[:5000]

            # Extract emails
            email_pattern = re.compile(
                r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
            )
            page_source = driver.page_source
            email_matches = email_pattern.findall(page_source)

            # Filter emails
            filtered_emails = []
            exclude_patterns = [
                "example.com",
                "test.com",
                "sample.com",
                "domain.com",
                "email.com",
                "@google",
                "@facebook",
                "@twitter",
                "@instagram",
                "noreply",
                "no-reply",
                "donotreply",
            ]
            for email in email_matches:
                email_lower = email.lower()
                if not any(pattern in email_lower for pattern in exclude_patterns):
                    if email_lower not in filtered_emails:
                        filtered_emails.append(email_lower)

            # Extract phone numbers
            phone_pattern = re.compile(
                r"\+?1?[\s\-]?\(?[0-9]{3}\)?[\s\-]?[0-9]{3}[\s\-]?[0-9]{4}"
            )
            phone_matches = phone_pattern.findall(page_source)
            phone_numbers = list(dict.fromkeys(phone_matches))[:5]

            return {
                "bodyText": body_text,
                "emails": filtered_emails,
                "phoneNumbers": phone_numbers,
            }

        except Exception as e:
            logger.warning(f"Error scraping page {url} with Selenium: {str(e)}")
            return {"bodyText": "", "emails": [], "phoneNumbers": []}

    async def _scrape_with_selenium(
        self, website_url: str, timeout: int = 30000, scrape_website_info: bool = False
    ) -> Dict[str, Any]:
        """
        Fallback scraping method using Selenium.
        Checks homepage, contact page, and about page for emails.

        Args:
            website_url: Website URL to scrape
            timeout: Timeout in seconds

        Returns:
            Dictionary containing website information and email addresses
        """
        if not SELENIUM_AVAILABLE:
            raise Exception("Selenium not available")

        try:
            logger.info(f"Attempting Selenium scraping for: {website_url}")

            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option(
                "excludeSwitches", ["enable-automation"]
            )
            chrome_options.add_experimental_option("useAutomationExtension", False)
            chrome_options.add_argument(
                f"--user-agent={self.user_agent_rotator.get_user_agent()}"
            )

            driver = webdriver.Chrome(options=chrome_options)
            # Convert milliseconds to seconds for Selenium
            timeout_seconds = timeout / 1000 if timeout > 1000 else timeout
            driver.set_page_load_timeout(timeout_seconds)

            try:
                # Step 1: Scrape homepage
                driver.get(website_url)
                WebDriverWait(driver, timeout_seconds).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )

                # Initialize combined info with homepage data
                homepage_content = self._scrape_page_selenium(driver, website_url)
                website_info = {
                    "emails": homepage_content.get("emails", []),
                    "phoneNumbers": homepage_content.get("phoneNumbers", []),
                }

                # Only scrape title, description, and summary if requested
                if scrape_website_info:
                    # Extract title and meta description from homepage
                    title = driver.title

                    try:
                        meta_desc = driver.find_element(
                            By.CSS_SELECTOR, 'meta[name="description"]'
                        )
                        meta_description = meta_desc.get_attribute("content") or ""
                    except:
                        try:
                            meta_desc = driver.find_element(
                                By.CSS_SELECTOR, 'meta[property="og:description"]'
                            )
                            meta_description = meta_desc.get_attribute("content") or ""
                        except:
                            meta_description = ""

                    website_info["title"] = title
                    website_info["metaDescription"] = meta_description
                    website_info["bodyText"] = homepage_content.get("bodyText", "")

                # Navigate back to homepage to find other pages
                driver.get(website_url)
                WebDriverWait(driver, timeout_seconds).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )

                # Step 2: Find and scrape Contact page for emails
                contact_keywords = [
                    "contact",
                    "contact us",
                    "contact-us",
                    "get in touch",
                    "reach us",
                    "email us",
                ]
                contact_url = self._find_page_url_selenium(
                    driver, website_url, contact_keywords
                )

                if contact_url:
                    logger.info(f"Found contact page: {contact_url}")
                    contact_content = self._scrape_page_selenium(driver, contact_url)
                    website_info["emails"].extend(contact_content.get("emails", []))
                    website_info["phoneNumbers"].extend(
                        contact_content.get("phoneNumbers", [])
                    )
                    # Navigate back to homepage to find about page
                    driver.get(website_url)
                    WebDriverWait(driver, timeout_seconds).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                else:
                    logger.info("No contact page found, using homepage emails only")

                # Step 3: Find and scrape About page for better summary (only if requested)
                if scrape_website_info:
                    about_keywords = [
                        "about",
                        "about us",
                        "about-us",
                        "our story",
                        "who we are",
                        "company",
                    ]
                    about_url = self._find_page_url_selenium(
                        driver, website_url, about_keywords
                    )

                    if about_url:
                        logger.info(f"Found about page: {about_url}")
                        about_content = self._scrape_page_selenium(driver, about_url)
                        about_text = about_content.get("bodyText", "")
                        if about_text and len(about_text) > 100:
                            website_info["bodyText"] = about_text

                # Remove duplicates from emails and phone numbers
                website_info["emails"] = list(dict.fromkeys(website_info["emails"]))[
                    :10
                ]
                website_info["phoneNumbers"] = list(
                    dict.fromkeys(website_info["phoneNumbers"])
                )[:5]

                return website_info

            finally:
                driver.quit()

        except Exception as e:
            logger.warning(f"Selenium scraping failed for {website_url}: {str(e)}")
            raise

    def _validate_email_syntax(self, email: str) -> bool:
        """
        Validate email syntax using regex.

        Args:
            email: Email address to validate

        Returns:
            True if email syntax is valid
        """
        email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        return bool(email_pattern.match(email))

    def _check_mx_records(self, domain: str) -> bool:
        """
        Check if domain has valid MX (Mail Exchange) records.
        This verifies the domain accepts email.

        Args:
            domain: Domain name to check

        Returns:
            True if domain has MX records
        """
        try:
            import socket

            if DNS_AVAILABLE:
                # Try to resolve MX records using dnspython
                try:
                    mx_records = dns.resolver.resolve(domain, "MX")
                    return len(mx_records) > 0
                except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                    # No MX records, but domain might still accept email via A record
                    # Check if domain resolves
                    try:
                        socket.gethostbyname(domain)
                        return True  # Domain exists, might accept email
                    except socket.gaierror:
                        return False
                except Exception:
                    return False
            else:
                # Fallback: just check if domain resolves
                try:
                    socket.gethostbyname(domain)
                    return True
                except socket.gaierror:
                    return False

        except Exception:
            return False

    def _is_disposable_email(self, email: str) -> bool:
        """
        Check if email is from a disposable/temporary email service.

        Args:
            email: Email address to check

        Returns:
            True if email is from a disposable service
        """
        domain = email.split("@")[-1].lower() if "@" in email else ""

        # Common disposable email domains
        disposable_domains = [
            "tempmail.com",
            "10minutemail.com",
            "guerrillamail.com",
            "mailinator.com",
            "throwaway.email",
            "temp-mail.org",
            "getnada.com",
            "mohmal.com",
            "yopmail.com",
            "sharklasers.com",
            "trashmail.com",
            "maildrop.cc",
            "mintemail.com",
            "fakeinbox.com",
            "dispostable.com",
        ]

        return domain in disposable_domains

    async def _verify_email_smtp(
        self, email: str, domain: str, timeout: int = 5
    ) -> bool:
        """
        Verify email exists by connecting to SMTP server.
        This is the most accurate but slowest method.
        Note: Many servers block this to prevent email harvesting.
        This method is NOT used by default due to rate limiting and blocking.

        Args:
            email: Email address to verify
            domain: Domain name
            timeout: Connection timeout in seconds

        Returns:
            True if email appears to exist (but may be blocked)
        """
        if not DNS_AVAILABLE:
            return False

        try:
            import socket
            import smtplib

            # Get MX records
            try:
                mx_records = dns.resolver.resolve(domain, "MX")
                mx_host = str(mx_records[0].exchange).rstrip(".")
            except Exception:
                # Fallback to domain itself
                mx_host = domain

            # Connect to SMTP server
            try:
                server = smtplib.SMTP(timeout=timeout)
                server.set_debuglevel(0)
                server.connect(mx_host, 25)

                # Try to verify email (VRFY command)
                try:
                    code, message = server.verify(email)
                    server.quit()
                    # 250 = success, 251 = forward, 252 = cannot verify but will accept
                    return code in [250, 251, 252]
                except smtplib.SMTPException:
                    # VRFY might be disabled, try MAIL FROM
                    try:
                        server.mail("test@example.com")
                        server.rcpt(email)
                        code, message = server.rcpt(email)
                        server.quit()
                        return code == 250
                    except Exception:
                        server.quit()
                        return False

            except (socket.timeout, socket.gaierror, smtplib.SMTPException):
                return False

        except Exception:
            return False

    def _guess_emails_from_domain(
        self, website_url: str, validate: bool = True
    ) -> List[str]:
        """
        Guess common email addresses from domain name and validate them.
        This is a fast method that doesn't require scraping.

        Args:
            website_url: Website URL
            validate: If True, validate emails (check MX records, syntax, disposable)

        Returns:
            List of guessed and validated email addresses
        """
        try:
            from urllib.parse import urlparse

            parsed = urlparse(website_url)
            domain = parsed.netloc.replace("www.", "")

            if not domain:
                return []

            # Common email patterns (ordered by likelihood)
            common_patterns = [
                "info",
                "contact",
                "hello",
                "support",
                "sales",
                "admin",
                "help",
                "inquiry",
                "general",
                "office",
                "team",
                "service",
                "careers",
                "jobs",
                "press",
                "media",
                "marketing",
                "business",
            ]

            guessed_emails = [f"{pattern}@{domain}" for pattern in common_patterns]

            if not validate:
                return guessed_emails

            # Validate emails
            validated_emails = []

            # First, check if domain has MX records (only check once)
            has_mx = self._check_mx_records(domain)

            if not has_mx:
                logger.debug(
                    f"Domain {domain} has no MX records, skipping email guessing"
                )
                return []

            for email in guessed_emails:
                # Validate syntax
                if not self._validate_email_syntax(email):
                    continue

                # Check if disposable
                if self._is_disposable_email(email):
                    continue

                validated_emails.append(email)

            logger.info(
                f"Guessed {len(validated_emails)} validated emails from domain {domain}"
            )
            return validated_emails

        except Exception as e:
            logger.warning(f"Email guessing failed for {website_url}: {str(e)}")
            return []

    def _get_emails_from_whois(self, website_url: str) -> List[str]:
        """
        Extract email addresses from WHOIS data.
        This is a free method that doesn't require scraping.

        Args:
            website_url: Website URL

        Returns:
            List of email addresses from WHOIS
        """
        if not WHOIS_AVAILABLE:
            return []

        try:
            from urllib.parse import urlparse

            parsed = urlparse(website_url)
            domain = parsed.netloc.replace("www.", "")

            if not domain:
                return []

            w = whois.whois(domain)
            emails = []

            # WHOIS data can have emails in various fields
            if w:
                if isinstance(w.emails, list):
                    emails.extend([str(e).lower() for e in w.emails if e])
                elif w.emails:
                    emails.append(str(w.emails).lower())

                # Check other fields that might contain emails
                for field in ["admin_email", "tech_email", "registrar_email"]:
                    if hasattr(w, field):
                        value = getattr(w, field)
                        if value:
                            if isinstance(value, list):
                                emails.extend([str(e).lower() for e in value if e])
                            else:
                                emails.append(str(value).lower())

            # Remove duplicates and filter
            unique_emails = list(dict.fromkeys(emails))
            filtered = [
                e
                for e in unique_emails
                if "@" in e
                and not any(
                    pattern in e
                    for pattern in [
                        "example.com",
                        "test.com",
                        "privacy",
                        "proxy",
                        "whois",
                    ]
                )
            ]

            return filtered[:5]  # Limit to 5 emails

        except Exception as e:
            logger.debug(f"WHOIS lookup failed for {website_url}: {str(e)}")
            return []

    async def _scrape_page_content(self, page: Page, url: str) -> Dict[str, Any]:
        """
        Scrape content from a specific page.

        Args:
            page: Playwright page object
            url: URL to scrape

        Returns:
            Dictionary containing page content, emails, and phone numbers
        """
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(1.5)  # Wait for dynamic content

            content = await page.evaluate(
                """
                () => {
                    const info = {
                        bodyText: '',
                        emails: [],
                        phoneNumbers: []
                    };

                    // Extract body text from main content areas
                    const contentSelectors = [
                        'main', 'article', '[role="main"]', 
                        '.content', '#content', '.main-content',
                        '.contact', '#contact', '.about', '#about'
                    ];
                    
                    let contentElement = null;
                    for (const selector of contentSelectors) {
                        contentElement = document.querySelector(selector);
                        if (contentElement) break;
                    }
                    
                    if (!contentElement) {
                        contentElement = document.body;
                    }

                    // Extract text from headings and paragraphs
                    const textElements = contentElement.querySelectorAll('h1, h2, h3, h4, h5, h6, p, li, span, div');
                    const textParts = Array.from(textElements)
                        .map(el => el.textContent?.trim())
                        .filter(text => text && text.length > 0);
                    
                    info.bodyText = textParts.join('\\n').substring(0, 5000);

                    // Extract email addresses from text content
                    const emailPattern = /([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,})/g;
                    const allText = document.body.innerText || document.body.textContent || '';
                    const emailMatches = allText.match(emailPattern);
                    
                    if (emailMatches) {
                        const filteredEmails = emailMatches
                            .map(email => email.toLowerCase().trim())
                            .filter(email => {
                                const excludePatterns = [
                                    'example.com', 'test.com', 'sample.com',
                                    'domain.com', 'email.com', 'yourdomain.com',
                                    'yoursite.com', 'website.com', 'company.com',
                                    '@google', '@facebook', '@twitter', '@instagram',
                                    'noreply', 'no-reply', 'donotreply'
                                ];
                                return !excludePatterns.some(pattern => email.includes(pattern));
                            })
                            .filter((email, index, self) => self.indexOf(email) === index);
                        
                        info.emails = filteredEmails.slice(0, 10);
                    }

                    // Extract phone numbers from text content
                    const phonePattern = /\\+?1?[\\s\\-]?\\(?[0-9]{3}\\)?[\\s\\-]?[0-9]{3}[\\s\\-]?[0-9]{4}/g;
                    const phoneMatches = allText.match(phonePattern);
                    
                    if (phoneMatches) {
                        info.phoneNumbers = phoneMatches
                            .map(phone => phone.trim())
                            .filter((phone, index, self) => self.indexOf(phone) === index)
                            .slice(0, 5);
                    }

                    // Check for mailto links
                    const mailtoLinks = document.querySelectorAll('a[href^="mailto:"]');
                    for (const link of mailtoLinks) {
                        const href = link.getAttribute('href') || '';
                        const emailMatch = href.match(/mailto:([^?\\s]+)/);
                        if (emailMatch) {
                            const email = emailMatch[1].toLowerCase().trim();
                            if (!info.emails.includes(email)) {
                                info.emails.push(email);
                            }
                        }
                    }

                    // Check for tel: links
                    const telLinks = document.querySelectorAll('a[href^="tel:"]');
                    for (const link of telLinks) {
                        const href = link.getAttribute('href') || '';
                        const phoneMatch = href.match(/tel:([\\d\\+\\-\\(\\)\\s]+)/);
                        if (phoneMatch) {
                            const phone = phoneMatch[1].trim();
                            if (!info.phoneNumbers.includes(phone)) {
                                info.phoneNumbers.push(phone);
                            }
                        }
                    }

                    return info;
                }
                """
            )

            return content

        except Exception as e:
            logger.warning(f"Error scraping page {url}: {str(e)}")
            return {"bodyText": "", "emails": [], "phoneNumbers": []}

    async def scrape_website_info(
        self, website_url: str, timeout: int = 30000, scrape_website_info: bool = False
    ) -> Dict[str, Any]:
        """
        Scrape website information and extract email addresses using multiple methods.
        Tries methods in order: Static HTML -> Playwright -> Selenium -> WHOIS -> Email Guessing

        Args:
            website_url: Website URL to scrape
            timeout: Timeout in milliseconds
            scrape_website_info: If True, scrapes title, description, and summary. If False, only emails and phone numbers.

        Returns:
            Dictionary containing website information and email addresses
        """
        # Try methods in order with fallback
        methods = []

        # Method 1: Static HTML parsing (fastest, no JS)
        if HTTPX_AVAILABLE and BEAUTIFULSOUP_AVAILABLE:
            methods.append(("static_html", self._scrape_with_static_html))

        # Method 2: Playwright Stealth (primary browser method)
        methods.append(("playwright_stealth", self._scrape_with_playwright))

        # Method 3: Selenium (fallback browser method)
        if SELENIUM_AVAILABLE:
            methods.append(("selenium", self._scrape_with_selenium))

        # Try each method in order
        last_error = None
        for method_name, method in methods:
            try:
                logger.info(f"Attempting scrape with method: {method_name}")
                result = await method(
                    website_url, timeout, scrape_website_info=scrape_website_info
                )
                if result and (
                    result.get("emails")
                    or (scrape_website_info and result.get("title"))
                ):
                    logger.info(f"Successfully scraped with {method_name}")
                    return result
            except PlaywrightTimeoutError as e:
                # If Playwright times out, skip this URL entirely (don't try other methods)
                logger.warning(
                    f"Playwright timeout exceeded for {website_url}: {str(e)}. Skipping URL."
                )
                raise PlaywrightTimeoutSkipException(
                    f"Playwright timeout exceeded (30000ms): {str(e)}"
                )
            except Exception as e:
                logger.warning(f"Method {method_name} failed: {str(e)}")
                last_error = e
                continue

        # If all scraping methods failed, try WHOIS and email guessing
        logger.info("All scraping methods failed, trying WHOIS and email guessing")
        whois_emails = self._get_emails_from_whois(website_url)
        guessed_emails = self._guess_emails_from_domain(website_url)

        # Combine WHOIS and guessed emails (WHOIS emails are more reliable, so they come first)
        all_emails = list(dict.fromkeys(whois_emails + guessed_emails))[:10]

        if all_emails or last_error is None:
            # Return partial result with guessed emails
            result = {
                "emails": all_emails,
                "phoneNumbers": [],
                "error": (
                    f"Scraping failed, using WHOIS and guessed emails. Last error: {str(last_error)}"
                    if last_error
                    else None
                ),
            }
            if scrape_website_info:
                result["title"] = ""
                result["metaDescription"] = ""
                result["bodyText"] = ""
            return result

        # All methods failed
        if last_error:
            raise last_error
        raise AllMethodsFailedException("All scraping methods failed")

    async def _scrape_with_playwright(
        self, website_url: str, timeout: int = 30000, scrape_website_info: bool = False
    ) -> Dict[str, Any]:
        """
        Primary scraping method using Playwright with stealth configuration.
        Checks homepage, contact page (for emails), and about page (for summary).

        Args:
            website_url: Website URL to scrape
            timeout: Timeout in milliseconds

        Returns:
            Dictionary containing website information and email addresses
        """
        try:
            logger.info(f"Scraping website with Playwright: {website_url}")

            async with async_playwright() as p:
                # Get browser args with optional proxy
                browser_args = self._get_browser_args()

                browser = await p.chromium.launch(
                    headless=True,
                    args=browser_args,
                )

                try:
                    # Create stealth page
                    page = await self._create_stealth_page(
                        browser, self._current_location
                    )

                    # Step 1: Scrape homepage for basic info with human-like navigation
                    await self._human_like_navigation(page, website_url, timeout)

                    # Initialize combined info with homepage data
                    website_info = {
                        "emails": [],
                        "phoneNumbers": [],
                    }

                    # Only scrape title, description, and summary if requested
                    if scrape_website_info:
                        homepage_info = await page.evaluate(
                            """
                            () => {
                                return {
                                    title: document.title || '',
                                    metaDescription: document.querySelector('meta[name="description"]')?.content || 
                                                    document.querySelector('meta[property="og:description"]')?.content || ''
                                };
                            }
                            """
                        )
                        website_info["title"] = homepage_info.get("title", "")
                        website_info["metaDescription"] = homepage_info.get(
                            "metaDescription", ""
                        )
                        website_info["bodyText"] = ""

                    # Step 2: Find and scrape Contact page for emails
                    contact_keywords = [
                        "contact",
                        "contact us",
                        "contact-us",
                        "get in touch",
                        "reach us",
                        "email us",
                    ]
                    contact_url = await self._find_page_url(
                        page, website_url, contact_keywords
                    )

                    if contact_url:
                        logger.info(f"Found contact page: {contact_url}")
                        contact_content = await self._scrape_page_content(
                            page, contact_url
                        )
                        website_info["emails"].extend(contact_content.get("emails", []))
                        website_info["phoneNumbers"].extend(
                            contact_content.get("phoneNumbers", [])
                        )
                    else:
                        logger.info(
                            "No contact page found, checking homepage for emails"
                        )
                        # Fallback: check homepage for emails
                        homepage_content = await self._scrape_page_content(
                            page, website_url
                        )
                        website_info["emails"].extend(
                            homepage_content.get("emails", [])
                        )
                        website_info["phoneNumbers"].extend(
                            homepage_content.get("phoneNumbers", [])
                        )

                    # Step 3: Find and scrape About page for better summary (only if requested)
                    if scrape_website_info:
                        about_keywords = [
                            "about",
                            "about us",
                            "about-us",
                            "our story",
                            "who we are",
                            "company",
                        ]
                        about_url = await self._find_page_url(
                            page, website_url, about_keywords
                        )

                        if about_url:
                            logger.info(f"Found about page: {about_url}")
                            about_content = await self._scrape_page_content(
                                page, about_url
                            )
                            # Use about page content for summary (better than homepage)
                            about_text = about_content.get("bodyText", "")
                            if about_text and len(about_text) > 100:
                                website_info["bodyText"] = about_text
                            else:
                                # Fallback to homepage if about page is too short
                                homepage_content = await self._scrape_page_content(
                                    page, website_url
                                )
                                website_info["bodyText"] = homepage_content.get(
                                    "bodyText", ""
                                )
                        else:
                            logger.info(
                                "No about page found, using homepage for summary"
                            )
                            # Fallback: use homepage for summary
                            homepage_content = await self._scrape_page_content(
                                page, website_url
                            )
                            website_info["bodyText"] = homepage_content.get(
                                "bodyText", ""
                            )

                    # Remove duplicates from emails and phone numbers
                    website_info["emails"] = list(
                        dict.fromkeys(website_info["emails"])
                    )[
                        :10
                    ]  # Limit to 10 emails
                    website_info["phoneNumbers"] = list(
                        dict.fromkeys(website_info["phoneNumbers"])
                    )[
                        :5
                    ]  # Limit to 5 phone numbers

                    logger.info(
                        f"Successfully scraped website: {website_url}, found {len(website_info.get('emails', []))} emails"
                    )
                    return website_info

                finally:
                    await browser.close()

        except Exception as e:
            logger.error(
                f"Error scraping website {website_url} with Playwright: {str(e)}"
            )
            raise


# ============================================================================
# Graph Nodes
# ============================================================================

scraper = WebsiteScraper()


async def find_emails_node(state: EmailFinderState) -> EmailFinderState:
    """Find emails for all websites."""
    try:
        print("\n" + "=" * 80)
        print("🔍 NODE: find_emails_node - Finding emails from websites")
        print("=" * 80)
        logger.info(f"Finding emails for {len(state['websites'])} websites")

        websites = state.get("websites", [])
        location = state.get("location")
        scrape_website_info = state.get("scrape_website_info", False)
        enriched_results = []

        # Store location for context in the scraper instance
        scraper._current_location = location

        for i, website_data in enumerate(websites, 1):
            website_url = website_data.get("website") or website_data.get("url", "")
            if not website_url or not website_url.startswith("http"):
                logger.warning(
                    f"Skipping invalid website URL: {website_url} (item {i})"
                )
                error_result = {
                    **website_data,
                    "email": None,
                    "emails": [],
                    "phoneNumber": None,
                    "phoneNumbers": [],
                    "error": "Invalid URL",
                }
                if scrape_website_info:
                    error_result["website_title"] = ""
                    error_result["website_description"] = ""
                    error_result["website_summary"] = ""
                # Don't include these keys when scrape_website_info is False
                enriched_results.append(error_result)
                continue

            logger.info(f"Processing {i}/{len(websites)}: {website_url}")

            try:
                # Scrape website information
                website_info = await scraper.scrape_website_info(
                    website_url, scrape_website_info=scrape_website_info
                )

                # Create enriched result
                enriched_result = {**website_data}
                emails_list = website_info.get("emails", [])
                phone_numbers_list = website_info.get("phoneNumbers", [])
                enriched_result["emails"] = emails_list
                enriched_result["email"] = (
                    emails_list[0] if emails_list else None
                )  # First email as primary
                enriched_result["phoneNumbers"] = phone_numbers_list
                enriched_result["phoneNumber"] = (
                    phone_numbers_list[0] if phone_numbers_list else None
                )  # First phone number as primary

                # Only include website info fields if scraping was requested
                if scrape_website_info:
                    enriched_result["website_title"] = website_info.get("title", "")
                    enriched_result["website_description"] = website_info.get(
                        "metaDescription", ""
                    )
                    enriched_result["website_summary"] = website_info.get(
                        "bodyText", ""
                    )[
                        :500
                    ]  # First 500 chars
                # Don't include these keys when scrape_website_info is False

                if website_info.get("error"):
                    enriched_result["error"] = website_info["error"]

                enriched_results.append(enriched_result)

                logger.info(
                    f"Found {len(enriched_result.get('emails', []))} emails for {website_url}"
                )

                # Small delay between website scrapes to avoid rate limiting
                await asyncio.sleep(1)

            except PlaywrightTimeoutSkipException as e:
                # Playwright timeout - skip this URL and move to next website
                logger.warning(
                    f"Playwright timeout for {website_url}. Skipping and moving to next website: {str(e)}"
                )
                timeout_result = {
                    **website_data,
                    "email": None,
                    "emails": [],
                    "phoneNumber": None,
                    "phoneNumbers": [],
                    "error": f"Playwright timeout exceeded (30000ms) - skipped",
                }
                if scrape_website_info:
                    timeout_result["website_title"] = ""
                    timeout_result["website_description"] = ""
                    timeout_result["website_summary"] = ""
                # Don't include these keys when scrape_website_info is False
                enriched_results.append(timeout_result)
                # Continue to next website without trying other methods
                continue

            except Exception as e:
                logger.error(f"Error finding emails for {website_url}: {str(e)}")
                # Add result with error
                error_result = {
                    **website_data,
                    "email": None,
                    "emails": [],
                    "phoneNumber": None,
                    "phoneNumbers": [],
                    "error": str(e),
                }
                if scrape_website_info:
                    error_result["website_title"] = ""
                    error_result["website_description"] = ""
                    error_result["website_summary"] = ""
                # Don't include these keys when scrape_website_info is False
                enriched_results.append(error_result)

        print(f"✅ Successfully processed {len(enriched_results)} websites")
        return {
            **state,
            "enriched_results": enriched_results,
            "status": "completed",
        }
    except Exception as e:
        print(f"❌ Error in find_emails_node: {str(e)}")
        logger.error(f"Error in find_emails_node: {str(e)}")
        return {**state, "status": "error", "error": str(e)}


async def agent_node(state: EmailFinderState) -> EmailFinderState:
    """Main agent node that orchestrates the workflow."""
    try:
        current_status = state.get("status", "initialized")

        if current_status == "initialized":
            return await find_emails_node(state)

        elif current_status == "completed":
            return {**state, "status": "completed"}

        return state

    except Exception as e:
        logger.error(f"Error in agent_node: {str(e)}")
        return {**state, "status": "error", "error": str(e)}


def should_continue(state: EmailFinderState) -> Literal["continue", "end"]:
    """Determine if the workflow should continue or end."""
    status = state.get("status", "")

    if status == "completed":
        return "end"
    elif status == "error":
        return "end"
    else:
        return "continue"


# ============================================================================
# Graph Construction
# ============================================================================


def create_email_finder_agent():
    """Create and compile the email finder LangGraph agent."""

    workflow = StateGraph(EmailFinderState)

    workflow.add_node("agent", agent_node)
    workflow.set_entry_point("agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "continue": "agent",
            "end": END,
        },
    )

    memory = MemorySaver()
    graph = workflow.compile(checkpointer=memory)

    return graph


# ============================================================================
# Agent Interface
# ============================================================================


class EmailFinderAgent:
    """Standalone LangGraph agent for finding emails from websites."""

    def __init__(self):
        self.graph = create_email_finder_agent()
        logger.info("Email Finder Agent initialized")

    async def process(
        self,
        websites: List[Dict[str, Any]],
        location: Optional[str] = None,
        scrape_website_info: bool = False,
        thread_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Process a list of websites to find emails.

        Args:
            websites: List of website dictionaries (must have 'website' field,
                     may include 'companyName', 'address', 'phone', and other optional fields)
            location: Optional location for context (used for timezone/geolocation)
            scrape_website_info: If True, scrapes website_title, website_description, and website_summary
            thread_id: Thread ID for conversation tracking

        Returns:
            Dictionary containing enriched results with emails and all original fields preserved
        """
        try:
            if not websites:
                raise ValueError("Websites list must be provided")

            initial_state = {
                "messages": [],
                "websites": websites,
                "location": location,
                "scrape_website_info": scrape_website_info,
                "enriched_results": None,
                "status": "initialized",
                "error": None,
            }

            print("\n" + "=" * 80)
            print("🚀 Starting Email Finder Agent Workflow")
            print("=" * 80)
            config = {"configurable": {"thread_id": thread_id}}
            result = None

            async for event in self.graph.astream(initial_state, config):
                result = event
                if "agent" in event:
                    status = event["agent"].get("status", "processing")
                    logger.info(f"Agent status: {status}")

            print("\n" + "=" * 80)
            print("✅ Workflow completed successfully!")
            print("=" * 80)

            final_state = (
                result.get("agent", initial_state) if result else initial_state
            )

            if final_state.get("status") == "error":
                error_msg = final_state.get("error", "Unknown error occurred")
                raise ValueError(f"Agent processing failed: {error_msg}")

            return {
                "status": "success",
                "total_websites": len(websites),
                "results": final_state.get("enriched_results", []),
                "processing_status": final_state.get("status", "unknown"),
            }

        except Exception as e:
            logger.error(f"Error processing email finder request: {str(e)}")
            raise


# ============================================================================
# Factory Function
# ============================================================================


def create_agent() -> EmailFinderAgent:
    """Factory function to create a new email finder agent instance."""
    return EmailFinderAgent()


# ============================================================================
# Note: This module is designed to be used with the FastAPI application (main.py)
# For standalone usage, use the FastAPI API endpoints instead.
# ============================================================================
