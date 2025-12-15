"""
Tools for SEO Outreach Agent.

This module provides tools that reuse existing Google Maps scraper and email finder code.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from langchain.tools import tool

# Ensure local package root is on sys.path so absolute imports work when running as a script
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Local imports (copied into this package)
from google_maps_scraper_agent import GoogleMapsScraper
from email_finder_agent import WebsiteScraper
from website_audit_agent import extract_webpage_content, LLMService as SEOLLMService

logger = logging.getLogger(__name__)

# Initialize scrapers (lazy initialization)
_google_maps_scraper = None
_email_finder_scraper = None
_seo_llm_service = None


def get_google_maps_scraper():
    """Get or create Google Maps scraper instance."""
    global _google_maps_scraper
    if _google_maps_scraper is None:
        _google_maps_scraper = GoogleMapsScraper()
    return _google_maps_scraper


def get_email_finder_scraper():
    """Get or create email finder scraper instance."""
    global _email_finder_scraper
    if _email_finder_scraper is None:
        _email_finder_scraper = WebsiteScraper()
    return _email_finder_scraper


def get_seo_llm_service():
    """Get or create SEO LLM service instance."""
    global _seo_llm_service
    if _seo_llm_service is None:
        _seo_llm_service = SEOLLMService()
    return _seo_llm_service


@tool
async def scrape_google_maps_tool(
    query: str, location: Optional[str] = None, max_results: Optional[int] = 20
) -> Dict[str, Any]:
    """
    Extract companies from Google Maps based on keyword and location.

    Args:
        query: Search keyword (e.g., "restaurants", "dentists", "lawyers")
        location: Location for search (e.g., "New York, NY")
        max_results: Maximum number of companies to extract (default: 20)

    Returns:
        Dictionary with 'results' list containing company information
    """
    try:
        if not query:
            raise ValueError("query parameter is required")

        scraper = get_google_maps_scraper()

        results = await scraper.scrape_search_results(
            query=query,
            location=location,
            max_results=max_results,
        )

        # Format results for consistency
        formatted_results = []
        for result in results:
            formatted_result = {
                "name": result.get("name", ""),
                "address": result.get("address", ""),
                "phone": result.get("phone", ""),
                "website": result.get("website") or result.get("website_url", ""),
                "website_url": result.get("website") or result.get("website_url", ""),
                "rating": result.get("rating", 0),
                "reviews": result.get("reviews", 0),
                "category": result.get("category", ""),
                "google_maps_url": result.get("google_maps_url", ""),
            }
            formatted_results.append(formatted_result)

        return {
            "success": True,
            "results": formatted_results,
            "total": len(formatted_results),
        }
    except Exception as e:
        logger.error(f"Error scraping Google Maps: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "results": [],
            "total": 0,
        }


@tool
async def find_emails_tool(website: str) -> Dict[str, Any]:
    """
    Find email addresses from a company website.

    Args:
        website: Website URL to scrape for emails

    Returns:
        Dictionary with 'emails' list and 'phoneNumbers' list
    """
    try:
        if not website or not website.startswith("http"):
            raise ValueError("Valid website URL is required")

        scraper = get_email_finder_scraper()

        # Scrape website for emails (don't scrape full website info for speed)
        website_info = await scraper.scrape_website_info(
            website_url=website,
            scrape_website_info=False,  # Only get emails, not full site info
        )

        emails = website_info.get("emails", [])
        phone_numbers = website_info.get("phoneNumbers", [])

        return {
            "success": True,
            "emails": emails,
            "phoneNumbers": phone_numbers,
            "email": emails[0] if emails else None,
            "phoneNumber": phone_numbers[0] if phone_numbers else None,
        }
    except Exception as e:
        logger.error(f"Error finding emails for {website}: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "emails": [],
            "phoneNumbers": [],
            "email": None,
            "phoneNumber": None,
        }


@tool
async def analyze_seo_tool(
    website_url: str, analyze_multiple_pages: bool = True
) -> Dict[str, Any]:
    """
    Analyze a website for SEO issues with enhanced keyword analysis and multi-page support.

    Args:
        website_url: Website URL to analyze
        analyze_multiple_pages: If True, also analyze key pages (About, Services, Contact)

    Returns:
        Dictionary with SEO audit results including scores, keyword analysis, and issues
    """
    try:
        if not website_url or not website_url.startswith("http"):
            raise ValueError("Valid website URL is required")

        # Extract content from homepage
        content_json = await extract_webpage_content.ainvoke(website_url)

        # Parse JSON response
        if isinstance(content_json, str):
            try:
                homepage_content = json.loads(content_json)
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "error": "Failed to parse content extraction result",
                    "seo_audit": {},
                    "overall_score": 0,
                }
        else:
            homepage_content = content_json

        if not homepage_content or homepage_content.get("error"):
            return {
                "success": False,
                "error": homepage_content.get(
                    "error", "Failed to extract content from website"
                ),
                "seo_audit": {},
                "overall_score": 0,
            }

        # Analyze homepage SEO using LLM
        llm_service = get_seo_llm_service()
        homepage_audit = await llm_service.analyze_seo(homepage_content)

        # Parse homepage audit
        if isinstance(homepage_audit, str):
            try:
                homepage_audit = json.loads(homepage_audit)
            except json.JSONDecodeError:
                import re

                json_match = re.search(
                    r"```json\s*(\{.*?\})\s*```", homepage_audit, re.DOTALL
                )
                if json_match:
                    homepage_audit = json.loads(json_match.group(1))
                else:
                    homepage_audit = {
                        "overall_seo_score": 50,
                        "priority_fixes": [
                            {"issue": "Analysis incomplete", "priority": "medium"}
                        ],
                    }

        # Multi-page analysis if enabled
        additional_pages_audit = {}
        if analyze_multiple_pages:
            key_pages = homepage_content.get("links", {}).get("key_pages", [])[
                :3
            ]  # Top 3 key pages

            if key_pages:
                logger.info(f"Analyzing {len(key_pages)} additional key pages")
                additional_pages_audit = {}

                for page_info in key_pages:
                    page_url = page_info.get("url", "")
                    if not page_url:
                        continue

                    try:
                        # Extract content from key page
                        page_content_json = await extract_webpage_content.ainvoke(
                            page_url
                        )
                        if isinstance(page_content_json, str):
                            page_content = json.loads(page_content_json)
                        else:
                            page_content = page_content_json

                        if page_content and not page_content.get("error"):
                            # Quick analysis of key page
                            page_audit = await llm_service.analyze_seo(page_content)

                            if isinstance(page_audit, str):
                                try:
                                    page_audit = json.loads(page_audit)
                                except:
                                    import re

                                    json_match = re.search(
                                        r"```json\s*(\{.*?\})\s*```",
                                        page_audit,
                                        re.DOTALL,
                                    )
                                    if json_match:
                                        page_audit = json.loads(json_match.group(1))

                            additional_pages_audit[page_url] = {
                                "page_type": page_info.get("page_type", "unknown"),
                                "seo_score": page_audit.get("overall_seo_score", 0),
                                "key_issues": page_audit.get("priority_fixes", [])[:3],
                            }

                        # Small delay between page analyses
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.warning(f"Error analyzing key page {page_url}: {str(e)}")
                        continue

        # Combine homepage and multi-page analysis
        overall_score = homepage_audit.get("overall_seo_score", 0)

        # Add multi-page insights to audit
        if additional_pages_audit:
            homepage_audit["multi_page_analysis"] = {
                "pages_analyzed": len(additional_pages_audit),
                "page_audits": additional_pages_audit,
                "site_wide_issues": _identify_site_wide_issues(
                    homepage_audit, additional_pages_audit
                ),
            }

        return {
            "success": True,
            "seo_audit": homepage_audit,
            "overall_score": overall_score,
            "website_url": website_url,
            "pages_analyzed": 1 + len(additional_pages_audit),
            "extracted_content": homepage_content,  # Include extracted content for PDF generation
        }
    except Exception as e:
        logger.error(f"Error analyzing SEO for {website_url}: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "seo_audit": {},
            "overall_score": 0,
        }


def _identify_site_wide_issues(
    homepage_audit: Dict[str, Any], additional_pages: Dict[str, Any]
) -> List[str]:
    """Identify site-wide SEO issues from multiple page analyses."""
    issues = []

    # Check for common issues across pages
    low_scores = [
        audit.get("seo_score", 0)
        for audit in additional_pages.values()
        if audit.get("seo_score", 0) < 70
    ]
    if len(low_scores) > 0:
        issues.append(f"{len(low_scores)} key pages have low SEO scores (<70)")

    # Check for missing keywords across pages
    keyword_issues = []
    for page_url, audit in additional_pages.items():
        if audit.get("key_issues"):
            keyword_issues.extend(
                [
                    issue.get("issue", "")
                    for issue in audit["key_issues"]
                    if "keyword" in issue.get("issue", "").lower()
                ]
            )

    if keyword_issues:
        issues.append("Keyword optimization issues found across multiple pages")

    return issues


@tool
async def generate_email_tool(
    company_name: str,
    company_website: str,
    contact_email: str,
    seo_issues: Dict[str, Any],
    contact_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate a personalized outreach email based on SEO analysis.

    Args:
        company_name: Name of the company
        company_website: Company website URL
        contact_email: Contact email address
        seo_issues: SEO audit results dictionary
        contact_name: Optional contact person name

    Returns:
        Dictionary with generated email content and subject
    """
    try:
        # This will be handled by the LLM service in the main agent
        # This tool is here for consistency but the actual generation
        # happens in the generate_emails_node
        return {
            "success": True,
            "message": "Email generation handled by agent node",
        }
    except Exception as e:
        logger.error(f"Error generating email: {str(e)}")
        return {
            "success": False,
            "error": str(e),
        }


