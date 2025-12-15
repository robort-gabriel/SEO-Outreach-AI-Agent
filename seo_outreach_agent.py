"""
SEO Outreach Agent

A production-ready LangGraph agent that:
1. Extracts companies from Google Maps based on keyword and location
2. Enriches company data with email addresses from websites
3. Analyzes websites for SEO issues
4. Generates personalized outreach emails
5. Sends emails and tracks responses

This agent uses existing Google Maps scraper and email finder code.
"""

import logging
import os
import json
import re
import asyncio
from pathlib import Path
from typing import TypedDict, Annotated, List, Optional, Dict, Any, Literal
from datetime import datetime
import operator

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

# Import tools
from tools.seo_outreach_tools import (
    scrape_google_maps_tool,
    find_emails_tool,
    analyze_seo_tool,
    generate_email_tool,
    send_email_tool,
)

# Load environment variables
try:
    from dotenv import load_dotenv

    script_dir = Path(__file__).parent.absolute()
    env_path = script_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()
except ImportError:
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M%S",
)
logger = logging.getLogger(__name__)

# Get OpenAI API key and model
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")  # Default to gpt-4o


# ============================================================================
# State Definition
# ============================================================================


class SEOOutreachState(TypedDict):
    """State for the SEO Outreach agent."""

    messages: Annotated[List[BaseMessage], operator.add]
    query: str  # Search keyword
    location: Optional[str]  # Location for Google Maps search
    max_results: Optional[int]  # Max companies to extract
    send_emails: bool  # Whether to send emails (default: False)
    generate_pdf: bool  # Whether to generate PDF reports (default: False)

    # Step 1: Google Maps extraction
    companies: List[Dict[str, Any]]  # Extracted companies from Google Maps

    # Step 2: Email enrichment
    enriched_companies: List[Dict[str, Any]]  # Companies with emails

    # Step 3: SEO analysis
    seo_analyzed_companies: List[Dict[str, Any]]  # Companies with SEO analysis

    # Step 4: Email generation
    emails_generated: List[Dict[str, Any]]  # Companies with generated emails

    # Step 5: Email sending
    emails_sent: List[Dict[str, Any]]  # Companies with sent emails

    # Status tracking
    current_step: Literal[
        "extract_companies",
        "enrich_emails",
        "analyze_seo",
        "generate_emails",
        "send_emails",
        "completed",
        "error",
    ]
    status: str
    error: Optional[str]
    results: Optional[Dict[str, Any]]


# ============================================================================
# LLM Service
# ============================================================================


# ============================================================================
# Structured Output Models
# ============================================================================


class PersonalizedEmail(BaseModel):
    """Structured output for personalized outreach email."""

    subject: str = Field(
        description="Email subject line (50-70 characters, compelling and specific)"
    )
    body_html: str = Field(
        description="Email body formatted in HTML tags (100-150 words). Use <p>, <ul>, <li>, <strong> tags. Do NOT include ```html or <!DOCTYPE html> tags, just the HTML tags to format the email body."
    )


