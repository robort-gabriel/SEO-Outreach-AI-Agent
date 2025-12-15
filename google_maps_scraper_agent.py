"""
Google Maps Scraper Agent for FastAPI

This is a production-ready backend agent that uses LangGraph
to orchestrate Google Maps search result scraping using Playwright
with advanced anti-detection features.

This module is designed to be used with the FastAPI application (app.py).
Use the FastAPI endpoints to interact with the scraper.

FEATURES:
    - Stealth browser configuration to avoid bot detection
    - Proxy rotation support
    - Human-like behavior simulation
    - CAPTCHA detection and handling
    - Multiple fallback methods (Playwright -> Browserless -> Selenium)

REQUIRED ENVIRONMENT VARIABLES:
    - OPENAI_API_KEY: Your OpenAI API key (optional, for LLM analysis)

OPTIONAL ENVIRONMENT VARIABLES:
    - STEALTH_ENABLED: Enable stealth mode (default: true)
    - HUMAN_SIMULATION_ENABLED: Enable human behavior simulation (default: true)
    - PROXY_URL: Proxy server URL
    - PROXY_USERNAME: Proxy authentication username
    - PROXY_PASSWORD: Proxy authentication password
    - PROXY_ROTATION_ENABLED: Enable proxy rotation (default: false)
    - BROWSERLESS_TOKEN: Browserless.io API token (for fallback)
    - BROWSERLESS_BASE_URL: Browserless base URL (default: https://chrome.browserless.io)
    - CAPTCHA_SERVICE: CAPTCHA solving service (2captcha or anticaptcha)
    - CAPTCHA_API_KEY: API key for CAPTCHA solving service

USAGE:
    This module is imported and used by app.py. To use the scraper:
    1. Start the FastAPI server: python app.py
    2. Make API requests to /api/v1/scrape endpoint
"""

import logging
import os
import random
import time
from pathlib import Path
from typing import TypedDict, Annotated, List, Optional, Dict, Any, Literal
from urllib.parse import quote_plus, urlparse, urljoin
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

# Try to import aiohttp for browserless fallback
try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logger.warning("aiohttp not installed. Browserless fallback will not be available.")


# ============================================================================
# State Definition
# ============================================================================


class GoogleMapsScraperState(TypedDict):
    """State for the Google Maps scraper agent."""

    messages: Annotated[List, lambda x, y: x + y]
    query: str
    max_results: int
    location: Optional[str]
    enrich_with_website: bool  # Enable website scraping and email extraction
    raw_results: Optional[List[Dict[str, Any]]]
    processed_results: Optional[List[Dict[str, Any]]]
    total_found: int
    status: str
    error: Optional[str]


# ============================================================================
# Google Maps Scraper
# ============================================================================