@tool
async def send_email_tool(
    to_email: str,
    subject: str,
    body: str,
    company_name: Optional[str] = None,
    pdf_bytes: Optional[bytes] = None,
    pdf_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send an email using free SMTP (Gmail, Outlook, etc.).

    Note: Requires SMTP credentials in environment variables:
    - SMTP_HOST: SMTP server host (e.g., smtp.gmail.com)
    - SMTP_PORT: SMTP port (e.g., 587)
    - SMTP_USER: Your email address
    - SMTP_PASSWORD: Your email password or app password
    - FROM_EMAIL: Sender email (defaults to SMTP_USER)
    - FROM_NAME: Sender name (default: "SEO Outreach")

    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Email body content
        company_name: Optional company name for logging
        pdf_bytes: Optional PDF file bytes to attach
        pdf_filename: Optional PDF filename for attachment

    Returns:
        Dictionary with success status and message ID
    """
    try:
        if not to_email or "@" not in to_email:
            raise ValueError("Valid email address is required")

        # Get SMTP settings from environment
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER")
        smtp_password = os.getenv("SMTP_PASSWORD")
        from_email = os.getenv("FROM_EMAIL", smtp_user)
        from_name = os.getenv("FROM_NAME", "SEO Outreach")

        if not smtp_user or not smtp_password:
            logger.warning("SMTP credentials not configured. Email will not be sent.")
            return {
                "success": False,
                "error": "SMTP credentials not configured",
                "message": "Please set SMTP_HOST, SMTP_PORT, SMTP_USER, and SMTP_PASSWORD environment variables",
            }

        # Create email message
        msg = MIMEMultipart()
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject

        # Add body (check if HTML or plain text)
        if "<p>" in body or "<html>" in body or "<div>" in body:
            # HTML email
            msg.attach(MIMEText(body, "html"))
        else:
            # Plain text email
            msg.attach(MIMEText(body, "plain"))

        # Attach PDF if provided
        if pdf_bytes:
            try:
                attachment = MIMEBase("application", "pdf")
                attachment.set_payload(pdf_bytes)
                encoders.encode_base64(attachment)
                attachment_filename = pdf_filename or f"SEO_Audit_Report_{company_name or 'Report'}.pdf"
                # Sanitize filename
                attachment_filename = "".join(
                    c if c.isalnum() or c in ("-", "_", ".") else "_" for c in attachment_filename
                )
                attachment.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{attachment_filename}"',
                )
                msg.attach(attachment)
                logger.info(f"Attached PDF to email: {attachment_filename}")
            except Exception as e:
                logger.warning(f"Error attaching PDF to email: {str(e)}")
                # Continue sending email even if PDF attachment fails

        # Send email
        try:
            # Use context manager for SMTP connection
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()  # Enable encryption
                server.login(smtp_user, smtp_password)
                text = msg.as_string()
                server.sendmail(from_email, to_email, text)

            logger.info(f"Email sent successfully to {to_email}")

            return {
                "success": True,
                "message_id": f"sent_{to_email}_{asyncio.get_event_loop().time()}",
                "to": to_email,
                "subject": subject,
            }
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error sending email: {str(e)}")
            return {
                "success": False,
                "error": f"SMTP error: {str(e)}",
            }
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}")
            return {
                "success": False,
                "error": str(e),
            }
    except Exception as e:
        logger.error(f"Error in send_email_tool: {str(e)}")
        return {
            "success": False,
            "error": str(e),
        }