class LLMService:
    """Service for LLM operations with structured outputs."""

    def __init__(self, model: Optional[str] = None):
        if not OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY is not set. Please set it in environment variables."
            )

        # Use provided model or env variable or default
        self.model_name = model or OPENAI_MODEL
        logger.info(f"Using OpenAI model: {self.model_name}")

        self.model = ChatOpenAI(
            model=self.model_name,
            temperature=1,
            streaming=False,
            api_key=OPENAI_API_KEY,
        )

        # Create structured output model
        self.structured_model = self.model.with_structured_output(
            PersonalizedEmail, method="function_calling"
        )

        self.profile = self._load_profile()

    def _load_profile(self) -> Dict[str, Any]:
        """Load profile information from profile.md file."""
        profile_path = Path(__file__).parent / "profile.md"
        profile_data = {
            "name": "SEO Consultant",
            "title": "SEO Specialist",
            "email": "",
            "phone": "",
            "website": "",
            "experience": "",
            "specialization": "",
            "services": [],
            "value_proposition": "",
            "call_to_action": "I'd love to schedule a brief call to discuss how I can help improve your website's SEO.",
            "signature": "Best regards",
        }

        if profile_path.exists():
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Parse profile.md using simple regex patterns
                # Extract name
                name_match = re.search(r"\*\*Name:\*\*\s*(.+?)(?:\n|$)", content)
                if name_match:
                    profile_data["name"] = name_match.group(1).strip()

                # Extract title
                title_match = re.search(r"\*\*Title:\*\*\s*(.+?)(?:\n|$)", content)
                if title_match:
                    profile_data["title"] = title_match.group(1).strip()

                # Extract email
                email_match = re.search(r"\*\*Email:\*\*\s*(.+?)(?:\n|$)", content)
                if email_match:
                    profile_data["email"] = email_match.group(1).strip()

                # Extract phone
                phone_match = re.search(r"\*\*Phone:\*\*\s*(.+?)(?:\n|$)", content)
                if phone_match:
                    profile_data["phone"] = phone_match.group(1).strip()

                # Extract website
                website_match = re.search(r"\*\*Website:\*\*\s*(.+?)(?:\n|$)", content)
                if website_match:
                    profile_data["website"] = website_match.group(1).strip()

                # Extract experience
                exp_match = re.search(
                    r"\*\*Experience:\*\*\s*(.+?)(?:\n|$)", content, re.MULTILINE
                )
                if exp_match:
                    profile_data["experience"] = exp_match.group(1).strip()

                # Extract specialization
                spec_match = re.search(
                    r"\*\*Specialization:\*\*\s*(.+?)(?:\n|$)", content, re.MULTILINE
                )
                if spec_match:
                    profile_data["specialization"] = spec_match.group(1).strip()

                # Extract value proposition
                vp_match = re.search(
                    r"\*\*Value Proposition:\*\*\s*\n\n(.+?)(?:\n\n|\*\*)",
                    content,
                    re.DOTALL,
                )
                if vp_match:
                    profile_data["value_proposition"] = vp_match.group(1).strip()

                # Extract call to action
                cta_match = re.search(
                    r"\*\*Call to Action:\*\*\s*\n\n(.+?)(?:\n\n|\*\*)",
                    content,
                    re.DOTALL,
                )
                if cta_match:
                    profile_data["call_to_action"] = cta_match.group(1).strip()

                # Extract signature
                sig_match = re.search(
                    r"\*\*Best regards,\*\*\s*\n\*\*(.+?)\*\*", content, re.DOTALL
                )
                if sig_match:
                    profile_data["signature"] = (
                        f"Best regards,\n{sig_match.group(1).strip()}"
                    )

                logger.info(f"Loaded profile for: {profile_data['name']}")
            except Exception as e:
                logger.warning(f"Error loading profile.md: {str(e)}. Using defaults.")
        else:
            logger.warning(
                "profile.md not found. Using default values. Please create profile.md with your information."
            )

        return profile_data

    def generate_personalized_email(
        self,
        company_name: str,
        company_website: str,
        contact_email: str,
        seo_issues: Dict[str, Any],
        contact_name: Optional[str] = None,
    ) -> Dict[str, str]:
        """Generate a personalized outreach email based on SEO analysis using structured output."""
        # Build profile context
        profile_context = f"""
Your Profile:
- Name: {self.profile['name']}
- Title: {self.profile['title']}
- Experience: {self.profile['experience'] or 'Experienced SEO professional'}
- Specialization: {self.profile['specialization'] or 'SEO optimization'}
- Value Proposition: {self.profile['value_proposition'] or 'Helping businesses improve their online visibility'}
"""

        system_message = f"""You are {self.profile['name']}, an {self.profile['title']} writing a personalized outreach email to a business owner.

Your goal is to:
1. Introduce yourself briefly using your actual name and title
2. Mention that you analyzed their website
3. Highlight 2-3 most critical SEO issues (be specific and actionable)
4. Explain the impact of these issues
5. Offer your SEO services to help fix them
6. Include a clear call-to-action: {self.profile['call_to_action']}
7. Be professional, friendly, and not pushy
8. Sign the email with: {self.profile['signature']}

Keep the email SHORT and concise (100-150 words maximum). Be direct and to the point. Focus on the most critical issues only. Format the email body in HTML tags (use <p>, <ul>, <li>, <strong> tags). Do NOT include ```html or <!DOCTYPE html> tags, just the HTML tags to format the email body.

{profile_context}"""

        # Format SEO issues
        priority_fixes = seo_issues.get("priority_fixes", [])
        overall_score = seo_issues.get("overall_seo_score", 0)

        issues_text = ""
        if priority_fixes:
            for fix in priority_fixes[:3]:  # Top 3 issues
                issues_text += f"\n- {fix.get('issue', '')}: {fix.get('impact', '')}"

        user_message = f"""Company: {company_name}
Website: {company_website}
Contact Email: {contact_email}
Contact Name: {contact_name or 'Business Owner'}

SEO Analysis Results:
- Overall SEO Score: {overall_score}/100
- Critical Issues Found: {len(priority_fixes)}

Top SEO Issues:
{issues_text}

Generate a personalized, professional outreach email using your profile information. Return structured output with subject and HTML-formatted body."""

        messages = [
            SystemMessage(content=system_message),
            HumanMessage(content=user_message),
        ]

        try:
            # Use structured output
            response = self.structured_model.invoke(messages)

            # Clean HTML body - remove markdown code blocks if present
            body_html = response.body_html
            # Remove ```html and ``` markers
            body_html = re.sub(r"```html\s*", "", body_html)
            body_html = re.sub(r"```\s*$", "", body_html, flags=re.MULTILINE)
            body_html = body_html.strip()

            # Return as dictionary
            return {
                "subject": response.subject,
                "body_html": body_html,
            }
        except Exception as e:
            logger.error(f"Error generating structured email: {str(e)}")
            # Fallback to plain text
            fallback_response = self.model.invoke(messages)
            fallback_content = (
                fallback_response.content
                if hasattr(fallback_response, "content")
                else str(fallback_response)
            )

            # Extract subject if present, otherwise generate one
            subject = f"Quick SEO Fix for {company_name}"
            if "Subject:" in fallback_content:
                subject = fallback_content.split("Subject:")[1].split("\n")[0].strip()
                body_html = (
                    fallback_content.split("Subject:")[1].split("\n", 1)[1].strip()
                )
            else:
                body_html = fallback_content

            # Clean markdown code blocks
            body_html = re.sub(r"```html\s*", "", body_html)
            body_html = re.sub(r"```\s*$", "", body_html, flags=re.MULTILINE)
            body_html = body_html.strip()

            # Convert to HTML if not already
            if not body_html.startswith("<"):
                body_html = f"<p>{body_html.replace(chr(10), '</p><p>')}</p>"

            return {
                "subject": subject,
                "body_html": body_html,
            }