class GoogleMapsScraper:
    """
    Advanced scraper for extracting business information from Google Maps.

    Features:
    - Stealth browser configuration
    - Proxy rotation support
    - Human-like behavior simulation
    - CAPTCHA detection and handling
    - Multiple fallback methods
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
        self._retry_count: int = 0
        self._max_retries: int = 3

        logger.info(
            f"GoogleMapsScraper initialized (stealth={self.stealth_enabled}, human_sim={self.human_simulation_enabled})"
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
                captcha_type, "CAPTCHA detected and could not be solved"
            )

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
        self, page: Page, url: str, timeout: int = 90000
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
            # Use 'load' wait for more stable navigation
            await page.goto(url, wait_until="load", timeout=timeout)
            # Extra wait for dynamic content
            await asyncio.sleep(2)
        except PlaywrightTimeoutError:
            # Timeout is OK for Google Maps, page might still be usable
            logger.warning(
                f"Navigation timeout, but continuing (page might still be usable)"
            )
        except Exception as nav_error:
            # Check if page was closed during navigation
            if page.is_closed() or "closed" in str(nav_error).lower():
                error_msg = str(nav_error)
                # Provide more context about the error
                if "timeout" in error_msg.lower():
                    raise Exception(
                        f"Navigation timeout after {timeout}ms. Google Maps may be slow or blocking the request. Error: {error_msg}"
                    )
                elif "net::" in error_msg or "ERR_" in error_msg:
                    raise Exception(
                        f"Network error during navigation. This could be due to proxy issues, Google blocking, or network problems. Error: {error_msg}"
                    )
                else:
                    raise Exception(
                        f"Page/browser closed during navigation: {error_msg}"
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

    async def _human_like_scroll(self, page: Page, scroll_amount: int = 300) -> None:
        """Scroll with human-like behavior."""
        if self.human_simulation_enabled:
            await HumanBehavior.human_scroll(page, "down", scroll_amount)
            await asyncio.sleep(HumanBehavior.scroll_delay())
        else:
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(0.5)

    async def _human_like_click(self, element) -> None:
        """Click element with human-like behavior."""
        if self.human_simulation_enabled:
            # Get element bounding box
            box = await element.bounding_box()
            if box:
                # Move mouse to element with slight offset
                target_x = box["x"] + box["width"] / 2 + random.randint(-5, 5)
                target_y = box["y"] + box["height"] / 2 + random.randint(-5, 5)

                # Simulate mouse movement (simplified)
                await asyncio.sleep(HumanBehavior.click_delay())

            await element.click()
            await asyncio.sleep(HumanBehavior.between_actions_delay())
        else:
            await element.click()
            await asyncio.sleep(0.5)

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
        self, website_url: str, timeout: int = 30000
    ) -> Dict[str, Any]:
        """
        Scrape website information and extract email addresses.
        Checks homepage, contact page (for emails), and about page (for summary).
        Uses stealth browser configuration to avoid detection.

        Args:
            website_url: Website URL to scrape
            timeout: Timeout in milliseconds

        Returns:
            Dictionary containing website information and email addresses
        """
        try:
            logger.info(f"Scraping website: {website_url}")

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

                    # Initialize combined info with homepage data
                    website_info = {
                        "title": homepage_info.get("title", ""),
                        "metaDescription": homepage_info.get("metaDescription", ""),
                        "bodyText": "",
                        "emails": [],
                        "phoneNumbers": [],
                    }

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

                    # Step 3: Find and scrape About page for better summary
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
                        about_content = await self._scrape_page_content(page, about_url)
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
                        logger.info("No about page found, using homepage for summary")
                        # Fallback: use homepage for summary
                        homepage_content = await self._scrape_page_content(
                            page, website_url
                        )
                        website_info["bodyText"] = homepage_content.get("bodyText", "")

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
            logger.error(f"Error scraping website {website_url}: {str(e)}")
            return {
                "title": "",
                "metaDescription": "",
                "bodyText": "",
                "emails": [],
                "phoneNumbers": [],
                "error": str(e),
            }

    async def scrape_search_results(
        self,
        query: str,
        max_results: Optional[int] = None,
        location: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Scrape Google Maps search results for a given query.
        Uses stealth browser configuration and fallback methods.

        Args:
            query: Search query (e.g., "restaurants in New York")
            max_results: Maximum number of results to extract
            location: Optional location to append to query

        Returns:
            List of business information dictionaries
        """
        # Store location for context
        self._current_location = location

        # Try primary method first, then fallbacks
        methods = [
            ("stealth_playwright", self._scrape_with_stealth_playwright),
        ]

        # Add browserless fallback if configured
        if StealthConfig.has_browserless() and AIOHTTP_AVAILABLE:
            methods.append(("browserless", self._scrape_with_browserless))

        last_error = None
        for method_name, method in methods:
            try:
                logger.info(f"Attempting scrape with method: {method_name}")
                results = await method(query, max_results, location)
                if results:
                    logger.info(f"Successfully scraped with {method_name}")
                    return results
            except (DetectionException, CaptchaException) as e:
                logger.warning(f"Detection error with {method_name}: {e}")
                last_error = e
                # Rotate proxy on detection
                proxy = self.proxy_manager.get_proxy()
                if proxy:
                    self.proxy_manager.mark_proxy_failed(proxy)
                continue
            except Exception as e:
                logger.error(f"Error with {method_name}: {e}")
                last_error = e
                continue

        # All methods failed
        if last_error:
            raise last_error
        raise AllMethodsFailedException("All scraping methods failed")

    async def _scrape_with_stealth_playwright(
        self,
        query: str,
        max_results: Optional[int] = None,
        location: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Primary scraping method using stealth Playwright.

        Args:
            query: Search query
            max_results: Maximum results to extract
            location: Optional location

        Returns:
            List of business information dictionaries
        """
        try:
            # Build search query
            if location:
                search_query = f"{query} in {location}"
            else:
                search_query = query

            logger.info(f"Starting Google Maps scrape for: {search_query}")

            # Try without proxy first, then with proxy if needed
            use_proxy_attempts = (
                [False, True] if self.proxy_manager.get_proxy() else [False]
            )

            for attempt_idx, use_proxy in enumerate(use_proxy_attempts):
                try:
                    logger.info(
                        f"Scrape attempt {attempt_idx + 1}: proxy={'enabled' if use_proxy else 'disabled'}"
                    )
                    result = await self._scrape_with_browser(
                        search_query, max_results, location, use_proxy
                    )
                    if result:
                        return result
                except Exception as attempt_error:
                    logger.warning(
                        f"Attempt {attempt_idx + 1} failed: {str(attempt_error)}"
                    )
                    if attempt_idx == len(use_proxy_attempts) - 1:
                        raise  # Re-raise on last attempt
                    continue

            return []

        except Exception as e:
            logger.error(f"Error scraping Google Maps: {str(e)}")
            raise

    async def _scrape_with_browser(
        self,
        search_query: str,
        max_results: Optional[int],
        location: Optional[str],
        use_proxy: bool = False,
    ) -> List[Dict[str, Any]]:
        """Execute the actual browser scraping."""
        try:
            async with async_playwright() as p:
                # Get browser args with optional proxy
                proxy = self.proxy_manager.get_proxy() if use_proxy else None
                proxy_url = proxy.url if proxy else None
                browser_args = self._get_browser_args(proxy_url)

                # Add stability arguments to prevent crashes
                browser_args.extend(
                    [
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",  # Overcome limited resource problems
                        "--no-sandbox",  # Required for some environments
                        "--disable-setuid-sandbox",
                        "--disable-gpu",  # Disable GPU to prevent crashes
                        "--disable-software-rasterizer",
                        "--disable-accelerated-2d-canvas",
                        "--disable-background-networking",
                        "--disable-default-apps",
                        "--disable-extensions",
                        "--disable-sync",
                        "--disable-translate",
                        "--mute-audio",
                        "--no-first-run",
                        "--ignore-certificate-errors",
                    ]
                )

                browser = await p.chromium.launch(
                    headless=True,
                    args=browser_args,
                    timeout=120000,  # 2 minute timeout for browser launch
                    slow_mo=100,  # Slow down operations for stability
                )

                try:
                    # Create stealth page with location context
                    page = await self._create_stealth_page(browser, location)

                    # Build Google Maps search URL
                    encoded_query = quote_plus(search_query)
                    maps_url = f"https://www.google.com/maps/search/{encoded_query}"
                    logger.info(f"Navigating to: {maps_url}")

                    # Navigate with human-like behavior
                    try:
                        await self._human_like_navigation(page, maps_url, timeout=90000)
                    except Exception as nav_error:
                        # Check if page/browser was closed
                        if page.is_closed() or "closed" in str(nav_error).lower():
                            logger.error(
                                f"Page/browser closed during navigation: {str(nav_error)}"
                            )
                            raise Exception(
                                f"Browser closed during navigation: {str(nav_error)}"
                            )
                        raise

                    # Check if page is still valid
                    if page.is_closed():
                        raise Exception("Page was closed after navigation")

                    # Wait for results container - try multiple selectors
                    results_found = False
                    selectors_to_try = [
                        'div[role="feed"]',
                        "div.Nv2PK",  # Business card container (2024)
                        'a[href*="/maps/place/"]',  # Place links
                        "div.m6QErb",  # Results container
                        'div[aria-label*="Results"]',  # Results panel
                    ]

                    for selector in selectors_to_try:
                        try:
                            await page.wait_for_selector(selector, timeout=5000)
                            logger.info(f"Found results using selector: {selector}")
                            results_found = True
                            break
                        except PlaywrightTimeoutError:
                            continue

                    if not results_found:
                        logger.warning("No results container found with any selector")

                        # Save debug screenshot
                        try:
                            debug_path = (
                                Path("output")
                                / f"debug_screenshot_{int(time.time())}.png"
                            )
                            debug_path.parent.mkdir(exist_ok=True)
                            await page.screenshot(path=str(debug_path), full_page=True)
                            logger.info(f"Debug screenshot saved to: {debug_path}")
                        except Exception as ss_error:
                            logger.warning(
                                f"Could not save debug screenshot: {ss_error}"
                            )

                        # Log page content for debugging
                        try:
                            page_title = await page.title()
                            page_url = page.url
                            logger.info(f"Current page: {page_title} - {page_url}")

                            # Check what elements exist on the page
                            elements_info = await page.evaluate(
                                """
                                () => {
                                    return {
                                        hasConsentDialog: !!document.querySelector('[aria-label*="consent"], form[action*="consent"], #yDmH0d'),
                                        hasCaptcha: !!document.querySelector('[class*="captcha"], iframe[src*="recaptcha"]'),
                                        hasResults: !!document.querySelector('[role="feed"], div.Nv2PK, a[href*="/maps/place/"]'),
                                        bodyText: document.body?.innerText?.substring(0, 500) || 'No body text'
                                    };
                                }
                            """
                            )
                            logger.info(f"Page state: {elements_info}")

                            # Handle consent dialog if present
                            if elements_info.get("hasConsentDialog"):
                                logger.info(
                                    "Consent dialog detected, attempting to accept..."
                                )
                                try:
                                    # Try clicking accept/agree buttons
                                    accept_buttons = await page.query_selector_all(
                                        "button"
                                    )
                                    for btn in accept_buttons:
                                        btn_text = await btn.text_content()
                                        if btn_text and any(
                                            word in btn_text.lower()
                                            for word in [
                                                "accept",
                                                "agree",
                                                "allow",
                                                "ok",
                                            ]
                                        ):
                                            await btn.click()
                                            logger.info(
                                                f"Clicked consent button: {btn_text}"
                                            )
                                            await asyncio.sleep(2)
                                            break
                                except Exception as consent_err:
                                    logger.warning(
                                        f"Error handling consent: {consent_err}"
                                    )

                        except Exception as debug_err:
                            logger.warning(f"Error getting debug info: {debug_err}")

                        # Check if page is still valid
                        if page.is_closed():
                            raise Exception("Page was closed while waiting for results")
                        # Check for detection
                        await self._handle_detection(page)

                    # Extra wait for results to fully load
                    await asyncio.sleep(3)

                    results = []
                    previous_count = 0
                    scroll_attempts = 0
                    no_new_results_count = 0
                    max_no_new_results = (
                        5  # Stop if no new results after 5 scrolls (increased from 3)
                    )

                    # Calculate max scroll attempts based on desired results
                    # If max_results is None (unlimited), use a very high number
                    if max_results is None:
                        max_scroll_attempts = (
                            1000  # Very high limit for unlimited scraping
                        )
                        target_info = "all available results"
                    else:
                        max_scroll_attempts = max(
                            50, max_results // 2
                        )  # At least 50 attempts, or half of max_results
                        target_info = f"{max_results} results"

                    logger.info(
                        f"Starting to scroll and extract results (target: {target_info}, max scroll attempts: {max_scroll_attempts})"
                    )

                    # Scroll to load more results with human-like behavior
                    while (
                        (max_results is None or len(results) < max_results)
                        and scroll_attempts < max_scroll_attempts
                        and no_new_results_count < max_no_new_results
                    ):
                        # Check if page is still valid
                        if page.is_closed():
                            logger.warning(
                                "Page closed during scrolling, returning current results"
                            )
                            break

                        try:
                            # Extract current results
                            current_results = await self._extract_results_from_page(
                                page
                            )

                            # Check if we got new results (compare unique names to avoid duplicates)
                            current_unique = len(
                                set(
                                    r.get("name", "")
                                    for r in current_results
                                    if r.get("name")
                                )
                            )
                            previous_unique = len(
                                set(r.get("name", "") for r in results if r.get("name"))
                            )

                            if current_unique > previous_unique:
                                results = current_results
                                previous_count = current_unique
                                no_new_results_count = (
                                    0  # Reset counter when we get new results
                                )
                                target_display = max_results if max_results else "all"
                                logger.info(
                                    f"Extracted {current_unique} unique results so far... (target: {target_display})"
                                )
                            else:
                                # No new results this iteration - but continue scrolling
                                # Google Maps sometimes loads results in batches
                                no_new_results_count += 1
                                if no_new_results_count >= max_no_new_results:
                                    logger.info(
                                        f"⚠️  No new results after {max_no_new_results} scrolls. "
                                        f"Reached end of available results: {len(set(r.get('name', '') for r in results if r.get('name')))} unique results found."
                                    )
                                    break
                                else:
                                    # Continue scrolling even if no new results yet
                                    logger.debug(
                                        f"No new results yet (attempt {no_new_results_count}/{max_no_new_results}), continuing to scroll..."
                                    )

                            if max_results is not None and len(results) >= max_results:
                                logger.info(
                                    f"✅ Reached target of {max_results} results"
                                )
                                break

                            # Scroll the results panel with human-like behavior
                            can_scroll_more = await self._scroll_results_panel(page)
                            if not can_scroll_more:
                                logger.info(
                                    f"⚠️  Reached end of scrollable content. Found {len(results)} results (target: {max_results})"
                                )
                                no_new_results_count = (
                                    max_no_new_results  # Trigger exit
                                )
                                break

                            # Wait longer for Google Maps to load new results after scrolling
                            # Google Maps loads results dynamically, so we need to wait
                            # Increase wait time to ensure results are loaded
                            if self.human_simulation_enabled:
                                await asyncio.sleep(
                                    HumanBehavior.scroll_delay() + 2.0
                                )  # Extra wait for loading (increased from 1.0)
                            else:
                                await asyncio.sleep(
                                    4
                                )  # Longer wait for results to load (increased from 3)

                            # Sometimes Google Maps needs an extra moment to render
                            await asyncio.sleep(0.5)

                            scroll_attempts += 1

                            # Periodically check for detection
                            if scroll_attempts % 5 == 0:
                                if page.is_closed():
                                    logger.warning("Page closed during detection check")
                                    break
                                try:
                                    await self._handle_detection(page)
                                except (DetectionException, CaptchaException):
                                    raise
                        except Exception as scroll_error:
                            # Check if page was closed
                            if (
                                page.is_closed()
                                or "closed" in str(scroll_error).lower()
                            ):
                                logger.warning(
                                    f"Page closed during scrolling: {str(scroll_error)}"
                                )
                                break
                            # For other errors, log and continue
                            logger.warning(
                                f"Error during scrolling: {str(scroll_error)}"
                            )
                            scroll_attempts += 1
                            if scroll_attempts >= max_scroll_attempts:
                                break

                    # Limit to max_results if specified
                    if max_results is not None:
                        final_results = results[:max_results]
                    else:
                        final_results = results
                    total_available = len(results)

                    # Mark proxy as successful
                    if proxy:
                        self.proxy_manager.mark_proxy_success(proxy)

                    # Log final status
                    if max_results is None:
                        logger.info(
                            f"✅ Successfully extracted all available results: {len(final_results)} total"
                        )
                    elif total_available >= max_results:
                        logger.info(
                            f"✅ Successfully extracted {len(final_results)} results (requested: {max_results})"
                        )
                    else:
                        logger.info(
                            f"⚠️  Extracted {len(final_results)} results (requested: {max_results}). "
                            f"All available results in search have been retrieved."
                        )

                    # Return results without enrichment (enrichment is now a separate endpoint)
                    # The scraping endpoint should only return basic results
                    return final_results

                finally:
                    await browser.close()

        except (DetectionException, CaptchaException):
            raise
        except Exception as e:
            logger.error(f"Error in _scrape_with_browser: {str(e)}")
            raise

    async def _scrape_with_browserless(
        self,
        query: str,
        max_results: Optional[int] = None,
        location: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fallback scraping method using Browserless service.

        Args:
            query: Search query
            max_results: Maximum results to extract
            location: Optional location

        Returns:
            List of business information dictionaries
        """
        if not AIOHTTP_AVAILABLE:
            raise Exception("aiohttp not available for Browserless fallback")

        try:
            # Build search query
            if location:
                search_query = f"{query} in {location}"
            else:
                search_query = query

            encoded_query = quote_plus(search_query)
            maps_url = f"https://www.google.com/maps/search/{encoded_query}"

            logger.info(f"Attempting Browserless scrape for: {search_query}")

            # Browserless /content endpoint
            browserless_url = f"{StealthConfig.BROWSERLESS_BASE_URL}/content?token={StealthConfig.BROWSERLESS_TOKEN}"

            payload = {
                "url": maps_url,
                "gotoOptions": {"waitUntil": "networkidle0", "timeout": 60000},
                "waitForSelector": {"selector": 'div[role="feed"]', "timeout": 10000},
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    browserless_url, json=payload, timeout=70
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Browserless error: {error_text}")
                        return []

                    html_content = await response.text()

            # Parse HTML to extract results (simplified - Browserless returns raw HTML)
            # This is a basic extraction; full functionality requires browser interaction
            logger.warning(
                "Browserless fallback has limited functionality - consider using primary method"
            )

            # Return empty for now - browserless would need more complex implementation
            # to handle scrolling and clicking on Google Maps
            return []

        except Exception as e:
            logger.error(f"Browserless scraping failed: {e}")
            raise

    async def _extract_results_from_page(self, page: Page) -> List[Dict[str, Any]]:
        """Extract business information from the current page state."""
        try:
            # Extract data using JavaScript with multiple selector strategies
            results = await page.evaluate(
                """
                () => {
                    const results = [];
                    const seenNames = new Set();
                    
                    // Primary strategy: Find all Google Maps place links
                    const placeLinks = document.querySelectorAll('a[href*="/maps/place/"]');
                    console.log('Found place links:', placeLinks.length);
                    
                    placeLinks.forEach((linkEl) => {
                        try {
                            const result = {};
                            
                            // Get the Google Maps URL
                            result.url = linkEl.href || '';
                            
                            // Get the parent container for more info
                            const container = linkEl.closest('[role="article"]') || 
                                            linkEl.closest('div.Nv2PK') || 
                                            linkEl.closest('div[jsaction]') ||
                                            linkEl.parentElement?.parentElement;
                            
                            // Get name from aria-label (most reliable)
                            result.name = linkEl.getAttribute('aria-label') || '';
                            
                            // Try container aria-label
                            if (!result.name && container) {
                                result.name = container.getAttribute('aria-label') || '';
                            }
                            
                            // Try heading element
                            if (!result.name && container) {
                                const headingEl = container.querySelector('div.fontHeadlineSmall, .qBF1Pd, div.NrDZNb, h3');
                                if (headingEl) {
                                    result.name = headingEl.textContent?.trim() || '';
                                }
                            }
                            
                            // Extract name from URL as fallback
                            if (!result.name && result.url) {
                                const urlMatch = result.url.match(/place\\/([^/]+)/);
                                if (urlMatch) {
                                    result.name = decodeURIComponent(urlMatch[1].replace(/\\+/g, ' '));
                                }
                            }
                            
                            // Skip if no name or duplicate
                            if (!result.name || seenNames.has(result.name)) {
                                return;
                            }
                            seenNames.add(result.name);
                            
                            // Get text content from container
                            const allText = container ? (container.innerText || '') : '';
                            const lines = allText.split('\\n').map(l => l.trim()).filter(l => l && l !== '·');
                            
                            // Extract rating from text
                            const ratingPattern = /(\\d+[.,]\\d+)\\s*\\(([0-9,]+)\\)/;
                            const ratingMatch = allText.match(ratingPattern);
                            if (ratingMatch) {
                                result.rating = ratingMatch[1].replace(',', '.');
                                result.reviews = ratingMatch[2].replace(/,/g, '');
                            }
                            
                            // Try rating from container element
                            if (!result.rating && container) {
                                const ratingEl = container.querySelector('span.MW4etd, span.ZkP5Je');
                                if (ratingEl) {
                                    const ratingText = ratingEl.textContent || '';
                                    const match = ratingText.match(/(\\d+[.,]?\\d*)/);
                                    if (match) result.rating = match[1].replace(',', '.');
                                }
                            }
                            
                            // Extract category from text
                            if (lines.length > 1) {
                                // Category is usually after the rating line
                                for (const line of lines.slice(1)) {
                                    if (!line.match(/^\\d/) && !line.match(/\\(\\d/) && line.length > 2) {
                                        const parts = line.split('·').map(p => p.trim()).filter(p => p);
                                        if (parts[0] && !parts[0].match(/^\\d/)) {
                                            result.category = parts[0];
                                            break;
                                        }
                                    }
                                }
                            }
                            
                            // Extract address from text
                            for (const line of lines) {
                                if (line.match(/\\d+\\s+[\\w\\s]+(St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Ln|Lane|Way|Pkwy|Hwy|Place|Pl|Court|Ct)/i)) {
                                    result.address = line;
                                    break;
                                }
                            }
                            
                            // Extract phone number
                            const phonePattern = /\\+?1?[\\s\\-]?\\(?[0-9]{3}\\)?[\\s\\-]?[0-9]{3}[\\s\\-]?[0-9]{4}/;
                            const phoneMatch = allText.match(phonePattern);
                            if (phoneMatch) {
                                result.phone = phoneMatch[0].trim();
                            }
                            
                            // Extract website from container
                            if (container) {
                                const websiteLinks = container.querySelectorAll('a[href^="http"]');
                                for (const link of websiteLinks) {
                                    const href = link.getAttribute('href') || '';
                                    if (!href.includes('google.com') && !href.includes('maps')) {
                                        result.website = href;
                                        break;
                                    }
                                }
                            }
                            
                            results.push(result);
                        } catch (err) {
                            console.error('Error extracting item:', err);
                        }
                    });
                    
                    return results;
                }
             """
            )

            # Deduplicate results by name
            unique_results = []
            seen_names = set()

            for result in results:
                name = result.get("name", "").strip()
                if name and name not in seen_names:
                    seen_names.add(name)
                    unique_results.append(result)

            return unique_results

        except Exception as e:
            logger.error(f"Error extracting results from page: {str(e)}")
            return []

    async def _scroll_results_panel(self, page: Page) -> bool:
        """
        Scroll the Google Maps results panel to load more results with human-like behavior.

        Returns:
            True if scrolling was successful and more content is available, False if at the end
        """
        try:
            if self.human_simulation_enabled:
                # Get current scroll position and scroll incrementally
                # Try multiple container selectors
                scroll_info = await page.evaluate(
                    """
                    () => {
                        // Try multiple selectors for the scrollable container
                        const selectors = [
                            'div[role="feed"]',
                            'div.m6QErb.DxyBCb.kA9KIf.dS8AEf',  // Main results container
                            'div.m6QErb',  // Simplified results container
                            'div[aria-label*="Results"]',
                            'div.DxyBCb'
                        ];
                        
                        let container = null;
                        for (const selector of selectors) {
                            container = document.querySelector(selector);
                            if (container && container.scrollHeight > container.clientHeight) {
                                break;
                            }
                        }
                        
                        if (container) {
                            return {
                                scrollTop: container.scrollTop,
                                scrollHeight: container.scrollHeight,
                                clientHeight: container.clientHeight,
                                canScrollMore: container.scrollTop < (container.scrollHeight - container.clientHeight - 10)
                            };
                        }
                        return null;
                    }
                    """
                )

                if scroll_info:
                    # Check if we can scroll more
                    if not scroll_info.get("canScrollMore", True):
                        return False  # Reached the end

                    # Calculate scroll amount (simulate human scrolling)
                    max_scroll = (
                        scroll_info["scrollHeight"] - scroll_info["clientHeight"]
                    )
                    current_scroll = scroll_info["scrollTop"]

                    # Scroll in smaller increments with randomness
                    scroll_amount = random.randint(300, 500)  # Increased scroll amount
                    target_scroll = min(current_scroll + scroll_amount, max_scroll)

                    # Scroll with slight variations
                    steps = random.randint(3, 6)
                    for i in range(steps):
                        intermediate_scroll = current_scroll + (
                            target_scroll - current_scroll
                        ) * ((i + 1) / steps)
                        await page.evaluate(
                            f"""
                            () => {{
                                const selectors = ['div[role="feed"]', 'div.m6QErb.DxyBCb', 'div.m6QErb', 'div.DxyBCb'];
                                for (const selector of selectors) {{
                                    const container = document.querySelector(selector);
                                    if (container && container.scrollHeight > container.clientHeight) {{
                                        container.scrollTop = {intermediate_scroll};
                                        break;
                                    }}
                                }}
                            }}
                            """
                        )
                        await asyncio.sleep(random.uniform(0.05, 0.15))

                    # Wait a bit for new content to load
                    await asyncio.sleep(0.5)
                    return True
            else:
                # Simple scroll - check if we can scroll more first
                scroll_info = await page.evaluate(
                    """
                    () => {
                        const selectors = ['div[role="feed"]', 'div.m6QErb.DxyBCb', 'div.m6QErb', 'div.DxyBCb'];
                        for (const selector of selectors) {
                            const container = document.querySelector(selector);
                            if (container && container.scrollHeight > container.clientHeight) {
                                return {
                                    scrollTop: container.scrollTop,
                                    scrollHeight: container.scrollHeight,
                                    clientHeight: container.clientHeight,
                                    canScrollMore: container.scrollTop < (container.scrollHeight - container.clientHeight - 10)
                                };
                            }
                        }
                        return null;
                    }
                    """
                )

                if scroll_info and not scroll_info.get("canScrollMore", True):
                    return False  # Reached the end

                await page.evaluate(
                    """
                    () => {
                        const feed = document.querySelector('div[role="feed"]');
                        if (feed) {
                            feed.scrollTop = feed.scrollHeight;
                        }
                    }
                    """
                )
                # Wait for new content to load
                await asyncio.sleep(0.5)
                return True
        except Exception as e:
            logger.warning(f"Error scrolling results panel: {str(e)}")
            return False

    async def _enrich_business_details(
        self, page: Page, business: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enrich business data by clicking on the result and extracting phone and website.
        """
        try:
            business_name = business.get("name", "")
            if not business_name:
                return business

            # Check if page is still valid
            if page.is_closed():
                logger.warning(f"Page is closed, cannot enrich {business_name}")
                return business

            # Find and click on the business link
            try:
                # Wait for the results feed to be visible
                try:
                    await page.wait_for_selector('div[role="feed"]', timeout=5000)
                except:
                    logger.warning(
                        f"Results feed not found, skipping enrichment for {business_name}"
                    )
                    return business

                # Try to find the business by its name in the aria-label
                # Escape special characters in the name for the selector
                escaped_name = business_name.replace('"', '\\"').replace("'", "\\'")
                business_selector = f'[role="article"][aria-label*="{escaped_name}"] a'
                business_link = await page.query_selector(business_selector)

                if not business_link:
                    # Fallback: try to find by URL
                    business_url = business.get("url", "")
                    if business_url and "/place/" in business_url:
                        place_id = business_url.split("/place/")[1].split("/")[0]
                        business_link = await page.query_selector(
                            f'a[href*="{place_id}"]'
                        )

                if not business_link:
                    logger.warning(f"Could not find business link for {business_name}")
                    return business

                # Click on the business to open detail panel
                # Google Maps should open a side panel, but handle navigation if it occurs
                try:
                    # Try clicking without expecting navigation (side panel)
                    await business_link.click(timeout=5000)
                except Exception as click_error:
                    # If click fails, the link might not be clickable or page might be closing
                    logger.warning(
                        f"Error clicking business link for {business_name}: {str(click_error)}"
                    )
                    if page.is_closed():
                        raise
                    return business

                # Wait for detail panel to appear (side panel, not a new page)
                try:
                    # Wait for the detail panel/side panel to appear
                    await page.wait_for_selector('[role="main"]', timeout=5000)
                except:
                    # Try alternative selectors for the detail panel
                    try:
                        await page.wait_for_selector(".m6QErb", timeout=3000)
                    except:
                        logger.warning(f"Detail panel not found for {business_name}")
                        return business

                # Wait a bit for the panel content to load
                await asyncio.sleep(1.5)

                # Wait a bit more for the detail panel to fully render
                await asyncio.sleep(1)

                # Check if page is still valid before extracting
                if page.is_closed():
                    logger.warning(f"Page closed after clicking {business_name}")
                    return business

                # Extract phone and email from the detail panel ONLY
                # Website is already extracted from the list view, no need to get it here
                details = await page.evaluate(
                    """
                    () => {
                        const details = { phone: null, email: null };
                        
                        // Find the detail panel - the specific section that shows after clicking a business
                        // Look for the rightmost panel (role="main" or specific detail container)
                        const detailPanel = document.querySelector('[role="main"]') || 
                                          document.querySelector('.m6QErb') || 
                                          document.querySelector('[class*="pane"]') ||
                                          document.body;
                        
                        // Find phone number - look for clickable phone links within detail panel
                        const phoneLink = detailPanel.querySelector('a[href^="tel:"]');
                        if (phoneLink) {
                            const href = phoneLink.getAttribute('href') || '';
                            const phoneMatch = href.match(/tel:([\\d\\+\\-\\(\\)\\s]+)/);
                            if (phoneMatch) {
                                details.phone = phoneMatch[1].trim();
                            } else {
                                const text = phoneLink.textContent || '';
                                const phoneMatch2 = text.match(/([\\d\\s\\+\\-\\(\\)]+)/);
                                if (phoneMatch2) {
                                    details.phone = phoneMatch2[1].trim();
                                }
                            }
                        }
                        
                        // Also search for phone in the detail panel's text (not entire page)
                        if (!details.phone) {
                            const detailText = detailPanel.innerText;
                            const phonePattern = /\\+?1?\\s?[\\(\\[]?[0-9]{3}[\\)\\]]?[\\s\\-]?[0-9]{3}[\\s\\-]?[0-9]{4}/;
                            const phoneMatch = detailText.match(phonePattern);
                            if (phoneMatch) {
                                details.phone = phoneMatch[0].trim();
                            }
                        }
                        
                        // Find email - look for mailto links first (within detail panel)
                        const emailLink = detailPanel.querySelector('a[href^="mailto:"]');
                        if (emailLink) {
                            const href = emailLink.getAttribute('href') || '';
                            const emailMatch = href.match(/mailto:([^?\\s]+)/);
                            if (emailMatch) {
                                details.email = emailMatch[1].trim();
                            } else {
                                const text = emailLink.textContent || '';
                                const emailMatch2 = text.match(/([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,})/);
                                if (emailMatch2) {
                                    details.email = emailMatch2[1].trim();
                                }
                            }
                        }
                        
                        // Also search in detail panel text for email patterns (not entire page)
                        if (!details.email) {
                            const detailText = detailPanel.innerText;
                            const emailPattern = /([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,})/;
                            const emailMatch = detailText.match(emailPattern);
                            if (emailMatch) {
                                const email = emailMatch[1].trim();
                                // Filter out false positives
                                if (!email.includes('example.com') && !email.includes('test.com') && 
                                    !email.includes('google.com') && email.includes('@')) {
                                    details.email = email;
                                }
                            }
                        }
                        
                        return details;
                    }
                    """
                )

                # Add phone and email to business data
                # Phone and website are already extracted from list view, only use detail panel if not found
                # Only set phone if it wasn't already extracted from list view
                if details.get("phone") and not business.get("phone"):
                    business["phone"] = details["phone"]
                if details.get("email"):
                    business["email"] = details["email"]

                    # Close the detail panel (side panel) to return to search results
                    try:
                        if not page.is_closed():
                            # Press Escape to close the side panel
                            await page.keyboard.press("Escape")
                            await asyncio.sleep(0.5)

                            # Wait a bit for the panel to close
                            await asyncio.sleep(0.5)
                    except Exception as close_error:
                        logger.warning(
                            f"Error closing detail panel for {business_name}: {str(close_error)}"
                        )

            except Exception as e:
                logger.warning(f"Error clicking on business {business_name}: {str(e)}")
                # If page is closed, we can't continue enriching
                if "closed" in str(e).lower() or page.is_closed():
                    logger.error(
                        f"Page closed during enrichment, stopping enrichment process"
                    )
                    raise

            return business

        except Exception as e:
            logger.warning(f"Error enriching business data: {str(e)}")
            return business


# ============================================================================
# Graph Nodes
# ============================================================================

scraper = GoogleMapsScraper()


async def scrape_google_maps_node(
    state: GoogleMapsScraperState,
) -> GoogleMapsScraperState:
    """Scrape Google Maps search results."""
    try:
        print("\n" + "=" * 80)
        print("🔍 NODE: scrape_google_maps_node - Starting Google Maps scraping")
        print("=" * 80)
        logger.info(f"Scraping Google Maps for query: {state['query']}")

        results = await scraper.scrape_search_results(
            query=state["query"],
            max_results=state.get("max_results"),  # None means scrape all
            location=state.get("location"),
        )

        if not results:
            print("❌ No results found")
            return {
                **state,
                "status": "completed",
                "raw_results": [],
                "total_found": 0,
                "error": "No results found",
            }

        print(f"✅ Successfully scraped {len(results)} results")
        return {
            **state,
            "raw_results": results,
            "total_found": len(results),
            "status": "scraped",
        }
    except Exception as e:
        print(f"❌ Error in scrape_google_maps_node: {str(e)}")
        logger.error(f"Error in scrape_google_maps_node: {str(e)}")
        return {**state, "status": "error", "error": str(e)}


async def process_results_node(state: GoogleMapsScraperState) -> GoogleMapsScraperState:
    """Process and structure the scraped results."""
    try:
        print("\n" + "=" * 80)
        print("📊 NODE: process_results_node - Processing results")
        print("=" * 80)
        logger.info("Processing scraped results")

        raw_results = state.get("raw_results", [])

        if not raw_results:
            return {**state, "status": "completed", "processed_results": []}

        # Process and clean results
        processed_results = []
        for i, result in enumerate(raw_results, 1):
            processed = {
                "rank": i,
                "name": result.get("name", "N/A"),
                "rating": result.get("rating", "N/A"),
                "reviews": result.get("reviews", "N/A"),
                "category": result.get("category", "N/A"),
                "price_level": result.get("price_level", "N/A"),
                "address": result.get("address", "N/A"),
                "phone": result.get("phone", "N/A"),
                "website": result.get("website", "N/A"),
                "email": result.get("email", "N/A"),
                "url": result.get("url", "N/A"),
            }
            processed_results.append(processed)

        print(f"✅ Processed {len(processed_results)} results")
        return {
            **state,
            "processed_results": processed_results,
            "status": "processed",
        }
    except Exception as e:
        print(f"❌ Error in process_results_node: {str(e)}")
        logger.error(f"Error in process_results_node: {str(e)}")
        return {**state, "status": "error", "error": str(e)}


async def enrich_websites_node(state: GoogleMapsScraperState) -> GoogleMapsScraperState:
    """Enrich results with website information and email addresses."""
    try:
        print("\n" + "=" * 80)
        print("🌐 NODE: enrich_websites_node - Scraping websites for additional info")
        print("=" * 80)
        logger.info("Enriching results with website information")

        processed_results = state.get("processed_results", [])
        if not processed_results:
            logger.warning("No processed results to enrich")
            return {**state, "status": "completed"}

        enriched_results = []
        for i, result in enumerate(processed_results, 1):
            website = result.get("website", "N/A")

            # Skip if no website or website is N/A
            if not website or website == "N/A" or not website.startswith("http"):
                enriched_results.append(result)
                continue

            logger.info(
                f"Enriching {i}/{len(processed_results)}: {result.get('name', 'Unknown')} - {website}"
            )

            try:
                # Scrape website information
                website_info = await scraper.scrape_website_info(website)

                # Update result with website information
                enriched_result = {**result}

                # Add website metadata
                if website_info.get("title"):
                    enriched_result["website_title"] = website_info["title"]
                if website_info.get("metaDescription"):
                    enriched_result["website_description"] = website_info[
                        "metaDescription"
                    ]
                if website_info.get("bodyText"):
                    enriched_result["website_summary"] = website_info["bodyText"][
                        :500
                    ]  # First 500 chars

                # Update email if found on website and not already set
                if website_info.get("emails") and len(website_info["emails"]) > 0:
                    # Use the first email found, or keep existing if already set
                    if enriched_result.get("email") == "N/A" or not enriched_result.get(
                        "email"
                    ):
                        enriched_result["email"] = website_info["emails"][0]
                    # Also store all emails found
                    enriched_result["website_emails"] = website_info["emails"]

                # Update phone if found on website and not already set
                if (
                    website_info.get("phoneNumbers")
                    and len(website_info["phoneNumbers"]) > 0
                ):
                    if enriched_result.get("phone") == "N/A" or not enriched_result.get(
                        "phone"
                    ):
                        enriched_result["phone"] = website_info["phoneNumbers"][0]

                enriched_results.append(enriched_result)

                # Small delay between website scrapes to avoid rate limiting
                await asyncio.sleep(1)

            except Exception as e:
                logger.error(
                    f"Error enriching website for {result.get('name', 'Unknown')}: {str(e)}"
                )
                # Add result without enrichment if scraping fails
                enriched_results.append(result)

        print(f"✅ Enriched {len(enriched_results)} results with website information")
        return {
            **state,
            "processed_results": enriched_results,
            "status": "enriched",
        }
    except Exception as e:
        print(f"❌ Error in enrich_websites_node: {str(e)}")
        logger.error(f"Error in enrich_websites_node: {str(e)}")
        return {**state, "status": "error", "error": str(e)}


async def agent_node(state: GoogleMapsScraperState) -> GoogleMapsScraperState:
    """Main agent node that orchestrates the workflow."""
    try:
        current_status = state.get("status", "initialized")
        enrich_with_website = state.get("enrich_with_website", False)

        if current_status == "initialized":
            return await scrape_google_maps_node(state)

        elif current_status == "scraped":
            return await process_results_node(state)

        elif current_status == "processed":
            # Only enrich with website if enabled
            if enrich_with_website:
                return await enrich_websites_node(state)
            else:
                return {**state, "status": "completed"}

        elif current_status == "enriched":
            return {**state, "status": "completed"}

        return state

    except Exception as e:
        logger.error(f"Error in agent_node: {str(e)}")
        return {**state, "status": "error", "error": str(e)}


def should_continue(state: GoogleMapsScraperState) -> Literal["continue", "end"]:
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


def create_google_maps_scraper_agent():
    """Create and compile the Google Maps scraper LangGraph agent."""

    workflow = StateGraph(GoogleMapsScraperState)

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


class GoogleMapsScraperAgent:
    """Standalone LangGraph agent for Google Maps scraping."""

    def __init__(self):
        self.graph = create_google_maps_scraper_agent()
        logger.info("Google Maps Scraper Agent initialized")

    async def process(
        self,
        query: str,
        max_results: Optional[int] = None,
        location: Optional[str] = None,
        enrich_with_website: bool = False,
        thread_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Process a Google Maps search query.

        Args:
            query: Search query (e.g., "coffee shops", "restaurants")
            max_results: Maximum number of results to scrape (None = scrape all available results)
            location: Optional location (e.g., "New York, NY")
            enrich_with_website: If True, visit each business website to extract additional info and emails (default: False)
            thread_id: Thread ID for conversation tracking

        Returns:
            Dictionary containing scraped results
        """
        try:
            if not query:
                raise ValueError("Query must be provided")

            initial_state = {
                "messages": [],
                "query": query,
                "max_results": max_results,
                "location": location,
                "enrich_with_website": enrich_with_website,
                "raw_results": None,
                "processed_results": None,
                "total_found": 0,
                "status": "initialized",
                "error": None,
            }

            print("\n" + "=" * 80)
            print("🚀 Starting Google Maps Scraper Agent Workflow")
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
                "query": query,
                "location": location,
                "total_found": final_state.get("total_found", 0),
                "results": final_state.get("processed_results", []),
                "processing_status": final_state.get("status", "unknown"),
            }

        except Exception as e:
            logger.error(f"Error processing Google Maps scrape request: {str(e)}")
            raise

    async def enrich_results(
        self,
        results: List[Dict[str, Any]],
        location: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Enrich existing business results with website information and email addresses.

        Args:
            results: List of business dictionaries to enrich
            location: Optional location for context (used for timezone/geolocation)

        Returns:
            List of enriched business dictionaries
        """
        try:
            if not results:
                logger.warning("No results provided for enrichment")
                return []

            logger.info(
                f"Enriching {len(results)} business results with website information"
            )

            # Store location for context in the scraper instance
            scraper._current_location = location

            enriched_results = []
            for i, result in enumerate(results, 1):
                website = result.get("website", "N/A")

                # Skip if no website or website is N/A
                if not website or website == "N/A" or not website.startswith("http"):
                    enriched_results.append(result)
                    continue

                logger.info(
                    f"Enriching {i}/{len(results)}: {result.get('name', 'Unknown')} - {website}"
                )

                try:
                    # Scrape website information using the global scraper instance
                    website_info = await scraper.scrape_website_info(website)

                    # Update result with website information
                    enriched_result = {**result}

                    # Add website metadata
                    if website_info.get("title"):
                        enriched_result["website_title"] = website_info["title"]
                    if website_info.get("metaDescription"):
                        enriched_result["website_description"] = website_info[
                            "metaDescription"
                        ]
                    if website_info.get("bodyText"):
                        enriched_result["website_summary"] = website_info["bodyText"][
                            :500
                        ]  # First 500 chars

                    # Update email if found on website and not already set
                    if website_info.get("emails") and len(website_info["emails"]) > 0:
                        # Use the first email found, or keep existing if already set
                        if enriched_result.get(
                            "email"
                        ) == "N/A" or not enriched_result.get("email"):
                            enriched_result["email"] = website_info["emails"][0]
                        # Also store all emails found
                        enriched_result["website_emails"] = website_info["emails"]

                    # Update phone if found on website and not already set
                    if (
                        website_info.get("phoneNumbers")
                        and len(website_info["phoneNumbers"]) > 0
                    ):
                        if enriched_result.get(
                            "phone"
                        ) == "N/A" or not enriched_result.get("phone"):
                            enriched_result["phone"] = website_info["phoneNumbers"][0]

                    enriched_results.append(enriched_result)

                    # Small delay between website scrapes to avoid rate limiting
                    await asyncio.sleep(1)

                except Exception as e:
                    logger.error(
                        f"Error enriching website for {result.get('name', 'Unknown')}: {str(e)}"
                    )
                    # Add result without enrichment if scraping fails
                    enriched_results.append(result)

            logger.info(
                f"Successfully enriched {len(enriched_results)} results with website information"
            )
            return enriched_results

        except Exception as e:
            logger.error(f"Error enriching results: {str(e)}")
            raise


# ============================================================================
# Factory Function
# ============================================================================


def create_agent() -> GoogleMapsScraperAgent:
    """Factory function to create a new Google Maps scraper agent instance."""
    return GoogleMapsScraperAgent()


# ============================================================================
# Note: This module is designed to be used with the FastAPI application (app.py)
# For standalone usage, use the FastAPI API endpoints instead.
# ============================================================================