# ============================================================================
# Graph Nodes
# ============================================================================

_llm_service = None


def get_llm_service(model: Optional[str] = None):
    """Get or create LLM service instance."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService(model=model)
    return _llm_service


async def extract_companies_node(state: SEOOutreachState) -> SEOOutreachState:
    """Step 1: Extract companies from Google Maps."""
    try:
        logger.info(f"Extracting companies for query: {state['query']}")

        result = await scrape_google_maps_tool.ainvoke(
            {
                "query": state["query"],
                "location": state.get("location"),
                "max_results": state.get("max_results", 20),
            }
        )

        companies = result.get("results", [])
        logger.info(f"Extracted {len(companies)} companies")

        # Save extracted companies to JSON
        _save_phase_output(
            phase="1_extracted_companies",
            query=state["query"],
            location=state.get("location"),
            data={"companies": companies, "total": len(companies)},
        )

        return {
            **state,
            "companies": companies,
            "current_step": "enrich_emails",
            "status": "companies_extracted",
        }
    except Exception as e:
        logger.error(f"Error extracting companies: {str(e)}")
        return {
            **state,
            "current_step": "error",
            "status": "error",
            "error": str(e),
        }


async def enrich_emails_node(state: SEOOutreachState) -> SEOOutreachState:
    """Step 2: Enrich companies with email addresses."""
    try:
        companies = state.get("companies", [])
        if not companies:
            return {
                **state,
                "current_step": "error",
                "status": "error",
                "error": "No companies to enrich",
            }

        logger.info(f"Enriching {len(companies)} companies with emails")

        enriched_companies = []
        for company in companies:
            website = company.get("website") or company.get("website_url")
            if not website:
                # Skip companies without websites
                company["email"] = None
                company["emails"] = []
                enriched_companies.append(company)
                continue

            try:
                result = await find_emails_tool.ainvoke(
                    {
                        "website": website,
                    }
                )

                emails = result.get("emails", [])
                company["email"] = emails[0] if emails else None
                company["emails"] = emails
                company["phoneNumbers"] = result.get("phoneNumbers", [])

                enriched_companies.append(company)

                # Small delay to avoid rate limiting
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Error finding email for {website}: {str(e)}")
                company["email"] = None
                company["emails"] = []
                enriched_companies.append(company)

        logger.info(f"Enriched {len(enriched_companies)} companies")

        # Save enriched companies to JSON
        _save_phase_output(
            phase="2_enriched_companies",
            query=state["query"],
            location=state.get("location"),
            data={
                "companies": enriched_companies,
                "total": len(enriched_companies),
                "with_emails": len([c for c in enriched_companies if c.get("email")]),
            },
        )

        return {
            **state,
            "enriched_companies": enriched_companies,
            "current_step": "analyze_seo",
            "status": "emails_enriched",
        }
    except Exception as e:
        logger.error(f"Error enriching emails: {str(e)}")
        return {
            **state,
            "current_step": "error",
            "status": "error",
            "error": str(e),
        }


async def analyze_seo_node(state: SEOOutreachState) -> SEOOutreachState:
    """Step 3: Analyze SEO issues for each company website."""
    try:
        enriched_companies = state.get("enriched_companies", [])
        generate_pdf = state.get("generate_pdf", False)
        if not enriched_companies:
            return {
                **state,
                "current_step": "error",
                "status": "error",
                "error": "No companies to analyze",
            }

        logger.info(f"Analyzing SEO for {len(enriched_companies)} companies")

        # Import PDFGenerator if PDF generation is enabled
        pdf_generator = None
        if generate_pdf:
            try:
                from pdf_generator import PDFGenerator
                pdf_generator = PDFGenerator()
                logger.info("PDF generation enabled")
            except ImportError:
                logger.warning("PDFGenerator not available. PDF generation will be skipped.")
                generate_pdf = False

        seo_analyzed_companies = []
        for company in enriched_companies:
            website = company.get("website") or company.get("website_url")
            if not website:
                company["seo_analysis"] = None
                company["pdf_path"] = None
                seo_analyzed_companies.append(company)
                continue

            try:
                result = await analyze_seo_tool.ainvoke(
                    {
                        "website_url": website,
                        "analyze_multiple_pages": True,  # Enable multi-page analysis
                    }
                )

                company["seo_analysis"] = result.get("seo_audit", {})
                company["seo_score"] = result.get("overall_score", 0)
                extracted_content = result.get("extracted_content", {})

                # Generate PDF if enabled
                if generate_pdf and pdf_generator and company.get("seo_analysis"):
                    try:
                        company_name = company.get("name", "Business")
                        pdf_bytes = pdf_generator.generate_seo_audit_pdf(
                            url=website,
                            company_name=company_name,
                            extracted_content=extracted_content,
                            seo_audit=company["seo_analysis"],
                            overall_score=company["seo_score"],
                            speed_audit=None,  # Speed audit not available in outreach workflow
                        )

                        # Save PDF to file
                        from urllib.parse import urlparse
                        parsed_url = urlparse(website)
                        domain = parsed_url.netloc.replace("www.", "")
                        safe_domain = "".join(
                            c if c.isalnum() or c in ("-", "_") else "_" for c in domain
                        )[:50]
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        output_dir = Path("output")
                        output_dir.mkdir(exist_ok=True)
                        pdf_filename = output_dir / f"seo_audit_{safe_domain}_{timestamp}.pdf"

                        with open(pdf_filename, "wb") as f:
                            f.write(pdf_bytes)

                        company["pdf_path"] = str(pdf_filename)
                        company["pdf_bytes"] = pdf_bytes  # Store bytes for email attachment
                        logger.info(f"Generated PDF for {company_name}: {pdf_filename}")
                    except Exception as e:
                        logger.warning(f"Error generating PDF for {website}: {str(e)}")
                        company["pdf_path"] = None
                        company["pdf_bytes"] = None
                else:
                    company["pdf_path"] = None
                    company["pdf_bytes"] = None

                seo_analyzed_companies.append(company)

                # Small delay to avoid rate limiting
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Error analyzing SEO for {website}: {str(e)}")
                company["seo_analysis"] = None
                company["seo_score"] = 0
                company["pdf_path"] = None
                company["pdf_bytes"] = None
                seo_analyzed_companies.append(company)

        logger.info(f"Analyzed SEO for {len(seo_analyzed_companies)} companies")

        # Save SEO analysis results to JSON
        seo_results = []
        for company in seo_analyzed_companies:
            seo_results.append(
                {
                    "name": company.get("name"),
                    "website": company.get("website") or company.get("website_url"),
                    "seo_score": company.get("seo_score", 0),
                    "seo_analysis": company.get("seo_analysis"),
                }
            )

        _save_phase_output(
            phase="3_seo_analysis",
            query=state["query"],
            location=state.get("location"),
            data={
                "companies": seo_results,
                "total": len(seo_results),
                "with_analysis": len([c for c in seo_results if c.get("seo_analysis")]),
            },
        )

        return {
            **state,
            "seo_analyzed_companies": seo_analyzed_companies,
            "current_step": "generate_emails",
            "status": "seo_analyzed",
        }
    except Exception as e:
        logger.error(f"Error analyzing SEO: {str(e)}")
        return {
            **state,
            "current_step": "error",
            "status": "error",
            "error": str(e),
        }


async def generate_emails_node(state: SEOOutreachState) -> SEOOutreachState:
    """Step 4: Generate personalized outreach emails."""
    try:
        seo_analyzed_companies = state.get("seo_analyzed_companies", [])
        if not seo_analyzed_companies:
            return {
                **state,
                "current_step": "error",
                "status": "error",
                "error": "No companies to generate emails for",
            }

        logger.info(f"Generating emails for {len(seo_analyzed_companies)} companies")

        llm_service = get_llm_service()
        emails_generated = []

        for company in seo_analyzed_companies:
            email = company.get("email")
            seo_analysis = company.get("seo_analysis")

            # Skip if no email or no SEO analysis
            if not email or not seo_analysis:
                company["generated_email"] = None
                emails_generated.append(company)
                continue

            try:
                email_result = llm_service.generate_personalized_email(
                    company_name=company.get("name", "Business"),
                    company_website=company.get("website")
                    or company.get("website_url", ""),
                    contact_email=email,
                    seo_issues=seo_analysis,
                    contact_name=company.get("contact_name"),
                )

                company["generated_email"] = email_result.get("body_html", "")
                company["email_subject"] = email_result.get(
                    "subject",
                    f"Quick SEO Fix for {company.get('name', 'Your Website')}",
                )

                emails_generated.append(company)
            except Exception as e:
                logger.warning(
                    f"Error generating email for {company.get('name')}: {str(e)}"
                )
                company["generated_email"] = None
                emails_generated.append(company)

        logger.info(f"Generated emails for {len(emails_generated)} companies")

        # Save generated emails to JSON
        email_results = []
        for company in emails_generated:
            email_results.append(
                {
                    "name": company.get("name"),
                    "website": company.get("website") or company.get("website_url"),
                    "email": company.get("email"),
                    "email_subject": company.get("email_subject"),
                    "generated_email": company.get("generated_email"),
                    "seo_score": company.get("seo_score", 0),
                }
            )

        _save_phase_output(
            phase="4_generated_emails",
            query=state["query"],
            location=state.get("location"),
            data={
                "companies": email_results,
                "total": len(email_results),
                "with_emails": len(
                    [c for c in email_results if c.get("generated_email")]
                ),
            },
        )

        return {
            **state,
            "emails_generated": emails_generated,
            "current_step": "send_emails",
            "status": "emails_generated",
        }
    except Exception as e:
        logger.error(f"Error generating emails: {str(e)}")
        return {
            **state,
            "current_step": "error",
            "status": "error",
            "error": str(e),
        }


async def send_emails_node(state: SEOOutreachState) -> SEOOutreachState:
    """Step 5: Send outreach emails (optional)."""
    try:
        emails_generated = state.get("emails_generated", [])
        send_emails = state.get("send_emails", False)

        if not emails_generated:
            return {
                **state,
                "current_step": "error",
                "status": "error",
                "error": "No emails to send",
            }

        # Skip sending if send_emails is False
        if not send_emails:
            logger.info(
                f"Email sending is disabled. Skipping send step for {len(emails_generated)} companies"
            )
            emails_sent = []
            for company in emails_generated:
                company["email_sent"] = False
                company["email_sent_at"] = None
                company["email_sending_status"] = "skipped"
                emails_sent.append(company)

            # Prepare final results
            results = {
                "total_companies": len(state.get("companies", [])),
                "companies_with_emails": len(
                    [c for c in emails_sent if c.get("email")]
                ),
                "companies_with_seo_analysis": len(
                    [c for c in emails_sent if c.get("seo_analysis")]
                ),
                "emails_generated": len(
                    [c for c in emails_sent if c.get("generated_email")]
                ),
                "emails_sent": 0,
                "companies": emails_sent,
            }

            return {
                **state,
                "emails_sent": emails_sent,
                "current_step": "completed",
                "status": "completed",
                "results": results,
            }

        logger.info(f"Sending emails for {len(emails_generated)} companies")

        emails_sent = []
        for company in emails_generated:
            email = company.get("email")
            generated_email = company.get("generated_email")
            subject = company.get("email_subject", "SEO Improvement Opportunity")

            if not email or not generated_email:
                company["email_sent"] = False
                company["email_sent_at"] = None
                company["email_sending_status"] = "skipped_no_email"
                emails_sent.append(company)
                continue

            try:
                # Prepare PDF attachment if available
                pdf_bytes = company.get("pdf_bytes")
                pdf_path = company.get("pdf_path")
                pdf_filename = None
                if pdf_path:
                    # Extract filename from path
                    pdf_filename = Path(pdf_path).name

                result = await send_email_tool.ainvoke(
                    {
                        "to_email": email,
                        "subject": subject,
                        "body": generated_email,
                        "company_name": company.get("name", "Business"),
                        "pdf_bytes": pdf_bytes,
                        "pdf_filename": pdf_filename,
                    }
                )

                company["email_sent"] = result.get("success", False)
                company["email_sent_at"] = datetime.now().isoformat()
                company["email_message_id"] = result.get("message_id")
                company["email_sending_status"] = (
                    "sent" if result.get("success") else "failed"
                )

                emails_sent.append(company)

                # Small delay between emails
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning(f"Error sending email to {email}: {str(e)}")
                company["email_sent"] = False
                company["email_sent_at"] = None
                company["email_error"] = str(e)
                company["email_sending_status"] = "error"
                emails_sent.append(company)

        logger.info(f"Sent emails for {len(emails_sent)} companies")

        # Prepare final results
        results = {
            "total_companies": len(state.get("companies", [])),
            "companies_with_emails": len([c for c in emails_sent if c.get("email")]),
            "companies_with_seo_analysis": len(
                [c for c in emails_sent if c.get("seo_analysis")]
            ),
            "emails_generated": len(
                [c for c in emails_sent if c.get("generated_email")]
            ),
            "emails_sent": len([c for c in emails_sent if c.get("email_sent")]),
            "companies": emails_sent,
        }

        return {
            **state,
            "emails_sent": emails_sent,
            "current_step": "completed",
            "status": "completed",
            "results": results,
        }
    except Exception as e:
        logger.error(f"Error sending emails: {str(e)}")
        return {
            **state,
            "current_step": "error",
            "status": "error",
            "error": str(e),
        }


def _save_phase_output(
    phase: str, query: str, location: Optional[str], data: Dict[str, Any]
):
    """Save phase output to JSON file."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        safe_query = "".join(
            c if c.isalnum() or c in (" ", "-", "_") else "_" for c in query
        )[:50]

        filename = output_dir / f"{phase}_{safe_query}_{timestamp}.json"

        output_data = {
            "phase": phase,
            "query": query,
            "location": location,
            "timestamp": datetime.now().isoformat(),
            **data,
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved {phase} results to {filename}")
    except Exception as e:
        logger.warning(f"Error saving {phase} output: {str(e)}")


def route_next_step(state: SEOOutreachState) -> str:
    """Route to next step based on current step."""
    current_step = state.get("current_step", "extract_companies")
    status = state.get("status", "")

    if status == "error" or current_step in {"error", "completed"}:
        return "end"

    # We store the intended next step in current_step after each node.
    # Route directly to whatever current_step indicates, if known.
    allowed = {
        "extract_companies",
        "enrich_emails",
        "analyze_seo",
        "generate_emails",
        "send_emails",  # This is the current_step value, not the node name
    }
    if current_step in allowed:
        return current_step

    return "end"


# ============================================================================
# Graph Construction
# ============================================================================


def create_seo_outreach_agent():
    """Create and compile the SEO Outreach agent graph."""
    workflow = StateGraph(SEOOutreachState)

    # Add nodes
    workflow.add_node("extract_companies", extract_companies_node)
    workflow.add_node("enrich_emails", enrich_emails_node)
    workflow.add_node("analyze_seo", analyze_seo_node)
    workflow.add_node("generate_emails", generate_emails_node)
    workflow.add_node("deliver_emails", send_emails_node)

    # Set entry point
    workflow.set_entry_point("extract_companies")

    # Add conditional edges
    workflow.add_conditional_edges(
        "extract_companies",
        route_next_step,
        {
            "enrich_emails": "enrich_emails",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "enrich_emails",
        route_next_step,
        {
            "analyze_seo": "analyze_seo",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "analyze_seo",
        route_next_step,
        {
            "generate_emails": "generate_emails",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "generate_emails",
        route_next_step,
        {
            "send_emails": "deliver_emails",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "deliver_emails",
        route_next_step,
        {
            "end": END,
        },
    )

    # Compile graph
    return workflow.compile()


# ============================================================================
# Agent Interface
# ============================================================================


class SEOOutreachAgent:
    """SEO Outreach Agent Interface."""

    def __init__(self):
        self.graph = create_seo_outreach_agent()
        self.log_entries = []
        logger.info("SEO Outreach Agent initialized")

    def _log(self, message: str, data: dict = None):
        """Log agent activity."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "data": data,
        }
        self.log_entries.append(entry)
        logger.info(f"[{entry['timestamp']}] {message}")
        if data:
            logger.debug(f"  Data: {json.dumps(data, indent=2)[:200]}...")

    async def process(
        self,
        query: str,
        location: Optional[str] = None,
        max_results: Optional[int] = 20,
        send_emails: bool = False,
        generate_pdf: bool = False,
        save_output: bool = True,
    ) -> Dict[str, Any]:
        """
        Process SEO outreach workflow.

        Args:
            query: Search keyword for Google Maps (e.g., "restaurants", "dentists")
            location: Location for search (e.g., "New York, NY")
            max_results: Maximum number of companies to process
            send_emails: Whether to actually send emails (default: False)
            generate_pdf: Whether to generate PDF reports (default: False)
            save_output: Whether to save results to file

        Returns:
            Dictionary with results and metadata
        """
        self._log(f"Processing SEO outreach: query='{query}', location='{location}'")

        # Initialize state
        initial_state = {
            "messages": [],
            "query": query,
            "location": location,
            "max_results": max_results,
            "send_emails": send_emails,
            "generate_pdf": generate_pdf,
            "companies": [],
            "enriched_companies": [],
            "seo_analyzed_companies": [],
            "emails_generated": [],
            "emails_sent": [],
            "current_step": "extract_companies",
            "status": "initialized",
            "error": None,
            "results": None,
        }

        try:
            # Run the graph
            self._log("Running SEO outreach workflow...")
            final_state = await self.graph.ainvoke(initial_state)

            self._log(
                "Workflow completed",
                {
                    "status": final_state.get("status"),
                    "current_step": final_state.get("current_step"),
                },
            )

            # Prepare result
            results_data = final_state.get("results")
            if results_data is None:
                results_data = {}

            result = {
                "query": query,
                "location": location,
                "results": results_data,
                "status": final_state.get("status", "unknown"),
                "timestamp": datetime.now().isoformat(),
            }

            # Save output if requested
            if save_output:
                self._save_output(result)
                self._save_final_results_json(final_state)

            return result

        except Exception as e:
            import traceback

            traceback.print_exc()
            self._log(f"Error during processing: {str(e)}")
            return {
                "query": query,
                "location": location,
                "error": str(e),
                "status": "failed",
                "timestamp": datetime.now().isoformat(),
            }

    def _save_output(self, result: dict):
        """Save results to markdown file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        safe_query = "".join(
            c if c.isalnum() or c in (" ", "-", "_") else "_"
            for c in result.get("query", "seo_outreach")
        )[:50]

        filename = output_dir / f"seo_outreach_{safe_query}_{timestamp}.md"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# SEO Outreach Results\n\n")
            f.write(f"**Query:** {result.get('query', 'N/A')}\n\n")
            f.write(f"**Location:** {result.get('location', 'N/A')}\n\n")
            f.write(f"**Generated:** {result.get('timestamp', 'N/A')}\n\n")
            f.write(f"**Status:** {result.get('status', 'N/A')}\n\n")
            f.write(f"---\n\n")

            results_data = result.get("results") or {}
            f.write(f"## Summary\n\n")
            f.write(
                f"- Total Companies Found: {results_data.get('total_companies', 0)}\n"
            )
            f.write(
                f"- Companies with Emails: {results_data.get('companies_with_emails', 0)}\n"
            )
            f.write(
                f"- Companies with SEO Analysis: {results_data.get('companies_with_seo_analysis', 0)}\n"
            )
            f.write(f"- Emails Generated: {results_data.get('emails_generated', 0)}\n")
            f.write(f"- Emails Sent: {results_data.get('emails_sent', 0)}\n\n")
            f.write(f"---\n\n")

            f.write(f"## Companies\n\n")
            companies = (
                results_data.get("companies", [])
                if isinstance(results_data, dict)
                else []
            )
            for i, company in enumerate(companies, 1):
                f.write(f"### {i}. {company.get('name', 'Unknown')}\n\n")
                f.write(
                    f"- **Website:** {company.get('website') or company.get('website_url', 'N/A')}\n"
                )
                f.write(f"- **Email:** {company.get('email', 'N/A')}\n")
                f.write(f"- **SEO Score:** {company.get('seo_score', 0)}/100\n")
                f.write(
                    f"- **Email Sent:** {'Yes' if company.get('email_sent') else 'No'}\n\n"
                )

                if company.get("generated_email"):
                    f.write(f"**Generated Email:**\n\n")
                    f.write(f"```\n{company['generated_email']}\n```\n\n")

                f.write(f"---\n\n")

        self._log(f"Results saved to {filename}")

    def _save_final_results_json(self, final_state: Dict[str, Any]):
        """Save final results in a single JSON file with specific fields."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = Path("output")
            output_dir.mkdir(exist_ok=True)

            query = final_state.get("query", "seo_outreach")
            safe_query = "".join(
                c if c.isalnum() or c in (" ", "-", "_") else "_" for c in query
            )[:50]

            filename = output_dir / f"final_results_{safe_query}_{timestamp}.json"

            companies = final_state.get("emails_sent", []) or []
            final_results = []

            for company in companies:
                result_entry = {
                    "name": company.get("name", ""),
                    "address": company.get("address", ""),
                    "phone": company.get("phone", ""),
                    "website": company.get("website") or company.get("website_url", ""),
                    "email": company.get("email", ""),
                    "email_subject": company.get("email_subject", ""),
                    "email_body": company.get("generated_email", ""),
                    "email_sending_status": company.get(
                        "email_sending_status", "unknown"
                    ),
                }
                final_results.append(result_entry)

            output_data = {
                "query": query,
                "location": final_state.get("location"),
                "timestamp": datetime.now().isoformat(),
                "total_companies": len(final_results),
                "companies": final_results,
            }

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            self._log(f"Final results saved to {filename}")
        except Exception as e:
            logger.warning(f"Error saving final results JSON: {str(e)}")


# ============================================================================
# Main Execution
# ============================================================================

if __name__ == "__main__":
    import asyncio

    async def main():
        agent = SEOOutreachAgent()
        result = await agent.process(
            query="digital marketing agency",
            location="california, usa",
            max_results=3,
            send_emails=False,  # Set to True to actually send emails
        )
        print(json.dumps(result, indent=2))

    asyncio.run(main())
